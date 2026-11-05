# LenDen Saathi

A digital udhaar (credit) ledger for Indian shopkeepers and their customers: record who you lent money to, how much,
and what is still to come back. Works offline on the phone, syncs when online.

- **Phone app** (Android first): React Native + TypeScript (Expo), offline-first with a local database and a sync outbox.
- **Backend + website**: Django + Django REST Framework on PostgreSQL (Neon), deployed on Render.
- **Pricing**: 3 months free, then Rs 49 a month (one trial per person). Payments through Razorpay (pay-as-you-go).
- **Languages**: the website is in English and Hindi (हिन्दी). Money is always stored as whole paise, never floats.

| Environment | Git branch | URL | Database (Neon branch) |
|---|---|---|---|
| Development | `dev` | https://udhaarsaathi-api-dev.onrender.com | `development` |
| Staging | `staging` | https://udhaarsaathi-api-staging.onrender.com | `staging` |
| Production | `main` | https://udhaarsaathi-api.onrender.com | `production` |

The free Render plan sleeps after about 15 minutes idle, so the first request after a pause can take up to a minute.

## What works today

**Website** (Django templates, responsive, animated vector art)
- Public pages: home, features, how it works, pricing (read live from the database), security, FAQ (editable in admin), contact, terms, privacy.
- A **mobile number is mandatory** for every account (one number per account); older accounts without one are asked to add it. Sign up with an **email OTP** (6 digits, hashed, 10-minute expiry, 5 attempts, resend cooldown, rate limits), login, logout, password reset by email code.
- **Udhaar ledger** at `/ledger/`: add people, record money you gave and money you got back, see each person's balance and the total still to collect. Entries are never edited or deleted; a mistake is cancelled and stays in the history.
- **Documents** on the dashboard: upload ID/shop proof/bills to a private **Google Drive** folder. Only a reference is kept in the database, and only the owner can download.
- **English / हिन्दी switch** in the header and footer. English is the default; Hindi appears only after the visitor picks it.
- **Django admin** at `/admin/` to manage users, profiles, FAQs, documents, ledger and the whole app database. A superuser-only page at `/admin/email-check/` tests email delivery from inside the live server.

**Backend API** (`/api/v1/`, Swagger at `/api/docs/`): phone-OTP login with JWT, shops, customers, ledger sync with idempotent push/pull, subscription and payments. Append-only ledger tables are protected by database triggers.

**Phone app**: sign-in, shops, customers, ledger, offline outbox with background sync. See [mobile/README.md](mobile/README.md).

## Not built yet

- Itemised credit entries (item, quantity, price) and printable receipts on the website.
- Reminder buttons (WhatsApp / phone SMS app) and the daily automatic reminder job. The Hindi/English reminder text and a Fast2SMS sender are already in `backend/apps/web/reminders.py` and `sms.py`, switched off.
- Reports and export, a customer-side view across all shops, Punjabi, Razorpay live keys.

## Repository layout

```
backend/    Django project (API + website + admin). Start here: backend/README.md
  apps/web        the website: pages, email OTP, ledger, documents, Google Drive/Gmail, i18n
  apps/accounts, shops, sync, subscriptions, system, common   the REST API
  apps/ledger     the ledger rules in one place (shops, customers, ledger events); used by the app's sync and the REST reads
  apps/legacy     read-mostly admin models for the app tables (inspectdb)
  locale/hi       Hindi translations (django.po, compiled django.mo is committed)
  templates/, static/   website HTML, CSS, JS, SVG art
  tests/          pytest suite (123 tests)
mobile/     Expo app. Start here: mobile/README.md
database/   create_tables.py (one file creates the schema), copy_data.py, check_neon.py
deploy/     render_deploy.py, render_update.py, e2e_site.py (live end-to-end test)
brand/      the owner's logo and make_assets.py (regenerates every icon from it)
render.yaml, DEPLOY_RENDER.md   Render blueprint and deployment guide
.github/workflows/ci.yml        the "test" environment: runs the suite against a Postgres service
```

## Run it locally

You need Python 3.12 and a PostgreSQL database. Hosted databases (Neon) are the default; a local scratch database is
used only by the tests.

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env                                  # then fill in DATABASE_URL and the other values
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the website and http://127.0.0.1:8000/admin/ for admin. Create an admin with
`python manage.py create_site_admin` (the password is read from an environment variable, never typed on the command line).

Phone app: see [mobile/README.md](mobile/README.md) (`npm install`, then `npm run start:account`).

## Tests

```bash
cd backend
python -m pytest -q -p no:warnings tests
```

Tests run against their own local database (`udhaar_saathi_test`) and refuse to run on any other, so real data is never
touched. Email and Google calls are replaced by fakes. `python deploy/e2e_site.py staging` runs the whole journey
(register, OTP, login, reset, contact, ledger, Drive upload, admin) against a live server and cleans up after itself.

## Configuration

All secrets live in git-ignored files (`backend/.env`, `database/.env`, `mobile/.env.*`) or in Render's environment
settings. Only the `*.example` files are committed. Main variables:

| Area | Variables |
|---|---|
| Database | `DATABASE_URL` (required; `USE_LOCAL_DB=1` is for tests only) |
| Django | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `APP_ENV` |
| Email | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` (a Gmail app password), `DEFAULT_FROM_EMAIL` |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GOOGLE_DRIVE_FOLDER_ID` |
| Automatic SMS (optional) | `SMS_PROVIDER`, `FAST2SMS_API_KEY`, `FAST2SMS_SENDER_ID`, `FAST2SMS_TEMPLATE_EN/HI/BOTH` |
| Payments | Razorpay key id and secret (test mode until live keys are added) |
| Ledger | `LEDGER_BACKEND` = `legacy` (default; the website's own tables) or `unified` (shared app ledger, planned; see `docs/UNIFY_LEDGER_PLAN.md`) |

**Email on Render.** Render blocks outbound SMTP ports (25, 465, 587) on the free plan, so the server tries SMTP first and
falls back to the **Gmail API over HTTPS**, which needs a Google token with the Drive and Gmail-send permissions. Run
`python manage.py google_consent --redirect <url>` to get the consent link and exchange the code. While the Google
consent screen is in "Testing" mode the refresh token expires after 7 days; publish the app in Google Cloud to stop that.

**SMS in India.** There is no free, fully automatic SMS route: TRAI requires a DLT-registered sender ID and pre-approved
templates. The free option is a WhatsApp / phone-SMS link the shopkeeper taps to send. Automatic SMS stays off until a
provider is configured. Templates to register are listed in `backend/apps/web/sms.py`.

## Deploy

Pushing a branch deploys it: `dev` on every push, `staging` and `main` after the GitHub checks pass. Each Render service has
its own Neon database branch. Details, the service table and the Render API helpers are in
[DEPLOY_RENDER.md](DEPLOY_RENDER.md). `python deploy/render_update.py` applies the email/Google settings to all three
services; changing an environment variable does not redeploy by itself, so trigger a deploy afterwards.

Android test build (points at staging):

```bash
cd mobile
npm run eas:me -- build --profile preview --platform android
```

## Languages

The site uses Django's translation system. Hindi strings live in `backend/locale/hi/LC_MESSAGES/django.po`.
GNU gettext is not needed: `python backend/tools/extract_messages.py` finds new strings and
`python backend/tools/compile_messages.py` builds `django.mo`, which is committed so Render needs nothing extra.
FAQ answers have Hindi fields editable in admin.

## Brand

The product is called **LenDen Saathi** (it was UdhaarSaathi before; that name is taken in the market). The logo is the
owner's own design, kept unchanged in `brand/lenden-saathi-logo-original.webp`. `python brand/make_assets.py` cuts the
tile out of its white background and regenerates the app icon, Android adaptive layers, splash, favicons and the website
logo. Internal identifiers such as the Render service names, URLs, the GitHub repository, the Expo slug and the Android
package id still say `udhaarsaathi`; they are not shown to users.

## Security notes

- Secrets are never committed; scan before every push. Rotate anything that has been shared in chat or tickets.
- OTP codes and passwords are hashed (HMAC / argon2); logins, OTPs, contact and uploads are rate limited.
- Money tables are append-only. Ledger entries and documents are visible only to their owner.
