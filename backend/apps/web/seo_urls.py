"""Addresses that exist once and in one form, whatever the language: they are NOT given the /hi/ prefix."""
from django.http import HttpResponse
from django.urls import path

from . import seo_views

GOOGLE_VERIFICATION = "googlea5ba097df5b18d2f.html"            # Search Console ownership file: keep it, even after verifying


def google_verification(request):
    return HttpResponse(f"google-site-verification: {GOOGLE_VERIFICATION}", content_type="text/html; charset=utf-8")


urlpatterns = [
    path(GOOGLE_VERIFICATION, google_verification, name="google_verification"),
    path("robots.txt", seo_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", seo_views.sitemap_xml, name="sitemap_xml"),
    path("site.webmanifest", seo_views.web_manifest, name="web_manifest"),
    path("favicon.ico", seo_views.favicon_ico, name="favicon_ico"),
]
