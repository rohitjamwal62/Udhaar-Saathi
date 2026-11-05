# LenDen Saathi: Android app (React Native + TypeScript)

Android-first, offline-first digital khata and sales tracking for small shops. Built from the
LenDen Saathi Master Blueprint V4. This folder is the mobile client only; it talks to the Django
`/api/v1` backend (not included here).

## Run and test with Expo

Project: slug `udhaarsaathi`, owner `rohit62`, EAS project id `cc817678-c8a1-43f2-a661-b234a48e2843` (already set in `app.json`).

### Option A: Expo Go on your phone (fastest)
1. Install **Expo Go** from the Play Store. It must support Expo SDK 58 (this project's SDK); update Expo Go if it complains.
2. Phone and PC on the same Wi-Fi.
3. In this folder:
   ```bash
   npm install
   npm start          # use this instead of `npx expo start` (see note below)
   ```
4. Scan the QR code with Expo Go. If the phone cannot reach the PC, use `npx expo start --tunnel`.
5. On the login screen tap **Continue in demo mode (dev only)**. `.env` already has `EXPO_PUBLIC_DEMO_MODE=true`, so no server is needed.
   If you change `.env`, restart with `npx expo start -c`.

Everything local works in Expo Go: shop setup, customers, khata, sales, reports, offline data, camera/gallery for bills.
Razorpay checkout is the only part that does not (native module); it needs a development build (Option B).

> **Error "You're signed in to Expo CLI as X and to Expo Go as Y - these accounts need to match"**
> Your PC has an `EXPO_TOKEN` environment variable (robot account) while Expo Go is signed in as you.
> `npm start` ignores that token for this run, so the error goes away. Alternatives: sign out of Expo Go, or
> run `Remove-Item Env:EXPO_TOKEN` before `npx expo start`. Keep `EXPO_TOKEN` only for `eas build` / `eas update`.

> **Error "You're signed in to Expo Go as X, but not signed in to Expo CLI"**
> Expo Go (signed in as you) insists the CLI uses the same account when the served app carries an Expo account
> link (`owner` / EAS `projectId`). `app.config.js` removes that link for `expo start`, so local testing needs no
> login at all. `eas build` / `eas update` still get the link. Restart Metro after pulling this change.

### Signing the CLI in as yourself (needed only if Expo Go is signed in)
The browser login now works on Windows (`scripts/winfix.js` escapes the `&` that used to crash it).
```bat
npm run start:account        # online; if Expo asks "Log in", choose it, sign in as rohit62 in the browser
```
Or without a browser: put a personal token in `.env.account` (see `.env.account.example`). Do not use the robot token here.
Simplest of all: log out of Expo Go and use `npm start`.

### Option B: development build (needed for payments)
```bash
npm install -g eas-cli          # or use npx eas-cli@latest
eas login                       # or set the EXPO_TOKEN environment variable in your shell (never commit it)
eas build --profile development --platform android   # installs as an APK on your phone
npx expo start --dev-client
```
Or locally with Android Studio installed: `npx expo run:android`.

### A quick test script (demo mode)
1. Create shop -> Khata tab -> **Add customer** (add an opening balance of 500).
2. Open the customer -> **Add credit** (itemized: Rice, qty 2.5, unit kg, price 60) -> check the total is Rs 150 and the balance is Rs 650.
3. **Receive payment** 200 -> balance Rs 450. **Reverse** that payment with a reason -> balance back to Rs 650, original row still visible.
4. Sales tab -> **New sale**, 2 payment rows (cash + KHATA credit, pick the customer) -> the customer's balance rises by the credit part only.
5. Open that sale -> **Return / refund** -> net sales drop, reports update.
6. Turn on airplane mode, add entries, then check **Settings -> Sync status** (items stay "Pending").

### Checks
```bash
npm run typecheck && npm test
npx expo-doctor
```

## Database (local PostgreSQL)
The schema lives in one file: `../database/create_tables.py` (creates all 38 tables, constraints, append-only triggers and seeds the Rs 49 plan).
```bash
cd ../database
pip install psycopg2-binary
copy .env.example .env      # then put your PostgreSQL password in .env
python create_tables.py     # safe to re-run;  --check verifies,  --reset recreates (asks to confirm)
```
The mobile app does not connect to PostgreSQL directly. It will talk to the Django API (next step), which uses this database.

## What is built

| Area | Status |
|---|---|
| Signup, OTP, login, forgot/reset password (calls Django auth API), secure token storage, token refresh | UI + API client done; needs backend |
| Shop setup | Done |
| Customers: add, search, duplicate warning (no auto-merge), opening balance, archive | Done (local) |
| Udhaar ledger: itemized or total-only credit, paid-now split, payments, running balance, bill photo, reversal with reason | Done (local) |
| Sales tracking: quick/itemized, split payments, discounts, credit sale linked to exactly one khata entry, returns, reports, CSV share | Done (local) |
| Dashboard: Udhaar and Sales cards side by side (stacked on narrow phones) | Done |
| Offline outbox + sync engine (UUIDs, idempotency keys, exponential backoff, conflict/failed states, single-flight, runs on start/resume/reconnect/every minute) | Done; needs `POST /sync/batch` |
| Subscription screen, Razorpay checkout (server-created order, server verification), payment history, cancel renewal | UI + API client done; needs backend + Razorpay keys |
| Server-controlled update prompt (optional / forced) | Done |

## Not built yet (later phases in the blueprint)
Customer-side app (multi-shop dashboard, shop linking), customer OTP/signature confirmation and disputes,
SMS/WhatsApp/email/FCM, Hindi translations (language is stored; strings are English), app lock/biometrics,
true background sync when the app is closed, encrypted local database, screenshot tests, release signing,
custom icon/splash (template placeholders are still in `assets/`).
Until the confirmation flow exists, every credit entry shows as **Shopkeeper recorded**; the app never marks anything customer-confirmed.

## Backend contract the app expects
See `src/core/api/endpoints.ts`: `/auth/*`, `/app/config`, `/sync/batch`, `/subscriptions/*`.
`/sync/batch` receives `{device_id, items:[{idempotency_key, entity, op, payload}]}` and must answer
`{results:[{idempotency_key, status: accepted|duplicate|conflict|rejected, error?}], cursor}`.
The server must enforce entitlements, tenant isolation and never trust amounts from the client.

## Layout
```
src/app        navigation, update prompt
src/core       theme tokens, money (integer paise), db (SQLite + repo), sync (outbox/engine), api, auth
src/features   auth, shops, customers, ledger, sales, subscriptions, reports, settings, home
src/shared     design-system components, hooks, query hooks
```
Package id: `com.udhaarsaathi.app` (keep it unchanged so Play Store updates reach installed apps).
