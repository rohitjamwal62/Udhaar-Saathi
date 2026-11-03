import json
import uuid
from datetime import timedelta

from django.utils import timezone

from apps.common.db import q, q1, x
from apps.subscriptions.gateway import fake_sign_payment, fake_sign_webhook

from .helpers import API, ledger_item, ledger_payload, setup_shop_with_customer, sync


def sub_info(c):
    r = c.get(f"{API}/subscriptions/current")
    assert r.status_code == 200, r.content
    return r.data


def test_new_shop_gets_exactly_one_three_month_trial():
    c, shop_id, _ = setup_shop_with_customer()
    info = sub_info(c)
    assert info["status"] == "TRIALING" and info["amount_paise"] == 4900
    row = q1("SELECT trial_started_at, trial_ends_at FROM subscriptions WHERE shop_id=%s", [shop_id])
    months = (row["trial_ends_at"].year - row["trial_started_at"].year) * 12 + row["trial_ends_at"].month - row["trial_started_at"].month
    assert months == 3
    assert q1("SELECT COUNT(*) AS n FROM trial_grants")["n"] == 1


def _expire_trial(shop_id):
    x("UPDATE subscriptions SET trial_ends_at = now() - interval '1 day' WHERE shop_id=%s", [shop_id])


def test_expired_subscription_is_read_only_but_history_stays_readable():
    c, shop_id, cust = setup_shop_with_customer()
    sync(c, [ledger_item(ledger_payload(cust, "credit", 5000))])
    _expire_trial(shop_id)
    assert sub_info(c)["status"] == "EXPIRED"
    res = sync(c, [ledger_item(ledger_payload(cust, "credit", 100))])[0]
    assert res["status"] == "rejected" and "subscription_required" in res["error"]
    assert c.get(f"{API}/shops/{shop_id}/customers/{cust}/ledger").data["balance_paise"] == 5000  # data kept


def _order_and_pay(c, key=None, payment_id="pay_test_1"):
    o = c.post(f"{API}/subscriptions/orders", {"idempotency_key": key or str(uuid.uuid4())})
    assert o.status_code == 200, o.content
    sig = fake_sign_payment(o.data["order_id"], payment_id)
    return o.data, c.post(f"{API}/subscriptions/verify", {"order_id": o.data["order_id"], "payment_id": payment_id, "signature": sig})


def test_payment_activates_after_verified_signature_and_extends_one_month():
    c, shop_id, cust = setup_shop_with_customer()
    _expire_trial(shop_id)
    order, r = _order_and_pay(c)
    assert order["amount_paise"] == 4900 and order["currency"] == "INR"
    assert r.status_code == 200 and r.data["status"] == "ACTIVE"
    info = sub_info(c)
    assert info["current_period_end"] is not None
    assert sync(c, [ledger_item(ledger_payload(cust, "credit", 100))])[0]["status"] == "accepted"  # writes work again
    assert q1("SELECT COUNT(*) AS n FROM subscription_invoices")["n"] == 1


def test_bad_signature_never_activates():
    c, shop_id, _ = setup_shop_with_customer()
    _expire_trial(shop_id)
    o = c.post(f"{API}/subscriptions/orders", {"idempotency_key": "k1"}).data
    r = c.post(f"{API}/subscriptions/verify", {"order_id": o["order_id"], "payment_id": "pay_x", "signature": "deadbeef"})
    assert r.status_code == 400
    assert sub_info(c)["status"] == "EXPIRED"
    assert q1("SELECT COUNT(*) AS n FROM payments")["n"] == 0


def test_repeated_verify_does_not_extend_twice():
    c, shop_id, _ = setup_shop_with_customer()
    _expire_trial(shop_id)
    order, _ = _order_and_pay(c, "same", "pay_dup")
    end1 = sub_info(c)["current_period_end"]
    sig = fake_sign_payment(order["order_id"], "pay_dup")
    c.post(f"{API}/subscriptions/verify", {"order_id": order["order_id"], "payment_id": "pay_dup", "signature": sig})
    assert sub_info(c)["current_period_end"] == end1
    assert q1("SELECT COUNT(*) AS n FROM payments")["n"] == 1


def test_order_is_idempotent_and_amount_is_server_decided():
    c, shop_id, _ = setup_shop_with_customer()
    a = c.post(f"{API}/subscriptions/orders", {"idempotency_key": "abc", "amount_paise": 1}).data
    b = c.post(f"{API}/subscriptions/orders", {"idempotency_key": "abc"}).data
    assert a["order_id"] == b["order_id"] and a["amount_paise"] == 4900


def _webhook(c, event_id, payload):
    body = json.dumps(payload).encode()
    return c.generic("POST", f"{API}/webhooks/razorpay", body, content_type="application/json",
                     HTTP_X_RAZORPAY_SIGNATURE=fake_sign_webhook(body), HTTP_X_RAZORPAY_EVENT_ID=event_id)


def _captured(order_id, payment_id, amount=4900):
    return {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": payment_id, "order_id": order_id, "amount": amount, "method": "upi"}}}}


def test_webhook_activates_and_duplicates_are_ignored():
    c, shop_id, _ = setup_shop_with_customer()
    _expire_trial(shop_id)
    o = c.post(f"{API}/subscriptions/orders", {"idempotency_key": "w1"}).data
    r1 = _webhook(c, "evt_1", _captured(o["order_id"], "pay_w1"))
    r2 = _webhook(c, "evt_1", _captured(o["order_id"], "pay_w1"))  # same delivery again
    r3 = _webhook(c, "evt_2", _captured(o["order_id"], "pay_w1"))  # different event, same payment
    assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 200)
    assert r2.data["status"] == "duplicate"
    assert sub_info(c)["status"] == "ACTIVE"
    assert q1("SELECT COUNT(*) AS n FROM payments")["n"] == 1
    assert q1("SELECT COUNT(*) AS n FROM subscription_invoices")["n"] == 1


def test_webhook_with_bad_signature_or_wrong_amount_is_not_applied():
    c, shop_id, _ = setup_shop_with_customer()
    _expire_trial(shop_id)
    o = c.post(f"{API}/subscriptions/orders", {"idempotency_key": "w2"}).data
    body = json.dumps(_captured(o["order_id"], "pay_bad")).encode()
    bad = c.generic("POST", f"{API}/webhooks/razorpay", body, content_type="application/json",
                    HTTP_X_RAZORPAY_SIGNATURE="nope", HTTP_X_RAZORPAY_EVENT_ID="evt_bad")
    assert bad.status_code == 400
    wrong_amount = _webhook(c, "evt_amt", _captured(o["order_id"], "pay_amt", amount=100))
    assert wrong_amount.status_code == 200 and wrong_amount.data["status"] == "ignored"
    assert sub_info(c)["status"] == "EXPIRED"


def test_webhook_for_unknown_order_is_stored_not_applied():
    c, *_ = setup_shop_with_customer()
    r = _webhook(c, "evt_unknown", _captured("order_missing", "pay_u"))
    assert r.status_code == 200 and r.data["status"] == "ignored"
    assert q1("SELECT processed_at FROM gateway_webhook_events WHERE event_id='evt_unknown'")["processed_at"] is None


def test_grace_period_then_expiry_and_history_preserved():
    c, shop_id, cust = setup_shop_with_customer()
    _expire_trial(shop_id)
    _order_and_pay(c, "g1", "pay_g1")
    x("UPDATE subscriptions SET current_period_end = now() - interval '3 days' WHERE shop_id=%s", [shop_id])
    assert sub_info(c)["status"] == "GRACE_PERIOD"
    assert sync(c, [ledger_item(ledger_payload(cust, "credit", 100))])[0]["status"] == "accepted"
    x("UPDATE subscriptions SET current_period_end = now() - interval '8 days' WHERE shop_id=%s", [shop_id])
    assert sub_info(c)["status"] == "EXPIRED"
    assert sync(c, [ledger_item(ledger_payload(cust, "credit", 100))])[0]["status"] == "rejected"
    assert c.get(f"{API}/shops/{shop_id}/customers").status_code == 200


def test_cancel_keeps_access_until_paid_through_date():
    c, shop_id, cust = setup_shop_with_customer()
    _expire_trial(shop_id)
    _order_and_pay(c, "c1", "pay_c1")
    r = c.post(f"{API}/subscriptions/cancel")
    assert r.status_code == 200 and r.data["cancel_at_period_end"] is True and r.data["status"] == "CANCELED"
    assert sync(c, [ledger_item(ledger_payload(cust, "credit", 100))])[0]["status"] == "accepted"
    x("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE shop_id=%s", [shop_id])
    assert sub_info(c)["status"] == "EXPIRED"  # canceled renewals get no grace


def test_payment_history_lists_payments_with_invoice_numbers():
    c, shop_id, _ = setup_shop_with_customer()
    _expire_trial(shop_id)
    _order_and_pay(c, "h1", "pay_h1")
    rows = c.get(f"{API}/subscriptions/payments").data["results"]
    assert len(rows) == 1 and rows[0]["status"] == "success" and rows[0]["invoice_number"].startswith("US-")
