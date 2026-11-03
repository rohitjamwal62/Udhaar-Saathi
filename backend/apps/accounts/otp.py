"""OTP challenges. Raw codes are never stored (only an HMAC) and never logged by this module."""
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.db import q1, x
from apps.common.errors import ApiProblem
from apps.common.ratelimit import check

# In-memory outbox used by tests (OTP_SENDER='memory').
MEMORY_OUTBOX: list[tuple[str, str]] = []


def _digest(challenge_id: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _deliver(mobile: str, code: str) -> None:
    sender = settings.OTP_SENDER
    if sender == "memory":
        MEMORY_OUTBOX.append((mobile, code))
    elif sender == "console" and (settings.DEBUG or settings.ALLOW_DEV_OTP_IN_LOGS):
        # Development convenience only: stands in for the SMS provider.
        print(f"[DEV OTP] {mobile}: {code}", flush=True)
    else:
        # Plug a DLT-registered SMS provider in here (MSG91, Twilio, ...) and never log the code.
        raise ApiProblem("OTP delivery is not configured on this server.", "otp_unavailable", 503)


def create_challenge(mobile: str, purpose: str, send: bool = True) -> str:
    """Create a challenge. With send=False a challenge is still returned (so callers cannot be used
    to discover which numbers are registered) but no code is delivered."""
    check(f"otp:cool:{mobile}", 1, settings.OTP_RESEND_COOLDOWN_SECONDS,
          "Please wait a little before requesting another OTP.")
    check(f"otp:hour:{mobile}", settings.OTP_MAX_PER_HOUR, 3600, "Too many OTP requests. Try again later.")
    challenge_id = str(uuid.uuid4())
    code = f"{secrets.randbelow(1_000_000):06d}"
    x(
        """INSERT INTO otp_challenges(id, mobile_e164, purpose, code_hash, max_attempts, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        [challenge_id, mobile, purpose, _digest(challenge_id, code), settings.OTP_MAX_ATTEMPTS,
         timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS)],
    )
    if send:
        _deliver(mobile, code)
    return challenge_id


def consume_challenge(challenge_id: str, mobile: str, purpose: str, code: str) -> None:
    """Verify and burn a challenge, or raise a generic error. Counts every attempt atomically."""
    bad = ApiProblem("That OTP is incorrect or has expired.", "invalid_otp", 400)
    try:
        uuid.UUID(challenge_id)
    except (ValueError, TypeError):
        raise bad
    row = q1(
        """UPDATE otp_challenges SET attempts = attempts + 1
            WHERE id = %s AND mobile_e164 = %s AND purpose = %s
              AND consumed_at IS NULL AND expires_at > now() AND attempts < max_attempts
        RETURNING code_hash""",
        [challenge_id, mobile, purpose],
    )
    if not row or not hmac.compare_digest(row["code_hash"], _digest(challenge_id, code)):
        raise bad
    x("UPDATE otp_challenges SET consumed_at = now() WHERE id = %s", [challenge_id])
