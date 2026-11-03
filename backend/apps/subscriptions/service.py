"""Subscription lifecycle: 3-month one-time trial, Rs 49/month, 7-day grace after a paid period lapses.

Entitlements are decided HERE on the server for every protected write. The app cannot unlock
anything by changing its clock or local storage. Ledger history is never deleted or hidden:
an expired shop becomes read-only, it does not lose data.
"""
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.common.db import q, q1, x

WRITE_OK = {"TRIALING", "ACTIVE", "CANCELED", "GRACE_PERIOD", "PAYMENT_PENDING", "PAST_DUE"}


def audit(subscription_id, actor: str, event: str, old: str | None, new: str | None, reason: str | None = None):
    x("""INSERT INTO subscription_audit_events(subscription_id, actor, event_type, old_state, new_state, reason)
         VALUES (%s,%s,%s,%s,%s,%s)""", [subscription_id, actor, event, old, new, reason])


def create_for_shop(shop_id: str, owner_id: str) -> None:
    """Called when a shop is created. One free trial per owner account, ever."""
    plan = q1("SELECT id, trial_months FROM subscription_plans WHERE active ORDER BY amount_paise LIMIT 1")
    now = timezone.now()
    granted = x("INSERT INTO trial_grants(user_id, shop_id) VALUES (%s,%s) ON CONFLICT (user_id) DO NOTHING",
                [owner_id, shop_id]) == 1
    if granted:
        status, started, ends = "TRIALING", now, now + relativedelta(months=plan["trial_months"])
    else:
        status, started, ends = "EXPIRED", None, None
    sub = q1("""INSERT INTO subscriptions(shop_id, plan_id, status, trial_started_at, trial_ends_at)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (shop_id) DO NOTHING RETURNING id""",
             [shop_id, plan["id"], status, started, ends])
    if sub:
        audit(sub["id"], "system", "subscription_created", None, status,
              "free trial granted" if granted else "trial already used by this account")


def effective_status(sub: dict, now: datetime | None = None) -> tuple[str, datetime | None]:
    """Derive the current state from the stored dates. Returns (status, grace_ends_at)."""
    now = now or timezone.now()
    if sub["status"] == "SUSPENDED":
        return "SUSPENDED", None
    plan = q1("SELECT grace_days FROM subscription_plans WHERE id = %s", [sub["plan_id"]])
    paid_end = sub["current_period_end"]
    if paid_end and now < paid_end:
        return ("CANCELED" if sub["cancel_at_period_end"] else "ACTIVE"), None
    if sub["trial_ends_at"] and now < sub["trial_ends_at"] and not paid_end:
        return "TRIALING", None
    if paid_end:  # a paid period lapsed: grace window for retry / manual renewal
        grace_end = paid_end + timedelta(days=plan["grace_days"])
        if now < grace_end and not sub["cancel_at_period_end"]:
            return "GRACE_PERIOD", grace_end
    return "EXPIRED", None


def refresh(shop_id: str) -> dict | None:
    """Load the shop's subscription, persist any status transition (with audit) and return it."""
    sub = q1("SELECT * FROM subscriptions WHERE shop_id = %s", [shop_id])
    if not sub:
        return None
    status, grace = effective_status(sub)
    if status != sub["status"] or grace != sub["grace_ends_at"]:
        x("UPDATE subscriptions SET status=%s, grace_ends_at=%s, updated_at=now() WHERE id=%s",
          [status, grace, sub["id"]])
        audit(sub["id"], "system", "status_changed", sub["status"], status)
        sub = {**sub, "status": status, "grace_ends_at": grace}
    return sub


def can_write(shop_id: str) -> bool:
    sub = refresh(shop_id)
    return bool(sub) and sub["status"] in WRITE_OK


def refresh_all() -> int:
    n = 0
    for r in q("SELECT shop_id FROM subscriptions"):
        before = q1("SELECT status FROM subscriptions WHERE shop_id=%s", [r["shop_id"]])["status"]
        after = refresh(r["shop_id"])["status"]
        n += before != after
    return n


def apply_payment_success(order: dict, gateway_payment_id: str, method: str | None, amount_paise: int) -> bool:
    """Idempotently record a verified payment and extend the paid period by one month.
    Returns False if this payment was already applied (duplicate webhook / retried verify)."""
    inserted = q1(
        """INSERT INTO payments(order_id, gateway_payment_id, amount_paise, status, method, paid_at)
           VALUES (%s,%s,%s,'success',%s,now())
           ON CONFLICT (gateway_payment_id) DO NOTHING RETURNING id""",
        [order["id"], gateway_payment_id, amount_paise, method])
    if not inserted:
        # Maybe an earlier 'pending'/'failed' row for the same payment id: upgrade it exactly once.
        upd = q1("""UPDATE payments SET status='success', method=COALESCE(%s, method), paid_at=now(), failure_code=NULL
                     WHERE gateway_payment_id=%s AND status IN ('pending','failed') RETURNING id""",
                 [method, gateway_payment_id])
        if not upd:
            return False
        inserted = upd
    sub = q1("SELECT * FROM subscriptions WHERE id = %s FOR UPDATE", [order["subscription_id"]])
    now = timezone.now()
    start = max([t for t in (now, sub["current_period_end"], sub["trial_ends_at"]) if t])
    end = start + relativedelta(months=1)
    x("UPDATE payment_orders SET status='paid' WHERE id=%s", [order["id"]])
    x("""UPDATE subscriptions SET status='ACTIVE', current_period_start=%s, current_period_end=%s,
                grace_ends_at=NULL, cancel_at_period_end=FALSE, updated_at=now() WHERE id=%s""",
      [start, end, sub["id"]])
    x("""INSERT INTO subscription_invoices(subscription_id, payment_id, amount_paise, period_start, period_end)
         VALUES (%s,%s,%s,%s,%s) ON CONFLICT (payment_id) DO NOTHING""",
      [sub["id"], inserted["id"], amount_paise, start, end])
    audit(sub["id"], "payment", "payment_succeeded", sub["status"], "ACTIVE", f"payment {gateway_payment_id}")
    return True
