import uuid

from django.contrib.auth.hashers import check_password, make_password
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.db import atomic, q, q1, x
from apps.common.errors import ApiProblem
from apps.common.ratelimit import check, hit

from . import otp, tokens
from .serializers import (ForgotSerializer, LoginSerializer, OtpRequestSerializer, OtpVerifySerializer,
                          RefreshSerializer, ResetSerializer, SignupSerializer)

# Used to spend the same time hashing when the account does not exist (no timing oracle).
_DUMMY_HASH = make_password("dummy-password-for-timing")


def _user_payload(row: dict) -> dict:
    roles = [r["role"] for r in q("SELECT role FROM user_roles WHERE user_id = %s", [row["id"]])]
    return {"id": str(row["id"]), "name": row["name"], "mobile": row["mobile_e164"], "roles": roles}


class _Public(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class SignupView(_Public):
    def post(self, request):
        s = SignupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        existing = q1("SELECT id, status FROM users WHERE mobile_e164 = %s", [d["mobile"]])
        if existing and existing["status"] != "pending":
            # Same response as a fresh signup so numbers cannot be enumerated; nothing is sent.
            return Response({"challenge_id": otp.create_challenge(d["mobile"], "signup", send=False)})
        with atomic():
            if existing:
                x("""UPDATE users SET name=%s, password_hash=%s, preferred_language=%s,
                            accepted_terms_version=%s, accepted_terms_at=now(), updated_at=now() WHERE id=%s""",
                  [d["name"], make_password(d["password"]), d["language"], d["accepted_terms_version"], existing["id"]])
            else:
                x("""INSERT INTO users(mobile_e164, password_hash, name, status, preferred_language,
                                      accepted_terms_version, accepted_terms_at)
                     VALUES (%s,%s,%s,'pending',%s,%s,now())""",
                  [d["mobile"], make_password(d["password"]), d["name"], d["language"], d["accepted_terms_version"]])
            user = q1("SELECT id FROM users WHERE mobile_e164 = %s", [d["mobile"]])
            x("INSERT INTO user_roles(user_id, role) VALUES (%s,%s) ON CONFLICT DO NOTHING", [user["id"], d["role"]])
        return Response({"challenge_id": otp.create_challenge(d["mobile"], "signup")})


class OtpRequestView(_Public):
    def post(self, request):
        s = OtpRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        mobile, purpose = s.validated_data["mobile"], s.validated_data["purpose"]
        user = q1("SELECT status FROM users WHERE mobile_e164 = %s", [mobile])
        ok = bool(user) and ((purpose == "signup" and user["status"] == "pending")
                             or (purpose in ("login", "recovery") and user["status"] == "active"))
        return Response({"challenge_id": otp.create_challenge(mobile, purpose, send=ok)})


class OtpVerifyView(_Public):
    """Verifies the signup OTP, activates the account and signs the user in."""

    def post(self, request):
        s = OtpVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        otp.consume_challenge(d["challenge_id"], d["mobile"], "signup", d["otp"])
        user = q1("SELECT id, name, mobile_e164, status FROM users WHERE mobile_e164 = %s", [d["mobile"]])
        if not user or user["status"] not in ("pending", "active"):
            raise ApiProblem("That OTP is incorrect or has expired.", "invalid_otp")
        x("UPDATE users SET status='active', mobile_verified_at=COALESCE(mobile_verified_at, now()), updated_at=now() "
          "WHERE id=%s", [user["id"]])
        session = tokens.issue_session(user["id"], str(d.get("device_id") or uuid.uuid4()))
        return Response({**session, "user": _user_payload(user)})


class LoginView(_Public):
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        check(f"login:{d['mobile']}", 10, 900, "Too many login attempts. Try again in a few minutes.")
        user = q1("SELECT id, name, mobile_e164, password_hash, status FROM users WHERE mobile_e164 = %s", [d["mobile"]])
        good = check_password(d["password"], user["password_hash"] if user else _DUMMY_HASH)
        if not (user and good and user["status"] == "active"):
            raise ApiProblem("Mobile number or password is incorrect.", "invalid_credentials", 401)
        session = tokens.issue_session(user["id"], str(d["device_id"]))
        return Response({**session, "user": _user_payload(user)})


class RefreshView(_Public):
    def post(self, request):
        s = RefreshSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(tokens.rotate(s.validated_data["refresh"]))


class LogoutView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        if request.data.get("all_devices") is True:
            tokens.revoke_all(request.user.id)
        else:
            tokens.revoke_session(request.user.session_id)
        return Response(status=204)


class ForgotPasswordView(_Public):
    def post(self, request):
        s = ForgotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        mobile = s.validated_data["mobile"]
        user = q1("SELECT id FROM users WHERE mobile_e164 = %s AND status = 'active'", [mobile])
        return Response({"challenge_id": otp.create_challenge(mobile, "recovery", send=bool(user))})


class ResetPasswordView(_Public):
    def post(self, request):
        s = ResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        check(f"reset:{d['mobile']}", 10, 900)
        otp.consume_challenge(d["challenge_id"], d["mobile"], "recovery", d["otp"])
        user = q1("SELECT id FROM users WHERE mobile_e164 = %s AND status = 'active'", [d["mobile"]])
        if not user:
            raise ApiProblem("That OTP is incorrect or has expired.", "invalid_otp")
        with atomic():
            x("UPDATE users SET password_hash=%s, updated_at=now() WHERE id=%s", [make_password(d["new_password"]), user["id"]])
            tokens.revoke_all(user["id"])  # a reset signs the user out everywhere
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        row = q1("SELECT id, name, mobile_e164, email, preferred_language FROM users WHERE id = %s", [request.user.id])
        shops = q("SELECT id, name, shop_id_code FROM shops WHERE owner_user_id = %s ORDER BY created_at", [request.user.id])
        return Response({**_user_payload(row), "language": row["preferred_language"],
                         "shops": [{"id": str(s["id"]), "name": s["name"], "code": s["shop_id_code"]} for s in shops]})


class SessionsView(APIView):
    """Device/session list with revoke, so a lost phone can be signed out remotely."""

    def get(self, request):
        rows = q("""SELECT id, device_id, device_name, last_seen, created_at FROM devices_sessions
                     WHERE user_id = %s AND revoked_at IS NULL ORDER BY last_seen DESC""", [request.user.id])
        return Response({"results": [{**r, "id": str(r["id"]), "device_id": str(r["device_id"]),
                                      "current": str(r["id"]) == request.user.session_id} for r in rows]})

    def delete(self, request, session_id):
        n = x("UPDATE devices_sessions SET revoked_at = now() WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
              [session_id, request.user.id])
        if not n:
            raise ApiProblem("Session not found.", "not_found", 404)
        return Response(status=204)
