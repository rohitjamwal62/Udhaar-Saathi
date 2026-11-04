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


def register(c: Client, email="asha@example.com", **extra):
    data = {"full_name": "Asha Verma", "email": email, "phone": "98765 43210", "shop_name": "Asha Kirana", "role": "shopkeeper",
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
    r = register(c)
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
