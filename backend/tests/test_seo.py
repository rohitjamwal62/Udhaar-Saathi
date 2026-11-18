"""SEO: meta tags, canonical addresses, structured data, robots.txt, sitemap.xml, indexing rules, images and internal links."""
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.web.models import FAQ
from apps.web import seo

STATIC_IMG = Path(__file__).resolve().parents[1] / "static" / "img"
SITE = "https://www.example.com"
PROD = override_settings(APP_ENV="production", SITE_URL=SITE)
PUBLIC = ["home", "features", "how_it_works", "pricing", "about", "faq", "security", "contact", "terms", "privacy"]
VARIANTS = ["Lenden Saathi", "Len Den Saathi", "LenDenSaathi"]


class Page(HTMLParser):
    """Collects what a search engine reads from a page."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self.h1, self.imgs, self.ld, self.hrefs, self.svgs = "", {}, [], [], [], [], [], []
        self._in, self._buf, self.lang, self._svg_depth = None, [], None, 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "meta" and (a.get("name") or a.get("property")):
            self.meta.setdefault(a.get("name") or a.get("property"), []).append(a.get("content", ""))
        elif tag == "link":
            self.links.append(a)
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "svg":
            self.svgs.append(a)
            self._svg_depth += 1
        elif tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        elif tag == "title" and self._svg_depth == 0 and not self.title:    # the page title, not the <title> of an inline SVG drawing
            self._in, self._buf = tag, []
        elif tag == "h1":
            self._in, self._buf = tag, []
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in, self._buf = "ld", []

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "svg":
            self._svg_depth -= 1
        if self._in == "title" and tag == "title":
            self.title = "".join(self._buf).strip(); self._in = None
        elif self._in == "h1" and tag == "h1":
            self.h1.append(" ".join("".join(self._buf).split())); self._in = None
        elif self._in == "ld" and tag == "script":
            self.ld.append("".join(self._buf)); self._in = None

    def one(self, name):
        vals = self.meta.get(name, [])
        assert len(vals) == 1, f"expected exactly one <meta {name}>, found {len(vals)}"
        return vals[0]

    def canonical(self):
        c = [l["href"] for l in self.links if l.get("rel") == "canonical"]
        return c


def get(name, client=None, **kw):
    r = (client or Client()).get(reverse(name), **kw)
    assert r.status_code == 200, name
    return r, Page(r.content.decode())


def graph(page):
    assert len(page.ld) == 1, "exactly one JSON-LD block expected"
    data = json.loads(page.ld[0])
    assert data["@context"] == "https://schema.org"
    return data["@graph"]


def nodes(page, kind):
    return [n for n in graph(page) if n["@type"] == kind]


# ───────────── meta tags on every public page ─────────────
@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_every_public_page_has_the_essential_tags(name):
    r, p = get(name)
    assert 0 < len(p.title) <= 70 and "LenDen Saathi" in p.title, p.title
    desc = p.one("description")
    assert 70 <= len(desc) <= 170, (name, len(desc))
    assert len(p.h1) == 1 and p.h1[0], f"{name}: exactly one non-empty <h1>"
    assert p.lang == "en"
    assert p.one("robots").startswith("index, follow")
    assert p.canonical() == [SITE + reverse(name)]                                   # one canonical, absolute, from SITE_URL
    assert p.one("og:title") == p.title and p.one("og:description") == desc
    assert p.one("og:url") == SITE + reverse(name) and p.one("og:type") == "website" and p.one("og:site_name") == "LenDen Saathi"
    assert p.one("og:image").startswith(SITE + "/static/") and p.one("og:image:width") == "1200" and p.one("og:image:height") == "630"
    assert p.one("og:image:alt")
    assert p.one("twitter:card") == "summary_large_image" and p.one("twitter:title") == p.title and p.one("twitter:image") == p.one("og:image")
    assert p.one("og:locale") == "en_IN" and p.one("og:locale:alternate") == "hi_IN"
    kw = p.one("keywords")
    assert all(v in kw for v in VARIANTS) and "digital khata" in kw


@PROD
def test_titles_and_descriptions_are_unique_across_the_site():
    pages = {n: get(n)[1] for n in PUBLIC}
    titles = [p.title for p in pages.values()]
    descs = [p.one("description") for p in pages.values()]
    assert len(set(titles)) == len(titles) and len(set(descs)) == len(descs)


@PROD
def test_the_home_page_is_optimised_for_the_brand_and_its_spellings():
    r, p = get("home")
    assert p.title.startswith("LenDen Saathi") and "khata" in p.title.lower()
    assert "LenDen Saathi" in p.h1[0]
    text = r.content.decode()
    assert all(v in text for v in VARIANTS) and "लेनदेन साथी" in text                      # visible, honest explanation of the name


@PROD
def test_the_about_page_explains_the_name_and_links_onward():
    r, p = get("about")
    text = re.sub(r"<[^>]+>", " ", r.content.decode())
    assert all(v in text for v in VARIANTS) and "लेनदेन साथी" in text and "give and take" in text
    words = len(text.split())
    assert text.count("LenDen Saathi") / words < 0.08, "brand name stuffing"               # natural writing, not keyword stuffing
    for target in ("pricing", "features", "faq", "how_it_works", "contact", "security"):
        assert reverse(target) in p.hrefs


@PROD
def test_the_brand_questions_are_answered_in_the_faq_in_english_and_hindi():
    qs = list(FAQ.objects.filter(published=True).values_list("question", flat=True))
    for q in ("What is LenDen Saathi?", "Is it LenDen Saathi, Lenden Saathi or Len Den Saathi?", "What does LenDen mean?",
              "Is LenDen Saathi a loan or lending app?"):
        assert q in qs
    assert all(f.question_hi and f.answer_hi for f in FAQ.objects.filter(question__startswith="What is LenDen"))


# ───────────── structured data ─────────────
@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_structured_data_is_valid_json_with_the_organization_on_every_page(name):
    r, p = get(name)
    org = nodes(p, "Organization")[0]
    assert org["name"] == "LenDen Saathi" and set(seo.NAME_VARIANTS) <= set(org["alternateName"])
    assert org["logo"]["url"].startswith(SITE + "/static/") and org["logo"]["width"] == 512 == org["logo"]["height"]
    assert org["contactPoint"][0]["email"] and org["areaServed"]["name"] == "India"
    site = nodes(p, "WebSite")[0]
    assert site["name"] == "LenDen Saathi" and site["url"] == SITE + "/" and "hi-IN" in site["inLanguage"]
    blob = p.ld[0]
    assert "aggregateRating" not in blob and '"review"' not in blob                           # nothing we cannot prove
    for url in re.findall(r'"(?:url|item|@id|image)": "(https?://[^"]+)"', blob):
        assert url.startswith(SITE), url                                                      # never a staging or Host-header address


@PROD
@pytest.mark.parametrize("name", ["home", "pricing"])
def test_the_app_and_its_real_price_are_in_the_structured_data(name):
    _, p = get(name)
    app = nodes(p, "SoftwareApplication")[0]
    assert app["name"] == "LenDen Saathi" and app["operatingSystem"] == "Android" and app["applicationCategory"] == "BusinessApplication"
    offer = app["offers"]
    assert offer["price"] == "49" and offer["priceCurrency"] == "INR" and "months free" in offer["description"]
    assert "installUrl" not in app and "downloadUrl" not in app                               # there is no store listing to point to yet


@PROD
def test_the_faq_page_lists_every_published_question():
    _, p = get("faq")
    q = nodes(p, "FAQPage")[0]["mainEntity"]
    assert len(q) == FAQ.objects.filter(published=True).count() and all(i["acceptedAnswer"]["text"] for i in q)
    assert "What is LenDen Saathi?" in [i["name"] for i in q]


@PROD
def test_inner_pages_have_breadcrumbs_in_both_the_page_and_the_data():
    for name in ("features", "pricing", "about", "faq"):
        r, p = get(name)
        crumbs = nodes(p, "BreadcrumbList")[0]["itemListElement"]
        assert [c["position"] for c in crumbs] == [1, 2] and crumbs[0]["item"] == SITE + "/" and crumbs[1]["item"] == SITE + reverse(name)
        assert 'aria-label="Breadcrumb"' in r.content.decode() and 'aria-current="page"' in r.content.decode()
    r, p = get("home")
    assert not nodes(p, "BreadcrumbList") and "Breadcrumb" not in r.content.decode()


@PROD
def test_page_types_are_right():
    assert nodes(get("about")[1], "WebPage") == [] and any(n["@type"] == "AboutPage" for n in graph(get("about")[1]))
    assert any(n["@type"] == "ContactPage" for n in graph(get("contact")[1]))


@PROD
def test_a_faq_answer_cannot_break_out_of_the_structured_data_script():
    FAQ.objects.create(question="Tricky?", answer='x </script><script>alert(1)</script> "quoted" <b>bold</b>', order=500)
    r, p = get("faq")
    q = [i for i in nodes(p, "FAQPage")[0]["mainEntity"] if i["name"] == "Tricky?"][0]
    assert q["acceptedAnswer"]["text"] == 'x alert(1) "quoted" bold'                          # tags stripped, quotes preserved
    assert "<script>alert(1)" not in r.content.decode()


@override_settings(APP_ENV="production", SITE_URL=SITE, SOCIAL_PROFILES="https://www.youtube.com/@lendensaathi, https://www.instagram.com/lendensaathi")
def test_official_profiles_become_sameas_links():
    org = nodes(get("home")[1], "Organization")[0]
    assert org["sameAs"] == ["https://www.youtube.com/@lendensaathi", "https://www.instagram.com/lendensaathi"]


@PROD
def test_without_profiles_there_is_no_sameas():
    assert "sameAs" not in nodes(get("home")[1], "Organization")[0]


# ───────────── indexing rules ─────────────
@pytest.mark.parametrize("env", ["development", "staging", "local"])
@pytest.mark.parametrize("name", ["home", "pricing", "about"])
def test_only_production_is_indexable_other_environments_say_noindex_everywhere(env, name):
    with override_settings(APP_ENV=env, SITE_URL="https://udhaarsaathi-api-staging.onrender.com"):
        r, p = get(name)
        assert p.one("robots") == "noindex, nofollow" and r["X-Robots-Tag"] == "noindex, nofollow"
        assert p.canonical() == [] and p.ld == []                                            # nothing to index, nothing to describe
        txt = Client().get("/robots.txt")
        assert txt.status_code == 200 and txt.content.decode() == "User-agent: *\nDisallow: /\n"
        assert Client().get("/sitemap.xml").status_code == 404                               # nobody can submit a staging sitemap


@PROD
@pytest.mark.parametrize("path", ["/login/", "/register/", "/forgot-password/", "/verify/", "/dashboard/", "/ledger/", "/my/",
                                  "/admin/login/", "/api/docs/", "/health/live", "/i18n/setlang/"])
def test_private_pages_are_noindex_even_in_production(path):
    r = Client().get(path)
    assert r["X-Robots-Tag"] == "noindex, nofollow", path                                    # also for redirects, JSON and file responses
    if r.status_code == 200 and "text/html" in r["Content-Type"] and not path.startswith(("/admin/", "/api/")):
        assert Page(r.content.decode()).one("robots") == "noindex, nofollow"           # our own pages also carry the meta tag
                                                                                          # (Django's admin and the API docs are covered by the header)


@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_public_pages_are_not_blocked_by_the_robots_header(name):
    r, _ = get(name)
    assert "X-Robots-Tag" not in r


@PROD
def test_robots_txt_in_production():
    r = Client().get("/robots.txt")
    body = r.content.decode()
    assert r.status_code == 200 and r["Content-Type"].startswith("text/plain") and "max-age=3600" in r["Cache-Control"]
    lines = body.splitlines()
    assert lines[:2] == ["User-agent: *", "Allow: /"]
    for p in ("/admin/", "/api/", "/dashboard/", "/my/", "/ledger/"):
        assert f"Disallow: {p}" in lines
    assert f"Sitemap: {SITE}/sitemap.xml" in lines
    assert "Disallow: /\n" not in body + "\n" or "Disallow: / " not in body                  # the whole site is not blocked
    assert not any(l in ("Disallow: /", "Disallow:") for l in lines)


@PROD
def test_login_and_register_stay_crawlable_so_their_noindex_tag_can_be_seen():
    body = Client().get("/robots.txt").content.decode()
    assert "Disallow: /login" not in body and "Disallow: /register" not in body


@PROD
def test_sitemap_is_valid_complete_and_only_lists_pages_that_deserve_indexing():
    r = Client().get("/sitemap.xml")
    assert r.status_code == 200 and r["Content-Type"].startswith("application/xml")
    root = ET.fromstring(r.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.find("s:loc", ns).text for e in root.findall("s:url", ns)]
    assert sorted(locs) == sorted(SITE + reverse(n) for n in PUBLIC) and len(set(locs)) == len(locs)
    for e in root.findall("s:url", ns):
        assert e.find("s:changefreq", ns).text in ("always", "hourly", "daily", "weekly", "monthly", "yearly", "never")
        assert 0.0 <= float(e.find("s:priority", ns).text) <= 1.0
    for loc in locs:                                                                         # every listed address is a real, indexable, self-canonical page
        path = loc[len(SITE):]
        resp = Client().get(path)
        assert resp.status_code == 200 and "X-Robots-Tag" not in resp, path
        p = Page(resp.content.decode())
        assert p.canonical() == [loc] and p.one("robots").startswith("index")
    assert not any(seo.is_private_path(l[len(SITE):]) for l in locs)


@PROD
def test_canonical_comes_from_site_url_ignores_the_query_string_and_the_host_header():
    r = Client().get("/pricing/?utm_source=ad&ref=x&lang=hi", HTTP_HOST="testserver")
    assert Page(r.content.decode()).canonical() == [SITE + "/pricing/"]
    with override_settings(ALLOWED_HOSTS=["*"]):
        r2 = Client().get("/pricing/", HTTP_HOST="evil.example.org")
        assert Page(r2.content.decode()).canonical() == [SITE + "/pricing/"]


# ───────────── Hindi ─────────────
@PROD
def test_hindi_pages_declare_hindi_and_keep_the_same_canonical():
    c = Client()
    c.post("/i18n/setlang/", {"language": "hi", "next": "/"})
    _, p = get("pricing", client=c)
    assert p.lang == "hi" and p.one("og:locale") == "hi_IN" and p.one("og:locale:alternate") == "en_IN"
    assert re.search("[ऀ-ॿ]", p.title) and re.search("[ऀ-ॿ]", p.one("description"))
    assert p.canonical() == [SITE + "/pricing/"]
    assert "LenDen Saathi" in p.title                                                        # the brand stays in Latin letters


# ───────────── verification tags ─────────────
@override_settings(APP_ENV="production", SITE_URL=SITE, GOOGLE_SITE_VERIFICATION="abc123", BING_SITE_VERIFICATION="bing456")
def test_search_console_verification_tags_appear_when_configured():
    _, p = get("home")
    assert p.one("google-site-verification") == "abc123" and p.one("msvalidate.01") == "bing456"


@PROD
def test_no_verification_tags_when_not_configured():
    _, p = get("home")
    assert "google-site-verification" not in p.meta and "msvalidate.01" not in p.meta


# ───────────── images, icons, manifest ─────────────
@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_images_have_alt_and_size_and_illustrations_have_a_description(name):
    _, p = get(name)
    for img in p.imgs:
        assert "alt" in img and img.get("width") and img.get("height"), img
        assert "logo-72.png" in img["src"]                                                    # the small logo, never the 230 KB one
    for svg in p.svgs:
        if svg.get("role") == "img":
            assert svg.get("aria-label"), "illustration without a text description"


def test_the_seo_images_exist_with_the_right_sizes():
    from PIL import Image
    og = Image.open(STATIC_IMG / "og-image.png")
    assert og.size == (1200, 630) and (STATIC_IMG / "og-image.png").stat().st_size < 400_000
    assert Image.open(STATIC_IMG / "logo.png").size == (512, 512)
    assert Image.open(STATIC_IMG / "apple-touch-icon.png").size == (180, 180)
    assert Image.open(STATIC_IMG / "logo-192.png").size == (192, 192)
    assert (STATIC_IMG / "logo-72.png").stat().st_size < 30_000
    ico = Image.open(STATIC_IMG / "favicon.ico")
    assert {(16, 16), (32, 32), (48, 48)} <= set(ico.info.get("sizes", {ico.size}))


@PROD
def test_favicon_and_manifest():
    r = Client().get("/favicon.ico")
    assert r.status_code == 301 and r["Location"].endswith("/static/img/favicon.ico")
    m = Client().get("/site.webmanifest")
    data = json.loads(m.content)
    assert m["Content-Type"].startswith("application/manifest+json")
    assert data["name"] == "LenDen Saathi" and data["start_url"] == "/" and {i["sizes"] for i in data["icons"]} == {"192x192", "512x512"}
    _, p = get("home")
    rels = {l.get("rel"): l.get("href") for l in p.links}
    assert rels["manifest"] == "/site.webmanifest" and rels["apple-touch-icon"].endswith("apple-touch-icon.png") and rels["icon"]


# ───────────── internal links ─────────────
@PROD
def test_every_internal_link_on_public_pages_works_and_the_home_page_links_to_the_key_pages():
    seen = set()
    for name in PUBLIC:
        _, p = get(name)
        for href in p.hrefs:
            if href.startswith("/") and not href.startswith(("/static/", "//")):
                seen.add(href.split("#")[0].split("?")[0])
    seen.discard("")
    for href in sorted(seen):
        assert Client().get(href).status_code in (200, 301, 302), f"broken internal link: {href}"
    home_links = set(get("home")[1].hrefs)
    for target in ("about", "features", "pricing", "faq", "how_it_works"):
        assert reverse(target) in home_links, f"the home page should link to {target}"
    for name in PUBLIC[1:]:
        assert "/" in get(name)[1].hrefs                                                      # every inner page links back home
