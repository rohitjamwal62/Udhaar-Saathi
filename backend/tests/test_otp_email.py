"""The phone app's verification codes are delivered by EMAIL (works with no SMS provider)."""
import re
import uuid
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, override_settings

from apps.accounts import otp
from apps.common.db import q1
from apps.web import google

from .helpers import API, PASSWORD, new_client, register

email_mode = override_settings(OTP_SENDER="email")


def _signup(c, mobile="9876500200", email="asha@example.com", language="en", **extra):
    body = {"mobile": mobile, "name": "Asha", "password": PASSWORD, "role": "shopkeeper", "language": language,
            "accepted_terms_version": "v1", **({"email": email} if email is not None else {}), **extra}
    return c.post(f"{API}/auth/signup", body, format="json")


def _outbox() -> list:
    return getattr(mail, "outbox", [])          # Django creates the outbox on the first email


def _code() -> str:
    return re.search(r"\b(\d{6})\b", _outbox()[-1].body).group(1)


def _verify(c, mobile, challenge, code):
    return c.post(f"{API}/auth/otp/verify", {"mobile": mobile, "challenge_id": challenge, "otp": code, "device_id": str(uuid.uuid4())}, format="json")


def _row(mobile="+919876500200"):
    return q1("SELECT status, email, mobile_verified_at, preferred_language FROM users WHERE mobile_e164 = %s", [mobile])


# ───────────── sign-up ─────────────
@email_mode
def test_signup_needs_a_valid_email_when_codes_are_emailed():
    c = new_client()
    for bad in (None, "", "not-an-email", "a@b"):
        r = _signup(c, email=bad)
        assert r.status_code == 400, bad
        assert "email" in str(r.content).lower()
    assert len(_outbox()) == 0 and _row() is None                      # nothing sent, no half-created account


@email_mode
def test_signup_emails_the_code_and_verification_signs_the_user_in():
    c = new_client()
    r = _signup(c, email="Asha.Verma@Example.com")
    assert r.status_code == 200
    assert r.data["delivery"] == "email" and r.data["sent_to"] == "as***@example.com" and r.data["challenge_id"]
    assert len(_outbox()) == 1 and _outbox()[0].to == ["asha.verma@example.com"]                # lower-cased
    assert "verification code" in _outbox()[0].subject.lower()
    v = _verify(c, "9876500200", r.data["challenge_id"], _code())
    assert v.status_code == 200 and v.data["access"] and v.data["user"]["mobile"] == "+919876500200"
    row = _row()
    assert row["status"] == "active" and row["email"] == "asha.verma@example.com"
    assert row["mobile_verified_at"] is None                                                         # an emailed code does not prove the mobile number


@email_mode
def test_wrong_codes_are_refused_and_a_code_works_only_once():
    c = new_client()
    r = _signup(c)
    code = _code()
    bad = "000000" if code != "000000" else "111111"
    assert _verify(c, "9876500200", r.data["challenge_id"], bad).status_code == 400
    assert _verify(c, "9876500200", r.data["challenge_id"], code).status_code == 200
    assert _verify(c, "9876500200", r.data["challenge_id"], code).status_code == 400                 # burned


@email_mode
def test_an_existing_active_account_gets_the_same_answer_and_no_email():
    c = new_client()
    r = _signup(c)
    _verify(c, "9876500200", r.data["challenge_id"], _code())
    _outbox().clear()
    again = _signup(new_client(), email="someone-else@example.com")
    assert again.status_code == 200 and again.data["delivery"] == "email" and again.data["challenge_id"]
    assert len(_outbox()) == 0                                                                     # nobody can probe which numbers exist


@email_mode
def test_a_retried_pending_signup_updates_the_email_and_sends_to_the_new_one():
    c = new_client()
    _signup(c, email="old@example.com")
    r = _signup(c, email="new@example.com")
    assert r.status_code == 200 and _outbox()[-1].to == ["new@example.com"]
    assert _row()["email"] == "new@example.com"
    assert _verify(c, "9876500200", r.data["challenge_id"], _code()).status_code == 200


@email_mode
def test_the_code_email_follows_the_chosen_language():
    _signup(new_client(), language="hi")
    assert re.search("[ऀ-ॿ]", _outbox()[-1].subject)                                     # Hindi subject


# ───────────── resend, forgot password ─────────────
@email_mode
def test_resend_sends_a_fresh_code_to_the_email_on_file_and_reveals_nothing_for_unknown_numbers():
    c = new_client()
    _signup(c)
    _outbox().clear()
    r = c.post(f"{API}/auth/otp/request", {"mobile": "9876500200", "purpose": "signup"}, format="json")
    assert r.status_code == 200 and len(_outbox()) == 1 and _outbox()[0].to == ["asha@example.com"]
    assert "sent_to" not in r.data                                                                   # the address is not echoed back
    _outbox().clear()
    r2 = c.post(f"{API}/auth/otp/request", {"mobile": "9000000099", "purpose": "signup"}, format="json")
    assert r2.status_code == 200 and r2.data["challenge_id"] and len(_outbox()) == 0


@email_mode
def test_forgot_password_emails_a_reset_code_and_the_reset_works():
    c = new_client()
    r = _signup(c)
    _verify(c, "9876500200", r.data["challenge_id"], _code())
    _outbox().clear()
    f = c.post(f"{API}/auth/password/forgot", {"mobile": "9876500200"}, format="json")
    assert f.status_code == 200 and len(_outbox()) == 1 and "reset" in _outbox()[0].subject.lower()
    new_pw = "BrandNew-Pass9"
    ok = c.post(f"{API}/auth/password/reset", {"mobile": "9876500200", "challenge_id": f.data["challenge_id"], "otp": _code(), "new_password": new_pw}, format="json")
    assert ok.status_code == 204
    login = c.post(f"{API}/auth/login", {"mobile": "9876500200", "password": new_pw, "device_id": str(uuid.uuid4())}, format="json")
    assert login.status_code == 200


def test_an_older_account_with_no_email_cannot_be_emailed_and_nothing_leaks():
    c, _ = register("9876500201", "Old")                       # created in the test-only memory mode: no email on file
    with override_settings(OTP_SENDER="email"):
        _outbox().clear()
        f = new_client().post(f"{API}/auth/password/forgot", {"mobile": "9876500201"}, format="json")
        assert f.status_code == 200 and f.data["challenge_id"] and len(_outbox()) == 0
        g = new_client().post(f"{API}/auth/password/forgot", {"mobile": "9000000088"}, format="json")
        assert g.status_code == 200 and set(g.data) == set(f.data)                                   # same shape: no account probing


# ───────────── abuse and failure ─────────────
@email_mode
def test_one_email_address_cannot_be_used_to_flood_an_inbox():
    victim = "victim@example.com"
    codes = [_signup(new_client(), mobile=f"98765003{i:02d}", email=victim).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429 and len(_outbox()) == 5


@email_mode
@override_settings(DEBUG=False, ALLOW_DEV_OTP_IN_LOGS=False)
def test_when_email_cannot_be_sent_production_says_so_instead_of_pretending():
    with mock.patch("apps.web.mailer.send_otp_email", return_value=False):
        r = _signup(new_client())
    assert r.status_code == 503 and "could not send" in r.content.decode().lower()


@email_mode
@override_settings(DEBUG=False, ALLOW_DEV_OTP_IN_LOGS=True)
def test_on_a_test_server_a_failed_email_falls_back_to_the_log_so_testing_continues(capsys):
    with mock.patch("apps.web.mailer.send_otp_email", return_value=False):
        r = _signup(new_client())
    assert r.status_code == 200
    assert re.search(r"\[DEV OTP\] \+919876500200: \d{6}", capsys.readouterr().out)


def test_masking_shows_enough_to_recognise_but_not_to_harvest():
    assert otp.mask_email("ramesh@gmail.com") == "ra***@gmail.com"
    assert otp.mask_email("ab@x.in") == "a***@x.in"
    assert otp.mask_email("") == "***@"


def test_the_default_test_mode_is_unchanged_no_email_needed_and_mobile_marked_verified():
    c, data = register("9876500202", "Plain")
    row = _row("+919876500202")
    assert row["status"] == "active" and row["mobile_verified_at"] is not None and row["email"] is None


# ───────────── Google token health ─────────────
def test_mail_health_is_200_while_google_works_and_503_when_the_token_has_expired():
    from django.core.cache import cache
    c = Client()
    cache.clear()
    with mock.patch.object(google, "configured", return_value=True), mock.patch.object(google, "access_token", return_value="tok"):
        r = c.get("/health/mail")
        assert r.status_code == 200 and r.json() == {"email": "ok"}
    cache.clear()
    with mock.patch.object(google, "configured", return_value=True), \
            mock.patch.object(google, "access_token", side_effect=google.GoogleError("Google refused the token request (400 invalid_grant).")):
        r = c.get("/health/mail")
        assert r.status_code == 503 and r.json() == {"email": "token_expired"}
    cache.clear()
    assert c.get("/health/mail").json() == {"email": "not_configured"}                                # test settings: Google not connected


def test_the_admin_home_warns_administrators_when_google_must_be_reconnected():
    from django.core.cache import cache
    User = get_user_model()
    User.objects.create_superuser("Boss", "boss@example.com", "Test-Admin-Pass-1")
    c = Client()
    c.login(username="Boss", password="Test-Admin-Pass-1")
    cache.set("google:token_status", "token_expired", 60)
    assert "Google is disconnected" in c.get("/admin/").content.decode()
    cache.set("google:token_status", "ok", 60)
    assert "Google is disconnected" not in c.get("/admin/").content.decode()


@email_mode
@override_settings(DEBUG=False, ALLOW_DEV_OTP_IN_LOGS=True)
def test_on_a_test_server_the_code_is_also_logged_when_the_email_goes_out(capsys):
    r = _signup(new_client())
    assert r.status_code == 200 and len(_outbox()) == 1                                              # the email was sent
    assert re.search(r"\[DEV OTP\] \+919876500200: \d{6}", capsys.readouterr().out)                  # and the test server logged it too


@email_mode
@override_settings(DEBUG=False, ALLOW_DEV_OTP_IN_LOGS=False)
def test_production_never_logs_the_code(capsys):
    r = _signup(new_client())
    assert r.status_code == 200 and len(_outbox()) == 1
    assert "[DEV OTP]" not in capsys.readouterr().out and _code() not in capsys.readouterr().out
