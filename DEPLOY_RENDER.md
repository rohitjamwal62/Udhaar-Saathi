# Deploy the Django backend on Render (free)

The backend runs on Render; the database stays on **Neon**. The code is read from a GitHub repository.

## 1. Put the code on GitHub (once)
```bash
cd "D:\ROHIT JAMWAL\UDHAAR SAATHI"
git remote add origin https://github.com/<your-user>/udhaarsaathi-backend.git   # create an EMPTY repo on github.com first
git push -u origin main
```
The repo contains `backend/`, `database/` and `render.yaml` only. Secrets (`.env` files) are ignored by `.gitignore`.
Make the GitHub repo **private** if you like; Render can read private repos after you connect your GitHub account.

## 2. Create the service on Render
1. https://dashboard.render.com -> **New +** -> **Blueprint** -> connect GitHub -> choose the repo.
2. Render reads `render.yaml` and shows the service `udhaarsaathi-api` (plan: Free, region: Singapore).
3. It asks for the secret values:
   - `DATABASE_URL`: your Neon connection string (the same as in `backend/.env`).
   - Razorpay keys: leave empty for now.
4. Click **Apply**. The first build takes a few minutes.

## 3. Check it
- `https://<your-service>.onrender.com/health/ready`  ->  `{"status": "ok"}`
- `https://<your-service>.onrender.com/api/docs/`      ->  Swagger page
- `https://<your-service>.onrender.com/api/v1/app/config`

## 4. Point the app at it
Set `EXPO_PUBLIC_API_URL=https://<your-service>.onrender.com/api/v1` (in `mobile/.env` and in the `preview` profile in
`mobile/eas.json`), and remove `UDHAAR_ALLOW_CLEARTEXT` there (HTTPS needs no cleartext exception). Rebuild the app.

## Good to know (free plan)
- The service **sleeps after about 15 minutes without requests**; the next request takes roughly 30-60 seconds to wake it.
  The app handles slow requests, but the first sign-up after a break may feel slow.
- Neon also pauses when idle; both wake automatically.
- **OTPs**: there is no SMS provider yet, so `ALLOW_DEV_OTP_IN_LOGS=true` prints each OTP in the Render log
  (Dashboard -> your service -> **Logs**, search `DEV OTP`). Use this only for testing. Before real users, connect an SMS
  provider (see `backend/apps/accounts/otp.py`) and set `ALLOW_DEV_OTP_IN_LOGS` to `false`.
- **Payments** need Razorpay keys. Without them the payment endpoints answer "not configured"; nothing else is affected.
- The database tables already exist on Neon. A deploy never changes the schema.
