"""The ledger service called directly with typed arguments (the same code the app's sync and, next, the website use)."""
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.common.db import q, q1, x
from apps.ledger import service as L
from apps.ledger.errors import Conflict, Duplicate, Reject

from .helpers import register


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def shop():
    _, data = register("9876500100", "Mohan")
    user = data["user"]["id"]
    sid = L.create_shop(user_id=user, shop_id=_uid(), name="Mohan Kirana")
    return {"user": user, "shop": sid}


def _customer(shop, name="Asha", mobile=None):
    return L.create_customer(shop_id=shop["shop"], customer_id=_uid(), name=name, mobile=mobile)


def _post(shop, cust, etype, amount, **kw):
    return L.post_event(shop_id=shop["shop"], user_id=shop["user"], device_id=None, key=kw.pop("key", _uid()), event_id=kw.pop("event_id", _uid()),
                        customer_id=cust, etype=etype, amount_paise=amount, occurred_at=kw.pop("occurred_at", timezone.now() - timedelta(minutes=1)), **kw)


def test_credit_and_payment_set_the_sign_of_the_balance_themselves():
    _, data = register("9876500101")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s)
    _post(s, c, "credit", 100000)
    _post(s, c, "payment", 30000, payment_method="upi")
    assert {str(r["customer_id"]): r["balance_paise"] for r in L.list_customers(s["shop"])}[c] == 70000
    led = L.customer_ledger(s["shop"], c)
    assert led["balance_paise"] == 70000 and [e["delta_paise"] for e in led["events"]] == [100000, -30000]
    assert [e["confirmation_status"] for e in led["events"]] == ["shopkeeper_recorded"] * 2
    assert led["events"][-1]["running_balance_paise"] == 70000


def test_zero_or_unknown_amounts_and_types_are_refused(shop):
    c = _customer(shop)
    for etype, amt in (("credit", 0), ("payment", 0), ("opening", 0)):
        with pytest.raises(Reject):
            _post(shop, c, etype, amt)
    with pytest.raises(Reject, match="Unknown entry type"):
        _post(shop, c, "gift", 10)
    with pytest.raises(Reject, match="payment method"):
        _post(shop, c, "payment", 10, payment_method="barter")


def test_reversal_mirrors_the_original_and_cannot_happen_twice_or_be_reversed():
    _, data = register("9876500102")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s)
    orig = _post(s, c, "credit", 5000)
    with pytest.raises(Reject, match="needs a reason"):
        _post(s, c, "reversal", 1, reversal_of_id=orig)
    rev = _post(s, c, "reversal", 999, reversal_of_id=orig, reason="wrong amount")          # the amount given is ignored
    row = q1("SELECT amount_paise, delta_paise FROM ledger_events WHERE id = %s", [rev])
    assert (row["amount_paise"], row["delta_paise"]) == (5000, -5000)
    assert L.customer_ledger(s["shop"], c)["balance_paise"] == 0
    with pytest.raises(Conflict):
        _post(s, c, "reversal", 1, reversal_of_id=orig, reason="again")
    with pytest.raises(Reject, match="cannot be reversed"):
        _post(s, c, "reversal", 1, reversal_of_id=rev, reason="undo the undo")


def test_adjustment_needs_a_reason_and_a_matching_signed_delta():
    _, data = register("9876500103")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s)
    with pytest.raises(Reject):
        _post(s, c, "adjustment", 100, delta_paise=-50, reason="x")
    with pytest.raises(Reject, match="reason"):
        _post(s, c, "adjustment", 100, delta_paise=-100)
    _post(s, c, "credit", 500)
    _post(s, c, "adjustment", 100, delta_paise=-100, reason="discount")
    assert L.customer_ledger(s["shop"], c)["balance_paise"] == 400


def test_a_shop_can_never_touch_another_shops_customer_or_events():
    _, d1 = register("9876500104"); _, d2 = register("9876500105")
    a = {"user": d1["user"]["id"], "shop": L.create_shop(user_id=d1["user"]["id"], shop_id=_uid(), name="A")}
    b = {"user": d2["user"]["id"], "shop": L.create_shop(user_id=d2["user"]["id"], shop_id=_uid(), name="B")}
    ca, cb = _customer(a, "Aa"), _customer(b, "Bb")
    ev = _post(a, ca, "credit", 100)
    with pytest.raises(Reject, match="Customer not found"):
        _post(b, ca, "credit", 100)                                    # B writing to A's customer
    with pytest.raises(Reject, match="not found"):
        _post(b, cb, "reversal", 1, reversal_of_id=ev, reason="steal")  # B reversing A's event
    assert L.customer_ledger(b["shop"], ca) is None
    with pytest.raises(Reject, match="Customer not found"):
        L.archive_customer(shop_id=b["shop"], customer_id=ca)             # and cannot archive it either
    assert L.customer_ledger(a["shop"], ca)["balance_paise"] == 100       # A's data is untouched


def test_creating_the_same_thing_twice_is_a_safe_duplicate_and_ids_are_not_stolen():
    _, d1 = register("9876500106"); _, d2 = register("9876500107")
    user1, user2 = d1["user"]["id"], d2["user"]["id"]
    sid = _uid()
    L.create_shop(user_id=user1, shop_id=sid, name="One")
    with pytest.raises(Duplicate):
        L.create_shop(user_id=user1, shop_id=sid, name="One")
    with pytest.raises(Reject, match="not available"):
        L.create_shop(user_id=user2, shop_id=sid, name="Mine now")
    with pytest.raises(Conflict, match="already has a shop"):
        L.create_shop(user_id=user1, shop_id=_uid(), name="Second")
    s1 = {"user": user1, "shop": sid}
    cid = _uid()
    L.create_customer(shop_id=sid, customer_id=cid, name="Ravi")
    with pytest.raises(Duplicate):
        L.create_customer(shop_id=sid, customer_id=cid, name="Ravi")
    s2 = {"user": user2, "shop": L.create_shop(user_id=user2, shop_id=_uid(), name="Two")}
    with pytest.raises(Reject, match="not available"):
        L.create_customer(shop_id=s2["shop"], customer_id=cid, name="Stolen")
    eid = _uid()
    _post(s1, cid, "credit", 5, event_id=eid)
    with pytest.raises(Reject, match="not available"):
        _post(s1, cid, "credit", 5, event_id=eid)


def test_items_must_add_up_to_a_credit_and_are_stored():
    _, data = register("9876500108")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s)
    with pytest.raises(Reject, match="Item totals"):
        _post(s, c, "credit", 1000, items=[("Rice", 2000, "kg", 400, 800)])
    ev = _post(s, c, "credit", 1000, items=[("Rice", 2000, "kg", 400, 800), ("Salt", 1000, "kg", 200, 200)])
    got = L.customer_ledger(s["shop"], c)["events"][0]
    assert got["id"] == ev and [i["item_name"] for i in got["items"]] == ["Rice", "Salt"]


def test_receivables_and_khata_summary_ignore_settled_and_reversed_credit():
    _, data = register("9876500109")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    a, b, c = _customer(s, "A"), _customer(s, "B"), _customer(s, "C")
    _post(s, a, "credit", 900); _post(s, b, "credit", 400); _post(s, b, "payment", 400)
    wrong = _post(s, c, "credit", 700)
    _post(s, c, "reversal", 1, reversal_of_id=wrong, reason="mistake")
    owed = L.receivables(s["shop"])
    assert [(str(r["customer_id"]), r["balance_paise"]) for r in owed] == [(a, 900)]
    k = L.khata_summary(s["shop"])
    assert k["total_receivable_paise"] == 900 and k["customers_with_balance"] == 1
    assert k["credit_by_status"] == {"shopkeeper_recorded": 900 + 400}          # the reversed credit is excluded


def test_archiving_hides_a_customer_from_the_lists():
    _, data = register("9876500110")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s, "Gone")
    assert any(str(r["customer_id"]) == c for r in L.list_customers(s["shop"]))
    L.archive_customer(shop_id=s["shop"], customer_id=c)
    assert not any(str(r["customer_id"]) == c for r in L.list_customers(s["shop"]))
    assert [r["name"] for r in L.list_customers(s["shop"], "zzz")] == []


def test_ledger_rows_stay_append_only_at_the_database_level():
    _, data = register("9876500111")
    s = {"user": data["user"]["id"], "shop": L.create_shop(user_id=data["user"]["id"], shop_id=_uid(), name="S")}
    c = _customer(s)
    ev = _post(s, c, "credit", 100)
    with pytest.raises(Exception):
        x("UPDATE ledger_events SET amount_paise = 1 WHERE id = %s", [ev])
    with pytest.raises(Exception):
        x("DELETE FROM ledger_events WHERE id = %s", [ev])


def test_ledger_backend_switch_defaults_to_the_current_behaviour():
    from django.conf import settings
    assert settings.LEDGER_BACKEND == "legacy"          # the website keeps using its own tables until the migration phase
