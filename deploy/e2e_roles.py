#!/usr/bin/env python3
"""
Live end-to-end test of BOTH portals on dev or staging: a shopkeeper account and a customer account.

    python deploy/e2e_roles.py staging

Journey: register + verify a shopkeeper and a customer -> role guards (each is kept out of the other's pages) ->
shopkeeper adds the customer by email (automatic link) -> credit and a UPI payment -> customer sees credit, payment,
history and the remaining balance -> shopkeeper uploads proof (real Google Drive) -> customer downloads it ->
another person's page is a 404 for the customer -> unlink removes access, relink restores it -> cleanup of every row
and every Drive file the run created.

Needs the same git-ignored files as e2e_site.py.
"""
from __future__ import annotations

import re
import sys
import time

import requests

import e2e_site as base_mod
from e2e_site import ENVS, ROOT, check, otp_from_log, render_api, purge_user  # noqa: F401


class Site:
    def __init__(self, base: str):
        self.base, self.s = base, requests.Session()

    def token(self, url: str) -> str:
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', self.s.get(self.base + url, timeout=120).text).group(1)

    def get(self, url: str, **kw):
        return self.s.get(self.base + url, timeout=180, **kw)

    def post(self, url: str, data: dict, page: str | None = None, **kw):
        page = page or url
        return self.s.post(self.base + url, data={"csrfmiddlewaretoken": self.token(page), **data}, headers={"Referer": self.base + page}, timeout=240, **kw)


def sign_up(site: Site, owner: str, service: str, email: str, role: str, phone: str, name: str, shop: str) -> bool:
    pw = "E2E-Test-Pass-1"
    site.post("/register/", {"full_name": name, "email": email, "phone": phone, "shop_name": shop, "role": role,
                             "password1": pw, "password2": pw, "accept_terms": "on", "website": ""})
    code = otp_from_log(owner, service, email, "register", time.time())
    if not code:
        return False
    r = site.post("/verify/", {"code": code})
    return "/verify/" not in r.url


def main(env: str) -> int:
    base, service, _name = ENVS[env]
    stamp = time.strftime("%H%M%S")
    shop_email, cust_email = f"rohitjamwal62+shop{stamp}@gmail.com", f"rohitjamwal62+cust{stamp}@gmail.com"
    cust_phone = "9" + stamp.rjust(9, "1")                       # a fresh valid-looking 10-digit number per run
    owner = render_api("/owners?limit=5")[0]["owner"]["id"]
    shop, cust = Site(base), Site(base)
    print(f"Roles E2E on {env}: {base}\n  shopkeeper {shop_email}\n  customer   {cust_email} ({cust_phone})\n")
    check(shop.get("/health/ready").json().get("status") == "ok", "server and database are ready")

    # 1 sign up both accounts
    if not check(sign_up(shop, owner, service, shop_email, "shopkeeper", "9" + stamp.rjust(9, "5"), "E2E Shopkeeper", "E2E Store"), "shopkeeper registers and verifies by email code"):
        return finish(env, [shop_email, cust_email])
    if not check(sign_up(cust, owner, service, cust_email, "customer", cust_phone, "E2E Customer", ""), "customer registers and verifies by email code"):
        return finish(env, [shop_email, cust_email])

    # 2 role guards
    r = cust.get("/dashboard/")
    check(r.url.rstrip("/").endswith("/my"), "customer's dashboard is the customer portal (/my/)")
    r = cust.get("/ledger/")
    check(r.url.rstrip("/").endswith("/my") and "only for shopkeeper" in r.text, "customer is kept out of the shopkeeper ledger")
    check(cust.post("/ledger/people/add/", {"name": "Sneaky"}, page="/dashboard/profile/").status_code == 200, "customer cannot add people (redirected)")
    r = shop.get("/my/")
    check("/my" not in r.url and "only for customer" in r.text, "shopkeeper is kept out of the customer portal")
    check("You owe now" not in shop.get("/dashboard/").text, "shopkeeper dashboard has no customer widgets")

    # 3 shopkeeper adds the customer: automatic linking by email
    r = shop.post("/ledger/people/add/", {"name": "E2E Customer", "phone": "", "email": cust_email}, page="/ledger/")
    m = re.search(r"/ledger/people/(\d+)/", r.url)
    if not check(bool(m), "shopkeeper adds the customer by email"):
        return finish(env, [shop_email, cust_email])
    pid = m.group(1)
    page_url = f"/ledger/people/{pid}/"
    check("Linked" in r.text and "Matched by email" in r.text, "the customer's account was linked automatically")
    today = time.strftime("%Y-%m-%d")
    for kind, amt, method in (("gave", "1200.50", ""), ("received", "200.25", "upi")):
        shop.post(page_url, {"kind": kind, "amount": amt, "entry_date": today, "method": method, "note": "e2e"}, page=page_url)
    detail = shop.get(page_url).text
    check("Owes you Rs 1,000.25" in detail and "UPI" in detail and "1 payment" in detail, "shopkeeper sees the balance and the payment method")

    # 4 customer sees their own numbers
    home = cust.get("/my/").text
    check("Rs 1,000.25" in home and "Rs 1,200.50" in home and "Rs 200.25" in home, "customer sees owes now, credit taken and paid so far")
    link = re.search(r'href="(/my/shops/\d+/)"', home)
    cd = cust.get(link.group(1)).text if link else ""
    check(bool(link) and "Credit taken" in cd and "Payment made" in cd and "UPI" in cd and "Rs 1,000.25" in cd, "customer's history shows credit, payment, method and balance")

    # 5 proof for one customer
    files = {"file": ("e2e-proof.txt", b"UdhaarSaathi roles end-to-end proof", "text/plain")}
    shop.s.post(base + f"/ledger/people/{pid}/documents/upload/", data={"csrfmiddlewaretoken": shop.token(page_url), "title": "E2E receipt", "category": "bill", "visible_to_customer": "on"},
                files=files, headers={"Referer": base + page_url}, timeout=240)
    pd = shop.get(page_url).text
    check("E2E receipt" in pd, "proof is stored in Google Drive and listed on the customer's page")
    cd = cust.get(link.group(1)).text if link else ""
    dl = re.search(r'href="(/dashboard/documents/\d+/download/)"', cd)
    check(bool(dl) and "E2E receipt" in cd, "the customer sees the shared proof")
    got = cust.get(dl.group(1)) if dl else None
    check(bool(got) and got.status_code == 200 and got.content.startswith(b"UdhaarSaathi roles"), "the customer downloads the same bytes")

    # 6 isolation
    check(cust.get(f"/my/shops/{int(pid) + 99999}/").status_code == 404, "a customer cannot open a page that is not theirs")
    check(cust.get(page_url, allow_redirects=False).status_code == 302, "a customer cannot open the shopkeeper's page for them")

    # 7 unlink / relink
    shop.post(f"/ledger/people/{pid}/link/", {"action": "unlink"}, page=page_url)
    check(cust.get(link.group(1)).status_code == 404 and "No shop has added you yet" in cust.get("/my/").text, "unlinking removes the customer's access at once")
    shop.post(f"/ledger/people/{pid}/link/", {"action": "retry"}, page=page_url)
    check(cust.get(link.group(1)).status_code == 200, "linking again restores it")
    return finish(env, [shop_email, cust_email])


def finish(env: str, emails: list[str]) -> int:
    sys.path.insert(0, str(ROOT / "database"))
    import create_tables as ct

    n, url = None, ""
    for line in (ROOT / "render-secrets.local.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(\S+)\]", line)
        if m:
            n = m.group(1)
        elif line.startswith("DATABASE_URL=") and n == ENVS[env][2]:
            url = line.split("=", 1)[1].strip()
    c = ct.connect(ct.parse_database_url(url))
    c.autocommit = True
    cur = c.cursor()
    for e in emails:
        purge_user(cur, e)
    cur.execute("SELECT count(*) FROM auth_user WHERE email = ANY(%s)", (emails,))
    check(cur.fetchone()[0] == 0, "test rows removed from the database")
    c.close()
    bad = [m for ok, m in base_mod.RESULTS if not ok]
    print("\n" + ("ALL CHECKS PASSED" if not bad else f"{len(bad)} CHECK(S) FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ENVS:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
