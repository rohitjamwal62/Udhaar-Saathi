from django.conf import settings
from django.db import models


class Profile(models.Model):
    ROLES = [("shopkeeper", "Shopkeeper"), ("customer", "Customer")]
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
    CATEGORIES = [("id_proof", "ID proof"), ("shop_proof", "Shop proof / licence"), ("bill", "Bill or receipt"),
                  ("agreement", "Agreement"), ("other", "Other")]
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
    order = models.PositiveSmallIntegerField(default=100)
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question


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
    KINDS = [("gave", "Gave (udhaar)"), ("received", "Received (repayment)")]
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
