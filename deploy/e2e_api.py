#!/usr/bin/env python3
"""
Live smoke test of the phone app's REST API and offline sync on dev or staging.

    python deploy/e2e_api.py staging

Journey: signup + OTP (read from the Render log) -> create shop and customer through /sync/batch -> credit and payment ->
a retry of the same batch is reported as duplicate and posts nothing twice -> a reversal -> customers list, ledger
(running balance), dashboard and receivables report -> a second account cannot see the first one's customer.

NOTE: the ledger tables are append-only (database triggers), so this test cannot delete what it creates. It leaves
ONE small, clearly named test shop ("E2E API <time>") per run in that environment's database. Use dev or staging only.
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import requests

from e2e_site import ENVS, check, render_api, RESULTS

PW = "E2E-Test-Pass-1"


def otp_from_log(owner: str, service: str, mobile: str) -> str | None:
    for _ in range(12):
        try:
            q = urllib.parse.urlencode([("ownerId", owner), ("resource", service), ("text", "DEV OTP"), ("limit", 30), ("direction", "backward")])
            for line in render_api("/logs?" + q).get("logs", []):
                m = re.search(r"\[DEV OTP\] " + re.escape(mobile) + r": (\d{6})", line["message"])
                if m:
                    return m.group(1)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4)
    return None


def iso(minutes_ago=1) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def signup(api: str, owner: str, service: str, mobile: str, name: str) -> requests.Session | None:
    s = requests.Session()
    r = s.post(f"{api}/auth/signup", json={"mobile": mobile, "name": name, "password": PW, "role": "shopkeeper", "language": "en",
                                           "accepted_terms_version": "v1"}, timeout=180)
    if r.status_code != 200:
        print("signup failed", r.status_code, r.text[:200])
        return None
    code = otp_from_log(owner, service, mobile)
    if not code:
        return None
    v = s.post(f"{api}/auth/otp/verify", json={"mobile": mobile, "challenge_id": r.json()["challenge_id"], "otp": code, "device_id": uid()}, timeout=180)
    if v.status_code != 200:
        print("verify failed", v.status_code, v.text[:200])
        return None
    s.headers["Authorization"] = "Bearer " + v.json()["access"]
    return s


def sync(s, api, items):
    r = s.post(f"{api}/sync/batch", json={"device_id": uid(), "items": items}, timeout=180)
    return r.json()["results"] if r.status_code == 200 else [{"status": f"http {r.status_code}"}]


def item(entity, op, payload, key=None):
    return {"idempotency_key": key or f"{entity}:{payload['id']}", "entity": entity, "op": op, "payload": payload}


def event(cid, etype, amount, **extra):
    eid = uid()
    delta = amount if etype in ("credit", "opening") else -amount
    return {"id": eid, "customer_id": cid, "type": etype, "amount_paise": amount, "delta_paise": delta, "occurred_at": iso(), "created_at": iso(),
            "note": "e2e", "payment_method": "upi" if etype == "payment" else None, "payment_reference": None, "sale_id": None,
            "reversal_of_id": None, "reason": None, "items": [], **extra}


def main(env: str) -> int:
    base, service, _ = ENVS[env]
    api = base + "/api/v1"
    owner = render_api("/owners?limit=5")[0]["owner"]["id"]
    stamp = time.strftime("%H%M%S")
    mob1, mob2 = "+919" + stamp.rjust(9, "2"), "+918" + stamp.rjust(9, "3")
    print(f"API E2E on {env}: {base}\n  account 1 {mob1}\n  account 2 {mob2}\n")
    check(requests.get(base + "/health/ready", timeout=120).json().get("status") == "ok", "server and database are ready")
    check(requests.get(api + "/shops", timeout=60).status_code in (401, 403), "the API refuses requests without a login")

    a = signup(api, owner, service, mob1, "E2E API Owner")
    if not check(a is not None, "signup and OTP verification work"):
        return finish()
    sid, cid = uid(), uid()
    res = sync(a, api, [item("shop", "create", {"id": sid, "name": f"E2E API {stamp}", "category": "Kirana", "address": "-", "language": "en"}),
                        item("customer", "create", {"id": cid, "name": "E2E Customer", "mobile": None, "notes": None})])
    check([r["status"] for r in res] == ["accepted", "accepted"], "shop and customer are created through /sync/batch")

    credit, pay = event(cid, "credit", 150050), event(cid, "payment", 50000)
    batch = [item("ledger_event", "post", credit, f"ledger:{credit['id']}"), item("ledger_event", "post", pay, f"ledger:{pay['id']}")]
    check([r["status"] for r in sync(a, api, batch)] == ["accepted", "accepted"], "a credit and a payment are accepted")
    check([r["status"] for r in sync(a, api, batch)] == ["duplicate", "duplicate"], "retrying the same batch posts nothing twice")
    bad = event(cid, "credit", 0)
    r = sync(a, api, [item("ledger_event", "post", bad, f"ledger:{bad['id']}")])[0]
    check(r["status"] == "rejected" and "greater than zero" in r.get("error", ""), "a zero-amount credit is rejected with a clear message")

    rev = event(cid, "reversal", 1, reversal_of_id=pay["id"], reason="wrong entry")
    check(sync(a, api, [item("ledger_event", "post", rev, f"ledger:{rev['id']}")])[0]["status"] == "accepted", "a payment can be reversed")
    again = event(cid, "reversal", 1, reversal_of_id=pay["id"], reason="again")
    check(sync(a, api, [item("ledger_event", "post", again, f"ledger:{again['id']}")])[0]["status"] == "conflict", "reversing twice is a conflict")

    lst = a.get(f"{api}/shops/{sid}/customers", timeout=120).json()["results"]
    check(any(c["id"] == cid and c["balance_paise"] == 150050 for c in lst), "customers list shows the balance (credit, payment reversed)")
    led = a.get(f"{api}/shops/{sid}/customers/{cid}/ledger", timeout=120).json()
    check(led["balance_paise"] == 150050 and len(led["events"]) == 3 and led["events"][-1]["running_balance_paise"] == 150050, "ledger shows 3 events with a running balance")
    check(all(e["confirmation_status"] == "shopkeeper_recorded" for e in led["events"]), "confirmation status stays server-controlled")
    dash = a.get(f"{api}/shops/{sid}/dashboard", timeout=120).json()
    check(dash["khata"]["total_receivable_paise"] == 150050 and dash["khata"]["customers_with_balance"] == 1, "dashboard khata summary is right")
    rec = a.get(f"{api}/shops/{sid}/reports/receivables", timeout=120).json()
    check(rec["total_paise"] == 150050 and rec["results"][0]["customer_id"] == cid, "receivables report is right")

    b = signup(api, owner, service, mob2, "E2E API Other")
    if check(b is not None, "a second account signs up"):
        check(b.get(f"{api}/shops/{sid}/customers", timeout=120).status_code == 404, "the second account cannot see the first shop")
        check(b.get(f"{api}/shops/{sid}/customers/{cid}/ledger", timeout=120).status_code == 404, "nor its customer ledger")
    return finish()


def finish() -> int:
    bad = [m for ok, m in RESULTS if not ok]
    print("\n" + ("ALL CHECKS PASSED" if not bad else f"{len(bad)} CHECK(S) FAILED"))
    print("(left behind on purpose: one small test shop; ledger rows are append-only)")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ENVS:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
