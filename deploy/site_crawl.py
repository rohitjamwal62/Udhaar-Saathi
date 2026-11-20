#!/usr/bin/env python3
"""Site crawler for LenDen Saathi (standard library only).

Reads sitemap.xml, follows internal links, fetches every public page once and prints a report.
Exits with code 1 if any page is broken, so a scheduler (GitHub Actions) shows a failed run.

    python deploy/site_crawl.py [base_url]
"""
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://udhaarsaathi-api.onrender.com").rstrip("/")
UA = "LenDenSaathi-SiteCheck/1.0"
TIMEOUT = 90            # the first request may wake a sleeping server
DELAY = 0.5             # seconds between requests (be gentle)
MAX_PAGES = 300         # safety limit
# Private or non-page areas (robots.txt blocks them as well)
SKIP = ("/admin/", "/api/", "/dashboard/", "/my/", "/ledger/", "/verify/", "/reset-password/", "/i18n/",
        "/health/", "/static/", "/hi/dashboard/", "/hi/my/", "/hi/ledger/", "/hi/verify/", "/hi/reset-password/")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read().decode("utf-8", "replace") if ("html" in ctype or "xml" in ctype) else ""
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # timeout, DNS, TLS ...
        return f"ERR {e}", ""


def sitemap_urls():
    status, body = fetch(BASE + "/sitemap.xml")
    if status != 200:
        print(f"WARNING: sitemap.xml returned {status}")
        return []
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [e.text.strip() for e in ElementTree.fromstring(body).findall(".//s:loc", ns)]


def internal(url):
    p = urlparse(url)
    return p.netloc == urlparse(BASE).netloc and not p.path.startswith(SKIP)


def links_in(html, page_url):
    out = set()
    for href in re.findall(r'href=["\']([^"\'#][^"\']*)["\']', html):
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(page_url, href))[0]
        if internal(url):
            out.add(url)
    return out


def main():
    queue = [BASE + "/"] + sitemap_urls()
    seen, bad = set(), []
    t0 = time.time()
    while queue and len(seen) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen or not internal(url):
            continue
        seen.add(url)
        status, html = fetch(url)
        print(f"{'OK ' if status == 200 else 'BAD'} {status}  {url}")
        if status != 200:
            bad.append((url, status))
        queue.extend(u for u in links_in(html, url) if u not in seen)
        time.sleep(DELAY)
    print(f"\nCrawled {len(seen)} pages in {time.time() - t0:.0f}s, {len(bad)} problem(s).")
    for url, status in bad:
        print(f"  {status}  {url}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
