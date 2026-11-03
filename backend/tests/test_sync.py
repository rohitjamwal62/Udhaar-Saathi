import uuid

from apps.common.db import q, q1

from .helpers import (API, customer_item, iso, item, ledger_item, ledger_payload, register, setup_shop_with_customer,
                      shop_item, sync)


def balance(shop_id, cust_id):
    return q1("SELECT balance_paise FROM customer_balances WHERE shop_id=%s AND customer_id=%s", [shop_id, cust_id])["balance_paise"]


def test_vertical_slice_credit_payment_reversal():
    c, shop_id, cust = setup_shop_with_customer()
    credit = ledger_payload(cust, "credit", 65000)
    pay = ledger_payload(cust, "payment", 20000)
    res = sync(c, [ledger_item(credit), ledger_item(pay)])
    assert [r["status"] for r in res] == ["accepted", "accepted"]
    assert balance(shop_id, cust) == 45000
    rev = ledger_payload(cust, "reversal", 0, reversal_of_id=pay["id"], reason="entered twice", delta_paise=0)
    assert sync(c, [ledger_item(rev)])[0]["status"] == "accepted"
    assert balance(shop_id, cust) == 65000  # reversal mirrors the original exactly
    ledger = c.get(f"{API}/shops/{shop_id}/customers/{cust}/ledger")
    assert ledger.data["balance_paise"] == 65000 and len(ledger.data["events"]) == 3


def test_retry_is_idempotent_no_double_posting():
    c, shop_id, cust = setup_shop_with_customer()
    credit = ledger_item(ledger_payload(cust, "credit", 10000))
    first = sync(c, [credit])[0]
    again = sync(c, [credit])[0]
    assert first["status"] == "accepted" and again["status"] == "duplicate" and again["server_id"] == first["server_id"]
    assert balance(shop_id, cust) == 10000
    assert q1("SELECT COUNT(*) AS n FROM ledger_events WHERE shop_id=%s", [shop_id])["n"] == 1


def test_client_cannot_forge_customer_confirmation():
    c, shop_id, cust = setup_shop_with_customer()
    p = ledger_payload(cust, "credit", 5000, confirmation_status="customer_confirmed")
    assert sync(c, [ledger_item(p)])[0]["status"] == "accepted"
    row = q1("SELECT confirmation_status FROM ledger_events WHERE id=%s", [p["id"]])
    assert row["confirmation_status"] == "shopkeeper_recorded"


def test_server_recomputes_delta_sign_and_rejects_bad_money():
    c, shop_id, cust = setup_shop_with_customer()
    pay = ledger_payload(cust, "payment", 3000, delta_paise=+999999)  # lying client
    assert sync(c, [ledger_item(pay)])[0]["status"] == "accepted"
    assert q1("SELECT delta_paise FROM ledger_events WHERE id=%s", [pay["id"]])["delta_paise"] == -3000
    for bad in (-5, 12.5, "100", True, 10**12):
        r = sync(c, [ledger_item(ledger_payload(cust, "credit", bad))])[0]
        assert r["status"] == "rejected", bad


def test_double_reversal_is_a_conflict():
    c, shop_id, cust = setup_shop_with_customer()
    credit = ledger_payload(cust, "credit", 1000)
    sync(c, [ledger_item(credit)])
    r1 = ledger_payload(cust, "reversal", 0, reversal_of_id=credit["id"], reason="mistake", delta_paise=0)
    r2 = ledger_payload(cust, "reversal", 0, reversal_of_id=credit["id"], reason="again", delta_paise=0)
    res = sync(c, [ledger_item(r1), ledger_item(r2)])
    assert [r["status"] for r in res] == ["accepted", "conflict"]
    assert balance(shop_id, cust) == 0


def test_tenant_isolation():
    a, shop_a, cust_a = setup_shop_with_customer("9876500001")
    b, session_b = register("9876500002")
    s_item, shop_b = shop_item()
    sync(b, [s_item])
    # B cannot read A's shop or ledger (404, indistinguishable from a missing id)
    assert b.get(f"{API}/shops/{shop_a}").status_code == 404
    assert b.get(f"{API}/shops/{shop_a}/customers").status_code == 404
    assert b.get(f"{API}/shops/{shop_a}/customers/{cust_a}/ledger").status_code == 404
    assert b.get(f"{API}/shops/{shop_b}/customers/{cust_a}/ledger").status_code == 404
    # B cannot post into A's customer or reuse A's ids
    assert sync(b, [ledger_item(ledger_payload(cust_a, "credit", 100))])[0]["status"] == "rejected"
    dup_customer = item("customer", "create", {"id": cust_a, "name": "Steal"}, "customer:steal")
    assert sync(b, [dup_customer])[0]["status"] == "rejected"
    steal_shop = item("shop", "create", {"id": shop_a, "name": "Steal"}, "shop:steal")
    assert sync(b, [steal_shop])[0]["status"] in ("rejected", "conflict")
    assert q1("SELECT COUNT(*) AS n FROM ledger_events WHERE shop_id=%s", [shop_a])["n"] == 0


def test_one_bad_item_does_not_block_the_batch():
    c, shop_id, cust = setup_shop_with_customer()
    good1 = ledger_item(ledger_payload(cust, "credit", 100))
    bad = ledger_item(ledger_payload(cust, "credit", -1))
    good2 = ledger_item(ledger_payload(cust, "credit", 200))
    assert [r["status"] for r in sync(c, [good1, bad, good2])] == ["accepted", "rejected", "accepted"]
    assert balance(shop_id, cust) == 300


def _sale(cust, payments, gross=10000, discount=1000, items=None, stype="quick"):
    sid = str(uuid.uuid4())
    return sid, {"id": sid, "sale_number": "S-1", "customer_id": cust, "sale_type": stype, "sale_at": iso(),
                 "gross_paise": gross, "discount_paise": discount, "note": None, "items": items or [], "payments": payments}


def test_credit_sale_links_exactly_one_khata_entry_and_does_not_double_count():
    c, shop_id, cust = setup_shop_with_customer()
    sid, sale = _sale(cust, [{"method": "cash", "amount_paise": 6000, "reference": None},
                             {"method": "credit", "amount_paise": 3000, "reference": None}])
    credit = ledger_payload(cust, "credit", 3000, sale_id=sid)
    res = sync(c, [item("sale", "post", sale, f"sale:{sid}"), ledger_item(credit)])
    assert [r["status"] for r in res] == ["accepted", "accepted"]
    assert balance(shop_id, cust) == 3000  # only the credit portion becomes debt
    # a second khata credit for the same sale is refused
    dup = ledger_payload(cust, "credit", 3000, sale_id=sid)
    assert sync(c, [ledger_item(dup)])[0]["status"] in ("conflict", "rejected")
    assert balance(shop_id, cust) == 3000
    # later payment of that debt is collection, not a sale
    sync(c, [ledger_item(ledger_payload(cust, "payment", 3000))])
    dash = c.get(f"{API}/shops/{shop_id}/dashboard").data
    assert dash["sales_today"]["net_paise"] == 9000
    assert dash["sales_today"]["collected_paise"] == 6000 and dash["sales_today"]["credit_sales_paise"] == 3000
    assert dash["sales_today"]["old_dues_collected_paise"] == 3000
    assert dash["khata"]["total_receivable_paise"] == 0


def test_sale_validation():
    c, shop_id, cust = setup_shop_with_customer()
    _, wrong_sum = _sale(cust, [{"method": "cash", "amount_paise": 100, "reference": None}])
    _, no_customer = _sale(None, [{"method": "credit", "amount_paise": 9000, "reference": None}])
    _, bad_method = _sale(cust, [{"method": "bitcoin", "amount_paise": 9000, "reference": None}])
    _, big_discount = _sale(cust, [{"method": "cash", "amount_paise": 1, "reference": None}], discount=10000)
    res = sync(c, [item("sale", "post", p, f"sale:{p['id']}") for p in (wrong_sum, no_customer, bad_method, big_discount)])
    assert [r["status"] for r in res] == ["rejected"] * 4
    assert q1("SELECT COUNT(*) AS n FROM sales WHERE shop_id=%s", [shop_id])["n"] == 0


def test_sale_return_cannot_exceed_remaining_value():
    c, shop_id, cust = setup_shop_with_customer()
    sid, sale = _sale(cust, [{"method": "upi", "amount_paise": 9000, "reference": None}])
    sync(c, [item("sale", "post", sale, f"sale:{sid}")])

    def ret(amount):
        rid = str(uuid.uuid4())
        return item("sale_return", "post", {"id": rid, "sale_id": sid, "return_paise": amount, "reason": "damaged",
                                            "refund_method": "cash", "returned_at": iso()}, f"return:{rid}")
    res = sync(c, [ret(4000), ret(6000), ret(5000)])
    assert [r["status"] for r in res] == ["accepted", "conflict", "accepted"]
    assert c.get(f"{API}/shops/{shop_id}/dashboard").data["sales_today"]["net_paise"] == 0


def test_posted_ledger_rows_are_immutable_in_the_database():
    import pytest
    from django.db import InternalError, IntegrityError, transaction
    from django.db.utils import DatabaseError
    c, shop_id, cust = setup_shop_with_customer()
    p = ledger_payload(cust, "credit", 500)
    sync(c, [ledger_item(p)])
    from apps.common.db import x
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            x("UPDATE ledger_events SET amount_paise = 1 WHERE id = %s", [p["id"]])
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            x("DELETE FROM ledger_events WHERE id = %s", [p["id"]])


def test_second_shop_for_same_account_is_a_conflict():
    c, shop_id, cust = setup_shop_with_customer()
    other, _ = shop_item()
    assert sync(c, [other])[0]["status"] == "conflict"


def test_items_must_add_up():
    c, shop_id, cust = setup_shop_with_customer()
    ok = ledger_payload(cust, "credit", 15000, items=[
        {"item_name": "Rice", "quantity_milli": 2500, "unit": "kg", "unit_price_paise": 6000, "line_total_paise": 15000}])
    bad = ledger_payload(cust, "credit", 15000, items=[
        {"item_name": "Rice", "quantity_milli": 2500, "unit": "kg", "unit_price_paise": 6000, "line_total_paise": 14000}])
    assert [r["status"] for r in sync(c, [ledger_item(ok), ledger_item(bad)])] == ["accepted", "rejected"]


def test_all_money_in_api_responses_is_an_integer():
    c, shop_id, cust = setup_shop_with_customer()
    sid, sale = _sale(cust, [{"method": "cash", "amount_paise": 9000, "reference": None}])
    sync(c, [item("sale", "post", sale, f"sale:{sid}"), ledger_item(ledger_payload(cust, "credit", 65000))])

    def walk(v, path=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif path.rsplit(".", 1)[-1].endswith(("_paise", "paise")) or ".by_method" in path:
            assert isinstance(v, int) and not isinstance(v, bool), f"{path} is {type(v).__name__}"
    for url in (f"/shops/{shop_id}/dashboard", f"/shops/{shop_id}/customers",
                f"/shops/{shop_id}/customers/{cust}/ledger", f"/shops/{shop_id}/reports/receivables"):
        r = c.get(API + url)
        assert r.status_code == 200
        walk(r.data)
