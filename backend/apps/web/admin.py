from django.contrib import admin
from django.utils.html import format_html

from .models import FAQ, ContactMessage, Document, EmailOTP, Profile

admin.site.site_header = "UdhaarSaathi administration"
admin.site.site_title = "UdhaarSaathi admin"
admin.site.index_title = "Manage the website, users, documents and the app database"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "phone", "shop_name", "email_verified", "created_at")
    list_filter = ("role", "email_verified")
    search_fields = ("user__email", "user__first_name", "phone", "shop_name")
    raw_id_fields = ("user",)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "handled", "notification_sent", "created_at")
    list_filter = ("handled", "notification_sent")
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("name", "email", "phone", "subject", "message", "created_at", "notification_sent")
    actions = ["mark_handled"]

    @admin.action(description="Mark selected messages as handled")
    def mark_handled(self, request, queryset):
        queryset.update(handled=True)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "category", "size_kb", "open_in_drive", "created_at")
    list_filter = ("category",)
    search_fields = ("title", "original_name", "owner__email")
    readonly_fields = ("owner", "original_name", "mime_type", "size_bytes", "sha256", "drive_file_id", "drive_link", "created_at")

    @admin.display(description="Size (KB)")
    def size_kb(self, obj):
        return round(obj.size_bytes / 1024, 1)

    @admin.display(description="Google Drive")
    def open_in_drive(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">Open</a>', obj.drive_link) if obj.drive_link else "-"

    def has_add_permission(self, request):
        return False   # documents are uploaded by users on the website


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    """Read-only: shows when codes were sent and used. The codes themselves are never stored."""
    list_display = ("email", "purpose", "attempts", "created_at", "expires_at", "consumed_at")
    list_filter = ("purpose",)
    search_fields = ("email",)
    exclude = ("code_hash",)
    readonly_fields = ("email", "purpose", "attempts", "expires_at", "consumed_at", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "order", "published")
    list_editable = ("order", "published")
    search_fields = ("question", "answer")


from .models import LedgerEntry, Party  # noqa: E402


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "phone", "created_at")
    search_fields = ("name", "phone", "owner__email")
    raw_id_fields = ("owner",)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Read-only history: money entries are never edited or deleted, only cancelled by their owner."""
    list_display = ("entry_date", "party", "owner", "kind", "rupees", "voided")
    list_filter = ("kind", "voided")
    search_fields = ("party__name", "owner__email", "note")
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]

    @admin.display(description="Amount (Rs)")
    def rupees(self, obj):
        return f"{obj.amount_paise / 100:,.2f}"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
