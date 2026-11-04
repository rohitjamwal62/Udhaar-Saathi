"""Automatic linking of a shopkeeper's customer (Party) to that customer's own account.

A customer account is found by:
  1. email: the customer's verified email equals the email the shopkeeper entered. Most reliable, because the email
     was proven by the sign-up code.
  2. mobile number: the customer's profile number equals the number the shopkeeper entered, and exactly ONE customer
     account uses that number. Numbers are not verified, so the shopkeeper can always unlink (see views.party_link).

Linking runs when a person is added or edited, when a credit/payment is recorded, when a customer verifies their email,
and when a customer changes their mobile number, so it works whichever side acts first.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import Party, Profile
from .reminders import normalize_mobile


def _customer_profiles():
    return Profile.objects.filter(role="customer", email_verified=True, user__is_active=True).select_related("user")


def find_customer(party: Party):
    """Return (user, method) for the customer account this person should be linked to, or (None, '')."""
    email = (party.email or "").strip().lower()
    if email:
        p = _customer_profiles().filter(user__email__iexact=email).exclude(user=party.owner).first()
        if p:
            return p.user, "email"
    if party.phone_norm:
        users = [p.user for p in _customer_profiles().filter(phone__endswith=party.phone_norm).exclude(user=party.owner)
                 if normalize_mobile(p.phone) == party.phone_norm]
        if len(users) == 1:
            return users[0], "phone"
    return None, ""


def link_party(party: Party) -> bool:
    """Link one person to a customer account if possible. Returns True if a new link was made."""
    if party.link_blocked or party.customer_id:
        return False
    user, method = find_customer(party)
    if not user:
        return False
    party.customer, party.link_method, party.linked_at = user, method, timezone.now()
    party.save(update_fields=["customer", "link_method", "linked_at"])
    return True


def revalidate_party(party: Party) -> None:
    """After the shopkeeper edits email/mobile: drop a link that no longer matches, then try to link again."""
    if party.customer_id:
        still = False
        cust = party.customer
        if party.link_method == "email":
            still = bool(party.email) and party.email.lower() == (cust.email or "").lower()
        elif party.link_method == "phone":
            prof = getattr(cust, "profile", None)
            still = bool(party.phone_norm) and bool(prof) and normalize_mobile(prof.phone) == party.phone_norm
        if not still:
            party.customer, party.link_method, party.linked_at = None, "", None
            party.save(update_fields=["customer", "link_method", "linked_at"])
    link_party(party)


def link_customer(user) -> int:
    """A customer account was verified or changed its mobile number: link every waiting person that matches it."""
    prof = getattr(user, "profile", None)
    if not prof or prof.role != "customer" or not prof.email_verified or not user.is_active:
        return 0
    digits = normalize_mobile(prof.phone) or ""
    phone_unique = bool(digits) and sum(1 for p in _customer_profiles().filter(phone__endswith=digits)
                                        if normalize_mobile(p.phone) == digits) == 1
    cond = Q(email__iexact=user.email)
    if phone_unique:
        cond |= Q(phone_norm=digits)
    n = 0
    for party in Party.objects.filter(cond, customer__isnull=True, link_blocked=False).exclude(owner=user):
        method = "email" if party.email and party.email.lower() == user.email.lower() else "phone"
        party.customer, party.link_method, party.linked_at = user, method, timezone.now()
        party.save(update_fields=["customer", "link_method", "linked_at"])
        n += 1
    return n
