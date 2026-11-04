"""Django admin for the app's PostgreSQL tables (the shop data). Dangerous tables are read-only."""
from django.apps import apps as django_apps
from django.contrib import admin
from django.db import models

# Posted money and audit trails: look, never touch (also enforced by database triggers).
READ_ONLY_TABLES = {
    "ledger_events", "transaction_items", "sales", "sale_items", "sale_payments", "sale_returns", "sale_ledger_links",
    "payments", "payment_orders", "payment_mandates", "payment_customers", "subscription_invoices", "gateway_webhook_events",
    "subscription_audit_events", "audit_logs", "sync_receipts", "sync_cursors", "otp_challenges", "devices_sessions",
    "confirmation_requests", "confirmation_events", "signature_evidence", "evidence_files", "schema_migrations", "trial_grants",
}
# Tables where adding rows from admin makes sense.
CAN_ADD = {"subscription_plans", "support_cases", "app_config"}
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

    def has_delete_permission(self, request, obj=None):
        return False if self._ro() or self.model._meta.db_table in {"users", "shops", "customers"} else super().has_delete_permission(request, obj)

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
