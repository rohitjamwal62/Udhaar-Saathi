# Deploy the Django backend on Render (dev, staging, production)

Code lives on GitHub (`rohitjamwal62/Udhaar-Saathi`). Render deploys it automatically. The database is **Neon**.

| Environment | Git branch | Render service | Neon database branch | Deploys |
|---|---|---|---|---|
| **dev** | `dev` | `udhaarsaathi-api-dev` | `development` | on every push |
| **staging** | `staging` | `udhaarsaathi-api-staging` | `staging` | after the tests pass on GitHub |
| **production** | `main` | `udhaarsaathi-api` | `production` | after the tests pass on GitHub |
| **test** | any push / pull request | (GitHub Actions) | throw-away database inside the job | runs `pytest` |

Every environment has its own database, so testing can never touch production data.

## Day-to-day flow
```
work on branch dev  ->  push            ->  dev service updates
merge dev -> staging  -> push           ->  tests run, then staging updates   (try the app here)
merge staging -> main -> push           ->  tests run, then production updates
```
```bash
git checkout staging && git merge dev && git push      # promote to staging
git checkout main    && git merge staging && git push  # promote to production
```

## One-time setup in the Render dashboard (needs your login)
1. Sign in at https://dashboard.render.com (use "Sign in with GitHub" so the accounts are linked).
2. **New +** -> **Blueprint** -> **Connect GitHub** -> allow Render to access the repo `Udhaar-Saathi` -> select it.
   This connection is what makes pushes deploy automatically.
3. Render shows 3 services from `render.yaml`. For each one it asks for `DATABASE_URL` (and optional Razorpay keys).
   Open `render-secrets.local.txt` (git-ignored, on your PC) and paste the matching connection string:
   `udhaarsaathi-api-dev` -> development, `udhaarsaathi-api-staging` -> staging, `udhaarsaathi-api` -> production.
4. **Apply**. The first builds take a few minutes. Then delete `render-secrets.local.txt`.

## Check each environment
`https://<service>.onrender.com/health/live` shows `{"status": "ok", "env": "staging"}` (the env name tells you which one it is),
`/health/ready` checks the database, `/api/docs/` is the Swagger page.

## Good to know (free plan)
- Free services **sleep after ~15 minutes idle**; the first request afterwards takes ~30-60 s. Free hours are shared across
  your services (check the limits on Render's pricing page; they can change).
- **OTPs**: there is no SMS provider yet. In dev and staging each OTP is printed in the Render log (Logs -> search `DEV OTP`).
  In production that is **off**, so sign-up there answers "OTP delivery is not configured" until you connect an SMS provider
  (`backend/apps/accounts/otp.py`). Point the test app at **staging** meanwhile.
- **Payments** need Razorpay keys: use Razorpay *test* keys on dev/staging, live keys only in production.
- The database tables already exist on all three Neon branches. A deploy never changes the schema.
- Rotate secrets (Neon password, Razorpay) if they were ever shared in chat.

## The website (Django templates + admin) on the same services
The same Django project serves the API (`/api/...`) **and** the website (`/`, `/features/`, `/pricing/`, `/register/`, `/login/`,
`/dashboard/`, ...) plus Django admin at **`/admin/`**. Each deploy runs `collectstatic` and `migrate` during the **build**, so a start only has to boot gunicorn.

| What | Where |
|---|---|
| Website pages | `https://<service>.onrender.com/` |
| Django admin (manage every table) | `https://<service>.onrender.com/admin/` |
| API docs | `/api/docs/` |

**Email.** Render's free web services block SMTP ports (25, 465, 587), so Gmail SMTP cannot be used there. The site tries SMTP
first and automatically falls back to the **Gmail API over HTTPS**, which needs the one-time Google connection below.

**Google (Drive documents + Gmail API).** One-time consent, then the refresh token is stored as `GOOGLE_REFRESH_TOKEN`:
```bash
cd backend
python manage.py google_consent --redirect https://www.google.com/            # prints the Google page to open
python manage.py google_consent --redirect https://www.google.com/ --code <code=...>   # saves GOOGLE_REFRESH_TOKEN in backend/.env
python deploy/render_update.py                                                  # pushes the settings to Render
```
The redirect address must be listed under *Authorized redirect URIs* of the OAuth client in Google Cloud Console, and the
**Google Drive API** and **Gmail API** must be enabled in that project. Google refresh tokens of apps in "Testing" status expire
after 7 days: publish the OAuth consent screen ("In production") to avoid that.

**Admin user.** `ADMIN_PASSWORD=... python manage.py create_site_admin --username Rohit --email you@example.com` (run once per
environment database). Change the password after the first login.


## Cold starts (why the first visit can take a minute)
Render's **free** plan stops a web service after 15 minutes without a request. The next visitor waits while Render starts it
again (they see Render's "waking up" page): measured at about **48 seconds** on staging before the changes below.

What was done:
- **Faster boot.** Migrations moved from the start command to the build command, and gunicorn runs one worker with 4 threads
  (`--workers 1 --threads 4 --worker-class gthread`). The service has less to do before it can answer.
- **Keep-alive.** `.github/workflows/keepalive.yml` requests `/health/live` of **production** every 5 minutes between 06:30 and
  23:25 India time, so shoppers rarely meet a sleeping server. Render gives 750 free hours a month shared by all three
  services, so it is deliberately not run 24 hours a day. GitHub scheduled runs are best effort and can be late, and the
  service still sleeps at night, so the first visit in the morning can still be slow.
- **The real fix** is the **Starter** plan for the production service: always awake, no cold start, no schedule to maintain.
  Change the plan on the service's Settings page (or ask the assistant to do it through the API), then delete the keep-alive workflow.
