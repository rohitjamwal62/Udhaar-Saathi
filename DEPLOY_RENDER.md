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
