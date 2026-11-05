import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

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
    raise forms.ValidationError(_("Enter a valid mobile number, for example 98765 43210."))


def clean_required_mobile(value: str, exclude_user_id=None) -> str:
    """A mobile number is mandatory for every account. It must be valid and not used by another account."""
    number = normalize_phone(value)
    if not number:
        raise forms.ValidationError(_("Please enter your mobile number."))
    taken = Profile.objects.filter(phone=number)
    if exclude_user_id:
        taken = taken.exclude(user_id=exclude_user_id)
    if taken.exists():
        raise forms.ValidationError(_("This mobile number is already used by another account."))
    return number


def check_password_rules(pw: str) -> str:
    if len(pw) < 8 or len(pw) > 128:
        raise forms.ValidationError(_("Use 8 to 128 characters."))
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise forms.ValidationError(_("Include both letters and numbers."))
    return pw


class HoneypotMixin(forms.Form):
    """A hidden field real people never fill in. Bots usually do."""
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}))

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("Spam detected."))
        return ""


class RegisterForm(HoneypotMixin):
    full_name = forms.CharField(max_length=120, label=gettext_lazy("Full name"))
    email = forms.EmailField(label=gettext_lazy("Email address"))
    phone = forms.CharField(max_length=20, label=gettext_lazy("Mobile number"))
    shop_name = forms.CharField(max_length=160, required=False, label=gettext_lazy("Shop name (optional)"))
    role = forms.ChoiceField(choices=Profile.ROLES, initial="shopkeeper", label=gettext_lazy("I am a"))
    password1 = forms.CharField(widget=forms.PasswordInput, label=gettext_lazy("Password"), strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label=gettext_lazy("Confirm password"), strip=False)
    accept_terms = forms.BooleanField(label=gettext_lazy("I accept the Terms and the Privacy Notice"))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(_("An account with this email already exists. Please log in instead."))
        return email

    def clean_phone(self):
        # An earlier, unverified attempt with the same email may be reused, so it does not count as "another account".
        email = (self.data.get("email") or "").strip().lower()
        same = User.objects.filter(email__iexact=email).values_list("pk", flat=True).first() if email else None
        return clean_required_mobile(self.cleaned_data.get("phone", ""), exclude_user_id=same)

    def clean_password1(self):
        return check_password_rules(self.cleaned_data["password1"])

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password2") and data["password1"] != data["password2"]:
            self.add_error("password2", _("The two passwords do not match."))
        return data


class OTPForm(forms.Form):
    code = forms.RegexField(r"^\d{6}$", label=gettext_lazy("6-digit code"), error_messages={"invalid": gettext_lazy("Enter the 6 digits from the email.")},
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "maxlength": "6", "pattern": "[0-9]{6}"}))


class LoginForm(forms.Form):
    identifier = forms.CharField(max_length=254, label=gettext_lazy("Email or username"))
    password = forms.CharField(widget=forms.PasswordInput, strip=False, label=gettext_lazy("Password"))


class EmailForm(forms.Form):
    email = forms.EmailField(label=gettext_lazy("Email address"))


class ResetForm(OTPForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label=gettext_lazy("New password"), strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label=gettext_lazy("Confirm new password"), strip=False)

    def clean_password1(self):
        return check_password_rules(self.cleaned_data["password1"])

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password2") and data["password1"] != data["password2"]:
            self.add_error("password2", _("The two passwords do not match."))
        return data


class ContactForm(HoneypotMixin):
    name = forms.CharField(max_length=120, label=gettext_lazy("Your name"))
    email = forms.EmailField(label=gettext_lazy("Email address"))
    phone = forms.CharField(max_length=20, required=False, label=gettext_lazy("Phone (optional)"))
    subject = forms.CharField(max_length=160, label=gettext_lazy("Subject"))
    message = forms.CharField(max_length=4000, label=gettext_lazy("Message"), widget=forms.Textarea(attrs={"rows": 6}))

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone", ""))


class DocumentForm(forms.Form):
    title = forms.CharField(max_length=160, label=gettext_lazy("Document title"))
    category = forms.ChoiceField(choices=Document.CATEGORIES, label=gettext_lazy("Type of document"))
    file = forms.FileField(label=gettext_lazy("File"))

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in settings.DOCUMENT_ALLOWED_EXTENSIONS:
            raise forms.ValidationError(_("Allowed file types: %(types)s.") % {"types": ", ".join(settings.DOCUMENT_ALLOWED_EXTENSIONS)})
        if f.size > settings.DOCUMENT_MAX_BYTES:
            raise forms.ValidationError(_("The file is too large (limit %(mb)s MB).") % {"mb": settings.DOCUMENT_MAX_BYTES // (1024 * 1024)})
        if f.size == 0:
            raise forms.ValidationError(_("The file is empty."))
        return f


class PartyForm(forms.Form):
    name = forms.CharField(max_length=120, label=gettext_lazy("Person's name"))
    phone = forms.CharField(max_length=20, required=False, label=gettext_lazy("Mobile number (optional)"))
    email = forms.EmailField(required=False, label=gettext_lazy("Customer's email (optional)"),
                             help_text=gettext_lazy("If the customer has a LenDen Saathi account with this email or mobile number, it is linked automatically."))
    note = forms.CharField(max_length=240, required=False, label=gettext_lazy("Note (optional)"))


class EntryForm(forms.Form):
    kind = forms.ChoiceField(choices=[("gave", gettext_lazy("I gave money (udhaar)")), ("received", gettext_lazy("I received money back"))], label=gettext_lazy("What happened"))
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01, max_value=10000000, label=gettext_lazy("Amount (Rs)"))
    entry_date = forms.DateField(label=gettext_lazy("Date"), widget=forms.DateInput(attrs={"type": "date"}))
    method = forms.ChoiceField(required=False, label=gettext_lazy("Paid by (for money received)"),
                               choices=[("", gettext_lazy("Not stated")), ("cash", gettext_lazy("Cash")), ("upi", "UPI"),
                                        ("bank", gettext_lazy("Bank transfer")), ("other", gettext_lazy("Other"))])
    note = forms.CharField(max_length=240, required=False, label=gettext_lazy("Note (optional)"))

    def clean_entry_date(self):
        from django.utils import timezone
        d = self.cleaned_data["entry_date"]
        if d > timezone.localdate():
            raise forms.ValidationError(_("The date cannot be in the future."))
        return d


class ProfileForm(forms.Form):
    full_name = forms.CharField(max_length=120, label=gettext_lazy("Full name"))
    phone = forms.CharField(max_length=20, label=gettext_lazy("Mobile number"))
    shop_name = forms.CharField(max_length=160, required=False, label=gettext_lazy("Shop name (optional)"))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_phone(self):
        return clean_required_mobile(self.cleaned_data.get("phone", ""), exclude_user_id=getattr(self.user, "pk", None))


class PartyDocumentForm(DocumentForm):
    """A proof attached to one customer, and optionally to one of that customer's entries."""
    entry = forms.ModelChoiceField(queryset=None, required=False, empty_label=gettext_lazy("Not tied to one entry"),
                                   label=gettext_lazy("Related entry (optional)"))
    visible_to_customer = forms.BooleanField(required=False, initial=True, label=gettext_lazy("Let the customer see this proof"))

    def __init__(self, party, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entry"].queryset = party.entries.all()
        self.fields["entry"].label_from_instance = lambda e: f"{e.entry_date:%d %b %Y} - {e.get_kind_display()} - {e.amount_paise / 100:,.2f}"
