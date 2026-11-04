"""Email one-time codes: create, send, verify. The code is stored only as an HMAC, is single-use, expires, and has an
attempt limit. Requests are rate-limited per email and per IP."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.common.ratelimit import hit

from . import mailer
from .models import EmailOTP


class OtpDeliveryError(Exception):
    """The code was created but the email could not be sent."""


class OtpError(Exception):
    """Carries a message that is safe to show to the user."""


def _digest(otp_id: int, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{otp_id}:{code}".encode(), hashlib.sha256).hexdigest()


def seconds_until_resend(email: str, purpose: str) -> int:
    last = EmailOTP.objects.filter(email__iexact=email, purpose=purpose).order_by("-created_at").first()
    if not last:
        return 0
    wait = settings.EMAIL_OTP_RESEND_SECONDS - (timezone.now() - last.created_at).total_seconds()
    return max(0, int(wait) + (1 if wait > 0 else 0))


def send_code(email: str, purpose: str, ip: str | None = None) -> None:
    """Create and email a fresh code. Raises OtpError with a user-safe message if throttled or the email cannot be sent."""
    email = email.strip().lower()
    wait = seconds_until_resend(email, purpose)
    if wait:
        raise OtpError(ngettext("Please wait %(n)d second before asking for another code.", "Please wait %(n)d seconds before asking for another code.", wait) % {"n": wait})
    if not hit(f"emailotp:hour:{email}", 6, 3600) or (ip and not hit(f"emailotp:ip:{ip}", 20, 3600)):
        raise OtpError(_("Too many code requests. Please try again in an hour."))
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction.atomic():
        EmailOTP.objects.filter(email__iexact=email, purpose=purpose, consumed_at__isnull=True).update(consumed_at=timezone.now())
        otp = EmailOTP.objects.create(email=email, purpose=purpose, code_hash="", ip_address=ip,
                                      expires_at=timezone.now() + timedelta(seconds=settings.EMAIL_OTP_TTL_SECONDS))
        otp.code_hash = _digest(otp.pk, code)
        otp.save(update_fields=["code_hash"])
    if settings.ALLOW_DEV_OTP_IN_LOGS:
        # TEST ENVIRONMENTS ONLY (dev/staging): also print the code in the server log so sign-up can be tested before
        # a mailbox is reachable. Anyone who can read the log can read the code. Never enabled in production.
        print(f"[DEV EMAIL OTP] {email} ({purpose}): {code}", flush=True)
    sent = mailer.send_otp_email(email, code, purpose, settings.EMAIL_OTP_TTL_SECONDS // 60)
    if not sent and not settings.ALLOW_DEV_OTP_IN_LOGS:
        raise OtpDeliveryError(_("We could not send the email right now. Please try again in a moment."))


def verify_code(email: str, purpose: str, code: str) -> None:
    """Burn the code if it is right; raise OtpError otherwise. Every wrong guess counts."""
    bad = OtpError(_("That code is incorrect or has expired."))
    email = email.strip().lower()
    with transaction.atomic():
        otp = (EmailOTP.objects.select_for_update()
               .filter(email__iexact=email, purpose=purpose, consumed_at__isnull=True, expires_at__gt=timezone.now())
               .order_by("-created_at").first())
        if not otp:
            raise bad
        if otp.attempts >= settings.EMAIL_OTP_MAX_ATTEMPTS:
            raise OtpError(_("Too many wrong attempts. Please request a new code."))
        otp.attempts += 1
        ok = hmac.compare_digest(otp.code_hash, _digest(otp.pk, code.strip()))
        if ok:
            otp.consumed_at = timezone.now()
        otp.save(update_fields=["attempts", "consumed_at"])
    if not ok:
        raise bad
