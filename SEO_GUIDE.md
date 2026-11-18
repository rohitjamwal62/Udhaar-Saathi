# SEO and search visibility for LenDen Saathi

Goal: when people search **LenDen Saathi**, **Lenden Saathi**, **Len Den Saathi** (and related words such as *digital khata app*,
*udhaar khata*), this website should be found and shown well. Nobody can guarantee a position in Google. What can be done is to
make the site easy to find, easy to understand and trustworthy, and to do the things outside the code that search engines reward.
This file lists what is already built and what only you can do.

## 1. What is built into the website

| Area | What was done |
|---|---|
| Titles and descriptions | Every public page has its own title (under about 70 characters, with the brand) and description (70 to 170 characters). Checked by tests. |
| Heading | Exactly one `<h1>` per page; the home page heading now starts with the brand name. |
| Keywords | A `keywords` meta tag with the brand spellings and phrases people search (Google ignores this tag, some other engines read it). The spellings also appear in visible text: the home page, the **About** page and the FAQ explain that *Lenden Saathi*, *Len Den Saathi*, *LenDenSaathi* and *लेनदेन साथी* are the same app. |
| New content | **About page** (`/about/`: what it is, what the name means, who it is for, what it is not, cost) and four **FAQ** answers about the name and about not being a loan app, in English and Hindi. |
| Canonical address | One canonical `<link>` per public page, built from `SITE_URL`, never from the Host header, without query strings, so `?utm=...` or a staging address can never become a duplicate. |
| robots.txt | `/robots.txt`: production allows the public pages, blocks admin, API, dashboard and ledger areas and points to the sitemap. |
| sitemap.xml | `/sitemap.xml`: the 10 public pages (home, features, how it works, pricing, about, FAQ, security, contact, terms, privacy) with priorities. A test checks that every listed address is a real, indexable page that is its own canonical. |
| Do not index the copies | **dev, staging and local answer `noindex, nofollow`** (header and meta tag), `robots.txt` disallows everything and they have no sitemap, so they can never compete with the live site. Private pages (login, accounts, ledger, admin, API) are `noindex` everywhere, also in production. |
| Social sharing | Open Graph and Twitter Card tags with an absolute 1200x630 picture made from your logo (`og-image.png`), locale tags for English and Hindi. |
| Structured data (JSON-LD) | `Organization` (name, alternative spellings, logo, support email, India), `WebSite`, `SoftwareApplication` with the real price (free to register, 3 months free, then Rs 49 a month), `FAQPage` built from the FAQ in the database, `ContactPage`, `AboutPage`, `BreadcrumbList`. Nothing we cannot prove: **no star ratings, no reviews, no download links**. |
| Links | Visible breadcrumbs on inner pages, the About link in the footer, links from the home page to the key pages, descriptive link texts. A test follows every internal link. |
| Images | The page logo is a small 11 KB file instead of 232 KB; icons for browsers, Apple devices and the web manifest; `favicon.ico`. Every illustration has a text description; every image has an `alt` and a size. |
| Speed | Smaller images, a one-day cache for static files, no external fonts, deferred scripts. |
| Language | The page declares its language (`en` or `hi`) and the share tags switch to `hi_IN`. |
| Verification tags | Set `GOOGLE_SITE_VERIFICATION` and `BING_SITE_VERIFICATION` and the site prints the matching meta tags (see below). |

## 2. What only you can do (this matters most)

### A. Get a real domain name (strongly recommended)
The site currently lives at `udhaarsaathi-api.onrender.com`: a sub-address of someone else's domain that still contains the old
brand name. Google ranks a brand most easily on its own domain. Buy something like `lendensaathi.com` or `lendensaathi.in` yourself, then:
1. Render dashboard, the production service, **Settings, Custom Domains, Add**; add the domain (and `www`) and create the DNS records Render shows. Render issues the HTTPS certificate for free.
2. Set these environment variables on the production service, then redeploy: `SITE_URL=https://www.yourdomain` (the one you chose as the main address), `DJANGO_ALLOWED_HOSTS` (add the domain), `CSRF_TRUSTED_ORIGINS=https://www.yourdomain`.
3. Redirect the other form (with or without `www`) to the main one (a Render setting or your DNS provider).
The sitemap, canonical links and structured data switch to the new domain by themselves because they all use `SITE_URL`.

### B. Tell Google and Bing about the site
1. **Google Search Console** (search.google.com/search-console): add your site as a property. Choose the *URL prefix* method and the **HTML tag** option. Copy the value of `content="..."`, set it as `GOOGLE_SITE_VERIFICATION` on the production service (or in `backend/.env`, then `python deploy/render_update.py`), redeploy, click *Verify*.
2. In Search Console, **Sitemaps**: submit `sitemap.xml`. Then **URL inspection**: paste the home page address and click *Request indexing* (repeat for About, Features, Pricing, FAQ).
3. **Bing Webmaster Tools**: add the site (you can import it from Search Console), set `BING_SITE_VERIFICATION` the same way, submit the sitemap.
4. After a few days look at *Performance* in Search Console: which searches show the site, and the pages Google has not indexed yet (with reasons).

### C. Make the brand exist elsewhere (this is how a new name starts to rank)
Search engines trust a name that appears in several places. Create, with the **same name spelling "LenDen Saathi"** and a link to the site:
- the **Google Play Store** listing of the app (title "LenDen Saathi", the keywords naturally in the description),
- a **YouTube** channel (a 1 to 2 minute demo in Hindi and English) and videos titled with the brand,
- **Instagram**, **Facebook** page and **LinkedIn** page,
- a few honest listings and write-ups (small-business and kirana communities, app directories).
When the profiles exist put their addresses in the setting `SOCIAL_PROFILES` (comma separated); they are added to the structured data as `sameAs`, which helps Google connect them with this site. Do not invent profiles that do not exist.

### D. Keep the server awake and fast
Google visits unannounced. On Render's free plan a sleeping site takes about 30 to 60 seconds to answer, and a crawler may give up.
Keep production awake (the daytime ping, or a paid plan: see `DEPLOY_RENDER.md`), and consider the Starter plan once the site is live.

## 3. Honest expectations
- A brand-new site usually needs **days to weeks** to be indexed and **months** to build trust. Submitting the sitemap speeds up the first step only.
- **"LenDen Saathi" is close to other names** (for example lending companies with "LenDen" in their name). Google may first show those. Being found for the exact brand needs the steps in section 2, especially the domain and the profiles. This product is a record-keeping app and says so, which also helps searchers who want a khata app.
- **Do not** stuff keywords, buy links or copy text from other sites: that gets sites removed from results.
- Rankings differ by place, language and device. Use Search Console, not a guess, to see the real position.

## 4. Next improvements (not done yet)
- ~~Hindi pages with their own addresses~~ **Done.** Hindi lives under `/hi/` (for example `/hi/pricing/`), English keeps its addresses. Every public page declares `hreflang` (en-IN, hi-IN, x-default) and is its own canonical; `sitemap.xml` lists both languages (20 addresses); the switcher is made of plain links. After deploying to production, in Search Console submit the sitemap again and request indexing of `/hi/`, `/hi/about/` and `/hi/pricing/`. Still open: a native Hindi reader should review the copy.
- Real **screenshots** of the app (with descriptions) on Features and How it works, and a short demo video.
- A small **blog or guide section** answering questions shopkeepers search (what is a digital khata, how to stop udhaar from piling up, udhaar reminder messages), each as its own page.
- Add the **Play Store address** to the structured data (`installUrl`) once the app is published.
- Measure Core Web Vitals in Search Console and PageSpeed Insights after the custom domain is live.

## 5. Where things live in the code
`backend/apps/web/seo.py` (rules, breadcrumbs, structured data), `seo_views.py` (robots.txt, sitemap.xml, manifest, favicon),
`backend/templates/base.html` (the page head), `backend/templates/web/about.html`, FAQ rows in migration `0012_brand_faqs.py` (editable
in Django admin), images generated by `python brand/make_assets.py` from your original logo, tests in `backend/tests/test_seo.py`.
