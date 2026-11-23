import uuid

from apps.accounts import otp

from .helpers import API, PASSWORD, item, ledger_item, ledger_payload, new_client, register, shop_item, sync


def register_customer(mobile):
    c = new_client()
    r = c.post(f"{API}/auth/signup", {"mobile": mobile, "name": "Asha", "password": PASSWORD, "role": "customer",
                                      "language": "en", "accepted_terms_version": "v1"})
    assert r.status_code == 200, r.content
    r = c.post(f"{API}/auth/otp/verify", {"mobile": mobile, "challenge_id": r.data["challenge_id"],
                                          "otp": otp.MEMORY_OUTBOX[-1][1], "device_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.content
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    return c, r.data


def test_restore_returns_shop_customers_and_ledger_so_a_new_login_never_asks_for_the_shop_again():
    c, _ = register("9876500001", "Ravi")
    s_item, shop_id = shop_item(name="Ravi Kirana")
    cid = str(uuid.uuid4())
    cust = item("customer", "create", {"id": cid, "name": "Asha", "mobile": None, "notes": None}, f"customer:{cid}")
    credit = ledger_payload(cid, "credit", 40000)
    sync(c, [s_item, cust, ledger_item(credit)])

    # a brand new login (empty phone) asks the server
    r = c.get(f"{API}/restore")
    assert r.status_code == 200
    assert r.data["shop"]["name"] == "Ravi Kirana" and r.data["shop"]["id"] == shop_id
    assert [x["name"] for x in r.data["customers"]] == ["Asha"]
    ev = r.data["ledger_events"]
    assert len(ev) == 1 and ev[0]["amount_paise"] == 40000 and ev[0]["idempotency_key"]


def test_restore_is_empty_for_a_user_without_a_shop_and_never_leaks_other_shops():
    c1, _ = register("9876500002")
    sync(c1, [shop_item(name="Other shop")[0]])
    c2, _ = register("9876500003")
    assert c2.get(f"{API}/restore").data == {"shop": None}


def test_customer_sees_only_their_own_dues_by_mobile_number():
    shop_c, _ = register("9876500004", "Ravi")
    s_item, shop_id = shop_item(name="Ravi Kirana")
    mine, other = str(uuid.uuid4()), str(uuid.uuid4())
    sync(shop_c, [s_item,
                  item("customer", "create", {"id": mine, "name": "Asha", "mobile": "+919876500005", "notes": None}, f"customer:{mine}"),
                  item("customer", "create", {"id": other, "name": "Bob", "mobile": "+919876500006", "notes": None}, f"customer:{other}")])
    sync(shop_c, [ledger_item(ledger_payload(mine, "credit", 25000)), ledger_item(ledger_payload(other, "credit", 99000))])

    cust_c, session = register_customer("9876500005")
    assert session["user"]["roles"] == ["customer"]
    r = cust_c.get(f"{API}/me/khata")
    assert r.status_code == 200
    assert [x["shop_name"] for x in r.data["results"]] == ["Ravi Kirana"]
    assert r.data["total_owed_paise"] == 25000
    cid = r.data["results"][0]["customer_id"]
    d = cust_c.get(f"{API}/me/khata/{cid}")
    assert d.status_code == 200 and d.data["balance_paise"] == 25000 and len(d.data["events"]) == 1
    # someone else's record is a plain 404
    assert cust_c.get(f"{API}/me/khata/{other}").status_code == 404
