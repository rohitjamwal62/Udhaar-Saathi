from dataclasses import dataclass

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .db import q1, x


@dataclass
class AppUser:
    id: str
    mobile: str
    name: str
    session_id: str
    is_authenticated: bool = True

    @property
    def pk(self) -> str:  # DRF throttling keys on user.pk
        return self.id


class JWTAuthentication(BaseAuthentication):
    """Short-lived access JWT. The session row is checked on every request so a revoked
    device/session stops working immediately."""

    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid authorization header")
        try:
            claims = jwt.decode(parts[1], settings.SECRET_KEY, algorithms=["HS256"],
                                options={"require": ["exp", "sub", "sid"]})
        except jwt.PyJWTError:
            raise AuthenticationFailed("Invalid or expired token")
        if claims.get("typ") != "access":
            raise AuthenticationFailed("Invalid token type")
        row = q1(
            """SELECT u.id, u.mobile_e164, u.name FROM devices_sessions s
                 JOIN users u ON u.id = s.user_id
                WHERE s.id = %s AND s.user_id = %s AND s.revoked_at IS NULL AND u.status = 'active'""",
            [claims["sid"], claims["sub"]],
        )
        if not row:
            raise AuthenticationFailed("Session is no longer valid")
        x("UPDATE devices_sessions SET last_seen = now() WHERE id = %s AND last_seen < now() - interval '1 minute'",
          [claims["sid"]])
        return AppUser(str(row["id"]), row["mobile_e164"], row["name"], str(claims["sid"])), None
