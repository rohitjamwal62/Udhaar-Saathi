#!/usr/bin/env python3
"""
Create the Render services from render.yaml through Render's API, then wait for each deploy and check it.

    python deploy/render_deploy.py --dry-run                 # show what would be created (nothing is sent)
    python deploy/render_deploy.py --only staging            # create/update just one environment
    python deploy/render_deploy.py                           # all three

Needs (kept out of Git):
  * RENDER_API_KEY            in the environment or in render-api.local.txt  ->  RENDER_API_KEY=rnd_...
                              (Render dashboard -> Account Settings -> API Keys)
  * render-secrets.local.txt  holds the Neon DATABASE_URL for each service (already created)
  * optional --owner-id       the Render workspace id (Workspace Settings); looked up automatically if omitted
Re-running is safe: services that already exist are not created twice (their env vars are left as they are).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.render.com/v1"
REPO = "https://github.com/rohitjamwal62/Udhaar-Saathi"


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("pip install pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def api_key() -> str:
    key = os.environ.get("RENDER_API_KEY", "").strip()
    f = ROOT / "render-api.local.txt"
    if not key and f.exists():
        m = re.search(r"^\s*RENDER_API_KEY\s*=\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
        key = m.group(1) if m else ""
    return key


def database_urls() -> dict[str, str]:
    """service name -> DATABASE_URL, from render-secrets.local.txt."""
    out: dict[str, str] = {}
    f = ROOT / "render-secrets.local.txt"
    if not f.exists():
        return out
    name = None
    for line in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(\S+)\]", line)
        if m:
            name = m.group(1)
        elif line.startswith("DATABASE_URL=") and name:
            out[name] = line.split("=", 1)[1].strip()
    return out


def build_payload(svc: dict, owner_id: str, db_urls: dict[str, str]) -> dict:
    env_vars = []
    for e in svc.get("envVars", []):
        if e.get("generateValue"):
            env_vars.append({"key": e["key"], "generateValue": True})
        elif "value" in e:
            env_vars.append({"key": e["key"], "value": str(e["value"])})
        elif e["key"] == "DATABASE_URL":
            if svc["name"] not in db_urls:
                sys.exit(f"No DATABASE_URL for {svc['name']} in render-secrets.local.txt")
            env_vars.append({"key": "DATABASE_URL", "value": db_urls[svc["name"]]})
        # other secret placeholders (Razorpay keys) are added later in the dashboard
    return {
        "type": "web_service",
        "name": svc["name"],
        "ownerId": owner_id,
        "repo": REPO,
        "branch": svc["branch"],
        "rootDir": svc.get("rootDir", ""),
        "autoDeployTrigger": svc.get("autoDeployTrigger", "commit"),
        "envVars": env_vars,
        "serviceDetails": {
            "runtime": svc["runtime"],
            "plan": svc["plan"],
            "region": svc["region"],
            "healthCheckPath": svc.get("healthCheckPath", "/"),
            "numInstances": 1,
            "envSpecificDetails": {"buildCommand": svc["buildCommand"], "startCommand": svc["startCommand"]},
        },
    }


def call(method: str, path: str, key: str, body: dict | None = None):
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        sys.exit(f"Render API {method} {path} failed: HTTP {e.code} {detail}")


def find_owner(key: str) -> str:
    data = call("GET", "/owners?limit=20", key)
    owners = [(o.get("owner") or o) for o in data] if isinstance(data, list) else []
    if not owners:
        sys.exit("Could not list your Render workspaces. Pass --owner-id (Render -> Workspace Settings).")
    if len(owners) > 1:
        print("Several workspaces found:", [(o.get("name"), o.get("id")) for o in owners], "-> using the first; use --owner-id to choose.")
    return owners[0]["id"]


def existing_services(key: str) -> dict[str, dict]:
    data = call("GET", "/services?limit=100", key)
    return {(s.get("service") or s)["name"]: (s.get("service") or s) for s in data} if isinstance(data, list) else {}


def wait_for_deploy(key: str, service_id: str, timeout_s: int = 900) -> str:
    end = time.time() + timeout_s
    last = ""
    while time.time() < end:
        data = call("GET", f"/services/{service_id}/deploys?limit=1", key)
        d = (data[0].get("deploy") or data[0]) if data else {}
        status = d.get("status", "unknown")
        if status != last:
            print(f"    deploy status: {status}")
            last = status
        if status in ("live", "build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed"):
            return status
        time.sleep(15)
    return "timeout"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["dev", "staging", "production"])
    ap.add_argument("--owner-id")
    args = ap.parse_args()

    services = load_yaml(ROOT / "render.yaml")["services"]
    wanted = {"dev": "udhaarsaathi-api-dev", "staging": "udhaarsaathi-api-staging", "production": "udhaarsaathi-api"}
    if args.only:
        services = [s for s in services if s["name"] == wanted[args.only]]
    db_urls = database_urls()

    if args.dry_run:
        for s in services:
            p = build_payload(s, args.owner_id or "<workspace-id>", db_urls)
            for e in p["envVars"]:
                if e["key"] in ("DATABASE_URL", "DJANGO_SECRET_KEY"):
                    e["value"] = "<hidden>" if "value" in e else "<generated by Render>"
            print(json.dumps(p, indent=2))
        print("\nDry run only: nothing was sent.")
        return

    key = api_key()
    if not key:
        sys.exit("No Render API key. Put RENDER_API_KEY=rnd_... in render-api.local.txt (git-ignored) or the environment.")
    owner = args.owner_id or find_owner(key)
    have = existing_services(key)
    results = []
    for s in services:
        name = s["name"]
        if name in have:
            sid = have[name]["id"]
            print(f"{name}: already exists ({sid}); not creating it again")
        else:
            res = call("POST", "/services", key, build_payload(s, owner, db_urls))
            sid = (res.get("service") or {}).get("id")
            print(f"{name}: created ({sid})")
        results.append((name, sid, s))
    for name, sid, s in results:
        print(f"\n{name}: waiting for the deploy ...")
        status = wait_for_deploy(key, sid)
        svc = call("GET", f"/services/{sid}", key)
        url = (svc.get("serviceDetails") or {}).get("url", "")
        print(f"  result: {status}  url: {url}")
        if status == "live" and url:
            try:
                with urllib.request.urlopen(url + "/health/live", timeout=90) as r:
                    print("  /health/live ->", r.read().decode())
            except Exception as e:  # noqa: BLE001
                print("  health check failed:", e)


if __name__ == "__main__":
    main()
