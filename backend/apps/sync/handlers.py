"""Server-side processing of the app's offline outbox.

Nothing the client sends is trusted:
  * ids are validated and every row is bound to the caller's own shop (no cross-tenant writes),
  * money must be integer paise; the sign of every ledger delta is recomputed here,
  * confirmation_status is ALWAYS forced to 'shopkeeper_recorded': only the server-side customer
    confirmation workflow may ever change it, so a modified client cannot forge confirmation,
  * (shop_id, idempotency_key) receipts make retries return the original result instead of posting twice.
"""
import logging
import uuid
from datetime import timedelta

from django.db import DatabaseError, IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.db import atomic, q, q1, x
from apps.subscriptions import service as subs

log = logging.getLogger("sync")

MAX_PAISE = 10_000_000_000  # Rs 10 crore: anything above is certainly a client bug
LEDGER_TYPES = {"opening", "credit", "payment", "adjustment", "reversal"}
PAY_METHODS = {"cash", "upi", "card", "bank", "other"}
SALE_METHODS = PAY_METHODS | {"credit"}
REFUND_METHODS = PAY_METHODS | {"khata"}


class Reject(Exception):
    """The item is invalid. The app marks it failed (and shows the message)."""


class Conflict(Exception):
    """The item clashes with existing server data and needs a human decision."""


# ── validation helpers ──────────────────────────────────────────────────────
def _uuid(v, name: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, AttributeError, TypeError):
        raise Reject(f"{name} is not a valid id")


def _int(v, name: str, lo: int = 0, hi: int = MAX_PAISE) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise Reject(f"{name} must be a whole number")
    if v < lo or v > hi:
        raise Reject(f"{name} is out of range")
    return v


def _ts(v, name: str):
    d = parse_datetime(v) if isinstance(v, str) else None
    if d is None or d.tzinfo is None:
        raise Reject(f"{name} must be an ISO timestamp with timezone")
    if d > timezone.now() + timedelta(days=1):
        raise Reject(f"{name} is in the future")
    return d


def _text(v, name: str, maxlen: int, required: bool = False) -> str | None:
    if v is None or v == "":
        if required:
            raise Reject(f"{name} is required")
        return None
    if not isinstance(v, str):
        raise Reject(f"{name} must be text")
    v = v.strip()
    if required and not v:
        raise Reject(f"{name} is required")
    return v[:maxlen] or None


def _key(v) -> str:
    if not isinstance(v, str) or not (1 <= len(v) <= 120):
        raise Reject("idempotency_key is invalid")
    return v


def _own_customer(shop_id: str, customer_id: str) -> dict:
    row = q1("SELECT id, status FROM customers WHERE id = %s AND shop_id = %s", [customer_id, shop_id])
    if not row:
        raise Reject("Customer not found in this shop")
    return row


# ── handlers: each returns the server id of the stored entity ───────────────
def create_shop(ctx: dict, p: dict) -> str:
    sid = _uuid(p.get("id"), "shop id")
    existing = q1("SELECT owner_user_id FROM shops WHERE id = %s", [sid])
    if existing:
        if str(existing["owner_user_id"]) == ctx["user_id"]:
            raise Duplicate(sid)
        raise Reject("Shop id is not available")
    if q1("SELECT 1 AS x FROM shops WHERE owner_user_id = %s", [ctx["user_id"]]):
        raise Conflict("This account already has a shop")
    name = _text(p.get("name"), "name", 160, required=True)
    x("""INSERT INTO shops(id, owner_user_id, name, category, address, timezone, language)
         VALUES (%s,%s,%s,%s,%s,%s,%s)""",
      [sid, ctx["user_id"], name, _text(p.get("category"), "category", 60), _text(p.get("address"), "address", 500),
       "Asia/Kolkata", p.get("language") if p.get("language") in ("en", "hi", "pa") else "en"])
    x("INSERT INTO shop_members(shop_id, user_id, role, status) VALUES (%s,%s,'owner','active')", [sid, ctx["user_id"]])
    subs.create_for_shop(sid, ctx["user_id"])
    ctx["shop_id"] = sid
    return sid


def create_customer(ctx: dict, p: dict) -> str:
    cid = _uuid(p.get("id"), "customer id")
    other = q1("SELECT shop_id FROM customers WHERE id = %s", [cid])
    if other:
        if str(other["shop_id"]) == ctx["shop_id"]:
            raise Duplicate(cid)
        raise Reject("Customer id is not available")
    mobile = _text(p.get("mobile"), "mobile", 16)
    x("INSERT INTO customers(id, shop_id, name, mobile_e164, notes) VALUES (%s,%s,%s,%s,%s)",
      [cid, ctx["shop_id"], _text(p.get("name"), "name", 160, True), mobile, _text(p.get("notes"), "notes", 1000)])
    return cid


def archive_customer(ctx: dict, p: dict) -> str:
    cid = _uuid(p.get("id"), "customer id")
    if not x("UPDATE customers SET status='archived', updated_at=now() WHERE id=%s AND shop_id=%s", [cid, ctx["shop_id"]]):
        raise Reject("Customer not found in this shop")
    return cid


def post_ledger_event(ctx: dict, p: dict) -> str:
    shop_id = ctx["shop_id"]
    eid = _uuid(p.get("id"), "event id")
    if q1("SELECT 1 AS x FROM ledger_events WHERE id = %s", [eid]):
        raise Reject("Entry id is not available")
    cust = _uuid(p.get("customer_id"), "customer id")
    _own_customer(shop_id, cust)
    etype = p.get("type")
    if etype not in LEDGER_TYPES:
        raise Reject("Unknown entry type")
    amount = _int(p.get("amount_paise"), "amount")
    occurred = _ts(p.get("occurred_at"), "occurred_at")
    created = _ts(p["created_at"], "created_at") if p.get("created_at") else None
    reason = _text(p.get("reason"), "reason", 500)
    reversal_of = None
    sale_id = None

    if etype in ("opening", "credit"):
        delta = amount
        if amount <= 0:
            raise Reject("Amount must be greater than zero")
    elif etype == "payment":
        delta = -amount
        if amount <= 0:
            raise Reject("Amount must be greater than zero")
        # An offline payment can exceed the balance if another device posted meanwhile. The event is a
        # fact, so it is kept (the customer simply shows an advance) rather than silently dropped.
    elif etype == "adjustment":
        raw = p.get("delta_paise")
        if isinstance(raw, bool) or not isinstance(raw, int) or abs(raw) != amount or amount <= 0:
            raise Reject("Adjustment must carry a signed amount equal to its size")
        delta = raw
        if not reason:
            raise Reject("An adjustment needs a reason")
    else:  # reversal
        reversal_of = _uuid(p.get("reversal_of_id"), "reversal_of_id")
        orig = q1("SELECT * FROM ledger_events WHERE id = %s AND shop_id = %s", [reversal_of, shop_id])
        if not orig:
            raise Reject("Entry to reverse was not found")
        if orig["type"] == "reversal":
            raise Reject("A reversal cannot be reversed")
        if str(orig["customer_id"]) != cust:
            raise Reject("Reversal customer does not match the original entry")
        if not reason:
            raise Reject("A reversal needs a reason")
        if q1("SELECT 1 AS x FROM ledger_events WHERE reversal_of_id = %s", [reversal_of]):
            raise Conflict("This entry has already been reversed")
        amount, delta = orig["amount_paise"], -orig["delta_paise"]  # always mirror the original exactly

    if p.get("sale_id"):
        sale_id = _uuid(p["sale_id"], "sale_id")
        if etype != "credit" and etype != "adjustment":
            raise Reject("Only credit or adjustment entries can reference a sale")
        sale = q1("SELECT customer_id FROM sales WHERE id = %s AND shop_id = %s", [sale_id, shop_id])
        if not sale or str(sale["customer_id"]) != cust:
            raise Reject("Linked sale not found for this customer")
        if etype == "credit":
            credit_total = q1("SELECT COALESCE(SUM(amount_paise),0)::bigint AS t FROM sale_payments "
                              "WHERE sale_id = %s AND payment_method = 'credit'", [sale_id])["t"]
            if credit_total != amount:
                raise Reject("Credit amount does not match the sale's credit portion")

    method = p.get("payment_method")
    if method is not None and method not in PAY_METHODS:
        raise Reject("Unknown payment method")

    items = p.get("items") or []
    if not isinstance(items, list):
        raise Reject("items must be a list")
    clean = []
    for it in items:
        qty = _int(it.get("quantity_milli"), "quantity", 1, 10**9)
        price = _int(it.get("unit_price_paise"), "unit price")
        line = _int(it.get("line_total_paise"), "line total")
        clean.append((_text(it.get("item_name"), "item name", 200, True), qty, _text(it.get("unit"), "unit", 20), price, line))
    if clean and etype == "credit" and not sale_id and sum(c[4] for c in clean) != amount:
        raise Reject("Item totals do not match the entry amount")

    x("""INSERT INTO ledger_events(id, shop_id, customer_id, type, amount_paise, delta_paise, occurred_at,
                client_created_at, created_by, device_id, idempotency_key, note, payment_method, payment_reference,
                sale_id, reversal_of_id, reason, confirmation_status)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'shopkeeper_recorded')""",
      [eid, shop_id, cust, etype, amount, delta, occurred, created, ctx["user_id"], ctx.get("device_id"),
       ctx["key"], _text(p.get("note"), "note", 1000), method, _text(p.get("payment_reference"), "reference", 120),
       sale_id, reversal_of, reason])
    for name, qty, unit, price, line in clean:
        x("""INSERT INTO transaction_items(ledger_event_id, item_name, quantity_milli, unit, unit_price_paise, line_total_paise)
             VALUES (%s,%s,%s,%s,%s,%s)""", [eid, name, qty, unit, price, line])
    if sale_id and etype == "credit":
        x("INSERT INTO sale_ledger_links(sale_id, ledger_transaction_id, idempotency_key) VALUES (%s,%s,%s)",
          [sale_id, eid, ctx["key"]])
    audit(ctx, "ledger_event_posted", "ledger_event", eid, {"type": etype, "amount_paise": amount})
    return eid


def post_sale(ctx: dict, p: dict) -> str:
    shop_id = ctx["shop_id"]
    sid = _uuid(p.get("id"), "sale id")
    if q1("SELECT 1 AS x FROM sales WHERE id = %s", [sid]):
        raise Reject("Sale id is not available")
    customer_id = None
    if p.get("customer_id"):
        customer_id = _uuid(p["customer_id"], "customer id")
        _own_customer(shop_id, customer_id)
    stype = p.get("sale_type")
    if stype not in ("quick", "itemized"):
        raise Reject("Unknown sale type")
    gross = _int(p.get("gross_paise"), "gross")
    discount = _int(p.get("discount_paise", 0), "discount")
    if gross <= 0 or discount >= gross:
        raise Reject("Discount must be less than the sale amount")
    payable = gross - discount

    items = p.get("items") or []
    if not isinstance(items, list) or (stype == "quick" and items) or (stype == "itemized" and not items):
        raise Reject("Sale items do not match the sale type")
    clean, item_disc = [], 0
    for it in items:
        qty = _int(it.get("quantity_milli"), "quantity", 1, 10**9)
        price = _int(it.get("unit_price_paise"), "unit price")
        idisc = _int(it.get("discount_paise", 0), "item discount")
        line = _int(it.get("line_total_paise"), "line total")
        clean.append((_text(it.get("item_name"), "item name", 200, True), qty, _text(it.get("unit"), "unit", 20), price, idisc, line))
        item_disc += idisc
    if clean:
        if sum(c[5] + c[4] for c in clean) != gross:
            raise Reject("Item totals do not add up to the sale amount")
        if discount < item_disc:
            raise Reject("Discount is less than the item discounts")

    pays = p.get("payments")
    if not isinstance(pays, list) or not pays:
        raise Reject("A sale needs at least one payment")
    cleanp, credit = [], 0
    for pay in pays:
        m = pay.get("method")
        if m not in SALE_METHODS:
            raise Reject("Unknown payment method")
        amt = _int(pay.get("amount_paise"), "payment amount", 1)
        credit += amt if m == "credit" else 0
        cleanp.append((m, amt, _text(pay.get("reference"), "reference", 120)))
    if sum(c[1] for c in cleanp) != payable:
        raise Reject("Payments must add up to the amount payable")
    if credit and not customer_id:
        raise Reject("A credit sale needs a customer")

    sale_at = _ts(p.get("sale_at"), "sale_at")
    x("""INSERT INTO sales(id, shop_id, sale_number, customer_id, sale_type, sale_at, gross_paise, discount_paise,
                           note, created_by, device_id, idempotency_key)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      [sid, shop_id, _text(p.get("sale_number"), "sale number", 40, True), customer_id, stype, sale_at, gross, discount,
       _text(p.get("note"), "note", 1000), ctx["user_id"], ctx.get("device_id"), ctx["key"]])
    for name, qty, unit, price, idisc, line in clean:
        x("""INSERT INTO sale_items(sale_id, item_name, quantity_milli, unit, unit_price_paise, discount_paise, line_total_paise)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""", [sid, name, qty, unit, price, idisc, line])
    for m, amt, ref in cleanp:
        x("INSERT INTO sale_payments(sale_id, payment_method, amount_paise, reference, paid_at) VALUES (%s,%s,%s,%s,%s)",
          [sid, m, amt, ref, sale_at])
    audit(ctx, "sale_posted", "sale", sid, {"gross_paise": gross, "credit_paise": credit})
    return sid


def post_sale_return(ctx: dict, p: dict) -> str:
    shop_id = ctx["shop_id"]
    rid = _uuid(p.get("id"), "return id")
    if q1("SELECT 1 AS x FROM sale_returns WHERE id = %s", [rid]):
        raise Reject("Return id is not available")
    sale_id = _uuid(p.get("sale_id"), "sale id")
    sale = q1("SELECT * FROM sales WHERE id = %s AND shop_id = %s", [sale_id, shop_id])
    if not sale:
        raise Reject("Sale not found in this shop")
    amount = _int(p.get("return_paise"), "return amount", 1)
    method = p.get("refund_method")
    if method not in REFUND_METHODS:
        raise Reject("Unknown refund method")
    if method == "khata" and not sale["customer_id"]:
        raise Reject("Khata refund needs a customer on the sale")
    returned = q1("SELECT COALESCE(SUM(return_paise),0)::bigint AS t FROM sale_returns WHERE sale_id = %s", [sale_id])["t"]
    if amount > sale["gross_paise"] - sale["discount_paise"] - returned:
        raise Conflict("Return is more than the remaining sale value")
    x("""INSERT INTO sale_returns(id, shop_id, sale_id, return_paise, reason, refund_method, returned_at, actor_id, idempotency_key)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      [rid, shop_id, sale_id, amount, _text(p.get("reason"), "reason", 500), method, _ts(p.get("returned_at"), "returned_at"),
       ctx["user_id"], ctx["key"]])
    audit(ctx, "sale_return_posted", "sale_return", rid, {"return_paise": amount})
    return rid


def audit(ctx: dict, action: str, entity_type: str, entity_id: str, meta: dict) -> None:
    import json
    x("""INSERT INTO audit_logs(shop_id, actor_id, action, entity_type, entity_id, metadata)
         VALUES (%s,%s,%s,%s,%s,%s)""", [ctx["shop_id"], ctx["user_id"], action, entity_type, entity_id, json.dumps(meta)])


class Duplicate(Exception):
    def __init__(self, server_id: str):
        self.server_id = server_id


HANDLERS = {
    ("shop", "create"): create_shop,
    ("customer", "create"): create_customer,
    ("customer", "archive"): archive_customer,
    ("ledger_event", "post"): post_ledger_event,
    ("sale", "post"): post_sale,
    ("sale_return", "post"): post_sale_return,
}


def process_batch(user_id: str, device_id: str | None, items: list) -> list[dict]:
    """Process items in order (the outbox sequence). Each item has its own transaction, so one bad
    item never blocks or rolls back the good ones."""
    results = []
    shop = q1("SELECT id FROM shops WHERE owner_user_id = %s ORDER BY created_at LIMIT 1", [user_id])
    ctx = {"user_id": user_id, "device_id": device_id, "shop_id": str(shop["id"]) if shop else None}
    for it in items:
        key = it.get("idempotency_key") if isinstance(it, dict) else None
        res = {"idempotency_key": key}
        try:
            key = _key(key)
            ctx["key"] = key
            entity, op = it.get("entity"), it.get("op")
            handler = HANDLERS.get((entity, op))
            if not handler:
                raise Reject(f"Unsupported item {entity}/{op}")
            payload = it.get("payload")
            if not isinstance(payload, dict):
                raise Reject("payload must be an object")
            is_shop_create = (entity, op) == ("shop", "create")
            if not is_shop_create:
                if not ctx["shop_id"]:
                    raise Reject("Create your shop first")
                receipt = q1("SELECT server_id FROM sync_receipts WHERE shop_id = %s AND idempotency_key = %s",
                             [ctx["shop_id"], key])
                if receipt:
                    results.append({**res, "status": "duplicate", "server_id": str(receipt["server_id"])})
                    continue
                if not subs.can_write(ctx["shop_id"]):
                    raise Reject("subscription_required: your plan has expired, so changes are read-only. "
                                 "Your records are safe.")
            with atomic():
                try:
                    server_id = handler(ctx, payload)
                except Duplicate as d:
                    results.append({**res, "status": "duplicate", "server_id": d.server_id})
                    continue
                x("""INSERT INTO sync_receipts(shop_id, idempotency_key, entity, status, server_id, device_id)
                     VALUES (%s,%s,%s,'accepted',%s,%s) ON CONFLICT DO NOTHING""",
                  [ctx["shop_id"], key, entity, server_id, device_id])
            results.append({**res, "status": "accepted", "server_id": server_id})
        except Reject as e:
            results.append({**res, "status": "rejected", "error": str(e)})
        except Conflict as e:
            results.append({**res, "status": "conflict", "error": str(e)})
        except IntegrityError:
            log.exception("sync integrity error")
            results.append({**res, "status": "conflict", "error": "This entry clashes with an existing record"})
        except DatabaseError:
            log.exception("sync database error")
            results.append({**res, "status": "rejected", "error": "Could not store this entry"})
    return results
