"""Website tests: registration with email OTP, login, password reset, contact, documents, admin, email transport."""
import re
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.web import google, mailer
from apps.web.models import EmailOTP, ContactMessage, Document, Profile

User = get_user_model()
PW = "Sup3rSecret"


def phone_for(email: str) -> str:
    """A different valid mobile number for every email, because a mobile number belongs to exactly one account."""
    import zlib
    return "9" + str(zlib.crc32(email.lower().encode()) % 10**9).zfill(9)


def register(c: Client, email="asha@example.com", **extra):
    data = {"full_name": "Asha Verma", "email": email, "phone": phone_for(email), "shop_name": "Asha Kirana", "role": "shopkeeper",
            "password1": PW, "password2": PW, "accept_terms": "on", "website": "", **extra}
    return c.post(reverse("register"), data)


def last_code() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def verified_client(email="asha@example.com") -> Client:
    c = Client()
    register(c, email)
    c.post(reverse("verify_otp"), {"code": last_code()})
    return c


# ───────────────────────── pages ─────────────────────────
@pytest.mark.parametrize("name", ["home", "features", "how_it_works", "pricing", "security", "faq", "contact", "terms", "privacy",
                                  "register", "login", "forgot_password"])
def test_public_pages_render(name):
    r = Client().get(reverse(name))
    assert r.status_code == 200 and b"UdhaarSaathi" in r.content


def test_faq_comes_from_the_database_and_is_seeded():
    from apps.web.models import FAQ
    assert Client().get(reverse("faq")).status_code == 200
    assert FAQ.objects.filter(question="What does it cost?", published=True).exists() and FAQ.objects.count() >= 8


def test_price_comes_from_the_live_plan_table():
    from apps.legacy.models import SubscriptionPlans
    assert SubscriptionPlans.objects.filter(code="udhaarsaathi_monthly").exists()
    from apps.web.context_processors import current_plan
    assert Client().get(reverse("pricing")).status_code == 200
    plan = current_plan()
    assert plan["amount_rupees"] == 49 and plan["trial_months"] == 3 and plan["source"] == "database"


def test_dashboard_requires_login():
    r = Client().get(reverse("dashboard"))
    assert r.status_code == 302 and r["Location"].startswith("/login/")


# ───────────────────────── registration + OTP ─────────────────────────
def test_register_sends_otp_then_verification_activates_and_logs_in():
    c = Client()
    r = register(c, phone="98765 43210")
    assert r.status_code == 302 and r["Location"] == reverse("verify_otp")
    u = User.objects.get(email="asha@example.com")
    assert u.is_active is False and u.username == "asha@example.com"       # not usable until verified
    assert Profile.objects.get(user=u).phone == "+919876543210" and Profile.objects.get(user=u).email_verified is False
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["asha@example.com"] and re.search(r"\b\d{6}\b", mail.outbox[0].body)

    r = c.post(reverse("verify_otp"), {"code": last_code()})
    assert r.status_code == 302 and r["Location"] == reverse("dashboard")
    u.refresh_from_db()
    assert u.is_active and Profile.objects.get(user=u).email_verified
    assert c.get(reverse("dashboard")).status_code == 200                   # now signed in
    assert any("Welcome" in m.subject for m in mail.outbox)                 # welcome email sent too


def test_otp_is_stored_only_as_a_hash():
    register(Client())
    code = last_code()
    row = EmailOTP.objects.get()
    assert code not in str(row.code_hash) and len(row.code_hash) == 64
    assert all(code not in str(v) for v in (row.email, row.purpose, row.ip_address))


def test_wrong_code_is_refused_and_attempts_lock_the_code():
    c = Client()
    register(c)
    good = last_code()
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        r = c.post(reverse("verify_otp"), {"code": bad})
        assert r.status_code == 200 and "incorrect or has expired" in r.content.decode()
    r = c.post(reverse("verify_otp"), {"code": good})                      # even the right code is refused now
    assert r.status_code == 200 and User.objects.get(email="asha@example.com").is_active is False


def test_code_is_single_use():
    c = Client()
    register(c)
    code = last_code()
    assert c.post(reverse("verify_otp"), {"code": code}).status_code == 302
    c2 = Client()
    c2.session["pending_email"] = "asha@example.com"
    s = c2.session; s["pending_email"] = "asha@example.com"; s.save()
    assert c2.post(reverse("verify_otp"), {"code": code}).status_code == 200


def test_expired_code_is_refused():
    c = Client()
    register(c)
    EmailOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert c.post(reverse("verify_otp"), {"code": last_code()}).status_code == 200
    assert User.objects.get(email="asha@example.com").is_active is False


@override_settings(EMAIL_OTP_RESEND_SECONDS=30)
def test_resend_has_a_cooldown_and_replaces_the_old_code():
    c = Client()
    register(c)
    first = last_code()
    c.post(reverse("resend_otp"))                                            # too soon
    assert len(mail.outbox) == 1
    EmailOTP.objects.update(created_at=timezone.now() - timedelta(seconds=40))
    c.post(reverse("resend_otp"))
    assert len(mail.outbox) == 2
    new = last_code()
    if new != first:
        assert c.post(reverse("verify_otp"), {"code": first}).status_code == 200   # the old code no longer works
    assert c.post(reverse("verify_otp"), {"code": new}).status_code == 302


def test_registering_an_active_email_is_refused_but_an_unverified_one_is_reused():
    verified_client("asha@example.com")
    r = register(Client(), "asha@example.com")
    assert r.status_code == 200 and "already exists" in r.content.decode()
    register(Client(), "ravi@example.com")
    register(Client(), "ravi@example.com")                                   # same person retrying
    assert User.objects.filter(email="ravi@example.com").count() == 1


def test_weak_or_mismatched_passwords_and_missing_terms_are_refused():
    assert register(Client(), password1="short", password2="short").status_code == 200
    assert register(Client(), password1="onlyletters", password2="onlyletters").status_code == 200
    assert register(Client(), password2="Different123").status_code == 200
    c = Client()
    data = {"full_name": "A", "email": "z@example.com", "role": "customer", "password1": PW, "password2": PW, "website": ""}
    assert c.post(reverse("register"), data).status_code == 200              # accept_terms missing
    assert not User.objects.filter(email="z@example.com").exists()


def test_honeypot_stops_bots():
    r = register(Client(), website="http://spam.example")
    assert r.status_code == 200 and not User.objects.filter(email="asha@example.com").exists() and not mail.outbox
    r = Client().post(reverse("contact"), {"name": "Bot", "email": "b@example.com", "subject": "x", "message": "y", "website": "spam"})
    assert r.status_code == 200 and not ContactMessage.objects.exists()


# ───────────────────────── login / logout ─────────────────────────
def test_login_with_email_or_username_and_logout():
    verified_client()
    c = Client()
    assert c.post(reverse("login"), {"identifier": "ASHA@example.com", "password": PW}).status_code == 302
    assert c.get(reverse("dashboard")).status_code == 200
    assert c.post(reverse("logout")).status_code == 302
    assert c.get(reverse("dashboard")).status_code == 302
    assert c.get(reverse("logout")).status_code == 405                       # logout needs POST


def test_login_errors_are_generic():
    verified_client()
    a = Client().post(reverse("login"), {"identifier": "asha@example.com", "password": "WrongPass1"})
    b = Client().post(reverse("login"), {"identifier": "nobody@example.com", "password": "WrongPass1"})
    assert a.status_code == b.status_code == 200
    assert "email or password is incorrect" in a.content.decode() and "email or password is incorrect" in b.content.decode()


def test_login_before_verifying_sends_a_new_code_and_blocks_access():
    c = Client()
    register(c)
    mail.outbox.clear()
    c2 = Client()
    r = c2.post(reverse("login"), {"identifier": "asha@example.com", "password": PW})
    assert r.status_code == 302 and r["Location"] == reverse("verify_otp") and len(mail.outbox) == 1
    assert c2.get(reverse("dashboard")).status_code == 302


def test_login_is_rate_limited():
    verified_client()
    c = Client()
    for _ in range(10):
        c.post(reverse("login"), {"identifier": "asha@example.com", "password": "WrongPass1"})
    r = c.post(reverse("login"), {"identifier": "asha@example.com", "password": PW})   # even the right password is paused
    assert r.status_code == 200 and "Too many login attempts" in r.content.decode()


# ───────────────────────── password reset ─────────────────────────
def test_password_reset_with_email_code():
    verified_client()
    c = Client()
    r = c.post(reverse("forgot_password"), {"email": "asha@example.com"})
    assert r.status_code == 302 and r["Location"] == reverse("reset_password")
    code = last_code()
    assert "Reset" in mail.outbox[-1].subject
    r = c.post(reverse("reset_password"), {"code": code, "password1": "BrandNew123", "password2": "BrandNew123"})
    assert r.status_code == 302 and r["Location"] == reverse("login")
    assert Client().post(reverse("login"), {"identifier": "asha@example.com", "password": "BrandNew123"}).status_code == 302
    assert Client().post(reverse("login"), {"identifier": "asha@example.com", "password": PW}).status_code == 200


def test_password_reset_for_unknown_email_looks_the_same_and_sends_nothing():
    c = Client()
    r = c.post(reverse("forgot_password"), {"email": "ghost@example.com"})
    assert r.status_code == 302 and r["Location"] == reverse("reset_password") and not mail.outbox


# ───────────────────────── contact ─────────────────────────
def test_contact_form_saves_and_emails_both_sides():
    r = Client().post(reverse("contact"), {"name": "Ravi", "email": "ravi@example.com", "phone": "", "subject": "Pricing question",
                                           "message": "Is there a free trial?", "website": ""})
    assert r.status_code == 302
    m = ContactMessage.objects.get()
    assert m.subject == "Pricing question" and m.notification_sent is True
    tos = sorted(sum((x.to for x in mail.outbox), []))
    assert tos == ["ravi@example.com", "support@example.test"]
    admin_mail = next(x for x in mail.outbox if x.to == ["support@example.test"])
    assert admin_mail.reply_to == ["ravi@example.com"] and "Is there a free trial?" in admin_mail.body


def test_contact_form_is_rate_limited():
    for i in range(5):
        Client().post(reverse("contact"), {"name": "R", "email": "r@example.com", "subject": f"s{i}", "message": "m", "website": ""})
    Client().post(reverse("contact"), {"name": "R", "email": "r@example.com", "subject": "sixth", "message": "m", "website": ""})
    assert ContactMessage.objects.count() == 5


# ───────────────────────── documents (Google Drive) ─────────────────────────
def _upload(c, name="id.pdf", data=b"%PDF-1.4 test", title="My ID", category="id_proof"):
    return c.post(reverse("document_upload"), {"title": title, "category": category, "file": SimpleUploadedFile(name, data, content_type="application/pdf")})


def test_upload_stores_the_file_in_drive_and_only_a_reference_in_the_database():
    c = verified_client()
    with mock.patch.object(google, "drive_configured", return_value=True), \
         mock.patch.object(google, "drive_upload", return_value={"id": "drive123", "webViewLink": "https://drive.google.com/file/d/drive123/view"}) as up:
        assert _upload(c).status_code == 302
    doc = Document.objects.get()
    assert doc.drive_file_id == "drive123" and doc.size_bytes == len(b"%PDF-1.4 test") and len(doc.sha256) == 64
    name, data, mime = up.call_args.args[0], up.call_args.args[1], up.call_args.args[2]
    assert data == b"%PDF-1.4 test" and name.endswith("_id.pdf") and mime == "application/pdf"
    assert b"My ID" in c.get(reverse("dashboard")).content            # listed on the dashboard


def test_upload_rejects_bad_type_size_and_empty_files_and_works_only_when_drive_is_connected():
    c = verified_client()
    with mock.patch.object(google, "drive_configured", return_value=True), mock.patch.object(google, "drive_upload") as up:
        _upload(c, name="virus.exe"); _upload(c, data=b""); _upload(c, data=b"x" * (10 * 1024 * 1024 + 1))
        assert not up.called and not Document.objects.exists()
    with mock.patch.object(google, "drive_configured", return_value=False):
        _upload(c)
    assert not Document.objects.exists()


def test_upload_failure_from_drive_is_handled_gracefully():
    c = verified_client()
    with mock.patch.object(google, "drive_configured", return_value=True), mock.patch.object(google, "drive_upload", side_effect=google.GoogleError("boom")):
        assert _upload(c).status_code == 302
    assert not Document.objects.exists()


def test_only_the_owner_can_download_a_document():
    owner = verified_client("asha@example.com")
    with mock.patch.object(google, "drive_configured", return_value=True), mock.patch.object(google, "drive_upload", return_value={"id": "d1", "webViewLink": ""}):
        _upload(owner)
    pk = Document.objects.get().pk
    with mock.patch.object(google, "drive_download", return_value=(b"BYTES", "application/pdf")):
        r = owner.get(reverse("document_download", args=[pk]))
        assert r.status_code == 200 and r.content == b"BYTES" and "attachment" in r["Content-Disposition"] and r["X-Content-Type-Options"] == "nosniff"
        other = verified_client("ravi@example.com")
        assert other.get(reverse("document_download", args=[pk])).status_code == 404
        assert Client().get(reverse("document_download", args=[pk])).status_code == 302


# ───────────────────────── admin ─────────────────────────
def _superuser(pw="Test-Admin-Pass-1"):
    return User.objects.create_superuser("Rohit", "rohitjamwal62@gmail.com", pw)


def test_admin_requires_a_staff_login_and_shows_the_app_database():
    _superuser()
    assert Client().get("/admin/").status_code == 302
    verified_client()                                                          # a normal user is not staff
    c = Client()
    c.login(username="asha@example.com", password=PW)
    assert c.get("/admin/").status_code == 302
    a = Client()
    assert a.login(username="Rohit", password="Test-Admin-Pass-1") and a.login(username="rohitjamwal62@gmail.com", password="Test-Admin-Pass-1")
    html = a.get("/admin/").content.decode()
    assert "App database" in html and "Website" in html
    for path in ("/admin/legacy/users/", "/admin/legacy/shops/", "/admin/legacy/ledgerevents/", "/admin/legacy/subscriptionplans/",
                 "/admin/web/faq/", "/admin/web/profile/", "/admin/web/document/", "/admin/web/contactmessage/", "/admin/auth/user/"):
        assert a.get(path).status_code == 200, path


def test_admin_cannot_edit_or_delete_posted_money_rows():
    _superuser()
    a = Client()
    a.login(username="Rohit", password="Test-Admin-Pass-1")
    from apps.legacy.admin import READ_ONLY_TABLES
    assert {"ledger_events", "sales", "payments", "audit_logs"} <= READ_ONLY_TABLES
    assert a.get("/admin/legacy/ledgerevents/add/").status_code == 403


def test_admin_login_is_throttled():
    _superuser()
    c = Client()
    codes = [c.post("/admin/login/", {"username": "Rohit", "password": "nope", "next": "/admin/"}).status_code for _ in range(12)]
    assert codes[-1] == 429 and 429 not in codes[:10]


def test_create_site_admin_command_makes_a_working_superuser(monkeypatch):
    from django.core.management import call_command
    monkeypatch.setenv("ADMIN_PASSWORD", "Test-Admin-Pass-1")
    call_command("create_site_admin", "--username", "Rohit", "--email", "ROHITJAMWAL62@gmail.com", "--first-name", "Rohit")
    u = User.objects.get(username="Rohit")
    assert u.is_superuser and u.is_staff and u.email == "rohitjamwal62@gmail.com" and u.check_password("Test-Admin-Pass-1")
    call_command("create_site_admin", "--username", "Rohit", "--email", "rohitjamwal62@gmail.com")      # idempotent
    assert User.objects.filter(username="Rohit").count() == 1


# ───────────────────────── email transport + Google client ─────────────────────────
def _msg():
    return mail.EmailMessage("Subject", "Body", "UdhaarSaathi <a@b.c>", ["to@example.com"])


@override_settings(EMAIL_HOST_USER="a@b.c", EMAIL_HOST_PASSWORD="x")
def test_smtp_blocked_falls_back_to_the_gmail_api_and_then_skips_smtp_for_a_while():
    mailer.FallbackEmailBackend._smtp_skip_until = 0.0
    with mock.patch.object(mailer.SmtpBackend, "send_messages", side_effect=OSError("port blocked")) as smtp, \
         mock.patch.object(google, "configured", return_value=True), \
         mock.patch.object(google, "gmail_send_raw", return_value={"id": "m1"}) as api:
        b = mailer.FallbackEmailBackend()
        assert b.send_messages([_msg()]) == 1 and mailer.FallbackEmailBackend.last_transport == "gmail_api"
        assert smtp.call_count == 1 and api.call_count == 1
        raw = api.call_args.args[0]
        import base64
        assert b"Subject: Subject" in base64.urlsafe_b64decode(raw) and b"to@example.com" in base64.urlsafe_b64decode(raw)
        b.send_messages([_msg()])
        assert smtp.call_count == 1 and api.call_count == 2            # SMTP is not retried during the skip window
    mailer.FallbackEmailBackend._smtp_skip_until = 0.0


@override_settings(EMAIL_HOST_USER="a@b.c", EMAIL_HOST_PASSWORD="x")
def test_smtp_is_used_when_it_works():
    mailer.FallbackEmailBackend._smtp_skip_until = 0.0
    with mock.patch.object(mailer.SmtpBackend, "send_messages", return_value=1), mock.patch.object(google, "gmail_send_raw") as api:
        assert mailer.FallbackEmailBackend().send_messages([_msg()]) == 1
        assert mailer.FallbackEmailBackend.last_transport == "smtp" and not api.called


@override_settings(EMAIL_HOST_USER="a@b.c", EMAIL_HOST_PASSWORD="x")
def test_email_failure_is_reported_when_nothing_can_send():
    mailer.FallbackEmailBackend._smtp_skip_until = 0.0
    with mock.patch.object(mailer.SmtpBackend, "send_messages", side_effect=OSError("blocked")), mock.patch.object(google, "configured", return_value=False):
        with pytest.raises(OSError):
            mailer.FallbackEmailBackend().send_messages([_msg()])
    mailer.FallbackEmailBackend._smtp_skip_until = 0.0


@override_settings(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="sec", GOOGLE_REFRESH_TOKEN="rt", GOOGLE_DRIVE_FOLDER_ID="folder1")
def test_google_token_refresh_and_drive_upload_request_shape():
    google._token.update(value="", exp=0.0)
    tok = mock.Mock(status_code=200, headers={"content-type": "application/json"}); tok.json.return_value = {"access_token": "AT", "expires_in": 3600}
    up = mock.Mock(status_code=200); up.json.return_value = {"id": "f1", "webViewLink": "https://drive/x"}
    with mock.patch.object(google.requests, "post", side_effect=[tok, up]) as post:
        info = google.drive_upload("a.pdf", b"DATA", "application/pdf")
    assert info["id"] == "f1"
    assert post.call_args_list[0].kwargs["data"]["grant_type"] == "refresh_token"
    call = post.call_args_list[1]
    assert call.kwargs["headers"]["Authorization"] == "Bearer AT" and call.kwargs["headers"]["Content-Type"].startswith("multipart/related")
    assert b'"parents": ["folder1"]' in call.kwargs["data"] and b"DATA" in call.kwargs["data"]
    google._token.update(value="", exp=0.0)


@override_settings(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="sec", GOOGLE_REFRESH_TOKEN="rt")
def test_google_expired_refresh_token_gives_a_clear_error():
    google._token.update(value="", exp=0.0)
    bad = mock.Mock(status_code=400, headers={"content-type": "application/json"}); bad.json.return_value = {"error": "invalid_grant"}
    with mock.patch.object(google.requests, "post", return_value=bad):
        with pytest.raises(google.GoogleError, match="connect Google again"):
            google.access_token()


def test_google_not_configured_is_reported_not_crashed():
    assert google.configured() is False and google.drive_configured() is False
    with pytest.raises(google.GoogleError):
        google.access_token()


# ───────────────────────── test-environment OTP echo ─────────────────────────
@override_settings(ALLOW_DEV_OTP_IN_LOGS=True)
def test_dev_staging_prints_the_code_in_the_log_even_if_email_fails(capsys):
    with mock.patch.object(mailer, "send_otp_email", return_value=False):
        r = register(Client())
    assert r.status_code == 302 and "[DEV EMAIL OTP] asha@example.com" in capsys.readouterr().out


@override_settings(ALLOW_DEV_OTP_IN_LOGS=False)
def test_production_never_prints_codes_and_reports_a_send_failure(capsys):
    c = Client()
    with mock.patch.object(mailer, "send_otp_email", return_value=False):
        r = register(c)
    assert r.status_code == 302 and "DEV EMAIL OTP" not in capsys.readouterr().out
    follow = c.get(reverse("verify_otp"))
    assert follow.status_code == 200 and "could not send the email" in follow.content.decode()


def test_contact_subject_cannot_inject_email_headers():
    Client().post(reverse("contact"), {"name": "Eve", "email": "eve@example.com", "subject": "Hi" + chr(13) + chr(10) + "Bcc: victim@example.com",
                                       "message": "m", "website": ""})
    admin_mail = next(x for x in mail.outbox if x.to == ["support@example.test"])
    assert chr(10) not in admin_mail.subject and chr(13) not in admin_mail.subject and not admin_mail.bcc


@override_settings(ALLOW_DEV_OTP_IN_LOGS=False)
def test_verify_page_does_not_claim_a_code_was_sent_when_the_email_failed():
    c = Client()
    with mock.patch.object(mailer, "send_otp_email", return_value=False):
        register(c)
    html = c.get(reverse("verify_otp")).content.decode()
    assert "We could not email the code" in html and "We sent a 6-digit code" not in html
    mail.outbox.clear()
    c.post(reverse("resend_otp"))                                              # email works now
    html = c.get(reverse("verify_otp")).content.decode()
    assert "We sent a 6-digit code" in html and "We could not email" not in html


def test_email_check_page_is_superuser_only_and_reports_the_network():
    verified_client()
    anon = Client()
    assert anon.get("/admin/email-check/").status_code == 302
    normal = Client(); normal.login(username="asha@example.com", password=PW)
    assert normal.get("/admin/email-check/").status_code == 302           # not staff
    get_user_model().objects.create_superuser("Rohit", "boss@example.com", "Test-Admin-Pass-1")
    a = Client(); a.login(username="Rohit", password="Test-Admin-Pass-1")
    with mock.patch("apps.web.diagnostics.socket.create_connection", side_effect=OSError("blocked")):
        data = a.get("/admin/email-check/").json()
    assert data["smtp_possible_here"] is False and len(data["network"]) == 3
    assert "password" not in {k for k in data if k.endswith("_password")} - {"smtp_password_configured"}
    out = a.get("/admin/email-check/?send=x@example.com").json()
    assert out["test_email"]["sent"] == 1 and mail.outbox[-1].to == ["x@example.com"]


# ───────────── ledger ─────────────
def _add_person(c, name="Ramesh"):
    r = c.post(reverse("party_add"), {"name": name, "phone": "9876543210"})
    from apps.web.models import Party
    return Party.objects.get(name=name)


def _entry(c, party, kind, amount, d=None):
    return c.post(reverse("party_detail", args=[party.pk]),
                  {"kind": kind, "amount": amount, "entry_date": (d or timezone.localdate()).isoformat(), "note": "test"})


def test_ledger_requires_login():
    assert Client().get(reverse("ledger")).status_code == 302


def test_lend_and_repay_updates_balances_in_paise():
    c = verified_client()
    p = _add_person(c)
    assert _entry(c, p, "gave", "1500.50").status_code == 302
    assert _entry(c, p, "gave", "500").status_code == 302
    assert _entry(c, p, "received", "700.25").status_code == 302
    from apps.web.models import LedgerEntry
    assert sorted(LedgerEntry.objects.values_list("amount_paise", flat=True)) == [50000, 70025, 150050]
    page = c.get(reverse("ledger")).content.decode()
    assert "Rs 1,300.25" in page and "Ramesh" in page          # 2000.50 - 700.25 still to collect
    detail = c.get(reverse("party_detail", args=[p.pk])).content.decode()
    assert "Owes you Rs 1,300.25" in detail


def test_invalid_amounts_and_future_dates_are_refused():
    c = verified_client()
    p = _add_person(c)
    from apps.web.models import LedgerEntry
    for bad in ("0", "-5", "abc", "99999999999"):
        _entry(c, p, "gave", bad)
    _entry(c, p, "gave", "10", timezone.localdate() + timedelta(days=2))
    assert LedgerEntry.objects.count() == 0


def test_cancelling_an_entry_keeps_history_but_removes_it_from_the_balance():
    c = verified_client()
    p = _add_person(c)
    _entry(c, p, "gave", "1000")
    from apps.web.models import LedgerEntry
    e = LedgerEntry.objects.get()
    assert c.post(reverse("entry_void", args=[e.pk])).status_code == 302
    e.refresh_from_db()
    assert e.voided and LedgerEntry.objects.count() == 1
    assert "Settled" in c.get(reverse("party_detail", args=[p.pk])).content.decode()


def test_people_and_entries_are_private_to_their_owner():
    a = verified_client("a@example.com")
    p = _add_person(a)
    _entry(a, p, "gave", "250")
    b = verified_client("b@example.com")
    assert b.get(reverse("party_detail", args=[p.pk])).status_code == 404
    from apps.web.models import LedgerEntry
    e = LedgerEntry.objects.get()
    assert b.post(reverse("entry_void", args=[e.pk])).status_code == 404
    assert "Ramesh" not in b.get(reverse("ledger")).content.decode()


def test_duplicate_person_names_are_refused_and_rupee_formatting_is_indian():
    c = verified_client()
    _add_person(c)
    c.post(reverse("party_add"), {"name": "ramesh"})
    from apps.web.models import Party
    assert Party.objects.count() == 1
    from apps.web.templatetags.money import rupees
    assert rupees(12345678) == "Rs 1,23,456.78" and rupees(5) == "Rs 0.05" and rupees(-10000) == "-Rs 100.00"



# ───────────────────────── English / Hindi language switch ─────────────────────────
def choose(c: Client, lang: str, nxt: str = "/"):
    return c.post("/i18n/setlang/", {"language": lang, "next": nxt})


def page(c: Client, name: str, **kw) -> str:
    r = c.get(reverse(name, **kw))
    assert r.status_code == 200
    return r.content.decode()


def main_of(html: str) -> str:
    return html.split("<main")[1].split("</main>")[0]


def test_default_language_is_english_even_if_the_browser_asks_for_hindi():
    for hdr in ({}, {"HTTP_ACCEPT_LANGUAGE": "hi-IN,hi;q=0.9"}):
        html = Client().get(reverse("home"), **hdr).content.decode()
        assert '<html lang="en">' in html and "Your shop's udhaar" in html and "उधार" not in main_of(html)


def test_language_switcher_is_in_the_header_and_the_footer():
    html = page(Client(), "home")
    assert html.count('name="language"') == 4                      # English + Hindi buttons, in the header and in the footer
    assert html.count('action="/i18n/setlang/"') == 2
    en_btn = re.search(r'<button[^>]*value="en"[^>]*>', html).group(0)
    hi_btn = re.search(r'<button[^>]*value="hi"[^>]*>', html).group(0)
    assert 'aria-current="true"' in en_btn and "aria-current" not in hi_btn and 'lang="hi"' in hi_btn
    c = Client()
    choose(c, "hi")
    html = page(c, "home")
    hi_btn = re.search(r'<button[^>]*value="hi"[^>]*>', html).group(0)
    assert 'aria-current="true"' in hi_btn and "csrfmiddlewaretoken" in html


@pytest.mark.parametrize("name,hindi,english", [
    ("home", "उधार", "Three simple steps"),
    ("features", "विशेषताएँ", "Digital khata for shopkeepers"),
    ("how_it_works", "यह कैसे काम करता है", "If you run the shop"),
    ("pricing", "एक सरल प्लान", "What happens when the trial ends"),
    ("security", "सुरक्षा", "Exact amounts"),
    ("faq", "सवालों के जवाब", "Questions, answered"),
    ("contact", "संदेश भेजें", "Send message"),
    ("terms", "उपयोग की शर्तें", "Acceptable use"),
    ("privacy", "गोपनीयता सूचना", "What we collect"),
    ("login", "फिर से स्वागत है", "Welcome back"),
    ("register", "अपना मुफ़्त खाता बनाएँ", "Create your free account"),
    ("forgot_password", "पासवर्ड भूल गए?", "Send code"),
])
def test_pages_switch_to_hindi_and_back(name, hindi, english):
    c = Client()
    r = choose(c, "hi", reverse(name))
    assert r.status_code == 302 and r["Location"] == reverse(name)
    html = page(c, name)
    assert '<html lang="hi">' in html and hindi in html
    assert english not in main_of(html)                            # no untranslated msgid leaks through
    assert "UdhaarSaathi" in html                                  # the brand stays as it is
    choose(c, "en", reverse(name))
    html = page(c, name)
    assert '<html lang="en">' in html and english in html


def test_hindi_is_remembered_in_the_cookie_and_prices_stay_untouched():
    c = Client()
    choose(c, "hi")
    assert c.cookies["django_language"].value == "hi"
    html = page(c, "pricing")                                      # the choice sticks on later pages
    assert "Rs 49" in html or "Rs</small> 49" in html
    assert "3 महीने" in html and "कीमत" in html and "फिर से स्वागत है" not in html


def test_ledger_and_person_pages_in_hindi():
    c = verified_client()
    choose(c, "hi")
    html = page(c, "ledger")
    assert '<html lang="hi">' in html and "आपका उधार बही-खाता" in html and "वसूली बाकी" in html
    assert "Your udhaar ledger" not in html and "To collect" not in html
    c.post(reverse("party_add"), {"name": "Ramesh", "phone": "", "note": ""})
    from apps.web.models import Party
    p = Party.objects.get(name="Ramesh")
    c.post(reverse("party_detail", args=[p.pk]), {"kind": "gave", "amount": "250", "entry_date": timezone.localdate().isoformat(), "note": ""})
    html = page(c, "party_detail", args=[p.pk])
    assert "पैसे लिखें" in html and "Rs 250.00" in html and "इतिहास" in html and "Record money" not in html
    assert "मैंने पैसे दिए (उधार)" in html
    html = page(c, "ledger")
    assert "1 व्यक्ति से" in html and "Rs 250.00" in html


def test_flash_messages_and_form_errors_follow_the_language():
    c = Client()
    choose(c, "hi")
    r = c.post(reverse("login"), {"identifier": "nobody@example.com", "password": "wrong-pass1"})
    assert "ईमेल या पासवर्ड गलत है।" in r.content.decode()
    r = c.post(reverse("register"), {"full_name": "A", "email": "a@example.com", "password1": "abc", "password2": "abd", "accept_terms": "on"})
    html = r.content.decode()
    assert "8 से 128 अक्षर रखें।" in html and "The two passwords" not in html
    r = Client().post(reverse("login"), {"identifier": "nobody@example.com", "password": "wrong-pass1"})
    assert "The email or password is incorrect." in r.content.decode()


def test_open_redirect_through_the_language_switch_is_refused():
    for bad in ("https://evil.example/phish", "//evil.example/x", "javascript:alert(1)"):
        r = Client().post("/i18n/setlang/", {"language": "hi", "next": bad})
        assert r.status_code == 302 and "evil" not in r["Location"] and r["Location"].startswith("/")
    c = Client()
    c.post("/i18n/setlang/", {"language": "fr", "next": "/pricing/"})           # only English and Hindi are ever used
    assert '<html lang="en">' in page(c, "pricing")


def test_language_switch_is_post_only_and_csrf_protected():
    c = Client(enforce_csrf_checks=True)
    assert c.post("/i18n/setlang/", {"language": "hi", "next": "/"}).status_code == 403
    r = c.get("/i18n/setlang/", {"language": "hi", "next": "/"})
    assert "django_language" not in r.cookies                      # a GET never changes the language


def test_otp_email_goes_out_in_the_chosen_language():
    register(Client(), "eng@example.com")
    assert mail.outbox[-1].subject.startswith("Your UdhaarSaathi verification code")
    assert "Use this code to verify your email" in mail.outbox[-1].body
    c = Client()
    choose(c, "hi")
    register(c, "hindi@example.com")
    m = mail.outbox[-1]
    assert m.subject.startswith("आपका UdhaarSaathi सत्यापन कोड: ") and re.search(r"\d{6}", m.subject)
    assert "सत्यापित करने के लिए यह कोड इस्तेमाल करें" in m.body and "मिनट" in m.body
    assert "सत्यापित" in m.alternatives[0][0] and "Use this code" not in m.body
    assert last_code() == re.search(r"\b(\d{6})\b", m.subject).group(1)
    r = c.post(reverse("verify_otp"), {"code": last_code()})           # the welcome email follows the same language
    assert r.status_code == 302 and mail.outbox[-1].subject == "UdhaarSaathi में आपका स्वागत है"


def test_reset_email_and_contact_ack_in_hindi_but_team_copy_stays_english():
    verified_client("reset@example.com")
    c2 = Client()
    choose(c2, "hi")
    c2.post(reverse("forgot_password"), {"email": "reset@example.com"})
    assert mail.outbox[-1].subject.startswith("अपना UdhaarSaathi पासवर्ड रीसेट करें")
    n = len(mail.outbox)
    c2.post(reverse("contact"), {"name": "Ravi", "email": "ravi@example.com", "phone": "", "subject": "Help", "message": "Please call", "website": ""})
    team, ack = mail.outbox[n], mail.outbox[n + 1]
    assert team.subject == "[Contact] Help" and "New contact message" in team.body
    assert ack.subject == "हमें आपका संदेश मिल गया" and "नमस्ते Ravi" in ack.body


def test_faqs_show_hindi_when_available_and_fall_back_to_english():
    from apps.web.models import FAQ
    from django.utils import translation
    seeded = FAQ.objects.get(question="What does it cost?")
    assert seeded.question_hi and seeded.answer_hi and "₹49" in seeded.answer_hi            # data migration 0005
    assert FAQ.objects.filter(question_hi__isnull=False).count() >= 9
    c = Client()
    choose(c, "hi")
    html = page(c, "faq")
    assert seeded.question_hi in html and "What does it cost?" not in html
    FAQ.objects.create(question="English only?", answer="Yes, only English.", order=999)    # no Hindi written yet
    assert "English only?" in page(c, "faq")
    assert "What does it cost?" in page(Client(), "faq")
    with translation.override("hi"):
        assert seeded.display_question == seeded.question_hi
    with translation.override("en"):
        assert seeded.display_question == seeded.question


def test_faq_hindi_fields_are_editable_in_admin():
    from django.contrib import admin
    from apps.web.models import FAQ
    fields = [f for _, opts in admin.site._registry[FAQ].get_fieldsets(None) for f in opts["fields"]]
    assert "question_hi" in fields and "answer_hi" in fields


@override_settings(DEBUG=False)
def test_404_page_follows_the_language():
    c = Client()
    choose(c, "hi")
    html = c.get("/no-such-page-here/").content.decode()
    assert '<html lang="hi">' in html and "पेज नहीं मिला" in html


# ───────────────────────── translation catalogue health ─────────────────────────
def _po_entries():
    import sys
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(base / "tools"))
    from compile_messages import parse_po
    po = base / "locale" / "hi" / "LC_MESSAGES" / "django.po"
    return base, po, [e for e in parse_po(po.read_text(encoding="utf-8")) if e["id"]]


def test_no_msgstr_in_the_hindi_catalogue_is_empty_or_fuzzy():
    _, _, entries = _po_entries()
    assert len(entries) > 400
    empty = [e["id"][:60] for e in entries if not e["str"] or any(not s.strip() for s in e["str"].values())]
    assert not empty, f"{len(empty)} untranslated strings, for example: {empty[:5]}"
    assert not [e["id"] for e in entries if "fuzzy" in e["flags"]]


def test_hindi_translations_keep_the_placeholders_and_html_tags():
    _, _, entries = _po_entries()
    tag = r"</?(?:strong|em|a|b|small)\b"
    bad = []
    for e in entries:
        if e["id_plural"] is not None:
            continue
        t = e["str"][0]
        if sorted(re.findall(r"%\(\w+\)\w", e["id"])) != sorted(re.findall(r"%\(\w+\)\w", t)):
            bad.append(e["id"][:50])
        if sorted(re.findall(tag, e["id"])) != sorted(re.findall(tag, t)):
            bad.append(e["id"][:50])
    assert not bad, bad[:5]


def test_every_translatable_string_in_the_code_is_in_the_catalogue_and_mo_is_current():
    import sys
    base, po, entries = _po_entries()
    sys.path.insert(0, str(base / "tools"))
    import extract_messages
    from compile_messages import build_mo, parse_po
    have = {(e["ctxt"], e["id"]) for e in entries}
    missing = [m for c, m, p, w in extract_messages.collect() if (c, m) not in have]
    assert not missing, f"run tools/extract_messages.py (new strings: {missing[:3]})"
    assert build_mo(parse_po(po.read_text(encoding="utf-8"))) == po.with_suffix(".mo").read_bytes(), \
        "django.mo is stale: run python tools/compile_messages.py and commit it"


# ───────────── everything editable is stored in the database ─────────────
def test_profile_edit_saves_to_the_database():
    c = verified_client()
    assert c.get(reverse("profile_edit")).status_code == 200
    r = c.post(reverse("profile_edit"), {"full_name": "Asha Verma", "phone": "98765 43210", "shop_name": "Asha Store"})
    assert r.status_code == 302
    u = get_user_model().objects.get(email="asha@example.com")
    assert u.first_name == "Asha Verma"
    p = Profile.objects.get(user=u)
    assert (p.phone, p.shop_name) == ("+919876543210", "Asha Store")
    assert Client().get(reverse("profile_edit")).status_code == 302          # login required


def test_profile_edit_rejects_a_bad_mobile_number():
    c = verified_client()
    r = c.post(reverse("profile_edit"), {"full_name": "Asha", "phone": "12345", "shop_name": ""})
    assert r.status_code == 200 and "valid mobile number" in r.content.decode()
    assert Profile.objects.get(user__email="asha@example.com").phone != "+9112345"


def test_person_edit_saves_and_is_private_and_keeps_the_money_entries():
    c = verified_client()
    p = _add_person(c)
    _entry(c, p, "gave", "300")
    r = c.post(reverse("party_edit", args=[p.pk]), {"name": "Ramesh Kumar", "phone": "9123456780", "note": "neighbour"})
    assert r.status_code == 302
    from apps.web.models import LedgerEntry, Party
    p.refresh_from_db()
    assert (p.name, p.phone, p.note) == ("Ramesh Kumar", "9123456780", "neighbour")
    assert LedgerEntry.objects.filter(party=p).count() == 1
    other = verified_client("b@example.com")
    assert other.get(reverse("party_edit", args=[p.pk])).status_code == 404
    assert other.post(reverse("party_edit", args=[p.pk]), {"name": "Hacked"}).status_code == 404
    Party.objects.create(owner=p.owner, name="Suresh")
    dup = c.post(reverse("party_edit", args=[p.pk]), {"name": "suresh"})
    assert dup.status_code == 200 and Party.objects.get(pk=p.pk).name == "Ramesh Kumar"


def test_site_contact_details_come_from_the_database_and_are_editable():
    from apps.web.models import SiteSetting
    from django.core.cache import cache
    assert SiteSetting.objects.exists()                                          # seeded by the migration
    row = SiteSetting.objects.first()
    old = (row.support_email, row.support_phone, row.whatsapp_number, row.address)
    try:
        row.support_email, row.support_phone, row.whatsapp_number, row.address = "help@example.org", "+91 11 2345 6789", "9876543210", "12 Market Road, Pune"
        row.save()
        cache.clear()
        page = Client().get(reverse("contact")).content.decode()
        assert "help@example.org" in page and "+91 11 2345 6789" in page and "wa.me/919876543210" in page and "12 Market Road" in page
        c = Client()
        c.post(reverse("contact"), {"name": "Ravi", "email": "ravi@example.com", "subject": "Hello", "message": "A question for you."})
        assert any(m.to == ["help@example.org"] for m in mail.outbox)            # contact mail goes to the database address
    finally:
        row.support_email, row.support_phone, row.whatsapp_number, row.address = old
        row.save()
        cache.clear()


def test_terms_and_privacy_are_stored_in_the_database_and_override_the_template():
    from apps.web.models import LegalPage
    t = LegalPage.objects.get(slug="terms")
    assert "Terms of use" in t.body_en and t.body_hi.strip()                      # seeded with the built-in text, both languages
    old = (t.body_en, t.body_hi)
    try:
        t.body_en, t.body_hi = "<h1>Custom terms</h1><p>Edited by the owner.</p>", ""
        t.save()
        c = Client()
        assert "Edited by the owner." in c.get(reverse("terms")).content.decode()
        c.post("/i18n/setlang/", {"language": "hi", "next": "/terms/"})
        assert "Edited by the owner." in c.get(reverse("terms")).content.decode()   # no Hindi text yet: falls back to English
        t.body_hi = "<h1>शर्तें</h1>"
        t.save()
        assert "शर्तें" in c.get(reverse("terms")).content.decode()
        t.body_en = t.body_hi = ""
        t.save()
        assert "Terms of use" in Client().get(reverse("terms")).content.decode()     # empty body: built-in text again
    finally:
        t.body_en, t.body_hi = old
        t.save()


def test_new_pages_render_in_hindi():
    c = verified_client()
    c.post("/i18n/setlang/", {"language": "hi", "next": "/"})
    assert "मेरी जानकारी बदलें" in c.get(reverse("profile_edit")).content.decode()
    p = _add_person(c)
    assert "व्यक्ति की जानकारी बदलें" in c.get(reverse("party_edit", args=[p.pk])).content.decode()


def test_admin_can_manage_the_new_content_but_cannot_add_a_second_settings_row():
    get_user_model().objects.create_superuser("Rohit", "boss@example.com", "Test-Admin-Pass-1")
    a = Client(); a.login(username="Rohit", password="Test-Admin-Pass-1")
    for url in ("/admin/web/sitesetting/", "/admin/web/legalpage/", "/admin/web/party/", "/admin/web/ledgerentry/"):
        assert a.get(url).status_code == 200, url
    assert a.get("/admin/web/sitesetting/add/").status_code == 403


# ───────────── the mobile number is mandatory and belongs to one account ─────────────
def test_registration_requires_a_valid_mobile_number():
    for bad in ("", "   ", "12345", "abcdefghij"):
        c = Client()
        r = register(c, f"x{abs(hash(bad)) % 9999}@example.com", phone=bad)
        assert r.status_code == 200 and not User.objects.filter(email__startswith="x").exists(), bad
    assert len(mail.outbox) == 0                                             # no code is sent for a rejected sign-up


def test_a_mobile_number_cannot_be_used_by_two_accounts():
    verified_client("one@example.com")
    shared = Profile.objects.get(user__email="one@example.com").phone
    c = Client()
    r = register(c, "two@example.com", phone=shared)
    assert r.status_code == 200 and "already used by another account" in r.content.decode()
    assert not User.objects.filter(email="two@example.com").exists()


def test_an_unverified_sign_up_can_be_retried_with_the_same_mobile_number():
    c = Client()
    register(c, "retry@example.com", phone="9876511111")
    assert register(Client(), "retry@example.com", phone="9876511111").status_code == 302      # same person, same number: fine
    assert Profile.objects.filter(phone="+919876511111").count() == 1


def test_profile_edit_cannot_clear_or_steal_a_mobile_number():
    a = verified_client("a@example.com")
    verified_client("b@example.com")
    theirs = Profile.objects.get(user__email="b@example.com").phone
    mine = Profile.objects.get(user__email="a@example.com").phone
    r = a.post(reverse("profile_edit"), {"full_name": "A", "phone": "", "shop_name": ""})
    assert r.status_code == 200 and "required" in r.content.decode().lower()
    r = a.post(reverse("profile_edit"), {"full_name": "A", "phone": theirs, "shop_name": ""})
    assert r.status_code == 200 and "already used by another account" in r.content.decode()
    assert Profile.objects.get(user__email="a@example.com").phone == mine
    assert a.post(reverse("profile_edit"), {"full_name": "A", "phone": mine, "shop_name": ""}).status_code == 302   # keeping your own is fine


def test_an_older_account_without_a_mobile_number_is_asked_to_add_one():
    c = verified_client("old@example.com")
    Profile.objects.filter(user__email="old@example.com").update(phone="")          # an account from before the rule
    for name in ("dashboard", "ledger"):
        r = c.get(reverse(name))
        assert r.status_code == 302 and r["Location"] == reverse("profile_edit"), name
    assert c.get(reverse("profile_edit")).status_code == 200                         # the page to fix it is reachable
    c.post(reverse("profile_edit"), {"full_name": "Old", "phone": "9876522222", "shop_name": ""})
    assert c.get(reverse("dashboard")).status_code == 200


def test_the_sign_up_form_marks_the_mobile_number_as_required():
    html = Client().get(reverse("register")).content.decode()
    assert "Mobile number" in html and "Mobile number (optional)" not in html
