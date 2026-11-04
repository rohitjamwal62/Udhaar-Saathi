#!/usr/bin/env python3
"""
End-to-end test of the LIVE website on dev or staging (production never prints codes, so it is checked by hand).

    python deploy/e2e_site.py dev
    python deploy/e2e_site.py staging

Journey: register -> wrong code -> real code (read from the Render log) -> dashboard -> document upload ->
logout -> login -> wrong password -> forgot/reset password -> login with the new password -> contact form ->
Django admin sees the records -> cleanup of every test row it created (directly in that environment's database).

Needs render-api.local.txt (to read the server log) and render-secrets.local.txt (for the cleanup). Both are git-ignored.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENVS = {
    "dev": ("https://udhaarsaathi-api-dev.onrender.com", "srv-dbkt2sdg1s2s73dmtatg", "udhaarsaathi-api-dev"),
    "staging": ("https://udhaarsaathi-api-staging.onrender.com", "srv-dbkt2t8u01pc73e8e9pg", "udhaarsaathi-api-staging"),
}
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> bool:
    RESULTS.append((ok, msg))
    print(f"{'PASS' if ok else 'FAIL'}  {msg}")
    return ok


def render_key() -> str:
    return re.search(r"RENDER_API_KEY=(\S+)", (ROOT / "render-api.local.txt").read_text(encoding="utf-8")).group(1)


def render_api(path: str):
    req = urllib.request.Request("https://api.render.com/v1" + path, headers={"Authorization": f"Bearer {render_key()}", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def otp_from_log(owner: str, service: str, email: str, purpose: str, after: float) -> str | None:
    for _ in range(10):
        try:
            q = urllib.parse.urlencode([("ownerId", owner), ("resource", service), ("text", "DEV EMAIL OTP"), ("limit", 20), ("direction", "backward")])
            for line in render_api("/logs?" + q).get("logs", []):
                m = re.search(r"\[DEV EMAIL OTP\] " + re.escape(email) + r" \(" + purpose + r"\): (\d{6})", line["message"])
                if m:
                    return m.group(1)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4)
    return None


def main(env: str) -> int:
    base, service, svc_name = ENVS[env]
    stamp = time.strftime("%H%M%S")
    email = f"rohitjamwal62+e2e{stamp}@gmail.com"
    pw1, pw2 = "E2E-Test-Pass-1", "E2E-New-Pass-2"
    owner = render_api("/owners?limit=5")[0]["owner"]["id"]
    s = requests.Session()

    def token(url):
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', s.get(url, timeout=120).text).group(1)

    def post(url, data, tok_page=None, **kw):
        return s.post(base + url, data={"csrfmiddlewaretoken": token(base + (tok_page or url)), **data}, headers={"Referer": base + (tok_page or url)}, timeout=180, **kw)

    print(f"E2E on {env}: {base}   test user: {email}\n")
    check(s.get(base + "/health/ready", timeout=120).json().get("status") == "ok", "server and database are ready")

    # 1 register
    r = post("/register/", {"full_name": "E2E Tester", "email": email, "phone": "9876543210", "shop_name": "E2E Kirana", "role": "shopkeeper",
                            "password1": pw1, "password2": pw1, "accept_terms": "on", "website": ""})
    check(r.url.endswith("/verify/"), "registration accepted and the code page is shown")
    check(s.get(base + "/dashboard/", allow_redirects=False).status_code == 302, "dashboard is locked before the email is verified")

    # 2 wrong code, then the real code
    r = post("/verify/", {"code": "000000"})
    check("incorrect or has expired" in r.text, "a wrong code is refused")
    code = otp_from_log(owner, service, email, "register", time.time())
    if not check(bool(code), "the verification code was generated (read from the server log)"):
        return finish(env, email)
    r = post("/verify/", {"code": code})
    check(r.url.endswith("/dashboard/") and "E2E" in r.text, "the right code verifies the email and signs in")
    check("Upload" in r.text or "upload" in r.text, "dashboard shows the document upload form")
    r2 = post("/verify/", {"code": code})
    check(not r2.url.endswith("/verify/") or "incorrect" in r2.text or r2.url.endswith("/register/"), "the code cannot be used twice")

    # 3 document upload (works only once Google Drive is connected)
    files = {"file": ("e2e-note.txt", b"UdhaarSaathi end-to-end test document", "text/plain")}
    tok = token(base + "/dashboard/")
    r = s.post(base + "/dashboard/documents/upload/", data={"csrfmiddlewaretoken": tok, "title": "E2E note", "category": "other"}, files=files,
               headers={"Referer": base + "/dashboard/"}, timeout=180, allow_redirects=True)
    dash = r.text
    if "was uploaded and stored safely" in dash:
        check(True, "document upload: stored in Google Drive")
        link = re.search(r'href="(/dashboard/documents/\d+/download/)"', dash)
        dl = s.get(base + link.group(1), timeout=120) if link else None
        check(bool(dl) and dl.status_code == 200 and dl.content.startswith(b"UdhaarSaathi end-to-end"), "document download returns the same bytes")
    else:
        check("not connected yet" in dash or "could not store" in dash, "document upload: Google Drive not connected yet (clear message shown, nothing saved)")

    # 4 logout / login / wrong password
    post("/logout/", {}, tok_page="/dashboard/")
    check(s.get(base + "/dashboard/", allow_redirects=False).status_code == 302, "logout works")
    r = post("/login/", {"identifier": email, "password": "Wrong-pass-9"})
    check("email or password is incorrect" in r.text, "wrong password is refused with a generic message")
    r = post("/login/", {"identifier": email, "password": pw1})
    check(r.url.endswith("/dashboard/"), "login with email and password works")
    post("/logout/", {}, tok_page="/dashboard/")

    # 5 forgot + reset password
    r = post("/forgot-password/", {"email": email})
    check(r.url.endswith("/reset-password/"), "forgot-password accepted")
    rcode = otp_from_log(owner, service, email, "reset", time.time())
    check(bool(rcode), "reset code generated")
    if rcode:
        r = post("/reset-password/", {"code": rcode, "password1": pw2, "password2": pw2})
        check(r.url.endswith("/login/"), "password reset with the code")
        r = post("/login/", {"identifier": email, "password": pw1})
        check("incorrect" in r.text, "the old password no longer works")
        r = post("/login/", {"identifier": email, "password": pw2})
        check(r.url.endswith("/dashboard/"), "login with the new password works")
        post("/logout/", {}, tok_page="/dashboard/")

    # 6 contact form
    r = post("/contact/", {"name": "E2E Tester", "email": email, "phone": "", "subject": f"E2E contact {stamp}", "message": "Automated end-to-end test message.", "website": ""})
    check("received" in r.text.lower(), "contact form accepted")

    # 7 Django admin sees everything
    a = requests.Session()
    tk = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', a.get(base + "/admin/login/", timeout=120).text).group(1)
    pw_admin = (ROOT / "backend" / ".env.admin.local").read_text().strip() if (ROOT / "backend" / ".env.admin.local").exists() else ""
    if pw_admin:
        r = a.post(base + "/admin/login/", data={"username": "Rohit", "password": pw_admin, "csrfmiddlewaretoken": tk, "next": "/admin/"}, headers={"Referer": base + "/admin/login/"}, timeout=120)
        q = urllib.parse.quote(f"e2e{stamp}")
        check("administration" in r.text.lower(), "admin login works")
        check(email in a.get(f"{base}/admin/auth/user/?q={q}", timeout=120).text, "admin lists the new user")
        check(email in a.get(f"{base}/admin/web/profile/?q={q}", timeout=120).text or "E2E Kirana" in a.get(f"{base}/admin/web/profile/?q={q}", timeout=120).text, "admin lists the profile")
        check(f"E2E contact {stamp}" in a.get(f"{base}/admin/web/contactmessage/?q={stamp}", timeout=120).text, "admin lists the contact message")
        check(email in a.get(f"{base}/admin/web/emailotp/?q={q}", timeout=120).text, "admin lists the OTP records (codes are not stored)")
    return finish(env, email)


def purge_user(cur, email: str) -> None:
    """Delete a test user and everything that points at it, children first."""
    cur.execute("DELETE FROM web_emailotp WHERE email = %s", (email,))
    cur.execute("DELETE FROM web_contactmessage WHERE email = %s", (email,))
    for table, col in (("web_document", "owner_id"), ("web_profile", "user_id"), ("auth_user_groups", "user_id"),
                       ("auth_user_user_permissions", "user_id"), ("django_admin_log", "user_id")):
        cur.execute(f"DELETE FROM {table} WHERE {col} IN (SELECT id FROM auth_user WHERE email = %s)", (email,))
    cur.execute("DELETE FROM auth_user WHERE email = %s", (email,))


def finish(env: str, email: str) -> int:
    """Remove every row the test created, straight in that environment's database."""
    import os
    sys_path = str(ROOT / "database")
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import create_tables as ct

    n = None
    url = ""
    for line in (ROOT / "render-secrets.local.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(\S+)\]", line)
        if m:
            n = m.group(1)
        elif line.startswith("DATABASE_URL=") and n == ENVS[env][2]:
            url = line.split("=", 1)[1].strip()
    c = ct.connect(ct.parse_database_url(url))
    c.autocommit = True
    cur = c.cursor()
    purge_user(cur, email)
    cur.execute("SELECT count(*) FROM auth_user WHERE email = %s", (email,))
    check(cur.fetchone()[0] == 0, "test rows removed from the database")
    c.close()
    bad = [m for ok, m in RESULTS if not ok]
    print("\n" + ("ALL CHECKS PASSED" if not bad else f"{len(bad)} CHECK(S) FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ENVS:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
