from django.conf import settings
from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.db import q1


def root(request):
    """Front page, so opening the bare address shows where things are instead of a 404."""
    return JsonResponse({"service": "UdhaarSaathi API", "env": settings.APP_ENV, "health": "/health/live",
                         "database_check": "/health/ready", "docs": "/api/docs/", "api": "/api/v1/"})


def live(request):
    return JsonResponse({"status": "ok", "env": settings.APP_ENV})


def ready(request):
    try:
        q1("SELECT 1 AS ok")
        q1("SELECT 1 FROM subscription_plans LIMIT 1")  # fails if create_tables.py was not run
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


class AppConfigView(APIView):
    """Server-controlled update prompt data (optional vs forced update)."""
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        row = q1("SELECT latest_version, minimum_supported_version, force_update, update_message FROM app_config WHERE id = 1")
        if not row:
            return Response({"latest_version": settings.APP_LATEST_VERSION,
                             "minimum_supported_version": settings.APP_MIN_VERSION, "force_update": False})
        out = {"latest_version": row["latest_version"], "minimum_supported_version": row["minimum_supported_version"],
               "force_update": row["force_update"]}
        if row["update_message"]:
            out["message"] = row["update_message"]
        return Response(out)
