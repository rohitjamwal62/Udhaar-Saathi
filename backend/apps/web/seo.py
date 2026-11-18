"""Search-engine optimisation in one place: which pages are indexed, canonical addresses, robots rules, sitemap, breadcrumbs and
structured data (JSON-LD).

Rules this module enforces:
  * ONLY the production site is indexable. dev, staging and local are duplicates of the live site and must never compete with it
    in Google, so they answer "noindex, nofollow" (header and meta tag) and robots.txt disallows everything.
  * private pages (accounts, ledger, admin, API) are never indexed, whatever the environment.
  * every public page has ONE canonical address, built from SITE_URL (never from the Host header), without query strings.
  * structured data only states facts that are true and visible on the site: no ratings, no reviews, no download links we do not have.
"""
import json

from django.conf import settings
from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.translation import get_language, gettext as _

BRAND = "LenDen Saathi"
# The spellings people actually type. Used in the structured data and in the visible text of the About page and FAQ.
NAME_VARIANTS = ["Lenden Saathi", "Len Den Saathi", "LenDenSaathi", "लेनदेन साथी"]
KEYWORDS = ("LenDen Saathi, Lenden Saathi, Len Den Saathi, LenDenSaathi, लेनदेन साथी, digital khata app, udhaar khata app, "
            "udhar khata, khata book for shopkeepers, credit ledger app India, baki hisab app, digital bahi khata, "
            "offline khata app, shop credit tracking")

# Never indexed. (Crawling of login/register stays allowed so the noindex tag can be seen.)
PRIVATE_PREFIXES = ("/admin/", "/api/", "/dashboard/", "/my/", "/ledger/", "/login/", "/register/", "/verify/",
                    "/forgot-password/", "/reset-password/", "/logout/", "/i18n/", "/health/", "/live", "/ready")
# Not even crawled: nothing a search engine should spend time on.
ROBOTS_DISALLOW = ("/admin/", "/api/", "/dashboard/", "/my/", "/ledger/", "/verify/", "/reset-password/", "/i18n/", "/health/")

# (url name, priority, change frequency): the public pages that go into sitemap.xml
PUBLIC_PAGES = [
    ("home", "1.0", "weekly"),
    ("features", "0.8", "monthly"),
    ("how_it_works", "0.8", "monthly"),
    ("pricing", "0.9", "monthly"),
    ("about", "0.7", "monthly"),
    ("faq", "0.7", "monthly"),
    ("security", "0.6", "monthly"),
    ("contact", "0.5", "yearly"),
    ("terms", "0.3", "yearly"),
    ("privacy", "0.3", "yearly"),
]
INDEX_DIRECTIVE = "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
NOINDEX_DIRECTIVE = "noindex, nofollow"


def site_url() -> str:
    return settings.SITE_URL.rstrip("/")


def is_production() -> bool:
    return settings.APP_ENV == "production"


def is_private_path(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PRIVATE_PREFIXES)


def robots_directive(path: str) -> str:
    """The robots rule for a response: only public pages of the production site may be indexed."""
    if not is_production():
        return NOINDEX_DIRECTIVE
    return NOINDEX_DIRECTIVE if is_private_path(path) else INDEX_DIRECTIVE


def absolute(path: str) -> str:
    return site_url() + path


def og_image_url() -> str:
    return absolute(static("img/og-image.png"))


# ───────────────────────── breadcrumbs ─────────────────────────
def _labels() -> dict:
    return {"features": _("Features"), "how_it_works": _("How it works"), "pricing": _("Pricing"), "about": _("About"),
            "faq": _("FAQ"), "security": _("Security"), "contact": _("Contact"), "terms": _("Terms"), "privacy": _("Privacy")}


def breadcrumbs(url_name: str) -> list[tuple[str, str]]:
    """[(label, path)] from Home to the page; empty for the home page and for anything that is not a public inner page."""
    from django.urls import reverse
    label = _labels().get(url_name)
    if not label:
        return []
    return [(_("Home"), reverse("home")), (label, reverse(url_name))]


# ───────────────────────── structured data ─────────────────────────
def _organization() -> dict:
    from .context_processors import support_email
    org = {
        "@type": "Organization", "@id": absolute("/#organization"), "name": BRAND, "alternateName": NAME_VARIANTS,
        "url": absolute("/"), "logo": {"@type": "ImageObject", "url": absolute(static("img/logo.png")), "width": 512, "height": 512},
        "image": og_image_url(),
        "description": "LenDen Saathi is a digital khata (udhaar ledger) and sales tracker for small shops in India.",
        "areaServed": {"@type": "Country", "name": "India"},
        "contactPoint": [{"@type": "ContactPoint", "contactType": "customer support", "email": support_email(),
                          "availableLanguage": ["English", "Hindi"]}],
    }
    profiles = [u.strip() for u in getattr(settings, "SOCIAL_PROFILES", "").split(",") if u.strip()]
    if profiles:
        org["sameAs"] = profiles
    return org


def _website() -> dict:
    return {"@type": "WebSite", "@id": absolute("/#website"), "url": absolute("/"), "name": BRAND, "alternateName": NAME_VARIANTS,
            "inLanguage": ["en-IN", "hi-IN"], "publisher": {"@id": absolute("/#organization")}}


def _software_application() -> dict:
    from .context_processors import current_plan
    plan = current_plan()
    return {
        "@type": "SoftwareApplication", "@id": absolute("/#app"), "name": BRAND, "alternateName": NAME_VARIANTS,
        "applicationCategory": "BusinessApplication", "operatingSystem": "Android", "inLanguage": ["en", "hi"],
        "description": ("A digital khata for small shops: record what was sold on credit, note every payment, work offline, "
                        "and let your customer see and confirm the same entry."),
        "featureList": ["Digital khata and udhaar ledger", "Works offline and syncs later", "Customer can see and confirm entries",
                        "Payments and balances per customer", "Hindi and English"],
        "url": absolute("/"), "publisher": {"@id": absolute("/#organization")},
        "offers": {"@type": "Offer", "price": str(plan["amount_rupees"]), "priceCurrency": "INR",
                   "description": f"Free to register, {plan['trial_months']} months free, then Rs {plan['amount_rupees']} per month.",
                   "url": absolute("/pricing/"), "availability": "https://schema.org/InStock"},
    }


def _faq_page() -> dict | None:
    from .models import FAQ
    items = []
    for f in FAQ.objects.filter(published=True):
        q, a = " ".join(strip_tags(f.display_question).split()), " ".join(strip_tags(f.display_answer).split())
        if q and a:
            items.append({"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}})
    return {"@type": "FAQPage", "@id": absolute("/faq/#faq"), "mainEntity": items} if items else None


def _breadcrumb_list(crumbs: list[tuple[str, str]]) -> dict:
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": absolute(path)} for i, (name, path) in enumerate(crumbs)]}


def structured_data(url_name: str | None, path: str) -> list[dict]:
    """The JSON-LD nodes for this page. Only for the public pages of the production site."""
    graph = [_organization(), _website()]
    if url_name in ("home", "pricing"):
        graph.append(_software_application())
    if url_name == "faq":
        faq = _faq_page()
        if faq:
            graph.append(faq)
    page_type = {"about": "AboutPage", "contact": "ContactPage", "faq": "FAQPage"}.get(url_name or "", "WebPage")
    crumbs = breadcrumbs(url_name or "")
    if url_name == "home" or crumbs:
        node = {"@type": "WebPage" if page_type == "FAQPage" else page_type, "@id": absolute(path) + "#webpage", "url": absolute(path),
                "isPartOf": {"@id": absolute("/#website")}, "about": {"@id": absolute("/#organization")},
                "inLanguage": "hi-IN" if (get_language() or "en").startswith("hi") else "en-IN"}
        if crumbs:
            node["name"] = f"{crumbs[-1][0]} | {BRAND}"
            node["breadcrumb"] = {"@id": absolute(path) + "#breadcrumb"}
        else:
            node["name"] = BRAND
        graph.append(node)
        if crumbs:
            graph.append({**_breadcrumb_list(crumbs), "@id": absolute(path) + "#breadcrumb"})
    return graph


def to_json(graph: list[dict]) -> str:
    """One JSON-LD document, safe to place inside a script tag (no '</script>' can be formed)."""
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=2).replace("</", "<\\/")


# ───────────────────────── template context ─────────────────────────
def context(request) -> dict:
    """Everything the page head needs. Cheap for private pages and for non-production environments."""
    path = request.path
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else None
    robots = robots_directive(path)
    indexable = robots == INDEX_DIRECTIVE
    hindi = (get_language() or "en").startswith("hi")
    seo = {
        "robots": robots, "indexable": indexable, "canonical": absolute(path), "keywords": KEYWORDS,
        "og_image": og_image_url(), "og_locale": "hi_IN" if hindi else "en_IN", "og_locale_alt": "en_IN" if hindi else "hi_IN",
        "google_verification": getattr(settings, "GOOGLE_SITE_VERIFICATION", ""), "bing_verification": getattr(settings, "BING_SITE_VERIFICATION", ""),
        "crumbs": breadcrumbs(url_name or ""), "jsonld": "",
    }
    if indexable:
        seo["jsonld"] = to_json(structured_data(url_name, path))
    return {"SEO": seo}
