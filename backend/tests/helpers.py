import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import otp

PASSWORD = "Sup3rSecret"
API = "/api/v1"


def iso(minutes_ago: int = 1) -> str:
    return (timezone.now() - timedelta(minutes=minutes_ago)).isoformat()


def new_client() -> APIClient:
    return APIClient()


def register(mobile: str = "9876543210", name: str = "Ravi") -> tuple[APIClient, dict]:
    """Full signup + OTP verification. Returns an authenticated client and the session payload."""
    c = new_client()
    r = c.post(f"{API}/auth/signup", {"mobile": mobile, "name": name, "password": PASSWORD, "role": "shopkeeper",
                                      "language": "en", "accepted_terms_version": "v1"})
    assert r.status_code == 200, r.content
    code = otp.MEMORY_OUTBOX[-1][1]
    r = c.post(f"{API}/auth/otp/verify", {"mobile": mobile, "challenge_id": r.data["challenge_id"], "otp": code,
                                          "device_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.content
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    return c, r.data


def sync(c: APIClient, items: list, device_id: str | None = None):
    r = c.post(f"{API}/sync/batch", {"device_id": device_id or str(uuid.uuid4()), "items": items})
    assert r.status_code == 200, r.content
    return r.data["results"]


def item(entity: str, op: str, payload: dict, key: str | None = None) -> dict:
    return {"idempotency_key": key or f"{entity}:{payload.get('id', uuid.uuid4())}", "entity": entity, "op": op,
            "payload": payload}


def shop_item(shop_id=None, name="Ravi Kirana") -> tuple[dict, str]:
    sid = shop_id or str(uuid.uuid4())
    return item("shop", "create", {"id": sid, "name": name, "category": "Kirana", "address": "Main Rd", "language": "en"},
                f"shop:{sid}"), sid


def customer_item(name="Asha") -> tuple[dict, str]:
    cid = str(uuid.uuid4())
    return item("customer", "create", {"id": cid, "name": name, "mobile": None, "notes": None}, f"customer:{cid}"), cid


def ledger_payload(customer_id: str, etype: str, amount: int, **extra) -> dict:
    eid = str(uuid.uuid4())
    given = extra.pop("delta_paise", None)
    if given is not None:
        delta = given
    else:
        delta = amount if etype in ("credit", "opening") else (-amount if etype == "payment" and isinstance(amount, int) else 0)
    return {"id": eid, "customer_id": customer_id, "type": etype, "amount_paise": amount, "delta_paise": delta,
            "occurred_at": iso(), "created_at": iso(), "note": None, "payment_method": "cash" if etype == "payment" else None,
            "payment_reference": None, "sale_id": None, "reversal_of_id": None, "reason": None,
            "confirmation_status": "shopkeeper_recorded", "items": [], **extra}


def ledger_item(payload: dict) -> dict:
    return item("ledger_event", "post", payload, f"ledger:{payload['id']}")


def setup_shop_with_customer(mobile="9876543210"):
    c, session = register(mobile)
    s_item, shop_id = shop_item()
    c_item, cust_id = customer_item()
    res = sync(c, [s_item, c_item])
    assert [r["status"] for r in res] == ["accepted", "accepted"], res
    return c, shop_id, cust_id
