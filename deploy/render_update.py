#!/usr/bin/env python3
"""
Apply the website's settings to the Render services through Render's API.

    python deploy/render_update.py --dry-run            # show what would change (values are hidden)
    python deploy/render_update.py --only dev            # one environment first
    python deploy/render_update.py                       # all three

Reads secrets from backend/.env (git-ignored) and the Render API key from render-api.local.txt (git-ignored).
Sets: email (SMTP + Gmail API) and Google Drive variables, and the build/start commands the website needs
(collectstatic + migrate). Variables that are empty locally are skipped, so a missing refresh token is never overwritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.render.com/v1"
SERVICES = {"dev": "srv-dbkt2sdg1s2s73dmtatg", "staging": "srv-dbkt2t8u01pc73e8e9pg", "production": "srv-dbkt2u6k1f9s73du3ei0"}
URLS = {"dev": "https://udhaarsaathi-api-dev.onrender.com", "staging": "https://udhaarsaathi-api-staging.onrender.com",
        "production": "https://udhaarsaathi-api.onrender.com"}
KEYS = ["EMAIL_HOST", "EMAIL_PORT", "EMAIL_USE_TLS", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL",
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_DRIVE_FOLDER_ID", "GOOGLE_REFRESH_TOKEN"]
SECRET = {"EMAIL_HOST_PASSWORD", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"}
BUILD = "pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput"
START = "gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --worker-class gthread --timeout 60 --access-logfile -"


def env_file() -> dict[str, str]:
    out = {}
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def api_key() -> str:
    m = re.search(r"RENDER_API_KEY=(\S+)", (ROOT / "render-api.local.txt").read_text(encoding="utf-8"))
    if not m:
        sys.exit("No RENDER_API_KEY in render-api.local.txt")
    return m.group(1)


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {api_key()}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Render API {method} {path}: HTTP {e.code} {e.read().decode()[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=list(SERVICES))
    ap.add_argument("--no-commands", action="store_true", help="only set variables")
    a = ap.parse_args()
    local = env_file()
    values = {k: local[k] for k in KEYS if local.get(k)}
    values["EMAIL_HOST_PASSWORD"] = values.get("EMAIL_HOST_PASSWORD", "").replace(" ", "")
    values["SUPPORT_EMAIL"] = local.get("SUPPORT_EMAIL") or local.get("EMAIL_HOST_USER", "")
    values["EMAIL_TRANSPORT"] = "auto"
    for env, sid in SERVICES.items():
        if a.only and env != a.only:
            continue
        print(f"\n== {env} ({sid}) ==")
        for k, v in values.items():
            shown = "<hidden>" if k in SECRET else v
            print(f"  env {k} = {shown}")
            if not a.dry_run:
                call("PUT", f"/services/{sid}/env-vars/{k}", {"value": v})
        if not a.no_commands:
            print(f"  build: {BUILD}\n  start: {START}")
            if not a.dry_run:
                call("PATCH", f"/services/{sid}", {"serviceDetails": {"envSpecificDetails": {"buildCommand": BUILD, "startCommand": START}}})
        time.sleep(0.5)
    print("\nDry run only: nothing was sent." if a.dry_run else "\nDone. Render redeploys each service with the new settings.")


if __name__ == "__main__":
    main()
