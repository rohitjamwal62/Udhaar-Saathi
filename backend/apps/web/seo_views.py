"""robots.txt, sitemap.xml, the web app manifest and favicon.ico."""
import json
from xml.sax.saxutils import escape

from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from . import seo


@require_GET
@cache_control(max_age=3600, public=True)
def robots_txt(request):
    """Production: crawl the public pages, skip the private ones, and point to the sitemap.
    Anywhere else (dev, staging, local): crawl nothing, so those copies never compete with the live site."""
    if not seo.is_production():
        body = "User-agent: *\nDisallow: /\n"
    else:
        lines = ["User-agent: *", "Allow: /"] + [f"Disallow: {p}" for p in seo.robots_disallow()]
        lines += ["", f"Sitemap: {seo.absolute('/sitemap.xml')}"]
        body = "\n".join(lines) + "\n"
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@require_GET
@cache_control(max_age=3600, public=True)
def sitemap_xml(request):
    """Only the public pages of the production site. The other environments have no sitemap (404), so nobody can submit them."""
    if not seo.is_production():
        raise Http404
    urls = []
    for name, priority, freq in seo.PUBLIC_PAGES:
        alts = seo.alternates(name)
        links = "".join(f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{escape(href)}"/>\n' for lang, href in alts)
        for lang in ("en", "hi"):                                  # one entry per language version, each listing both alternates
            urls.append(f"  <url>\n    <loc>{escape(seo.language_url(name, lang))}</loc>\n{links}"
                        f"    <changefreq>{freq}</changefreq>\n    <priority>{priority}</priority>\n  </url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n")
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


@require_GET
@cache_control(max_age=86400, public=True)
def web_manifest(request):
    data = {
        "name": seo.BRAND, "short_name": "LenDen Saathi", "description": "Digital khata and udhaar ledger for small shops in India.",
        "start_url": "/", "scope": "/", "display": "minimal-ui", "lang": "en-IN",
        "background_color": "#ffffff", "theme_color": "#0B6E4F",
        "icons": [{"src": static("img/logo-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
                  {"src": static("img/logo.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"}],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/manifest+json; charset=utf-8")


@require_GET
def favicon_ico(request):
    """Browsers and crawlers ask for /favicon.ico by default."""
    # Served directly (not a redirect): Google's icon crawler is most reliable with a plain 200 at /favicon.ico.
    from django.contrib.staticfiles import finders
    path = finders.find("img/favicon.ico")
    with open(path, "rb") as fh:
        resp = HttpResponse(fh.read(), content_type="image/x-icon")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp
