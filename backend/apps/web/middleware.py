from django.conf import settings
from django.http import HttpResponse

from apps.common.net import client_ip
from apps.common.ratelimit import hit


class AdminLoginThrottleMiddleware:
    """Slow down password guessing on the Django admin login (per IP, per 15 minutes)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path.rstrip("/").endswith("/admin/login"):
            ip = client_ip(request) or "?"
            if not hit(f"adminlogin:{ip}", settings.ADMIN_LOGIN_MAX_ATTEMPTS, 900):
                return HttpResponse("Too many login attempts. Please wait 15 minutes.", status=429)
        return self.get_response(request)


class IgnoreAcceptLanguageMiddleware:
    """The site is English for everybody. Hindi is used only after the visitor picks it (language cookie / session),
    never because the browser sends Accept-Language: hi. Runs before LocaleMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.META.pop("HTTP_ACCEPT_LANGUAGE", None)
        return self.get_response(request)
