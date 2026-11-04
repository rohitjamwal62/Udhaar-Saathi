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
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
