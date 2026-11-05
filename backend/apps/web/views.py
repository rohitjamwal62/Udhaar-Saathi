import hashlib
import logging
import mimetypes
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import BigIntegerField, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.common.ratelimit import hit

from . import google, linking, mailer, otp
from .forms import ProfileForm, ContactForm, DocumentForm, EmailForm, EntryForm, LoginForm, OTPForm, PartyDocumentForm, PartyForm, RegisterForm, ResetForm
from .models import FAQ, ContactMessage, Document, LedgerEntry, LegalPage, Party, Profile
from .context_processors import current_plan
from .roles import CUSTOMER, customer_required, role_of, shopkeeper_required

log = logging.getLogger("web")


def _send_otp(request, email: str, purpose: str) -> bool:
    """Send a code and remember on the session whether the email really went out. Returns True if it did."""
    try:
        otp.send_code(email, purpose, client_ip(request))
    except otp.OtpDeliveryError as e:
        request.session["otp_send_failed"] = True
        messages.warning(request, str(e))
        return False
    except otp.OtpError as e:                       # throttled: nothing new was sent, keep the previous state
        messages.warning(request, str(e))
        return False
    request.session["otp_send_failed"] = False
    return True
User = get_user_model()
BACKEND = "apps.web.auth_backends.EmailOrUsernameBackend"


def client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "*" * max(1, len(name) - 2) if len(name) > 2 else name[:1] + "*") + "@" + domain


# ───────────────────────────── public pages ─────────────────────────────
def home(request):
    return render(request, "web/home.html", {"plan": current_plan(), "faqs": FAQ.objects.filter(published=True)[:5]})


def features(request):
    return render(request, "web/features.html", {"plan": current_plan()})


def how_it_works(request):
    return render(request, "web/how_it_works.html", {"plan": current_plan()})


def pricing(request):
    return render(request, "web/pricing.html", {"plan": current_plan(), "faqs": FAQ.objects.filter(published=True)[:4]})


def security(request):
    return render(request, "web/security.html")


def faq(request):
    return render(request, "web/faq.html", {"faqs": FAQ.objects.filter(published=True)})


def _legal(request, slug: str, template: str):
    """Terms / Privacy: the text stored in the database wins; the built-in template text is the fallback."""
    from django.utils.translation import get_language
    page = LegalPage.objects.filter(slug=slug).first()
    body = ""
    if page:
        hindi = (get_language() or "en").startswith("hi") and page.body_hi.strip()
        body = (page.body_hi if hindi else page.body_en).strip()
    return render(request, template, {"legal_body": body})


def terms(request):
    return _legal(request, "terms", "web/terms.html")


def privacy(request):
    return _legal(request, "privacy", "web/privacy.html")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST":
        if not hit(f"contact:{client_ip(request)}", 5, 3600):
            messages.error(request, _("Too many messages from this connection. Please try again later."))
        elif form.is_valid():
            d = form.cleaned_data
            msg = ContactMessage.objects.create(name=d["name"], email=d["email"], phone=d["phone"], subject=d["subject"], message=d["message"])
            msg.notification_sent = mailer.send_contact_emails(d["name"], d["email"], d["phone"], d["subject"], d["message"])
            msg.save(update_fields=["notification_sent"])
            messages.success(request, _("Thank you. Your message was received and we will reply by email."))
            return redirect("contact")
    return render(request, "web/contact.html", {"form": form})


# ───────────────────────────── sign up with email OTP ─────────────────────────────
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            user = User.objects.filter(email__iexact=d["email"]).first()   # an unverified earlier attempt is reused
            if user is None:
                user = User(username=d["email"])
            user.email, user.first_name, user.is_active = d["email"], d["full_name"], False
            user.set_password(d["password1"])
            user.save()
            profile, _created = Profile.objects.get_or_create(user=user)
            profile.role, profile.shop_name = d["role"], d["shop_name"]
            from .reminders import normalize_mobile
            profile.phone = ("+91" + normalize_mobile(d["phone"])) if normalize_mobile(d["phone"]) else d["phone"]
            profile.terms_accepted_at = timezone.now()
            profile.save()
        request.session["pending_email"] = d["email"]
        if _send_otp(request, d["email"], "register"):
            messages.success(request, _("We sent a 6-digit code to %(email)s.") % {"email": mask_email(d["email"])})
        return redirect("verify_otp")
    return render(request, "web/auth/register.html", {"form": form})


def verify_otp(request):
    email = request.session.get("pending_email")
    if not email:
        messages.info(request, _("Please register first."))
        return redirect("register")
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not hit(f"verify:{client_ip(request)}", 30, 900):
            messages.error(request, _("Too many attempts. Please wait a few minutes."))
        else:
            try:
                otp.verify_code(email, "register", form.cleaned_data["code"])
            except otp.OtpError as e:
                form.add_error("code", str(e))
            else:
                user = get_object_or_404(User, email__iexact=email)
                user.is_active = True
                user.save(update_fields=["is_active"])
                Profile.objects.filter(user=user).update(email_verified=True)
                linking.link_customer(user)
                request.session.pop("pending_email", None)
                login(request, user, backend=BACKEND)
                mailer.send_welcome_email(user.email, user.first_name or _("there"))
                messages.success(request, _("Your email is verified. Welcome to LenDen Saathi!"))
                return redirect("dashboard")
    return render(request, "web/auth/verify_otp.html", {"form": form, "email": mask_email(email), "resend_in": otp.seconds_until_resend(email, "register"),
                                                        "send_failed": bool(request.session.get("otp_send_failed"))})


@require_POST
def resend_otp(request):
    email = request.session.get("pending_email")
    if not email:
        return redirect("register")
    if _send_otp(request, email, "register"):
        messages.success(request, _("A new code was sent to %(email)s.") % {"email": mask_email(email)})
    return redirect("verify_otp")


# ───────────────────────────── login / logout / reset ─────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ident = form.cleaned_data["identifier"].strip().lower()
        if not hit(f"login:{ident}", 10, 900) or not hit(f"login-ip:{client_ip(request)}", 40, 900):
            messages.error(request, _("Too many login attempts. Please try again in a few minutes."))
        else:
            user = User.objects.filter(email__iexact=ident).first() or User.objects.filter(username__iexact=ident).first()
            if user and user.check_password(form.cleaned_data["password"]):
                if not user.is_active:                      # right password, but the email was never verified
                    request.session["pending_email"] = user.email
                    if _send_otp(request, user.email, "register"):
                        messages.info(request, _("Please verify your email first. We sent you a new code."))
                    return redirect("verify_otp")
                login(request, user, backend=BACKEND)
                nxt = request.GET.get("next", "")
                return redirect(nxt if re.fullmatch(r"/[A-Za-z0-9_/\-]*", nxt) else "dashboard")
            form.add_error(None, _("The email or password is incorrect."))   # same message for unknown accounts
    return render(request, "web/auth/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, _("You are logged out."))
    return redirect("home")


def forgot_password(request):
    form = EmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        request.session["reset_email"] = email
        if User.objects.filter(email__iexact=email, is_active=True).exists():     # same reply either way
            _send_otp(request, email, "reset")
        messages.success(request, _("If that email has an account, we sent a code to it."))
        return redirect("reset_password")
    return render(request, "web/auth/forgot_password.html", {"form": form})


def reset_password(request):
    email = request.session.get("reset_email")
    if not email:
        return redirect("forgot_password")
    form = ResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            otp.verify_code(email, "reset", form.cleaned_data["code"])
        except otp.OtpError as e:
            form.add_error("code", str(e))
        else:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                user.set_password(form.cleaned_data["password1"])
                user.save(update_fields=["password"])
            request.session.pop("reset_email", None)
            messages.success(request, _("Your password was changed. Please log in."))
            return redirect("login")
    return render(request, "web/auth/reset_password.html", {"form": form, "email": mask_email(email)})


# ───────────────────────────── dashboard and documents ─────────────────────────────
@login_required
def dashboard(request):
    profile, _created = Profile.objects.get_or_create(user=request.user)
    if not profile.phone:
        messages.info(request, _("Please add your mobile number to continue. It is required for every account."))
        return redirect("profile_edit")
    if profile.role == CUSTOMER:
        return redirect("customer_home")
    docs = Document.objects.filter(owner=request.user)
    return render(request, "web/dashboard.html", {
        "profile": profile, "documents": docs, "upload_form": DocumentForm(), "plan": current_plan(),
        "drive_ready": google.drive_configured(), "doc_count": docs.count()})


@login_required
@require_POST
def document_upload(request):
    return _store_document(request, DocumentForm(request.POST, request.FILES), lambda: redirect("dashboard"))


def _store_document(request, form, back, party=None, entry=None, visible=True):
    """Validate, send the file to Google Drive and save the reference. Always returns a redirect via back()."""
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return back()
    if not google.drive_configured():
        messages.error(request, _("Document storage is not connected yet. Please try again later."))
        return back()
    if not hit(f"upload:{request.user.pk}", 20, 3600):
        messages.error(request, _("Upload limit reached. Please try again later."))
        return back()
    f = form.cleaned_data["file"]
    data = f.read()
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", f.name)[:120]
    drive_name = f"u{request.user.pk}_{timezone.now():%Y%m%d-%H%M%S}_{safe}"
    mime = f.content_type or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    try:
        info = google.drive_upload(drive_name, data, mime)
    except google.GoogleError:
        log.exception("drive upload failed")
        messages.error(request, _("We could not store the file right now. Please try again."))
        return back()
    Document.objects.create(owner=request.user, party=party, entry=entry, visible_to_customer=visible,
                            title=form.cleaned_data["title"], category=form.cleaned_data["category"],
                            original_name=f.name, mime_type=mime, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            drive_file_id=info["id"], drive_link=info.get("webViewLink", ""))
    messages.success(request, _("“%(title)s” was uploaded and stored safely.") % {"title": form.cleaned_data["title"]})
    return back()


@login_required
def document_download(request, pk: int):
    doc = get_object_or_404(Document, pk=pk)
    mine = doc.owner_id == request.user.pk
    shared = bool(doc.party_id and doc.visible_to_customer and doc.party.customer_id == request.user.pk)
    if not (mine or shared):                                         # the owner, or the linked customer: nobody else
        raise Http404
    try:
        data, ctype = google.drive_download(doc.drive_file_id)
    except google.GoogleError:
        raise Http404(_("The file could not be fetched."))
    resp = HttpResponse(data, content_type=doc.mime_type or ctype)
    resp["Content-Disposition"] = 'attachment; filename="%s"' % re.sub(r'[^A-Za-z0-9._ -]', "_", doc.original_name)
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ───────────────────────────── ledger: who owes me how much ─────────────────────────────
def _annotated(qs):
    gave = Sum("entries__amount_paise", filter=Q(entries__kind="gave", entries__voided=False), output_field=BigIntegerField())
    got = Sum("entries__amount_paise", filter=Q(entries__kind="received", entries__voided=False), output_field=BigIntegerField())
    people = list(qs.annotate(gave=gave, got=got))
    for p in people:
        p.gave, p.got = p.gave or 0, p.got or 0
        p.balance = p.gave - p.got
    return people


def _balances(user):
    return _annotated(Party.objects.filter(owner=user).select_related("customer"))


@shopkeeper_required
def ledger(request):
    people = _balances(request.user)
    return render(request, "web/ledger.html", {
        "people": sorted(people, key=lambda p: (-p.balance, p.name.lower())),
        "to_collect": sum(p.balance for p in people if p.balance > 0),
        "total_given": sum(p.gave for p in people), "total_received": sum(p.got for p in people),
        "owing_count": sum(1 for p in people if p.balance > 0), "form": PartyForm()})


@shopkeeper_required
@require_POST
def party_add(request):
    form = PartyForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return redirect("ledger")
    d = form.cleaned_data
    name = d["name"].strip()
    if Party.objects.filter(owner=request.user, name__iexact=name).exists():
        messages.error(request, _("You already have a person called %(name)s.") % {"name": name})
        return redirect("ledger")
    if Party.objects.filter(owner=request.user).count() >= 2000:
        messages.error(request, _("You have reached the limit of 2000 people."))
        return redirect("ledger")
    p = Party.objects.create(owner=request.user, name=name, phone=d["phone"].strip(), email=d["email"], note=d["note"].strip())
    if linking.link_party(p):
        messages.info(request, _("%(name)s has a LenDen Saathi account, so it is now linked. They can see their own balance.") % {"name": p.name})
    messages.success(request, _("%(name)s was added. Now record the money you gave.") % {"name": p.name})
    return redirect("party_detail", pk=p.pk)


@shopkeeper_required
def party_detail(request, pk: int):
    party = get_object_or_404(Party, pk=pk, owner=request.user)          # only the owner can see a person
    form = EntryForm(request.POST or None, initial={"kind": "gave", "entry_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        LedgerEntry.objects.create(owner=request.user, party=party, kind=d["kind"], amount_paise=int(d["amount"] * 100),
                                   method=d["method"] if d["kind"] == "received" else "", note=d["note"].strip(), entry_date=d["entry_date"])
        linking.link_party(party)                                    # a new credit is a good moment to connect the customer's account
        messages.success(request, _("Entry saved."))
        return redirect("party_detail", pk=party.pk)
    entries = list(party.entries.all())
    live = [e for e in entries if not e.voided]
    gave = sum(e.amount_paise for e in live if e.kind == "gave")
    got = sum(e.amount_paise for e in live if e.kind == "received")
    return render(request, "web/party.html", {
        "party": party, "entries": entries, "gave": gave, "got": got, "balance": gave - got, "form": form,
        "payments": [e for e in live if e.kind == "received"], "documents": party.documents.select_related("entry"),
        "doc_form": PartyDocumentForm(party), "drive_ready": google.drive_configured()})


@shopkeeper_required
@require_POST
def entry_void(request, pk: int):
    e = get_object_or_404(LedgerEntry, pk=pk, owner=request.user)
    if not e.voided:
        e.voided, e.voided_at = True, timezone.now()
        e.save(update_fields=["voided", "voided_at"])
        messages.success(request, _("Entry cancelled. It stays in the history, marked as cancelled."))
    return redirect("party_detail", pk=e.party_id)


# ───────────────────────────── edit my profile / a person ─────────────────────────────
@login_required
def profile_edit(request):
    profile, _created = Profile.objects.get_or_create(user=request.user)
    initial = {"full_name": request.user.first_name, "phone": profile.phone, "shop_name": profile.shop_name}
    form = ProfileForm(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            request.user.first_name = d["full_name"].strip()
            request.user.save(update_fields=["first_name"])
            profile.phone, profile.shop_name = d["phone"], d["shop_name"].strip()
            profile.save(update_fields=["phone", "shop_name", "updated_at"])
        linking.link_customer(request.user)
        messages.success(request, _("Your details were saved."))
        return redirect("dashboard")
    return render(request, "web/profile.html", {"form": form, "profile": profile})


@shopkeeper_required
def party_edit(request, pk: int):
    party = get_object_or_404(Party, pk=pk, owner=request.user)
    form = PartyForm(request.POST or None, initial={"name": party.name, "phone": party.phone, "email": party.email, "note": party.note})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        name = d["name"].strip()
        if Party.objects.filter(owner=request.user, name__iexact=name).exclude(pk=party.pk).exists():
            form.add_error("name", _("You already have a person called %(name)s.") % {"name": name})
        else:
            party.name, party.phone, party.email, party.note = name, d["phone"].strip(), d["email"], d["note"].strip()
            party.save(update_fields=["name", "phone", "email", "note"])
            linking.revalidate_party(party)
            messages.success(request, _("Details saved."))
            return redirect("party_detail", pk=party.pk)
    return render(request, "web/party_edit.html", {"form": form, "party": party})


# ───────────────────────────── shopkeeper: proofs and the customer link ─────────────────────────────
@shopkeeper_required
@require_POST
def party_document_upload(request, pk: int):
    party = get_object_or_404(Party, pk=pk, owner=request.user)
    form = PartyDocumentForm(party, request.POST, request.FILES)
    entry = form.cleaned_data.get("entry") if form.is_valid() else None
    visible = bool(form.cleaned_data.get("visible_to_customer")) if form.is_valid() else True
    return _store_document(request, form, lambda: redirect("party_detail", pk=party.pk), party=party, entry=entry, visible=visible)


@shopkeeper_required
@require_POST
def party_link(request, pk: int):
    """Unlink a wrong customer account (and stop automatic re-linking), or ask for automatic linking again."""
    party = get_object_or_404(Party, pk=pk, owner=request.user)
    if request.POST.get("action") == "unlink":
        party.customer, party.link_method, party.linked_at, party.link_blocked = None, "", None, True
        party.save(update_fields=["customer", "link_method", "linked_at", "link_blocked"])
        messages.success(request, _("The customer account was unlinked. They can no longer see this ledger."))
    else:
        party.link_blocked = False
        party.save(update_fields=["link_blocked"])
        if linking.link_party(party):
            messages.success(request, _("The customer account was found and linked."))
        else:
            messages.info(request, _("No matching customer account was found yet. Linking happens automatically when they sign up."))
    return redirect("party_detail", pk=party.pk)


# ───────────────────────────── customer portal: what I owe ─────────────────────────────
def _shop_label(owner) -> str:
    profile = getattr(owner, "profile", None)
    return (profile.shop_name if profile and profile.shop_name else "") or owner.first_name or _("Shop")


@customer_required
def customer_home(request):
    shops = _annotated(Party.objects.filter(customer=request.user).select_related("owner", "owner__profile"))
    for s in shops:
        s.shop = _shop_label(s.owner)
    return render(request, "web/customer_home.html", {
        "shops": sorted(shops, key=lambda s: (-s.balance, s.shop.lower())),
        "owed": sum(s.balance for s in shops if s.balance > 0),
        "credit_taken": sum(s.gave for s in shops), "paid": sum(s.got for s in shops),
        "profile": request.user.profile, "plan": current_plan()})


@customer_required
def customer_shop(request, pk: int):
    party = get_object_or_404(Party.objects.select_related("owner", "owner__profile"), pk=pk, customer=request.user)   # only my own
    entries = sorted(party.entries.all(), key=lambda e: (e.entry_date, e.id))
    running, rows = 0, []
    for e in entries:
        if not e.voided:
            running += e.amount_paise if e.kind == "gave" else -e.amount_paise
        rows.append({"e": e, "after": running})
    live = [e for e in entries if not e.voided]
    gave = sum(e.amount_paise for e in live if e.kind == "gave")
    got = sum(e.amount_paise for e in live if e.kind == "received")
    return render(request, "web/customer_shop.html", {
        "party": party, "shop": _shop_label(party.owner), "rows": list(reversed(rows)), "gave": gave, "got": got, "balance": gave - got,
        "documents": party.documents.filter(visible_to_customer=True)})
