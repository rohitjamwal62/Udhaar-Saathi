from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


def current_plan() -> dict:
    """The paid plan, read from the live database (subscription_plans). Falls back to the documented defaults."""
    plan = cache.get("site:plan")
    if plan:
        return plan
    plan = {"name": "LenDen Saathi", "amount_rupees": 49, "trial_months": 3, "grace_days": 7, "source": "default"}
    try:
        from apps.legacy.models import SubscriptionPlans
        row = SubscriptionPlans.objects.filter(active=True).order_by("amount_paise").first()
        if row:
            plan = {"name": row.name, "amount_rupees": row.amount_paise // 100, "trial_months": row.trial_months,
                    "grace_days": row.grace_days, "source": "database"}
    except Exception:  # noqa: BLE001  (the site must still render if the database is slow)
        pass
    cache.set("site:plan", plan, 300)
    return plan


def support_email() -> str:
    """The contact address: the database value (edited in admin) first, then the server setting."""
    from .models import SiteSetting
    return SiteSetting.current().support_email or settings.SUPPORT_EMAIL


def site(request):
    from .models import SiteSetting
    s = SiteSetting.current()
    return {"SITE_NAME": settings.SITE_NAME, "SUPPORT_EMAIL": s.support_email or settings.SUPPORT_EMAIL,
            "SUPPORT_PHONE": s.support_phone, "SUPPORT_WHATSAPP": s.whatsapp_number, "SUPPORT_ADDRESS": s.address,
            "APP_ENV": settings.APP_ENV,
            "SITE_URL": settings.SITE_URL, "YEAR": timezone.now().year, "PLAN": current_plan()}
