"""Who is a shopkeeper and who is a customer, and the guards that keep the two portals apart.

A user's role is Profile.role, chosen at sign-up and changeable only by an administrator. Accounts without a profile
(for example the admin superuser) are treated as shopkeepers so the existing tools keep working for them.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.translation import gettext as _

SHOPKEEPER, CUSTOMER = "shopkeeper", "customer"


def role_of(user) -> str:
    profile = getattr(user, "profile", None) if getattr(user, "is_authenticated", False) else None
    return profile.role if profile else SHOPKEEPER


def needs_mobile(user) -> bool:
    """True for a website account (with a profile) that has no mobile number yet: such accounts predate the rule."""
    profile = getattr(user, "profile", None) if getattr(user, "is_authenticated", False) else None
    return bool(profile) and not profile.phone


def _guard(required: str, message: str):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if needs_mobile(request.user):
                messages.info(request, _("Please add your mobile number to continue. It is required for every account."))
                return redirect("profile_edit")
            if role_of(request.user) != required:
                messages.warning(request, message)
                return redirect("dashboard")          # the dashboard sends each role to its own home
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def shopkeeper_required(view):
    return _guard(SHOPKEEPER, _("That page is only for shopkeeper accounts."))(view)


def customer_required(view):
    return _guard(CUSTOMER, _("That page is only for customer accounts."))(view)
