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


class GoogleConnectionNoticeMiddleware:
    """Shows administrators a warning on the admin home page when Google's token has expired, because emails
    (verification codes) and Drive uploads stop working until Google is connected again."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and request.path == "/admin/" and getattr(request, "user", None) and request.user.is_superuser:
            from django.contrib import messages

            from apps.web import google
            state = google.token_status()
            if state == "token_expired":
                messages.warning(request, "Google is disconnected (the refresh token expired), so verification emails and "
                                          "document uploads are not working. Run: python manage.py google_consent --redirect "
                                          "https://www.google.com  (see DEPLOY_RENDER.md), and publish the Google consent "
                                          "screen so it does not expire again.")
        return self.get_response(request)


class SeoHeadersMiddleware:
    """X-Robots-Tag on every response: only public pages of the production site may be indexed. This also covers responses
    that have no HTML head (file downloads, JSON), which a meta tag could never protect."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        from apps.web import seo
        directive = seo.robots_directive(request.path)
        if directive == seo.NOINDEX_DIRECTIVE and "X-Robots-Tag" not in response:
            response["X-Robots-Tag"] = directive
        return response
