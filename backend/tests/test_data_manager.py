"""The data manager (/admin/): what a superuser may add, edit and delete in the app database, and what stays protected."""
import uuid

from django.contrib.auth import get_user_model
from django.test import Client

from apps.common.db import q1

from .helpers import API, item, iso, register, sync

PW = "Test-Admin-Pass-1"


def _admin() -> Client:
    get_user_model().objects.create_superuser("RSRTEST", "owner@example.com", PW)
    a = Client()
    assert a.login(username="RSRTEST", password=PW)
    return a


def _shop_with_customer(mobile="9876543230", ledger=False):
    c, session = register(mobile)
    sid, cid = str(uuid.uuid4()), str(uuid.uuid4())
    sync(c, [item("shop", "create", {"id": sid, "name": "Data Shop", "category": "Kirana", "address": "-", "language": "en"}),
             item("customer", "create", {"id": cid, "name": "Data Customer", "mobile": None, "notes": None})])
    if ledger:
        eid = str(uuid.uuid4())
        sync(c, [item("ledger_event", "post", {"id": eid, "customer_id": cid, "type": "credit", "amount_paise": 5000, "delta_paise": 5000,
                                              "occurred_at": iso(), "created_at": iso(), "note": "t", "payment_method": None,
                                              "payment_reference": None, "sale_id": None, "reversal_of_id": None, "reason": None, "items": []})])
    return session["user"]["id"], sid, cid


def test_a_customer_can_be_added_from_the_data_manager():
    owner, sid, _ = _shop_with_customer()
    a = _admin()
    assert a.get("/admin/legacy/customers/add/").status_code == 200
    r = a.post("/admin/legacy/customers/add/", {"shop": sid, "name": "Added By Admin", "mobile_e164": "+919000000001",
                                                 "notes": "", "status": "active"})
    assert r.status_code == 302, r.content[:400]
    row = q1("SELECT name, status, created_at, updated_at FROM customers WHERE name = 'Added By Admin'")
    assert row and row["created_at"] and row["updated_at"]


def test_a_customer_can_be_edited_and_its_updated_time_moves():
    _, _, cid = _shop_with_customer("9876543231")
    a = _admin()
    before = q1("SELECT updated_at FROM customers WHERE id = %s", [cid])["updated_at"]
    page = a.get(f"/admin/legacy/customers/{cid}/change/")
    assert page.status_code == 200
    r = a.post(f"/admin/legacy/customers/{cid}/change/", {"shop": q1("SELECT shop_id FROM customers WHERE id = %s", [cid])["shop_id"],
                                                          "name": "Renamed", "mobile_e164": "", "notes": "edited", "status": "active"})
    assert r.status_code == 302
    after = q1("SELECT name, updated_at FROM customers WHERE id = %s", [cid])
    assert after["name"] == "Renamed" and after["updated_at"] > before


def test_an_empty_customer_can_be_deleted_but_one_with_ledger_entries_cannot():
    _, _, empty = _shop_with_customer("9876543232")
    _, _, used = _shop_with_customer("9876543233", ledger=True)
    a = _admin()
    assert a.post(f"/admin/legacy/customers/{used}/delete/", {"post": "yes"}).status_code in (403, 302)
    assert q1("SELECT 1 AS x FROM customers WHERE id = %s", [used]), "a customer with posted money must survive"
    assert q1("SELECT COUNT(*) AS n FROM ledger_events WHERE customer_id = %s", [used])["n"] == 1
    r = a.post(f"/admin/legacy/customers/{empty}/delete/", {"post": "yes"})
    assert r.status_code == 302 and q1("SELECT 1 AS x FROM customers WHERE id = %s", [empty]) is None


def test_a_shop_the_app_has_used_is_protected_and_one_added_here_can_be_removed():
    owner, sid, cid = _shop_with_customer("9876543234")
    a = _admin()
    a.post(f"/admin/legacy/shops/{sid}/delete/", {"post": "yes"})
    assert q1("SELECT 1 AS x FROM shops WHERE id = %s", [sid]), "a shop with customers must survive"
    a.post(f"/admin/legacy/customers/{cid}/delete/", {"post": "yes"})
    r = a.post(f"/admin/legacy/shops/{sid}/delete/", {"post": "yes"})
    assert r.status_code in (302, 403) and q1("SELECT 1 AS x FROM shops WHERE id = %s", [sid]), "its append-only sync records keep it"
    # a shop typed in by hand has no history, so it can go
    r = a.post("/admin/legacy/shops/add/", {"owner_user": owner, "shop_id_code": "ADMIN00001", "name": "By Hand", "category": "", "address": "",
                                            "timezone": "Asia/Kolkata", "language": "en", "status": "active"})
    assert r.status_code == 302, r.content[:300]
    mine = q1("SELECT id FROM shops WHERE shop_id_code = 'ADMIN00001'")["id"]
    assert a.post(f"/admin/legacy/shops/{mine}/delete/", {"post": "yes"}).status_code == 302
    assert q1("SELECT 1 AS x FROM shops WHERE id = %s", [mine]) is None


def test_users_and_posted_money_stay_protected():
    owner, _, _ = _shop_with_customer("9876543235", ledger=True)
    a = _admin()
    assert a.get("/admin/legacy/users/add/").status_code == 403           # accounts are created by sign-up (password rules)
    a.post(f"/admin/legacy/users/{owner}/delete/", {"post": "yes"})
    assert q1("SELECT 1 AS x FROM users WHERE id = %s", [owner]), "users are suspended, never deleted"
    assert a.get("/admin/legacy/ledgerevents/add/").status_code == 403
    ev = q1("SELECT id FROM ledger_events LIMIT 1")["id"]
    assert a.get(f"/admin/legacy/ledgerevents/{ev}/delete/").status_code == 403


def test_only_a_logged_in_superuser_reaches_the_data_manager():
    _shop_with_customer("9876543236")
    anon = Client().get("/admin/legacy/customers/")
    assert anon.status_code == 302 and "/admin/login" in anon["Location"]
    get_user_model().objects.create_user("staffonly", "s@example.com", PW, is_staff=True)   # staff without permissions
    c = Client()
    c.login(username="staffonly", password=PW)
    assert c.get("/admin/legacy/customers/").status_code in (302, 403)
