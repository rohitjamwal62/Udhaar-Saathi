"""Django admin for the app's PostgreSQL tables (the shop data). Dangerous tables are read-only.

What the data manager (/admin/) lets a superuser do:
  * posted money and audit trails: look only (the database itself refuses edits and deletes there),
  * shops and customers: add, edit, and delete when EMPTY (a customer with ledger entries or sales, or a shop that still has
    customers, is protected; the reason is shown instead of an error page),
  * plans, support cases, app config: add, edit, delete,
  * users: edit only (change the status to suspended or deleted instead of removing the row, so nothing is orphaned).
"""
import uuid

from django.apps import apps as django_apps
from django.contrib import admin, messages
from django.db import DatabaseError, models, transaction
from django.utils import timezone

from apps.common.db import q1

# Posted money and audit trails: look, never touch (also enforced by database triggers).
READ_ONLY_TABLES = {
    "ledger_events", "transaction_items", "sales", "sale_items", "sale_payments", "sale_returns", "sale_ledger_links",
    "payments", "payment_orders", "payment_mandates", "payment_customers", "subscription_invoices", "gateway_webhook_events",
    "subscription_audit_events", "audit_logs", "sync_receipts", "sync_cursors", "otp_challenges", "devices_sessions",
    "confirmation_requests", "confirmation_events", "signature_evidence", "evidence_files", "schema_migrations", "trial_grants",
}
# Tables where adding rows from admin makes sense.
CAN_ADD = {"subscription_plans", "support_cases", "app_config", "shops", "customers"}
# Deleting is allowed only when nothing depends on the row (see _in_use).
DELETE_WHEN_EMPTY = {"shops", "customers"}
NEVER_DELETE = {"users"}
# Never show password hashes.
HIDDEN_FIELDS = {"password_hash", "code_hash", "refresh_token_hash", "token_hash"}


class LegacyAdmin(admin.ModelAdmin):
    list_per_page = 50
    show_full_result_count = False

    def get_exclude(self, request, obj=None):
        return [f.name for f in self.model._meta.fields if f.name in HIDDEN_FIELDS] or None

    def get_list_display(self, request):
        fields = [f.name for f in self.model._meta.fields if f.name not in HIDDEN_FIELDS and f.get_internal_type() not in ("TextField", "JSONField")]
        return fields[:7] or ["__str__"]

    def _ro(self):
        return self.model._meta.db_table in READ_ONLY_TABLES

    def has_add_permission(self, request):
        return self.model._meta.db_table in CAN_ADD and super().has_add_permission(request)

    def _in_use(self, obj) -> str | None:
        """Why this row must stay, or None when it is safe to delete."""
        from . import models as m
        table = self.model._meta.db_table
        if table == "customers":
            if m.LedgerEvents.objects.filter(customer_id=obj.pk).exists():
                return "it has ledger entries (posted money is never deleted)"
            if m.Sales.objects.filter(customer_id=obj.pk).exists():
                return "it has sales"
        if table == "shops":
            if m.Customers.objects.filter(shop_id=obj.pk).exists():
                return "it still has customers"
            if m.Sales.objects.filter(shop_id=obj.pk).exists():
                return "it has sales"
            if q1("SELECT 1 AS x FROM sync_receipts WHERE shop_id = %s LIMIT 1", [obj.pk]):
                return "the app has already synced data for it (those records are append-only)"
        return None

    def has_delete_permission(self, request, obj=None):
        table = self.model._meta.db_table
        if self._ro() or table in NEVER_DELETE or not super().has_delete_permission(request, obj):
            return False
        if table in DELETE_WHEN_EMPTY and obj is not None:
            return self._in_use(obj) is None
        return True

    def save_model(self, request, obj, form, change):
        if not change:   # these tables fill their id and timestamps in the database/app, not in the form
            if isinstance(self.model._meta.pk, models.UUIDField) and not obj.pk:
                obj.pk = uuid.uuid4()
            now = timezone.now()
            for name in ("created_at", "updated_at"):
                if any(f.name == name for f in self.model._meta.fields) and getattr(obj, name, None) is None:
                    setattr(obj, name, now)
        elif any(f.name == "updated_at" for f in self.model._meta.fields):
            obj.updated_at = timezone.now()
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        try:
            with transaction.atomic():
                super().delete_model(request, obj)
        except DatabaseError as e:   # a foreign key or a database rule said no: say so politely instead of a 500 page
            request._delete_failed = True
            messages.error(request, f"Could not delete: the database refused ({str(e).splitlines()[0][:160]}).")

    def message_user(self, request, message, level=messages.INFO, extra_tags="", fail_silently=False):
        if getattr(request, "_delete_failed", False) and level == messages.SUCCESS:
            return   # Django would say "deleted successfully" right after our "could not delete" message
        super().message_user(request, message, level, extra_tags, fail_silently)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            if self.has_delete_permission(request, obj):
                self.delete_model(request, obj)
            else:
                messages.warning(request, f"Kept '{obj}': it is in use or protected.")

    def get_readonly_fields(self, request, obj=None):
        names = [f.name for f in self.model._meta.fields]
        if self._ro():
            return names
        # editable tables: keep identifiers and timestamps fixed
        return [n for n in names if n in {"id", "created_at", "updated_at", "server_created_at"}]


for model in django_apps.get_app_config("legacy").get_models():
    if isinstance(model._meta.pk, models.CompositePrimaryKey):
        continue  # admin cannot show composite-key tables; they stay reachable through their parent records
    admin.site.register(model, type(f"{model.__name__}Admin", (LegacyAdmin,), {}))
