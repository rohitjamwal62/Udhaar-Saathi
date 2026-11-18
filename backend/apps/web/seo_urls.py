"""Addresses that exist once and in one form, whatever the language: they are NOT given the /hi/ prefix."""
from django.urls import path

from . import seo_views

urlpatterns = [
    path("robots.txt", seo_views.robots_txt, name="robots_txt"),
    path("sitemap.xml", seo_views.sitemap_xml, name="sitemap_xml"),
    path("site.webmanifest", seo_views.web_manifest, name="web_manifest"),
    path("favicon.ico", seo_views.favicon_ico, name="favicon_ico"),
]
