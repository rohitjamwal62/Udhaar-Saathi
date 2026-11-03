import uuid

from apps.accounts import otp

from .helpers import API, PASSWORD, new_client, register


def test_signup_verify_login_me():
    c, session = register()
    assert session["user"]["roles"] == ["shopkeeper"]
    me = c.get(f"{API}/me")
    assert me.status_code == 200 and me.data["mobile"] == "+919876543210"
    anon = new_client()
    r = anon.post(f"{API}/auth/login", {"mobile": "9876543210", "password": PASSWORD, "device_id": str(uuid.uuid4())})
    assert r.status_code == 200 and r.data["access"] and r.data["refresh"]


def test_unauthenticated_requests_are_401():
    assert new_client().get(f"{API}/me").status_code == 401


def test_wrong_otp_and_attempt_limit():
    c = new_client()
    r = c.post(f"{API}/auth/signup", {"mobile": "9876543211", "name": "A", "password": PASSWORD, "role": "shopkeeper",
                                      "language": "en", "accepted_terms_version": "v1"})
    cid, good = r.data["challenge_id"], otp.MEMORY_OUTBOX[-1][1]
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        assert c.post(f"{API}/auth/otp/verify", {"mobile": "9876543211", "challenge_id": cid, "otp": wrong}).status_code == 400
    # after 5 failures even the correct OTP is refused
    assert c.post(f"{API}/auth/otp/verify", {"mobile": "9876543211", "challenge_id": cid, "otp": good}).status_code == 400


def test_otp_is_single_use():
    c = new_client()
    r = c.post(f"{API}/auth/signup", {"mobile": "9876543212", "name": "A", "password": PASSWORD, "role": "shopkeeper",
                                      "language": "en", "accepted_terms_version": "v1"})
    body = {"mobile": "9876543212", "challenge_id": r.data["challenge_id"], "otp": otp.MEMORY_OUTBOX[-1][1]}
    assert c.post(f"{API}/auth/otp/verify", body).status_code == 200
    assert c.post(f"{API}/auth/otp/verify", body).status_code == 400


def test_raw_otp_is_not_stored():
    from apps.common.db import q
    new_client().post(f"{API}/auth/signup", {"mobile": "9876543213", "name": "A", "password": PASSWORD, "role": "shopkeeper",
                                             "language": "en", "accepted_terms_version": "v1"})
    code = otp.MEMORY_OUTBOX[-1][1]
    assert all(code not in str(v) for row in q("SELECT * FROM otp_challenges") for v in row.values())


def test_login_errors_are_generic_and_do_not_reveal_accounts():
    register("9876543214")
    c = new_client()
    unknown = c.post(f"{API}/auth/login", {"mobile": "9000000000", "password": PASSWORD, "device_id": str(uuid.uuid4())})
    wrong = c.post(f"{API}/auth/login", {"mobile": "9876543214", "password": "WrongPass1", "device_id": str(uuid.uuid4())})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.data["detail"] == wrong.data["detail"]


def test_signup_for_registered_number_sends_no_otp():
    register("9876543215")
    otp.MEMORY_OUTBOX.clear()
    r = new_client().post(f"{API}/auth/signup", {"mobile": "9876543215", "name": "X", "password": PASSWORD,
                                                 "role": "shopkeeper", "language": "en", "accepted_terms_version": "v1"})
    assert r.status_code == 200 and "challenge_id" in r.data  # same shape as a real signup
    assert otp.MEMORY_OUTBOX == []


def test_weak_password_rejected():
    r = new_client().post(f"{API}/auth/signup", {"mobile": "9876543216", "name": "A", "password": "short", "role": "shopkeeper",
                                                 "language": "en", "accepted_terms_version": "v1"})
    assert r.status_code == 400


def test_refresh_rotation_and_replay_revokes_session():
    c, session = register("9876543217")
    old = session["refresh"]
    r = new_client().post(f"{API}/auth/token/refresh", {"refresh": old})
    assert r.status_code == 200 and r.data["refresh"] != old
    # replaying the already-used token fails and kills the session
    assert new_client().post(f"{API}/auth/token/refresh", {"refresh": old}).status_code == 401
    assert new_client().post(f"{API}/auth/token/refresh", {"refresh": r.data["refresh"]}).status_code == 401


def test_logout_revokes_access_immediately():
    c, _ = register("9876543218")
    assert c.post(f"{API}/auth/logout").status_code == 204
    assert c.get(f"{API}/me").status_code == 401


def test_password_reset_flow_signs_out_everywhere():
    c, _ = register("9876543219")
    anon = new_client()
    r = anon.post(f"{API}/auth/password/forgot", {"mobile": "9876543219"})
    code = otp.MEMORY_OUTBOX[-1][1]
    r2 = anon.post(f"{API}/auth/password/reset", {"mobile": "9876543219", "challenge_id": r.data["challenge_id"],
                                                  "otp": code, "new_password": "BrandNew123"})
    assert r2.status_code == 204
    assert c.get(f"{API}/me").status_code == 401  # old session revoked
    ok = anon.post(f"{API}/auth/login", {"mobile": "9876543219", "password": "BrandNew123", "device_id": str(uuid.uuid4())})
    assert ok.status_code == 200
    old = anon.post(f"{API}/auth/login", {"mobile": "9876543219", "password": PASSWORD, "device_id": str(uuid.uuid4())})
    assert old.status_code == 401


def test_forgot_password_for_unknown_number_looks_the_same():
    otp.MEMORY_OUTBOX.clear()
    r = new_client().post(f"{API}/auth/password/forgot", {"mobile": "9111111111"})
    assert r.status_code == 200 and "challenge_id" in r.data and otp.MEMORY_OUTBOX == []


def test_health_config_and_schema():
    c = new_client()
    assert c.get("/health/live").status_code == 200
    assert c.get("/health/ready").status_code == 200
    cfg = c.get(f"{API}/app/config")
    assert cfg.status_code == 200 and cfg.data["latest_version"]
    assert c.get("/api/schema/").status_code == 200
