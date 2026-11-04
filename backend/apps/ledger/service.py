"""Business rules for shops, customers and ledger events. Input is already parsed (typed); the rules live here.

Callers: apps.sync.handlers (the app's outbox), apps.shops.views (reads) and, next, the website.

Rules that never change:
  * money is whole paise; the sign of every delta is decided here, never by the caller,
  * confirmation_status is always written as 'shopkeeper_recorded' (only the server-side customer workflow may move it),
  * every row is bound to the shop it is written for (no cross-tenant writes),
  * ledger rows are append-only (database triggers); a correction is a reversal event that mirrors the original.
"""
import json

from apps.common.db import q, q1, x
from apps.subscriptions import service as subs

from .errors import Conflict, Duplicate, Reject

MAX_PAISE = 10_000_000_000  # Rs 10 crore: anything above is certainly a client bug
LEDGER_TYPES = {"opening", "credit", "payment", "adjustment", "reversal"}
PAY_METHODS = {"cash", "upi", "card", "bank", "other"}


# ───────────────────────── audit ─────────────────────────
def audit(shop_id, actor_id, action: str, entity_type: str, entity_id: str, meta: dict) -> None:
    x("""INSERT INTO audit_logs(shop_id, actor_id, action, entity_type, entity_id, metadata)
         VALUES (%s,%s,%s,%s,%s,%s)""", [shop_id, actor_id, action, entity_type, entity_id, json.dumps(meta)])


# ───────────────────────── shops and customers ─────────────────────────
def create_shop(*, user_id: str, shop_id: str, name: str, category: str | None = None, address: str | None = None,
                language: str = "en") -> str:
    existing = q1("SELECT owner_user_id FROM shops WHERE id = %s", [shop_id])
    if existing:
        if str(existing["owner_user_id"]) == str(user_id):
            raise Duplicate(shop_id)
        raise Reject("Shop id is not available")
    if q1("SELECT 1 AS x FROM shops WHERE owner_user_id = %s", [user_id]):
        raise Conflict("This account already has a shop")
    x("""INSERT INTO shops(id, owner_user_id, name, category, address, timezone, language)
         VALUES (%s,%s,%s,%s,%s,%s,%s)""",
      [shop_id, user_id, name, category, address, "Asia/Kolkata", language if language in ("en", "hi", "pa") else "en"])
    x("INSERT INTO shop_members(shop_id, user_id, role, status) VALUES (%s,%s,'owner','active')", [shop_id, user_id])
    subs.create_for_shop(shop_id, user_id)
    return shop_id


def own_customer(shop_id: str, customer_id: str) -> dict:
    row = q1("SELECT id, status FROM customers WHERE id = %s AND shop_id = %s", [customer_id, shop_id])
    if not row:
        raise Reject("Customer not found in this shop")
    return row


def create_customer(*, shop_id: str, customer_id: str, name: str, mobile: str | None = None, notes: str | None = None) -> str:
    other = q1("SELECT shop_id FROM customers WHERE id = %s", [customer_id])
    if other:
        if str(other["shop_id"]) == str(shop_id):
            raise Duplicate(customer_id)
        raise Reject("Customer id is not available")
    x("INSERT INTO customers(id, shop_id, name, mobile_e164, notes) VALUES (%s,%s,%s,%s,%s)",
      [customer_id, shop_id, name, mobile, notes])
    return customer_id


def archive_customer(*, shop_id: str, customer_id: str) -> str:
    if not x("UPDATE customers SET status='archived', updated_at=now() WHERE id=%s AND shop_id=%s", [customer_id, shop_id]):
        raise Reject("Customer not found in this shop")
    return customer_id


# ───────────────────────── ledger events ─────────────────────────
def post_event(*, shop_id: str, user_id: str, device_id: str | None, key: str, event_id: str, customer_id: str, etype: str,
               amount_paise: int, occurred_at, created_at=None, note: str | None = None, reason: str | None = None,
               reversal_of_id: str | None = None, delta_paise=None, sale_id: str | None = None,
               payment_method: str | None = None, payment_reference: str | None = None, items=()) -> str:
    """Store one ledger event. items: (item_name, quantity_milli, unit, unit_price_paise, line_total_paise) tuples."""
    if q1("SELECT 1 AS x FROM ledger_events WHERE id = %s", [event_id]):
        raise Reject("Entry id is not available")
    own_customer(shop_id, customer_id)
    if etype not in LEDGER_TYPES:
        raise Reject("Unknown entry type")
    amount = amount_paise
    reversal_of = None

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
        raw = delta_paise
        if isinstance(raw, bool) or not isinstance(raw, int) or abs(raw) != amount or amount <= 0:
            raise Reject("Adjustment must carry a signed amount equal to its size")
        delta = raw
        if not reason:
            raise Reject("An adjustment needs a reason")
    else:  # reversal
        reversal_of = reversal_of_id
        orig = q1("SELECT * FROM ledger_events WHERE id = %s AND shop_id = %s", [reversal_of, shop_id])
        if not orig:
            raise Reject("Entry to reverse was not found")
        if orig["type"] == "reversal":
            raise Reject("A reversal cannot be reversed")
        if str(orig["customer_id"]) != str(customer_id):
            raise Reject("Reversal customer does not match the original entry")
        if not reason:
            raise Reject("A reversal needs a reason")
        if q1("SELECT 1 AS x FROM ledger_events WHERE reversal_of_id = %s", [reversal_of]):
            raise Conflict("This entry has already been reversed")
        amount, delta = orig["amount_paise"], -orig["delta_paise"]  # always mirror the original exactly

    if sale_id:
        if etype != "credit" and etype != "adjustment":
            raise Reject("Only credit or adjustment entries can reference a sale")
        sale = q1("SELECT customer_id FROM sales WHERE id = %s AND shop_id = %s", [sale_id, shop_id])
        if not sale or str(sale["customer_id"]) != str(customer_id):
            raise Reject("Linked sale not found for this customer")
        if etype == "credit":
            credit_total = q1("SELECT COALESCE(SUM(amount_paise),0)::bigint AS t FROM sale_payments "
                              "WHERE sale_id = %s AND payment_method = 'credit'", [sale_id])["t"]
            if credit_total != amount:
                raise Reject("Credit amount does not match the sale's credit portion")

    if payment_method is not None and payment_method not in PAY_METHODS:
        raise Reject("Unknown payment method")
    items = list(items)
    if items and etype == "credit" and not sale_id and sum(i[4] for i in items) != amount:
        raise Reject("Item totals do not match the entry amount")

    x("""INSERT INTO ledger_events(id, shop_id, customer_id, type, amount_paise, delta_paise, occurred_at,
                client_created_at, created_by, device_id, idempotency_key, note, payment_method, payment_reference,
                sale_id, reversal_of_id, reason, confirmation_status)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'shopkeeper_recorded')""",
      [event_id, shop_id, customer_id, etype, amount, delta, occurred_at, created_at, user_id, device_id,
       key, note, payment_method, payment_reference, sale_id, reversal_of, reason])
    for name, qty, unit, price, line in items:
        x("""INSERT INTO transaction_items(ledger_event_id, item_name, quantity_milli, unit, unit_price_paise, line_total_paise)
             VALUES (%s,%s,%s,%s,%s,%s)""", [event_id, name, qty, unit, price, line])
    if sale_id and etype == "credit":
        x("INSERT INTO sale_ledger_links(sale_id, ledger_transaction_id, idempotency_key) VALUES (%s,%s,%s)",
          [sale_id, event_id, key])
    audit(shop_id, user_id, "ledger_event_posted", "ledger_event", event_id, {"type": etype, "amount_paise": amount})
    return event_id


# ───────────────────────── reads ─────────────────────────
def list_customers(shop_id: str, search: str = "") -> list[dict]:
    pattern = f"%{search.strip().lower()}%"
    return q("""SELECT b.customer_id, b.name, b.balance_paise, b.last_activity_at, c.mobile_e164
                  FROM customer_balances b JOIN customers c ON c.id = b.customer_id
                 WHERE b.shop_id = %s AND (LOWER(b.name) LIKE %s OR COALESCE(c.mobile_e164,'') LIKE %s)
                 ORDER BY b.balance_paise DESC, b.name LIMIT 500""", [shop_id, pattern, pattern])


def customer_ledger(shop_id: str, customer_id: str) -> dict | None:
    """One customer's full history with a running balance, or None if the customer is not in this shop."""
    cust = q1("SELECT id, name FROM customers WHERE id = %s AND shop_id = %s", [customer_id, shop_id])
    if not cust:
        return None
    events = q("""SELECT id, type, amount_paise, delta_paise, occurred_at, note, payment_method, reason,
                         reversal_of_id, sale_id, confirmation_status,
                         (SUM(delta_paise) OVER (ORDER BY occurred_at, server_created_at, id))::bigint AS running_balance_paise
                    FROM ledger_events WHERE shop_id = %s AND customer_id = %s
                   ORDER BY occurred_at, server_created_at, id""", [shop_id, cust["id"]])
    items = q("""SELECT t.ledger_event_id, t.item_name, t.quantity_milli, t.unit, t.unit_price_paise, t.line_total_paise
                   FROM transaction_items t JOIN ledger_events e ON e.id = t.ledger_event_id
                  WHERE e.shop_id = %s AND e.customer_id = %s""", [shop_id, cust["id"]])
    by_event: dict = {}
    for i in items:
        by_event.setdefault(str(i["ledger_event_id"]), []).append({k: v for k, v in i.items() if k != "ledger_event_id"})
    out = [{**{k: (str(v) if k in ("id", "reversal_of_id", "sale_id") and v else v) for k, v in e.items()},
            "items": by_event.get(str(e["id"]), [])} for e in events]
    balance = out[-1]["running_balance_paise"] if out else 0
    return {"customer": {"id": str(cust["id"]), "name": cust["name"]}, "balance_paise": balance, "events": out}


def receivables(shop_id: str) -> list[dict]:
    return q("""SELECT customer_id, name, balance_paise, last_activity_at FROM customer_balances
                 WHERE shop_id = %s AND balance_paise > 0 ORDER BY balance_paise DESC""", [shop_id])


def khata_summary(shop_id: str) -> dict:
    """Total still to collect, how many customers owe, and credit grouped by confirmation status."""
    bal = q("SELECT balance_paise FROM customer_balances WHERE shop_id = %s", [shop_id])
    status = q("""SELECT confirmation_status AS s, SUM(amount_paise)::bigint AS t FROM ledger_events e
                   WHERE shop_id = %s AND type = 'credit'
                     AND NOT EXISTS (SELECT 1 FROM ledger_events r WHERE r.reversal_of_id = e.id)
                   GROUP BY confirmation_status""", [shop_id])
    return {"total_receivable_paise": sum(b["balance_paise"] for b in bal if b["balance_paise"] > 0),
            "customers_with_balance": sum(1 for b in bal if b["balance_paise"] > 0),
            "credit_by_status": {r["s"]: r["t"] for r in status}}
