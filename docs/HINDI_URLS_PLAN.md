# Plan: Hindi pages with their own addresses (so Google can index and rank them)

Status: implemented (phases 1 to 4; copy review and rollout verification pending). Written 18 November 2026 against commit `bea75ce`.

## 1. The problem today (verified in the code)

- English and Hindi are served from the **same address**. The language is a cookie (`django_language`). `/pricing/` shows English
  to someone without the cookie and Hindi to someone with it.
- Google never sends that cookie, so it sees **English only**. The Hindi pages cannot be indexed or found, however good the
  translation is.
- The language switcher (`templates/partials/lang_switch.html`) is a **POST form**. Crawlers do not submit forms, so even if Hindi
  addresses existed there would be no link to find them.
- The title, description, share tags and structured data are already translated, so once there is an address to put them on,
  the Hindi pages are ready to be read.

Target:

| | English (unchanged) | Hindi (new) |
|---|---|---|
| Home | `/` | `/hi/` |
| Pricing | `/pricing/` | `/hi/pricing/` |
| About | `/about/` | `/hi/about/` |
| ... | every public page | the same path with `/hi/` in front |

## 2. Design decisions (with a recommendation for each)

| # | Decision | Recommendation and why |
|---|---|---|
| D1 | How to separate the languages | **English keeps its current addresses; Hindi gets the `/hi/` prefix.** Django does this natively (`i18n_patterns(prefix_default_language=False)`). Nothing already indexed, bookmarked or used by the test scripts changes. |
| D2 | Hindi words in the address (`/hi/मूल्य/`) or English words | **English words under `/hi/`** (`/hi/pricing/`). Short, easy to share and type, no ugly percent-encoding in links and chats. Search engines handle both; the page content carries the Hindi. |
| D3 | Which pages get the prefix | **The whole website**, public and signed-in (`/hi/ledger/`, `/hi/dashboard/`), so the language sticks while a person clicks around. **Not prefixed:** `/admin/`, `/api/`, `/health/`, `/static/`, `robots.txt`, `sitemap.xml`, `site.webmanifest`, `favicon.ico`, the language-switch endpoint. |
| D4 | Telling Google the pages are twins | **`hreflang`**: every public page declares `en-IN`, `hi-IN` and `x-default` (English) alternates, each version points to the other, and each version is its **own canonical**. The sitemap lists both versions with the alternates. |
| D5 | Language switcher | **Plain links** (`<a href="/hi/pricing/" hreflang="hi" lang="hi">`) so crawlers can follow them. The chosen language is also saved in the cookie when a person lands on a language address. |
| D6 | People who chose Hindi earlier | **Redirect humans, never crawlers:** if the cookie says Hindi and the person opens an English public page, send them to the Hindi twin (302). Crawlers carry no cookie, so they are never redirected. Optional; a polite "this page in Hindi" link is the lighter alternative. |
| D7 | Hindi search words | Add Hindi keywords (लेनदेन साथी, डिजिटल खाता ऐप, उधार खाता, उधार बही, दुकान का हिसाब) to the Hindi meta keywords and make sure the Hindi page text uses them naturally. A native Hindi reader should review the copy (see phase 5). |
| D8 | Order of work | **Attach the custom domain first** (see `SEO_GUIDE.md`). Changing the domain after the Hindi pages are indexed means redirecting twice as many addresses. |

## 3. What changes in the code

| File | Change |
|---|---|
| `backend/config/urls.py` | Wrap the website routes in `i18n_patterns(..., prefix_default_language=False)`. Leave admin, API, health, static and the SEO endpoints outside it. |
| `backend/apps/web/urls.py` | Split into two lists: `seo_urls` (robots, sitemap, manifest, favicon: never prefixed) and `site_urls` (everything else: prefixed). |
| `backend/apps/web/seo.py` | Make the private-page rules ignore a `/hi/` prefix (`/hi/ledger/` is as private as `/ledger/`). Build the canonical, breadcrumbs and structured data for the **current language's own address**. Add the `hreflang` alternates. Hindi keyword list. |
| `backend/apps/web/seo_views.py` | `sitemap.xml`: 20 addresses (10 English, 10 Hindi) each with its `xhtml:link` alternates. `robots.txt`: disallow the private areas under `/hi/` as well. |
| `backend/apps/web/middleware.py` | `SeoHeadersMiddleware` applies the noindex rule to `/hi/` private paths. New small middleware: remember the language of the address in the cookie, and (D6) the cookie-based redirect for humans. |
| `backend/templates/base.html` | `<link rel="alternate" hreflang="...">` tags; `og:locale` already follows the language. |
| `backend/templates/partials/lang_switch.html` | Replace the POST form by two links to the other language's address of the same page. |
| `backend/apps/web/views.py` | The "safe next address" check on login must accept `/hi/...` addresses. Redirects by name (`redirect("dashboard")`) are already language-aware. |
| `backend/tests/*`, `deploy/e2e_*.py` | Update the 11 tests that switch language by cookie; add the new tests below; add a Hindi journey to the live scripts. |
| `SEO_GUIDE.md` | Move "Hindi pages" from "not done" to "done"; add the Search Console steps. |

What does **not** change: the phone app and the API, the English addresses, the database, the admin, the email codes.

## 4. Risks and how they are handled

| Risk | Handling |
|---|---|
| Duplicate-content signals if a Hindi page shows English text (for example a database row with no Hindi) | Existing test already fails if English text leaks into the main area of 12 Hindi pages; extend it to every page; for any page that is not fully Hindi, set `noindex` until it is. |
| Wrong or missing `hreflang` is the commonest international-SEO mistake | Tests check reciprocity (A points to B and B points back to A), absolute addresses, a self-referencing entry, the `x-default`, and that every alternate really answers 200. |
| Hindi title and description get cut off in results (Devanagari is wider) | Check the Hindi title and description lengths with a stricter limit and shorten where needed. |
| Forms, redirects and `next=` links break under the prefix | Test registration, login, ledger, customer portal and document upload **under `/hi/`**; the live scripts run the Hindi journey. |
| People with the old Hindi cookie land on English pages | D6 (redirect for humans only), or a visible "this page in Hindi" link. |
| Crawlers cannot find the Hindi pages | Plain links in the header and footer switcher, plus the sitemap. |
| A mistake after launch | Roll back by removing the `i18n_patterns` wrapper and redirecting `/hi/*` to the English twin. English addresses were never touched, so nothing already indexed is lost. |

## 5. Phases

| Phase | Work | Effort |
|---|---|---|
| 0 | Approve the decisions above. Attach the custom domain (D8). | owner |
| 1 | Routing: split the URL files, add `i18n_patterns`, fix the safe-redirect check. Run the whole test suite. | 0.5 day |
| 2 | SEO layer: `hreflang`, per-language canonical, sitemap with alternates, robots rules, noindex for private `/hi/` paths, structured data per language. | 0.5 day |
| 3 | Switcher as crawlable links, cookie memory, optional redirect for humans (D6). | 0.5 day |
| 4 | Tests: update the 11, add the new set (below). | 0.5 day |
| 5 | **Hindi copy review** by a native reader; rewrite the Hindi titles, descriptions and headings to use the words people really search; check lengths. | 0.5 day plus the reviewer |
| 6 | Roll out dev, staging, production; run the live Hindi journey; in Search Console submit the new sitemap and request indexing of `/hi/`, `/hi/about/`, `/hi/pricing/`. | 0.5 day |
| 7 | Watch Search Console for 2 to 4 weeks: pages indexed, `hreflang` errors, searches in Hindi. | ongoing |

Total: about 2 to 3 working days, plus the Hindi reviewer.

## 6. Tests that will prove it works

- Every public page has a Hindi twin that answers 200, with `<html lang="hi">`, Hindi title and description (different from English), `og:locale=hi_IN`, its own canonical.
- `hreflang` is reciprocal and complete (`en-IN`, `hi-IN`, `x-default`), addresses absolute, all alternates answer 200.
- `sitemap.xml` lists 20 addresses with their alternates; robots rules cover `/hi/` private paths; staging and dev stay `noindex` in both languages.
- Private pages under `/hi/` are `noindex` (header and meta).
- The switcher is made of plain links (no form) and points at the matching page of the other language.
- The cookie redirect sends a Hindi-cookie visitor from `/pricing/` to `/hi/pricing/`, but a request without the cookie (a crawler) stays on `/pricing/`.
- No English sentence appears in the main area of any Hindi page.
- Register, verify, login, reset, contact, ledger, customer portal and uploads all work from `/hi/` addresses.
- All existing tests still pass.

## 7. Decisions needed from the owner

1. Approve D1 to D8 (especially: English unchanged, Hindi under `/hi/`, English words in the Hindi addresses).
2. Will you attach the custom domain first? (Recommended: yes.)
3. Can someone who reads Hindi well review the Hindi copy (phase 5)? Machine-quality Hindi ranks and converts worse than natural Hindi.
4. D6: redirect returning Hindi visitors automatically, or only show a link? (Recommended: redirect humans only.)
