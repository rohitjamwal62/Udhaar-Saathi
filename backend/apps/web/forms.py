import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Document, Profile

User = get_user_model()


def normalize_phone(value: str) -> str:
    """Indian mobile numbers become +91XXXXXXXXXX; other E.164 numbers are kept. Empty stays empty."""
    d = re.sub(r"[\s-]", "", value or "")
    if not d:
        return ""
    if re.fullmatch(r"[6-9]\d{9}", d):
        return "+91" + d
    if re.fullmatch(r"91[6-9]\d{9}", d.lstrip("+")):
        return "+" + d.lstrip("+")
    if re.fullmatch(r"\+[1-9]\d{7,14}", d):
        return d
    raise forms.ValidationError("Enter a valid mobile number, for example 98765 43210.")


def check_password_rules(pw: str) -> str:
    if len(pw) < 8 or len(pw) > 128:
        raise forms.ValidationError("Use 8 to 128 characters.")
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise forms.ValidationError("Include both letters and numbers.")
    return pw


class HoneypotMixin(forms.Form):
    """A hidden field real people never fill in. Bots usually do."""
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}))

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""


class RegisterForm(HoneypotMixin):
    full_name = forms.CharField(max_length=120, label="Full name")
    email = forms.EmailField(label="Email address")
    phone = forms.CharField(max_length=20, required=False, label="Mobile number (optional)")
    shop_name = forms.CharField(max_length=160, required=False, label="Shop name (optional)")
    role = forms.ChoiceField(choices=Profile.ROLES, initial="shopkeeper", label="I am a")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password", strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password", strip=False)
    accept_terms = forms.BooleanField(label="I accept the Terms and the Privacy Notice")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError("An account with this email already exists. Please log in instead.")
        return email

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone", ""))

    def clean_password1(self):
        return check_password_rules(self.cleaned_data["password1"])

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password2") and data["password1"] != data["password2"]:
            self.add_error("password2", "The two passwords do not match.")
        return data


class OTPForm(forms.Form):
    code = forms.RegexField(r"^\d{6}$", label="6-digit code", error_messages={"invalid": "Enter the 6 digits from the email."},
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "maxlength": "6", "pattern": "[0-9]{6}"}))


class LoginForm(forms.Form):
    identifier = forms.CharField(max_length=254, label="Email or username")
    password = forms.CharField(widget=forms.PasswordInput, strip=False, label="Password")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


class ResetForm(OTPForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label="New password", strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm new password", strip=False)

    def clean_password1(self):
        return check_password_rules(self.cleaned_data["password1"])

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password2") and data["password1"] != data["password2"]:
            self.add_error("password2", "The two passwords do not match.")
        return data


class ContactForm(HoneypotMixin):
    name = forms.CharField(max_length=120, label="Your name")
    email = forms.EmailField(label="Email address")
    phone = forms.CharField(max_length=20, required=False, label="Phone (optional)")
    subject = forms.CharField(max_length=160, label="Subject")
    message = forms.CharField(max_length=4000, label="Message", widget=forms.Textarea(attrs={"rows": 6}))

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone", ""))


class DocumentForm(forms.Form):
    title = forms.CharField(max_length=160, label="Document title")
    category = forms.ChoiceField(choices=Document.CATEGORIES, label="Type of document")
    file = forms.FileField(label="File")

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in settings.DOCUMENT_ALLOWED_EXTENSIONS:
            raise forms.ValidationError("Allowed file types: " + ", ".join(settings.DOCUMENT_ALLOWED_EXTENSIONS) + ".")
        if f.size > settings.DOCUMENT_MAX_BYTES:
            raise forms.ValidationError(f"The file is too large (limit {settings.DOCUMENT_MAX_BYTES // (1024 * 1024)} MB).")
        if f.size == 0:
            raise forms.ValidationError("The file is empty.")
        return f


class PartyForm(forms.Form):
    name = forms.CharField(max_length=120, label="Person's name")
    phone = forms.CharField(max_length=20, required=False, label="Mobile number (optional)")
    note = forms.CharField(max_length=240, required=False, label="Note (optional)")


class EntryForm(forms.Form):
    kind = forms.ChoiceField(choices=[("gave", "I gave money (udhaar)"), ("received", "I received money back")], label="What happened")
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01, max_value=10000000, label="Amount (Rs)")
    entry_date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(max_length=240, required=False, label="Note (optional)")

    def clean_entry_date(self):
        from django.utils import timezone
        d = self.cleaned_data["entry_date"]
        if d > timezone.localdate():
            raise forms.ValidationError("The date cannot be in the future.")
        return d
