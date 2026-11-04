"""Email: SMTP first, Gmail API (HTTPS) as the fallback, plus the app's message helpers."""
import base64
import logging
import smtplib
import time

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from . import google

log = logging.getLogger("mailer")


class FallbackEmailBackend(BaseEmailBackend):
    """Try SMTP. If it cannot connect (for example Render's free plan blocks SMTP ports) or the login is refused,
    send through the Gmail API instead. After a network failure SMTP is skipped for 10 minutes so mail is not delayed.

    EMAIL_TRANSPORT=auto (default) | smtp | gmail_api
    """
    _smtp_skip_until = 0.0
    last_transport = ""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        import os
        mode = os.environ.get("EMAIL_TRANSPORT", "auto")
        cls = type(self)
        if mode in ("auto", "smtp") and time.time() >= cls._smtp_skip_until and settings.EMAIL_HOST_USER:
            try:
                sent = SmtpBackend(fail_silently=False).send_messages(email_messages)
                cls.last_transport = "smtp"
                return sent
            except (OSError, smtplib.SMTPException) as exc:
                log.warning("SMTP failed (%s: %s)", type(exc).__name__, str(exc)[:120])
                if mode == "smtp" or not google.configured():
                    if self.fail_silently:
                        return 0
                    raise
                if isinstance(exc, OSError):  # blocked port / no route / timeout
                    cls._smtp_skip_until = time.time() + 600
        if not google.configured():
            if self.fail_silently:
                return 0
            raise RuntimeError("No email transport is available (SMTP failed or is not set, and Google is not connected).")
        sent = 0
        for message in email_messages:
            try:
                raw = base64.urlsafe_b64encode(message.message().as_bytes()).decode()
                google.gmail_send_raw(raw)
                sent += 1
            except google.GoogleError:
                if not self.fail_silently:
                    raise
        cls.last_transport = "gmail_api"
        return sent


def _send(subject: str, to: list[str], template: str, context: dict, reply_to: list[str] | None = None) -> bool:
    ctx = {"site_name": settings.SITE_NAME, "site_url": settings.SITE_URL, **context}
    text = render_to_string(f"emails/{template}.txt", ctx)
    html = render_to_string(f"emails/{template}.html", ctx)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, to, reply_to=reply_to)
    msg.attach_alternative(html, "text/html")
    try:
        return bool(msg.send(fail_silently=False))
    except Exception:  # noqa: BLE001
        log.exception("could not send '%s'", subject)
        return False


def send_otp_email(email: str, code: str, purpose: str, minutes: int) -> bool:
    """The code email goes out in the language the visitor has chosen on the website (English by default)."""
    subject = {"register": _("Your UdhaarSaathi verification code"), "reset": _("Reset your UdhaarSaathi password")}[purpose]
    return _send(f"{subject}: {code}", [email], "otp", {"code": code, "purpose": purpose, "minutes": minutes})


def send_welcome_email(email: str, name: str) -> bool:
    return _send(_("Welcome to UdhaarSaathi"), [email], "welcome", {"name": name})


def send_contact_emails(name: str, email: str, phone: str, subject: str, message: str) -> bool:
    """Notify the team (always in English: that is the team's language), and acknowledge the sender in their language."""
    subject = " ".join(subject.split())[:160]          # one line only: no header injection through the subject
    name = " ".join(name.split())[:120]
    with translation.override("en"):
        ok = _send(f"[Contact] {subject}", [settings.SUPPORT_EMAIL], "contact_admin",
                   {"name": name, "email": email, "phone": phone, "subject": subject, "message": message}, reply_to=[email])
    _send(_("We received your message"), [email], "contact_ack", {"name": name, "subject": subject})
    return ok
