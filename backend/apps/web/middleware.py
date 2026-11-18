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


class LanguageMemoryMiddleware:
    """The language now lives in the address (/hi/...). The cookie only REMEMBERS the choice, for two small conveniences:

    1. when a page is opened in a language, remember it;
    2. a visitor who earlier chose Hindi and opens an ENGLISH public page directly (a bookmark, a typed address, a search result)
       is sent to the Hindi twin of that page.

    Search engine crawlers carry no cookie, so they are never redirected and always see the page at the address they asked for.
    Someone who clicks "EN" inside the site is not redirected either (their request has a Referer from this site), so the English
    link always works.
    """

    SKIP = ("/admin/", "/api/", "/health/", "/static/", "/i18n/")

    def __init__(self, get_response):
        self.get_response = get_response

    def _public_english_page(self, request) -> bool:
        from django.urls import Resolver404, resolve

        from apps.web import seo
        if request.path.startswith(seo.HINDI_PREFIX + "/") or request.path == seo.HINDI_PREFIX:
            return False
        try:
            return resolve(request.path_info).url_name in seo.PUBLIC_NAMES
        except Resolver404:
            return False

    def _same_site_referer(self, request) -> bool:
        from urllib.parse import urlsplit
        ref = request.META.get("HTTP_REFERER", "")
        return bool(ref) and urlsplit(ref).netloc == request.get_host()

    def __call__(self, request):
        cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        ua = request.META.get("HTTP_USER_AGENT", "").lower()
        if (request.method == "GET" and cookie == "hi" and not any(w in ua for w in ("bot", "crawl", "spider", "slurp"))
                and not self._same_site_referer(request) and self._public_english_page(request)):
            from django.http import HttpResponseRedirect
            from django.urls import translate_url
            from django.utils.cache import patch_vary_headers
            response = HttpResponseRedirect(translate_url(request.get_full_path(), "hi"))
            patch_vary_headers(response, ("Cookie",))
            return response
        response = self.get_response(request)
        if (request.method == "GET" and response.status_code == 200 and "text/html" in response.get("Content-Type", "")
                and getattr(request, "resolver_match", None) is not None and not request.path.startswith(self.SKIP)):
            lang = getattr(request, "LANGUAGE_CODE", "en")
            if lang in ("en", "hi") and cookie != lang:
                response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=settings.LANGUAGE_COOKIE_AGE,
                                    samesite=settings.LANGUAGE_COOKIE_SAMESITE, path="/")
        return response
