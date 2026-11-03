import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from apps.common.db import q1, x
from apps.common.errors import ApiProblem


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _access(user_id: str, session_id: str) -> str:
    now = timezone.now()
    return jwt.encode(
        {"sub": str(user_id), "sid": str(session_id), "typ": "access", "iat": now,
         "exp": now + timedelta(minutes=settings.JWT_ACCESS_MINUTES)},
        settings.SECRET_KEY, algorithm="HS256",
    )


def issue_session(user_id: str, device_id: str, device_name: str | None = None) -> dict:
    """New login session for a device. Any older session on the same device is revoked."""
    x("UPDATE devices_sessions SET revoked_at = now() WHERE user_id = %s AND device_id = %s AND revoked_at IS NULL",
      [user_id, device_id])
    sid = str(uuid.uuid4())
    refresh = f"{sid}.{secrets.token_urlsafe(32)}"
    x(
        """INSERT INTO devices_sessions(id, user_id, device_id, device_name, refresh_token_hash)
           VALUES (%s, %s, %s, %s, %s)""",
        [sid, user_id, device_id, device_name, _hash(refresh)],
    )
    return {"access": _access(user_id, sid), "refresh": refresh}


def rotate(refresh: str) -> dict:
    """Exchange a refresh token for a new pair. The old refresh token stops working (rotation)."""
    bad = ApiProblem("Session expired. Please log in again.", "invalid_refresh", 401)
    try:
        sid, _ = refresh.split(".", 1)
        uuid.UUID(sid)
    except (ValueError, AttributeError):
        raise bad
    row = q1(
        """SELECT s.user_id, s.refresh_token_hash, s.last_seen FROM devices_sessions s
             JOIN users u ON u.id = s.user_id
            WHERE s.id = %s AND s.revoked_at IS NULL AND u.status = 'active'""",
        [sid],
    )
    if not row or not hmac.compare_digest(row["refresh_token_hash"], _hash(refresh)):
        # A stale/replayed token for a live session: revoke that session defensively.
        if row:
            x("UPDATE devices_sessions SET revoked_at = now() WHERE id = %s", [sid])
        raise bad
    if row["last_seen"] < timezone.now() - timedelta(days=settings.REFRESH_TOKEN_DAYS):
        x("UPDATE devices_sessions SET revoked_at = now() WHERE id = %s", [sid])
        raise bad
    new_refresh = f"{sid}.{secrets.token_urlsafe(32)}"
    x("UPDATE devices_sessions SET refresh_token_hash = %s, last_seen = now() WHERE id = %s", [_hash(new_refresh), sid])
    return {"access": _access(row["user_id"], sid), "refresh": new_refresh}


def revoke_session(session_id: str) -> None:
    x("UPDATE devices_sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL", [session_id])


def revoke_all(user_id: str) -> None:
    x("UPDATE devices_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", [user_id])
