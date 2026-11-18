"""Hindi pages have their own addresses (/hi/...): hreflang, canonicals, robots, noindex, the language cookie, forms and links."""
import json
import re

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import translation

from apps.web.models import FAQ

from .test_seo import PUBLIC, SITE, Page, graph, nodes
from .test_web import last_code, phone_for, register

PROD = override_settings(APP_ENV="production", SITE_URL=SITE)
DEVANAGARI = re.compile("[ऀ-ॿ]")


def en(name, *args):
    with translation.override("en"):
        return reverse(name, args=args or None)


def hi(name, *args):
    with translation.override("hi"):
        return reverse(name, args=args or None)


def get(path, client=None, **kw):
    r = (client or Client()).get(path, **kw)
    return r, Page(r.content.decode())


# ───────────── the addresses ─────────────
def test_hindi_addresses_are_the_english_ones_with_a_hi_prefix_and_english_is_unchanged():
    assert en("home") == "/" and hi("home") == "/hi/"
    for name in PUBLIC:
        assert hi(name) == "/hi" + en(name)
    assert en("pricing") == "/pricing/" and hi("pricing") == "/hi/pricing/"                  # nothing already indexed moved


def test_files_and_apps_are_not_given_a_hindi_copy():
    for path in ("/hi/robots.txt", "/hi/sitemap.xml", "/hi/site.webmanifest", "/hi/favicon.ico", "/hi/admin/login/", "/hi/api/docs/", "/hi/health/live"):
        assert Client().get(path).status_code == 404, path
    for path in ("/robots.txt", "/site.webmanifest", "/admin/login/", "/api/docs/", "/health/live"):
        assert Client().get(path).status_code == 200, path


# ───────────── every public page has a Hindi twin with its own content ─────────────
@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_every_public_page_has_a_hindi_twin_with_its_own_tags(name):
    r_en, p_en = get(en(name))
    r, p = get(hi(name))
    assert r.status_code == 200 and p.lang == "hi" and p_en.lang == "en"
    assert DEVANAGARI.search(p.title) and p.title != p_en.title and 0 < len(p.title) <= 80, p.title
    desc = p.one("description")
    assert DEVANAGARI.search(desc) and desc != p_en.one("description") and 40 <= len(desc) <= 200, (name, len(desc))
    assert len(p.h1) == 1 and p.h1[0] and p.h1[0] != p_en.h1[0]
    assert p.one("robots").startswith("index, follow") and "X-Robots-Tag" not in r
    assert p.canonical() == [SITE + hi(name)]                                                # each language version is its own canonical
    assert p.one("og:url") == SITE + hi(name) and p.one("og:locale") == "hi_IN" and p.one("og:locale:alternate") == "en_IN"
    assert p.one("og:title") == p.title and p.one("twitter:title") == p.title
    assert "लेनदेन साथी" in p.one("keywords") and "डिजिटल खाता" in p.one("keywords")             # Hindi search words, English brand spellings too
    assert "Lenden Saathi" in p.one("keywords")


@PROD
def test_hindi_titles_and_descriptions_are_unique():
    pages = {n: get(hi(n))[1] for n in PUBLIC}
    titles = [p.title for p in pages.values()]
    descs = [p.one("description") for p in pages.values()]
    assert len(set(titles)) == len(titles) and len(set(descs)) == len(descs)


@pytest.mark.parametrize("name", PUBLIC)
def test_no_english_sentence_is_left_in_the_main_area_of_a_hindi_page(name):
    r = Client().get(hi(name))
    main = r.content.decode().split("<main")[1].split("</main>")[0]
    text = re.sub(r"<[^>]+>", " ", main)
    english_runs = [w for w in re.findall(r"(?:[A-Za-z][A-Za-z'’,.-]*\s+){5,}[A-Za-z]+", text)]
    allowed = ("LenDen Saathi", "Lenden Saathi", "Len Den Saathi", "LenDenSaathi")                # the brand and its spellings are meant to stay
    leaks = [s for s in english_runs if not any(a in s for a in allowed)]
    assert not leaks, f"{name}: untranslated text on the Hindi page: {leaks[:2]}"


@PROD
def test_the_hindi_faq_page_shows_and_declares_hindi_questions():
    r, p = get(hi("faq"))
    q = nodes(p, "FAQPage")[0]["mainEntity"]
    assert len(q) == FAQ.objects.filter(published=True).count()
    hindi_questions = [i["name"] for i in q if DEVANAGARI.search(i["name"])]
    assert len(hindi_questions) >= 12 and "LenDen Saathi क्या है?" in hindi_questions


# ───────────── hreflang ─────────────
def _alternates(p):
    return [(l["hreflang"], l["href"]) for l in p.links if l.get("rel") == "alternate" and l.get("hreflang")]


@PROD
@pytest.mark.parametrize("name", PUBLIC)
def test_hreflang_is_complete_absolute_and_reciprocal(name):
    en_url, hi_url = SITE + en(name), SITE + hi(name)
    expected = [("en-IN", en_url), ("hi-IN", hi_url), ("x-default", en_url)]
    for path in (en(name), hi(name)):
        r, p = get(path)
        assert _alternates(p) == expected, path                                              # both versions list the same set, themselves included
    for _lang, address in expected:                                                          # every alternate really exists and points back
        resp, alt_page = get(address[len(SITE):])
        assert resp.status_code == 200 and expected[0] in _alternates(alt_page) and expected[1] in _alternates(alt_page)


def test_other_environments_publish_no_hreflang_and_stay_noindex():
    with override_settings(APP_ENV="staging", SITE_URL="https://udhaarsaathi-api-staging.onrender.com"):
        r, p = get(hi("pricing"))
        assert r.status_code == 200 and p.lang == "hi"
        assert _alternates(p) == [] and p.canonical() == [] and p.one("robots") == "noindex, nofollow"
        assert r["X-Robots-Tag"] == "noindex, nofollow"


# ───────────── robots.txt, private pages ─────────────
@PROD
def test_robots_txt_blocks_the_private_areas_in_both_languages_but_not_the_hindi_pages():
    lines = Client().get("/robots.txt").content.decode().splitlines()
    for area in ("dashboard", "my", "ledger", "verify", "reset-password"):
        assert f"Disallow: /{area}/" in lines and f"Disallow: /hi/{area}/" in lines, area
    assert "Disallow: /admin/" in lines and "Disallow: /hi/admin/" not in lines              # admin and API exist only once
    assert "Disallow: /hi/" not in lines and "Disallow: /hi" not in lines                    # the Hindi site itself is open to crawlers
    assert not any(l in ("Disallow: /", "Disallow:") for l in lines)


@PROD
@pytest.mark.parametrize("path", ["/hi/login/", "/hi/register/", "/hi/forgot-password/", "/hi/verify/", "/hi/dashboard/", "/hi/ledger/", "/hi/my/"])
def test_private_pages_are_noindex_under_hi_too(path):
    r = Client().get(path)
    assert r["X-Robots-Tag"] == "noindex, nofollow", path
    if r.status_code == 200:
        assert Page(r.content.decode()).one("robots") == "noindex, nofollow"


# ───────────── the language switcher and the cookie ─────────────
@pytest.mark.parametrize("name", PUBLIC)
def test_every_page_links_to_its_twin_with_plain_crawlable_links(name):
    for path, here in ((en(name), "en"), (hi(name), "hi")):
        html = Client().get(path).content.decode()
        assert f'<a href="{en(name)}" hreflang="en"' in html and f'<a href="{hi(name)}" hreflang="hi"' in html
        assert "/i18n/setlang/" not in html                                                  # no form to submit, nothing a crawler cannot follow
        current = re.findall(r'<a href="[^"]*" hreflang="(\w+)"[^>]*aria-current="true"', html)
        assert current == [here, here]                                                       # header and footer mark the current language


def test_someone_who_chose_hindi_is_taken_to_the_hindi_twin_when_opening_an_english_page_directly():
    c = Client()
    c.cookies["django_language"] = "hi"
    for name in ("home", "pricing", "about", "faq"):
        r = c.get(en(name))
        assert r.status_code == 302 and r["Location"] == hi(name) and "Cookie" in r["Vary"], name
    r = c.get("/pricing/?utm_source=ad")
    assert r["Location"] == "/hi/pricing/?utm_source=ad"                                     # the rest of the address is kept


def test_the_redirect_never_applies_to_crawlers_clicks_inside_the_site_or_private_pages():
    assert Client().get("/pricing/").status_code == 200                                      # no cookie (every crawler): never redirected
    c = Client()
    c.cookies["django_language"] = "hi"
    assert c.get("/pricing/", HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1)").status_code == 200
    r = c.get("/pricing/", HTTP_REFERER="http://testserver/hi/pricing/")                       # clicked "EN" on this site
    assert r.status_code == 200 and Page(r.content.decode()).lang == "en"
    assert c.cookies["django_language"].value == "en"                                        # and that choice is remembered
    assert c.get("/pricing/").status_code == 200                                             # so the next direct visit stays English
    c2 = Client()
    c2.cookies["django_language"] = "hi"
    assert c2.get("/login/").status_code == 200 and c2.get("/ledger/").status_code == 302 and c2.get("/ledger/")["Location"].startswith("/login")
    assert c2.post("/pricing/", {}).status_code in (200, 405)                                # only GET is ever redirected


def test_opening_a_language_address_remembers_that_language():
    c = Client()
    r = c.get("/hi/pricing/")
    assert r.status_code == 200 and c.cookies["django_language"].value == "hi"
    c.get("/about/", HTTP_REFERER="http://testserver/hi/about/")
    assert c.cookies["django_language"].value == "en"


def test_the_language_endpoint_still_works_and_lands_on_the_matching_address():
    r = Client().post("/i18n/setlang/", {"language": "hi", "next": "/pricing/"})
    assert r.status_code == 302 and r["Location"] == "/hi/pricing/"
    r = Client().post("/i18n/setlang/", {"language": "en", "next": "/pricing/"})
    assert r.status_code == 302 and r["Location"] == "/pricing/"


# ───────────── links, structured data ─────────────
@pytest.mark.parametrize("name", PUBLIC)
def test_links_on_a_hindi_page_stay_in_hindi(name):
    _, p = get(hi(name))
    site_links = [h for h in p.hrefs if h.startswith("/") and not h.startswith(("/static/", "//", "/favicon", "/robots", "/sitemap"))]
    strays = [h for h in site_links if not h.startswith("/hi/") and h != "/hi"]
    assert strays == [en(name)] * 2, f"{name}: only the link to the English twin may leave Hindi, found {strays}"   # the "EN" switch (header + footer)
    for h in site_links:
        if h.startswith("/hi/"):
            assert Client().get(h.split("#")[0].split("?")[0]).status_code in (200, 301, 302), h


@PROD
def test_structured_data_on_a_hindi_page_describes_that_page():
    _, p = get(hi("pricing"))
    g = graph(p)
    page_node = [n for n in g if n["@type"] == "WebPage"][0]
    assert page_node["inLanguage"] == "hi-IN" and page_node["url"] == SITE + "/hi/pricing/"
    crumbs = nodes(p, "BreadcrumbList")[0]["itemListElement"]
    assert [c["item"] for c in crumbs] == [SITE + "/hi/", SITE + "/hi/pricing/"] and DEVANAGARI.search(crumbs[1]["name"])
    assert nodes(p, "SoftwareApplication")[0]["offers"]["url"] == SITE + "/hi/pricing/"
    assert nodes(p, "Organization")[0]["name"] == "LenDen Saathi"
    html = Client().get("/hi/pricing/").content.decode()
    assert 'aria-label="पेज का रास्ता"' in html and 'href="/hi/"' in html                    # the visible breadcrumbs are Hindi too


# ───────────── forms and sign-in work under /hi/ ─────────────
def test_the_whole_sign_up_and_ledger_journey_works_from_hindi_addresses():
    c = Client()
    c.lang = "hi"
    r = register(c, "hindi-journey@example.com")
    assert r.status_code == 302 and r["Location"] == "/hi/verify/"
    r = c.post("/hi/verify/", {"code": last_code()})
    assert r.status_code == 302 and r["Location"] == "/hi/dashboard/"
    assert c.get("/hi/dashboard/").status_code == 200
    html = c.get("/hi/ledger/").content.decode()
    assert '<html lang="hi">' in html and "आपका उधार बही-खाता" in html
    r = c.post("/hi/ledger/people/add/", {"name": "रमेश", "phone": "", "email": "", "note": ""})
    assert r.status_code == 302 and r["Location"].startswith("/hi/ledger/people/")
    r = c.post("/hi/logout/")
    assert r.status_code == 302 and r["Location"] == "/hi/"
    r = c.post("/hi/login/?next=/hi/ledger/", {"identifier": "hindi-journey@example.com", "password": "Sup3rSecret"})
    assert r.status_code == 302 and r["Location"] == "/hi/ledger/"                           # a Hindi address is a safe place to return to


def test_a_wrong_login_and_the_contact_form_work_in_hindi():
    c = Client()
    r = c.post("/hi/login/", {"identifier": "nobody@example.com", "password": "wrong-pass1"})
    assert r.status_code == 200 and "ईमेल या पासवर्ड गलत है।" in r.content.decode()
    r = c.post("/hi/contact/", {"name": "Ravi", "email": "ravi@example.com", "phone": "", "subject": "Hello", "message": "A question.", "website": ""})
    assert r.status_code == 302 and r["Location"] == "/hi/contact/"


def test_an_open_redirect_through_next_is_still_refused_under_hindi():
    for bad in ("https://evil.example/", "//evil.example/", "/hi/../../evil", "javascript:alert(1)"):
        r = Client().post(f"/hi/login/?next={bad}", {"identifier": "nobody@example.com", "password": "x"})
        assert r.status_code in (200, 302) and "evil" not in r.get("Location", "")
