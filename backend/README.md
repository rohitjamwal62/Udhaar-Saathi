# UdhaarSaathi backend (Django + DRF + PostgreSQL)

The database schema is owned by `../database/create_tables.py`. Django has no models or migrations: it runs
plain SQL against those tables, so the constraints and append-only triggers in PostgreSQL always apply.

## Run (live database = Neon)
The backend uses **Neon** (hosted PostgreSQL) only. There is no local-database fallback: without `DATABASE_URL`
the server refuses to start.
```bash
cd ../database && pip install psycopg2-binary && python check_neon.py   # is Neon reachable and healthy?
cd ../backend
pip install -r requirements.txt
# backend/.env must contain DATABASE_URL=postgresql://...neon.tech/...?sslmode=require  (Neon console -> Connect)
python manage.py runserver 0.0.0.0:8000     # the first line printed shows which database it uses
```
- API: `http://localhost:8000/api/v1/`   Swagger UI: `/api/docs/`   OpenAPI: `/api/schema/`   Health: `/health/live`, `/health/ready`
- Development OTPs are printed in this console as `[DEV OTP] +91...: 123456` (`OTP_SENDER=console`, only when `DJANGO_DEBUG=true`).
- Payments use a **fake gateway** unless you set the Razorpay keys and `PAYMENT_GATEWAY=razorpay`.

## Test
```bash
python -m pytest        # 39 tests on a LOCAL scratch database `udhaar_saathi_test` (needs local PostgreSQL; never touches Neon)
```

## Move the database to Neon (hosted PostgreSQL)
1. In the Neon console open your project, branch `production`, click **Connect**, and copy the connection string
   (`postgresql://user:password@ep-...neon.tech/dbname?sslmode=require`).
2. Put it in `database/.env` (git-ignored, never in chat or in code): `DATABASE_URL=postgresql://...`
   While `DATABASE_URL` is set it replaces the local `PG*` settings for both the scripts and the backend.
   To go back to local PostgreSQL, empty that line.
3. From the `database` folder:
   ```bash
   python create_tables.py        # creates the 38 tables, rules and the Rs 49 plan on Neon
   python copy_data.py            # dry run: shows what would be copied from local PostgreSQL
   python copy_data.py --go       # copies your rows, then verifies the counts (safe to repeat)
   ```
4. Restart the backend. `/health/ready` must say ok. Tests always use the local `udhaar_saathi_test` database, never Neon.
Keep the local database as a backup until you have checked the app on Neon.

## Connect the Android app
1. Phone and PC on the same Wi-Fi. In `mobile/.env` set `EXPO_PUBLIC_API_URL=http://<PC-LAN-IP>:8000/api/v1` and `EXPO_PUBLIC_DEMO_MODE=false`.
2. Add that IP to `DJANGO_ALLOWED_HOSTS` in `backend/.env` and start the server with `0.0.0.0:8000`.
3. `cd mobile && npx expo start -c`, sign up in the app, read the OTP from the server console.
Android emulator uses `http://10.0.2.2:8000/api/v1`. Use HTTPS for any real deployment.

## What it enforces
- Auth: Argon2id passwords, OTP stored only as an HMAC (single use, 5 attempts, 5 min), generic login errors, rate limits,
  rotating refresh tokens (replay revokes the session), logout/reset revoke sessions, device list.
- `POST /sync/batch`: validates every item, binds it to the caller's own shop, recomputes ledger signs, **forces
  `confirmation_status='shopkeeper_recorded'`**, makes retries idempotent (receipts + unique keys), and returns
  accepted / duplicate / conflict / rejected per item.
- Subscriptions: one 3-month trial per owner account, Rs 49/month, 7-day grace, read-only after expiry (history kept), writes blocked
  server-side. Razorpay order is created on the server with a server-decided amount; payment is activated only after signature
  verification; webhooks are signature-checked and duplicate/out-of-order safe.
- Money is always an integer (paise) in every response.

## Not built yet
Customer-side endpoints (shop linking, confirmation links, OTP/signature confirmation, disputes), evidence file upload to private
storage, SMS/WhatsApp/email/FCM providers (OTP sender is a console stub: plug in a DLT-registered SMS provider in
`apps/accounts/otp.py`), `GET /sync/changes` (pulling server changes to a second device), UPI AutoPay mandates, Celery/Redis jobs
(status refresh is lazy on read; `subscriptions.service.refresh_all()` can be scheduled), per-endpoint OpenAPI request/response
annotations, production Redis cache for rate limits (the dev cache is per-process). The Dockerfile/compose are untested.

_Deployed automatically by Render from the `dev`, `staging` and `main` branches (see ../DEPLOY_RENDER.md)._
