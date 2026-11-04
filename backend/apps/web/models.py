from django.conf import settings
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class Profile(models.Model):
    ROLES = [("shopkeeper", _("Shopkeeper")), ("customer", _("Customer"))]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=12, choices=ROLES, default="shopkeeper")
    phone = models.CharField(max_length=16, blank=True, help_text="E.164, e.g. +919876543210")
    shop_name = models.CharField(max_length=160, blank=True)
    email_verified = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role})"


class EmailOTP(models.Model):
    """One-time codes sent by email. Only an HMAC of the code is stored, never the code itself."""
    PURPOSES = [("register", "Registration"), ("reset", "Password reset")]
    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=10, choices=PURPOSES)
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email OTP"
        verbose_name_plural = "Email OTPs"

    def __str__(self):
        return f"{self.purpose} OTP for {self.email}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=160)
    message = models.TextField()
    handled = models.BooleanField(default=False, help_text="Tick once you have replied.")
    notification_sent = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} - {self.name}"


class Document(models.Model):
    """A file uploaded by a signed-in user. The bytes live in Google Drive, only the reference is stored here."""
    CATEGORIES = [("id_proof", _("ID proof")), ("shop_proof", _("Shop proof / licence")), ("bill", _("Bill or receipt")),
                  ("agreement", _("Agreement")), ("other", _("Other"))]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    party = models.ForeignKey("Party", null=True, blank=True, on_delete=models.CASCADE, related_name="documents",
                              help_text="Set when a shopkeeper attaches this proof to one customer.")
    entry = models.ForeignKey("LedgerEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents",
                              help_text="Optional: the credit or payment this proof belongs to.")
    visible_to_customer = models.BooleanField(default=True, help_text="Let the linked customer view this proof.")
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=12, choices=CATEGORIES, default="other")
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    drive_file_id = models.CharField(max_length=120, unique=True)
    drive_link = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class FAQ(models.Model):
    """Questions shown on the website. Edit them in Django admin."""
    question = models.CharField(max_length=240)
    answer = models.TextField()
    question_hi = models.CharField("Question (Hindi)", max_length=240, blank=True, null=True,
                                   help_text="Optional. Shown instead of the English question when the visitor chose Hindi.")
    answer_hi = models.TextField("Answer (Hindi)", blank=True, null=True,
                                 help_text="Optional. Shown instead of the English answer when the visitor chose Hindi.")
    order = models.PositiveSmallIntegerField(default=100)
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question

    @property
    def display_question(self) -> str:
        """The question in the visitor's language (Hindi text when 'hi' is active and has been written)."""
        return self.question_hi if (get_language() or "").startswith("hi") and self.question_hi else self.question

    @property
    def display_answer(self) -> str:
        return self.answer_hi if (get_language() or "").startswith("hi") and self.answer_hi else self.answer


class Party(models.Model):
    """A person the signed-in user lends money to (a customer on credit)."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parties")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    phone_norm = models.CharField(max_length=10, blank=True, db_index=True, editable=False,
                                  help_text="The 10-digit mobile number, used to find the customer's own account.")
    email = models.EmailField(blank=True, help_text="The email the customer registered with (most reliable way to link).")
    note = models.CharField(max_length=240, blank=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="linked_parties",
                                 help_text="The customer's own UdhaarSaathi account. Set automatically; the customer sees only their own entries.")
    link_method = models.CharField(max_length=8, blank=True, editable=False)
    linked_at = models.DateTimeField(null=True, blank=True, editable=False)
    link_blocked = models.BooleanField(default=False, help_text="Set when the shopkeeper unlinks the account: stops automatic re-linking.")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from .reminders import normalize_mobile
        self.phone_norm = normalize_mobile(self.phone) or ""
        self.email = (self.email or "").strip().lower()
        fields = kwargs.get("update_fields")
        if fields is not None:
            kwargs["update_fields"] = set(fields) | {"phone_norm", "email"}
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["name"]
        verbose_name = "person"
        verbose_name_plural = "people (ledger)"

    def __str__(self):
        return self.name


class LedgerEntry(models.Model):
    """Money lent to a person (gave) or paid back by them (received). Amounts are whole paise.
    Entries are never edited or deleted: a mistake is cancelled (voided), so the history stays honest."""
    KINDS = [("gave", _("Gave (udhaar)")), ("received", _("Received (repayment)"))]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ledger_entries")
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=8, choices=KINDS)
    amount_paise = models.PositiveBigIntegerField()
    METHODS = [("cash", "Cash"), ("upi", "UPI"), ("bank", "Bank transfer"), ("other", "Other")]
    method = models.CharField(max_length=8, blank=True, choices=METHODS, help_text="How a payment was made (for money received).")
    note = models.CharField(max_length=240, blank=True)
    entry_date = models.DateField()
    voided = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-entry_date", "-id"]
        verbose_name = "ledger entry"
        verbose_name_plural = "ledger entries"

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount_paise / 100:.2f} - {self.party}"


class SiteSetting(models.Model):
    """Public contact details shown on the website. One row; edit it in Django admin. Empty fields fall back to the server settings."""
    support_email = models.EmailField(blank=True, help_text="Shown in the footer and on the contact page; contact messages are sent here.")
    support_phone = models.CharField(max_length=30, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True, help_text="10-digit Indian mobile number, shown as a WhatsApp link.")
    address = models.CharField(max_length=240, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site contact details"
        verbose_name_plural = "site contact details"

    def __str__(self):
        return "Site contact details"

    @classmethod
    def current(cls):
        """The one row, cached for a minute (cleared on save). Never raises: the site must render even if the table is not ready."""
        from django.core.cache import cache
        row = cache.get("site:setting")
        if row is None:
            try:
                row = cls.objects.order_by("id").first() or cls()
            except Exception:  # noqa: BLE001
                row = cls()
            cache.set("site:setting", row, 60)
        return row


class LegalPage(models.Model):
    """Terms and Privacy text in English and Hindi, editable in admin. HTML is allowed (admins only). Empty body = built-in text."""
    SLUGS = [("terms", "Terms of use"), ("privacy", "Privacy notice")]
    slug = models.CharField(max_length=20, choices=SLUGS, unique=True)
    body_en = models.TextField(blank=True, help_text="HTML. Leave empty to use the built-in English text.")
    body_hi = models.TextField(blank=True, help_text="HTML. Leave empty to use the built-in Hindi text.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "legal page"

    def __str__(self):
        return self.get_slug_display()
