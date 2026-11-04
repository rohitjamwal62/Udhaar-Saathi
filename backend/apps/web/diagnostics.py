"""Superuser-only page that shows, from INSIDE the running server, whether email can actually leave it.

Open /admin/email-check/ while logged in as a superuser.
Add ?send=you@example.com to also send one real test email through the configured backend.
"""
import socket
import time

import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.http import JsonResponse

from . import google


def _probe(host: str, port: int) -> dict:
    t = time.time()
    try:
        socket.create_connection((host, port), timeout=5).close()
        return {"host": host, "port": port, "reachable": True, "ms": int((time.time() - t) * 1000)}
    except OSError as e:
        return {"host": host, "port": port, "reachable": False, "error": type(e).__name__, "ms": int((time.time() - t) * 1000)}


@staff_member_required
def email_check(request):
    if not request.user.is_superuser:
        return JsonResponse({"detail": "superusers only"}, status=403)
    out = {
        "environment": settings.APP_ENV,
        "smtp_user_configured": bool(settings.EMAIL_HOST_USER),
        "smtp_password_configured": bool(settings.EMAIL_HOST_PASSWORD),
        "google_connected": google.configured(),
        "network": [_probe("smtp.gmail.com", 587), _probe("smtp.gmail.com", 465), _probe("gmail.googleapis.com", 443)],
    }
    out["smtp_possible_here"] = any(p["reachable"] for p in out["network"][:2])
    if google.configured():
        try:
            info = requests.get("https://oauth2.googleapis.com/tokeninfo",
                                params={"access_token": google.access_token()}, timeout=15).json()
            scopes = (info.get("scope") or "").split()
            out["gmail_send_permission"] = "https://www.googleapis.com/auth/gmail.send" in scopes
            out["drive_permission"] = "https://www.googleapis.com/auth/drive" in scopes
        except Exception as e:  # noqa: BLE001
            out["google_error"] = str(e)[:150]
    to = request.GET.get("send", "").strip()
    if to:
        try:
            n = send_mail("UdhaarSaathi email check", f"Sent from the {settings.APP_ENV} server.",
                          settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
            out["test_email"] = {"to": to, "sent": n}
        except Exception as e:  # noqa: BLE001
            out["test_email"] = {"to": to, "sent": 0, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return JsonResponse(out, json_dumps_params={"indent": 2})
