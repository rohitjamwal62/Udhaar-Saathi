import hashlib
import logging
import mimetypes
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.ratelimit import hit

from . import google, mailer, otp
from .forms import ContactForm, DocumentForm, EmailForm, LoginForm, OTPForm, RegisterForm, ResetForm
from .models import FAQ, ContactMessage, Document, Profile
from .context_processors import current_plan

log = logging.getLogger("web")
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


def terms(request):
    return render(request, "web/terms.html")


def privacy(request):
    return render(request, "web/privacy.html")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST":
        if not hit(f"contact:{client_ip(request)}", 5, 3600):
            messages.error(request, "Too many messages from this connection. Please try again later.")
        elif form.is_valid():
            d = form.cleaned_data
            msg = ContactMessage.objects.create(name=d["name"], email=d["email"], phone=d["phone"], subject=d["subject"], message=d["message"])
            msg.notification_sent = mailer.send_contact_emails(d["name"], d["email"], d["phone"], d["subject"], d["message"])
            msg.save(update_fields=["notification_sent"])
            messages.success(request, "Thank you. Your message was received and we will reply by email.")
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
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role, profile.phone, profile.shop_name = d["role"], d["phone"], d["shop_name"]
            profile.terms_accepted_at = timezone.now()
            profile.save()
        request.session["pending_email"] = d["email"]
        try:
            otp.send_code(d["email"], "register", client_ip(request))
            messages.success(request, f"We sent a 6-digit code to {mask_email(d['email'])}.")
        except otp.OtpError as e:
            messages.warning(request, str(e))
        return redirect("verify_otp")
    return render(request, "web/auth/register.html", {"form": form})


def verify_otp(request):
    email = request.session.get("pending_email")
    if not email:
        messages.info(request, "Please register first.")
        return redirect("register")
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not hit(f"verify:{client_ip(request)}", 30, 900):
            messages.error(request, "Too many attempts. Please wait a few minutes.")
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
                request.session.pop("pending_email", None)
                login(request, user, backend=BACKEND)
                mailer.send_welcome_email(user.email, user.first_name or "there")
                messages.success(request, "Your email is verified. Welcome to UdhaarSaathi!")
                return redirect("dashboard")
    return render(request, "web/auth/verify_otp.html", {"form": form, "email": mask_email(email), "resend_in": otp.seconds_until_resend(email, "register")})


@require_POST
def resend_otp(request):
    email = request.session.get("pending_email")
    if not email:
        return redirect("register")
    try:
        otp.send_code(email, "register", client_ip(request))
        messages.success(request, f"A new code was sent to {mask_email(email)}.")
    except otp.OtpError as e:
        messages.warning(request, str(e))
    return redirect("verify_otp")


# ───────────────────────────── login / logout / reset ─────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ident = form.cleaned_data["identifier"].strip().lower()
        if not hit(f"login:{ident}", 10, 900) or not hit(f"login-ip:{client_ip(request)}", 40, 900):
            messages.error(request, "Too many login attempts. Please try again in a few minutes.")
        else:
            user = User.objects.filter(email__iexact=ident).first() or User.objects.filter(username__iexact=ident).first()
            if user and user.check_password(form.cleaned_data["password"]):
                if not user.is_active:                      # right password, but the email was never verified
                    request.session["pending_email"] = user.email
                    try:
                        otp.send_code(user.email, "register", client_ip(request))
                    except otp.OtpError:
                        pass
                    messages.info(request, "Please verify your email first. We sent you a new code.")
                    return redirect("verify_otp")
                login(request, user, backend=BACKEND)
                nxt = request.GET.get("next", "")
                return redirect(nxt if re.fullmatch(r"/[A-Za-z0-9_/\-]*", nxt) else "dashboard")
            form.add_error(None, "The email or password is incorrect.")   # same message for unknown accounts
    return render(request, "web/auth/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "You are logged out.")
    return redirect("home")


def forgot_password(request):
    form = EmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        request.session["reset_email"] = email
        if User.objects.filter(email__iexact=email, is_active=True).exists():     # same reply either way
            try:
                otp.send_code(email, "reset", client_ip(request))
            except otp.OtpError as e:
                messages.warning(request, str(e))
        messages.success(request, "If that email has an account, we sent a code to it.")
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
            messages.success(request, "Your password was changed. Please log in.")
            return redirect("login")
    return render(request, "web/auth/reset_password.html", {"form": form, "email": mask_email(email)})


# ───────────────────────────── dashboard and documents ─────────────────────────────
@login_required
def dashboard(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    docs = Document.objects.filter(owner=request.user)
    return render(request, "web/dashboard.html", {
        "profile": profile, "documents": docs, "upload_form": DocumentForm(), "plan": current_plan(),
        "drive_ready": google.drive_configured(), "doc_count": docs.count()})


@login_required
@require_POST
def document_upload(request):
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return redirect("dashboard")
    if not google.drive_configured():
        messages.error(request, "Document storage is not connected yet. Please try again later.")
        return redirect("dashboard")
    if not hit(f"upload:{request.user.pk}", 20, 3600):
        messages.error(request, "Upload limit reached. Please try again later.")
        return redirect("dashboard")
    f = form.cleaned_data["file"]
    data = f.read()
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", f.name)[:120]
    drive_name = f"u{request.user.pk}_{timezone.now():%Y%m%d-%H%M%S}_{safe}"
    mime = f.content_type or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    try:
        info = google.drive_upload(drive_name, data, mime)
    except google.GoogleError:
        log.exception("drive upload failed")
        messages.error(request, "We could not store the file right now. Please try again.")
        return redirect("dashboard")
    Document.objects.create(owner=request.user, title=form.cleaned_data["title"], category=form.cleaned_data["category"],
                            original_name=f.name, mime_type=mime, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            drive_file_id=info["id"], drive_link=info.get("webViewLink", ""))
    messages.success(request, f"“{form.cleaned_data['title']}” was uploaded and stored safely.")
    return redirect("dashboard")


@login_required
def document_download(request, pk: int):
    doc = get_object_or_404(Document, pk=pk, owner=request.user)     # only the owner can fetch it
    try:
        data, ctype = google.drive_download(doc.drive_file_id)
    except google.GoogleError:
        raise Http404("The file could not be fetched.")
    resp = HttpResponse(data, content_type=doc.mime_type or ctype)
    resp["Content-Disposition"] = 'attachment; filename="%s"' % re.sub(r'[^A-Za-z0-9._ -]', "_", doc.original_name)
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
