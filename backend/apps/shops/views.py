from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.db import q, q1
from apps.common.errors import ApiProblem

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
        search = f"%{request.query_params.get('search', '').strip().lower()}%"
        rows = q("""SELECT b.customer_id, b.name, b.balance_paise, b.last_activity_at, c.mobile_e164
                      FROM customer_balances b JOIN customers c ON c.id = b.customer_id
                     WHERE b.shop_id = %s AND (LOWER(b.name) LIKE %s OR COALESCE(c.mobile_e164,'') LIKE %s)
                     ORDER BY b.balance_paise DESC, b.name LIMIT 500""", [shop["id"], search, search])
        return Response({"results": [{"id": str(r["customer_id"]), "name": r["name"], "mobile": r["mobile_e164"],
                                      "balance_paise": r["balance_paise"], "last_activity_at": r["last_activity_at"]}
                                     for r in rows]})


class LedgerView(APIView):
    def get(self, request, shop_id, customer_id):
        shop = shop_for_user(request.user.id, shop_id)
        cust = q1("SELECT id, name FROM customers WHERE id = %s AND shop_id = %s", [customer_id, shop["id"]])
        if not cust:
            raise ApiProblem("Customer not found.", "not_found", 404)
        events = q("""SELECT id, type, amount_paise, delta_paise, occurred_at, note, payment_method, reason,
                             reversal_of_id, sale_id, confirmation_status,
                             (SUM(delta_paise) OVER (ORDER BY occurred_at, server_created_at, id))::bigint AS running_balance_paise
                        FROM ledger_events WHERE shop_id = %s AND customer_id = %s
                       ORDER BY occurred_at, server_created_at, id""", [shop["id"], cust["id"]])
        items = q("""SELECT t.ledger_event_id, t.item_name, t.quantity_milli, t.unit, t.unit_price_paise, t.line_total_paise
                       FROM transaction_items t JOIN ledger_events e ON e.id = t.ledger_event_id
                      WHERE e.shop_id = %s AND e.customer_id = %s""", [shop["id"], cust["id"]])
        by_event: dict = {}
        for i in items:
            by_event.setdefault(str(i["ledger_event_id"]), []).append({k: v for k, v in i.items() if k != "ledger_event_id"})
        out = [{**{k: (str(v) if k in ("id", "reversal_of_id", "sale_id") and v else v) for k, v in e.items()},
                "items": by_event.get(str(e["id"]), [])} for e in events]
        balance = out[-1]["running_balance_paise"] if out else 0
        return Response({"customer": {"id": str(cust["id"]), "name": cust["name"]}, "balance_paise": balance, "events": out})


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
        bal = q("SELECT balance_paise FROM customer_balances WHERE shop_id = %s", [sid])
        status = q("""SELECT confirmation_status AS s, SUM(amount_paise)::bigint AS t FROM ledger_events e
                       WHERE shop_id = %s AND type = 'credit'
                         AND NOT EXISTS (SELECT 1 FROM ledger_events r WHERE r.reversal_of_id = e.id)
                       GROUP BY confirmation_status""", [sid])
        tz = ZoneInfo(shop["timezone"])
        now = timezone.now().astimezone(tz)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        end = day + timedelta(days=1)
        return Response({
            "khata": {"total_receivable_paise": sum(b["balance_paise"] for b in bal if b["balance_paise"] > 0),
                      "customers_with_balance": sum(1 for b in bal if b["balance_paise"] > 0),
                      "credit_by_status": {r["s"]: r["t"] for r in status}},
            "sales_today": _sales_between(sid, day, end),
            "sales_month": _sales_between(sid, month, end),
        })


class ReceivablesReportView(APIView):
    def get(self, request, shop_id):
        shop = shop_for_user(request.user.id, shop_id)
        rows = q("""SELECT customer_id, name, balance_paise, last_activity_at FROM customer_balances
                     WHERE shop_id = %s AND balance_paise > 0 ORDER BY balance_paise DESC""", [shop["id"]])
        return Response({"generated_at": timezone.now(), "total_paise": sum(r["balance_paise"] for r in rows),
                         "note": "Amounts are as recorded by the shopkeeper unless marked customer confirmed.",
                         "results": [{**r, "customer_id": str(r["customer_id"])} for r in rows]})
