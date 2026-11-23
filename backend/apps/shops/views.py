from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.db import q, q1
from apps.common.errors import ApiProblem
from apps.ledger import service as ledger

from .access import shop_for_user


def _shop_json(s: dict) -> dict:
    return {"id": str(s["id"]), "name": s["name"], "category": s["category"], "address": s["address"],
            "code": s["shop_id_code"], "timezone": s["timezone"], "language": s["language"], "status": s["status"]}


class ShopsView(APIView):
    def get(self, request):
        rows = q("""SELECT s.* FROM shops s WHERE s.owner_user_id = %s
                    OR EXISTS (SELECT 1 FROM shop_members m WHERE m.shop_id = s.id AND m.user_id = %s AND m.status = 'active')
                    ORDER BY s.created_at""", [request.user.id, request.user.id])
        return Response({"results": [_shop_json(s) for s in rows]})


class ShopDetailView(APIView):
    def get(self, request, shop_id):
        return Response(_shop_json(shop_for_user(request.user.id, shop_id)))


class CustomersView(APIView):
    def get(self, request, shop_id):
        shop = shop_for_user(request.user.id, shop_id)
        rows = ledger.list_customers(shop["id"], request.query_params.get("search", ""))
        return Response({"results": [{"id": str(r["customer_id"]), "name": r["name"], "mobile": r["mobile_e164"],
                                      "balance_paise": r["balance_paise"], "last_activity_at": r["last_activity_at"]}
                                     for r in rows]})


class LedgerView(APIView):
    def get(self, request, shop_id, customer_id):
        shop = shop_for_user(request.user.id, shop_id)
        data = ledger.customer_ledger(shop["id"], customer_id)
        if data is None:
            raise ApiProblem("Customer not found.", "not_found", 404)
        return Response(data)


def _sales_between(shop_id, start, end) -> dict:
    s = q1("""SELECT COALESCE(SUM(gross_paise),0)::bigint AS gross, COALESCE(SUM(discount_paise),0)::bigint AS discount, COUNT(*) AS n
                FROM sales WHERE shop_id = %s AND sale_at >= %s AND sale_at < %s""", [shop_id, start, end])
    ret = q1("""SELECT COALESCE(SUM(return_paise),0)::bigint AS t FROM sale_returns
                 WHERE shop_id = %s AND returned_at >= %s AND returned_at < %s""", [shop_id, start, end])["t"]
    pay = q("""SELECT p.payment_method AS m, SUM(p.amount_paise)::bigint AS t FROM sale_payments p JOIN sales s ON s.id = p.sale_id
                WHERE s.shop_id = %s AND s.sale_at >= %s AND s.sale_at < %s GROUP BY p.payment_method""", [shop_id, start, end])
    by = {r["m"]: r["t"] for r in pay}
    old = q1("""SELECT COALESCE(SUM(amount_paise),0)::bigint AS t FROM ledger_events e
                 WHERE shop_id = %s AND type = 'payment' AND occurred_at >= %s AND occurred_at < %s
                   AND NOT EXISTS (SELECT 1 FROM ledger_events r WHERE r.reversal_of_id = e.id)""", [shop_id, start, end])["t"]
    return {"gross_paise": s["gross"], "discount_paise": s["discount"], "returns_paise": ret,
            "net_paise": s["gross"] - s["discount"] - ret, "sale_count": s["n"],
            # collections are cash flow, NOT sales; old-dues collections are never counted as sales
            "collected_paise": sum(v for k, v in by.items() if k != "credit"), "credit_sales_paise": by.get("credit", 0),
            "old_dues_collected_paise": old, "by_method": by}


class DashboardView(APIView):
    def get(self, request, shop_id):
        shop = shop_for_user(request.user.id, shop_id)
        sid = shop["id"]
        tz = ZoneInfo(shop["timezone"])
        now = timezone.now().astimezone(tz)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        end = day + timedelta(days=1)
        return Response({
            "khata": ledger.khata_summary(sid),
            "sales_today": _sales_between(sid, day, end),
            "sales_month": _sales_between(sid, month, end),
        })


class ReceivablesReportView(APIView):
    def get(self, request, shop_id):
        shop = shop_for_user(request.user.id, shop_id)
        rows = ledger.receivables(shop["id"])
        return Response({"generated_at": timezone.now(), "total_paise": sum(r["balance_paise"] for r in rows),
                         "note": "Amounts are as recorded by the shopkeeper unless marked customer confirmed.",
                         "results": [{**r, "customer_id": str(r["customer_id"])} for r in rows]})


def _iso(v):
    return v.isoformat() if v is not None else None


class RestoreView(APIView):
    """Everything the shopkeeper's phone needs to rebuild its local copy after a fresh login or reinstall.
    The server is the source of truth, so a shop is never asked for twice."""

    def get(self, request):
        shop = q1("""SELECT s.* FROM shops s WHERE s.owner_user_id = %s
                      OR EXISTS (SELECT 1 FROM shop_members m WHERE m.shop_id = s.id AND m.user_id = %s AND m.status = 'active')
                      ORDER BY s.created_at LIMIT 1""", [request.user.id, request.user.id])
        if not shop:
            return Response({"shop": None})
        sid = shop["id"]
        owner = q1("SELECT name, mobile_e164 FROM users WHERE id = %s", [shop["owner_user_id"]]) or {}
        customers = q("SELECT id, name, mobile_e164, notes, status, created_at FROM customers WHERE shop_id = %s", [sid])
        events = q("""SELECT id, customer_id, type, amount_paise, delta_paise, occurred_at, server_created_at, note, payment_method,
                             payment_reference, sale_id, reversal_of_id, reason, confirmation_status, idempotency_key
                        FROM ledger_events WHERE shop_id = %s ORDER BY occurred_at""", [sid])
        items = q("""SELECT t.id, t.ledger_event_id, t.item_name, t.quantity_milli, t.unit, t.unit_price_paise, t.line_total_paise
                       FROM transaction_items t JOIN ledger_events e ON e.id = t.ledger_event_id WHERE e.shop_id = %s""", [sid])
        sales = q("""SELECT id, sale_number, customer_id, sale_type, sale_at, server_created_at, gross_paise, discount_paise, note,
                            idempotency_key FROM sales WHERE shop_id = %s AND status = 'posted' ORDER BY sale_at""", [sid])
        sale_items = q("""SELECT i.id, i.sale_id, i.item_name, i.quantity_milli, i.unit, i.unit_price_paise, i.discount_paise,
                                 i.line_total_paise FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE s.shop_id = %s""", [sid])
        pays = q("""SELECT p.id, p.sale_id, p.payment_method, p.amount_paise, p.reference, p.paid_at
                      FROM sale_payments p JOIN sales s ON s.id = p.sale_id WHERE s.shop_id = %s AND p.status = 'posted'""", [sid])
        returns = q("""SELECT id, sale_id, return_paise, reason, refund_method, returned_at, idempotency_key
                         FROM sale_returns WHERE shop_id = %s""", [sid])
        S = str
        return Response({
            "shop": {**_shop_json(shop), "owner_name": owner.get("name"), "owner_mobile": owner.get("mobile_e164"),
                     "created_at": _iso(shop["created_at"])},
            "customers": [{"id": S(c["id"]), "name": c["name"], "mobile": c["mobile_e164"], "notes": c["notes"],
                           "archived": c["status"] == "archived", "created_at": _iso(c["created_at"])} for c in customers],
            "ledger_events": [{**{k: v for k, v in e.items() if k not in ("occurred_at", "server_created_at")},
                               "id": S(e["id"]), "customer_id": S(e["customer_id"]),
                               "sale_id": S(e["sale_id"]) if e["sale_id"] else None,
                               "reversal_of_id": S(e["reversal_of_id"]) if e["reversal_of_id"] else None,
                               "occurred_at": _iso(e["occurred_at"]), "created_at": _iso(e["server_created_at"])} for e in events],
            "ledger_items": [{**i, "id": S(i["id"]), "event_id": S(i["ledger_event_id"])} for i in items],
            "sales": [{**{k: v for k, v in r.items() if k not in ("sale_at", "server_created_at")},
                       "id": S(r["id"]), "customer_id": S(r["customer_id"]) if r["customer_id"] else None,
                       "sale_at": _iso(r["sale_at"]), "created_at": _iso(r["server_created_at"])} for r in sales],
            "sale_items": [{**i, "id": S(i["id"]), "sale_id": S(i["sale_id"])} for i in sale_items],
            "sale_payments": [{**p, "id": S(p["id"]), "sale_id": S(p["sale_id"]), "paid_at": _iso(p["paid_at"])} for p in pays],
            "sale_returns": [{**r, "id": S(r["id"]), "sale_id": S(r["sale_id"]), "returned_at": _iso(r["returned_at"])} for r in returns],
        })


def _my_customer_rows(user_id):
    """Customer records that belong to this signed-in person: linked explicitly, or matching their verified mobile number."""
    me = q1("SELECT mobile_e164 FROM users WHERE id = %s", [user_id]) or {}
    return q("""SELECT c.id, c.shop_id, s.name AS shop_name, s.address AS shop_address, o.name AS owner_name,
                       o.mobile_e164 AS owner_mobile
                  FROM customers c JOIN shops s ON s.id = c.shop_id JOIN users o ON o.id = s.owner_user_id
                 WHERE c.status = 'active' AND (c.linked_user_id = %s OR (c.mobile_e164 IS NOT NULL AND c.mobile_e164 = %s))
                 ORDER BY s.name""", [user_id, me.get("mobile_e164") or ""])


class MyKhataView(APIView):
    """Customer portal: the shops that have this person on their khata, with what they owe each."""

    def get(self, request):
        rows = _my_customer_rows(request.user.id)
        out, owed = [], 0
        for r in rows:
            b = q1("SELECT COALESCE(SUM(delta_paise),0)::bigint AS b, MAX(occurred_at) AS last FROM ledger_events "
                   "WHERE shop_id = %s AND customer_id = %s", [r["shop_id"], r["id"]])
            owed += max(b["b"], 0)
            out.append({"customer_id": str(r["id"]), "shop_name": r["shop_name"], "shop_address": r["shop_address"],
                        "owner_name": r["owner_name"], "owner_mobile": r["owner_mobile"],
                        "balance_paise": b["b"], "last_activity_at": _iso(b["last"])})
        return Response({"total_owed_paise": owed, "results": out})


class MyKhataDetailView(APIView):
    def get(self, request, customer_id):
        mine = {str(r["id"]): r for r in _my_customer_rows(request.user.id)}
        row = mine.get(str(customer_id))
        if not row:
            raise ApiProblem("Not found.", "not_found", 404)
        data = ledger.customer_ledger(row["shop_id"], customer_id)
        if data is None:
            raise ApiProblem("Not found.", "not_found", 404)
        return Response({**data, "shop_name": row["shop_name"], "owner_name": row["owner_name"],
                         "owner_mobile": row["owner_mobile"]})
