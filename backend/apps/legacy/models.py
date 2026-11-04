"""Unmanaged Django models over the tables created by database/create_tables.py.

Django never creates, alters or drops these tables (managed = False): the schema is owned by create_tables.py.
They exist so the shop data can be viewed and, where safe, edited in Django admin. Money, audit and ledger tables are
read-only in admin (see admin.py), and PostgreSQL triggers also refuse edits to posted ledger entries.
"""
from django.db import models


def _label(obj) -> str:
    for attr in ("name", "invoice_number", "sale_number", "shop_id_code", "mobile_e164", "code", "gateway_order_id", "gateway_payment_id", "type"):
        v = getattr(obj, attr, None)
        if v:
            return str(v)
    return str(obj.pk)

class AppConfig(models.Model):
    id = models.SmallIntegerField(primary_key=True)
    latest_version = models.CharField(max_length=20)
    minimum_supported_version = models.CharField(max_length=20)
    force_update = models.BooleanField()
    update_message = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'app_config'
        verbose_name = 'App update setting'
        verbose_name_plural = 'App update settings'


class AuditLogs(models.Model):
    id = models.BigAutoField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING, blank=True, null=True)
    actor = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    action = models.CharField(max_length=60)
    entity_type = models.CharField(max_length=40)
    entity_id = models.UUIDField(blank=True, null=True)
    timestamp = models.DateTimeField()
    metadata = models.JSONField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'audit_logs'
        verbose_name = 'Audit log entry'
        verbose_name_plural = 'Audit log'


class CommunicationConsents(models.Model):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    customer = models.ForeignKey('Customers', models.DO_NOTHING, blank=True, null=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING, blank=True, null=True)
    channel = models.CharField(max_length=12)
    purpose = models.CharField(max_length=16)
    status = models.CharField(max_length=12)
    captured_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(blank=True, null=True)
    evidence_ref = models.TextField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'communication_consents'
        verbose_name = 'Communication consent'
        verbose_name_plural = 'Communication consents'


class ConfirmationEvents(models.Model):
    id = models.UUIDField(primary_key=True)
    request = models.ForeignKey('ConfirmationRequests', models.DO_NOTHING)
    status = models.CharField(max_length=12)
    method = models.CharField(max_length=12)
    consent_text_version = models.CharField(max_length=20)
    verified_at = models.DateTimeField(blank=True, null=True)
    server_timestamp = models.DateTimeField()
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    metadata = models.JSONField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'confirmation_events'
        verbose_name = 'Confirmation event'
        verbose_name_plural = 'Confirmation events'


class ConfirmationRequests(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    ledger_event = models.ForeignKey('LedgerEvents', models.DO_NOTHING)
    customer_user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    method = models.CharField(max_length=12)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    token_hash = models.TextField(unique=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=12)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'confirmation_requests'
        verbose_name = 'Confirmation request'
        verbose_name_plural = 'Confirmation requests'


class Customers(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    linked_user = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    name = models.CharField(max_length=160)
    mobile_e164 = models.CharField(max_length=16, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'customers'
        verbose_name = 'Shop customer'
        verbose_name_plural = 'Shop customers'
        unique_together = (('id', 'shop'),)


class DevicesSessions(models.Model):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey('Users', models.DB_CASCADE)
    device_id = models.UUIDField()
    device_name = models.CharField(max_length=120, blank=True, null=True)
    refresh_token_hash = models.TextField()
    fcm_token = models.TextField(blank=True, null=True)
    last_seen = models.DateTimeField()
    created_at = models.DateTimeField()
    revoked_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'devices_sessions'
        verbose_name = 'App login session'
        verbose_name_plural = 'App login sessions'


class Disputes(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    ledger_event = models.ForeignKey('LedgerEvents', models.DO_NOTHING)
    raised_by = models.ForeignKey('Users', models.DO_NOTHING, db_column='raised_by', blank=True, null=True)
    reason_code = models.CharField(max_length=40)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=16)
    resolution_event = models.ForeignKey('LedgerEvents', models.DO_NOTHING, related_name='disputes_resolution_event_set', blank=True, null=True)
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'disputes'
        verbose_name = 'Dispute'
        verbose_name_plural = 'Disputes'


class EvidenceFiles(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    ledger_event = models.ForeignKey('LedgerEvents', models.DO_NOTHING, blank=True, null=True)
    object_key = models.TextField()
    file_type = models.CharField(max_length=40)
    size_bytes = models.BigIntegerField(blank=True, null=True)
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey('Users', models.DO_NOTHING, db_column='uploaded_by', blank=True, null=True)
    uploaded_at = models.DateTimeField()
    scan_status = models.CharField(max_length=12)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'evidence_files'
        verbose_name = 'Evidence file'
        verbose_name_plural = 'Evidence files'


class GatewayWebhookEvents(models.Model):
    id = models.UUIDField(primary_key=True)
    gateway = models.CharField(max_length=20)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=60)
    signature_valid = models.BooleanField()
    payload = models.JSONField()
    received_at = models.DateTimeField()
    processed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'gateway_webhook_events'
        verbose_name = 'Gateway webhook event'
        verbose_name_plural = 'Gateway webhook events'
        unique_together = (('gateway', 'event_id'),)


class LedgerEvents(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    customer = models.ForeignKey(Customers, models.DO_NOTHING)
    type = models.CharField(max_length=12)
    amount_paise = models.BigIntegerField()
    delta_paise = models.BigIntegerField()
    occurred_at = models.DateTimeField()
    client_created_at = models.DateTimeField(blank=True, null=True)
    server_created_at = models.DateTimeField()
    created_by = models.ForeignKey('Users', models.DO_NOTHING, db_column='created_by', blank=True, null=True)
    device_id = models.UUIDField(blank=True, null=True)
    idempotency_key = models.CharField(max_length=120)
    note = models.TextField(blank=True, null=True)
    payment_method = models.CharField(max_length=10, blank=True, null=True)
    payment_reference = models.CharField(max_length=120, blank=True, null=True)
    sale_id = models.UUIDField(unique=True, blank=True, null=True)
    reversal_of = models.OneToOneField('self', models.DO_NOTHING, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    confirmation_status = models.CharField(max_length=24)
    evidence_note = models.TextField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'ledger_events'
        verbose_name = 'Ledger entry'
        verbose_name_plural = 'Ledger entries (khata)'
        unique_together = (('shop', 'idempotency_key'),)


class MessageJobs(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    customer = models.ForeignKey(Customers, models.DO_NOTHING, blank=True, null=True)
    ledger_event = models.ForeignKey(LedgerEvents, models.DO_NOTHING, blank=True, null=True)
    channel = models.CharField(max_length=12)
    template_id = models.CharField(max_length=80, blank=True, null=True)
    status = models.CharField(max_length=12)
    provider_ref = models.CharField(max_length=160, blank=True, null=True)
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'message_jobs'
        verbose_name = 'Message job'
        verbose_name_plural = 'Message jobs'
        unique_together = (('shop', 'idempotency_key'),)


class OtpChallenges(models.Model):
    id = models.UUIDField(primary_key=True)
    mobile_e164 = models.CharField(max_length=16)
    purpose = models.CharField(max_length=20)
    code_hash = models.TextField()
    attempts = models.SmallIntegerField()
    max_attempts = models.SmallIntegerField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'otp_challenges'
        verbose_name = 'Mobile OTP challenge'
        verbose_name_plural = 'Mobile OTP challenges'


class PaymentCustomers(models.Model):
    pk = models.CompositePrimaryKey('shop_id', 'gateway')
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    gateway = models.CharField(max_length=20)
    gateway_customer_id = models.CharField(max_length=80)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'payment_customers'
        verbose_name = 'Payment customer'
        verbose_name_plural = 'Payment customers'


class PaymentMandates(models.Model):
    id = models.UUIDField(primary_key=True)
    subscription = models.ForeignKey('Subscriptions', models.DO_NOTHING)
    gateway_mandate_id = models.CharField(unique=True, max_length=80, blank=True, null=True)
    method = models.CharField(max_length=20)
    status = models.CharField(max_length=12)
    consent_at = models.DateTimeField()
    revoked_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'payment_mandates'
        verbose_name = 'Payment mandate'
        verbose_name_plural = 'Payment mandates'


class PaymentOrders(models.Model):
    id = models.UUIDField(primary_key=True)
    subscription = models.ForeignKey('Subscriptions', models.DO_NOTHING)
    gateway = models.CharField(max_length=20)
    gateway_order_id = models.CharField(unique=True, max_length=80)
    amount_paise = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=12)
    idempotency_key = models.CharField(unique=True, max_length=120)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'payment_orders'
        verbose_name = 'Payment order'
        verbose_name_plural = 'Payment orders'


class Payments(models.Model):
    id = models.UUIDField(primary_key=True)
    order = models.ForeignKey(PaymentOrders, models.DO_NOTHING)
    gateway_payment_id = models.CharField(unique=True, max_length=80)
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=12)
    method = models.CharField(max_length=20, blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    failure_code = models.CharField(max_length=80, blank=True, null=True)
    gateway_fee_paise = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'payments'
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'


class SaleItems(models.Model):
    id = models.UUIDField(primary_key=True)
    sale = models.ForeignKey('Sales', models.DO_NOTHING)
    item_name = models.CharField(max_length=200)
    quantity_milli = models.BigIntegerField()
    unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price_paise = models.BigIntegerField()
    discount_paise = models.BigIntegerField()
    line_total_paise = models.BigIntegerField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sale_items'
        verbose_name = 'Sale item'
        verbose_name_plural = 'Sale items'


class SaleLedgerLinks(models.Model):
    pk = models.CompositePrimaryKey('sale_id', 'ledger_transaction_id')
    sale = models.OneToOneField('Sales', models.DO_NOTHING)
    ledger_transaction = models.OneToOneField(LedgerEvents, models.DO_NOTHING)
    idempotency_key = models.CharField(max_length=120)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sale_ledger_links'
        verbose_name = 'Sale-to-ledger link'
        verbose_name_plural = 'Sale-to-ledger links'


class SalePayments(models.Model):
    id = models.UUIDField(primary_key=True)
    sale = models.ForeignKey('Sales', models.DO_NOTHING)
    payment_method = models.CharField(max_length=10)
    amount_paise = models.BigIntegerField()
    reference = models.CharField(max_length=120, blank=True, null=True)
    paid_at = models.DateTimeField()
    status = models.CharField(max_length=10)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sale_payments'
        verbose_name = 'Sale payment'
        verbose_name_plural = 'Sale payments'


class SaleReturns(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    sale = models.ForeignKey('Sales', models.DO_NOTHING)
    return_paise = models.BigIntegerField()
    reason = models.TextField(blank=True, null=True)
    refund_method = models.CharField(max_length=10)
    returned_at = models.DateTimeField()
    actor = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    idempotency_key = models.CharField(max_length=120)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sale_returns'
        verbose_name = 'Sale return'
        verbose_name_plural = 'Sale returns'
        unique_together = (('shop', 'idempotency_key'),)


class Sales(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    sale_number = models.CharField(max_length=40)
    customer = models.ForeignKey(Customers, models.DO_NOTHING, blank=True, null=True)
    sale_type = models.CharField(max_length=10)
    sale_at = models.DateTimeField()
    gross_paise = models.BigIntegerField()
    discount_paise = models.BigIntegerField()
    note = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=12)
    created_by = models.ForeignKey('Users', models.DO_NOTHING, db_column='created_by', blank=True, null=True)
    device_id = models.UUIDField(blank=True, null=True)
    idempotency_key = models.CharField(max_length=120)
    server_created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sales'
        verbose_name = 'Sale'
        verbose_name_plural = 'Sales'
        unique_together = (('id', 'shop'), ('shop', 'idempotency_key'),)


class SchemaMigrations(models.Model):
    version = models.IntegerField(primary_key=True)
    applied_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'schema_migrations'
        verbose_name = 'Schema version'
        verbose_name_plural = 'Schema versions'


class ShopCustomerLinks(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey('Shops', models.DO_NOTHING)
    customer = models.ForeignKey(Customers, models.DO_NOTHING)
    user = models.ForeignKey('Users', models.DO_NOTHING)
    method = models.CharField(max_length=20)
    link_status = models.CharField(max_length=20)
    consent_at = models.DateTimeField(blank=True, null=True)
    linked_by = models.ForeignKey('Users', models.DO_NOTHING, db_column='linked_by', related_name='shopcustomerlinks_linked_by_set', blank=True, null=True)
    unlinked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'shop_customer_links'
        verbose_name = 'Customer link request'
        verbose_name_plural = 'Customer link requests'
        unique_together = (('shop', 'customer', 'user'),)


class ShopMembers(models.Model):
    pk = models.CompositePrimaryKey('shop_id', 'user_id')
    shop = models.ForeignKey('Shops', models.DB_CASCADE)
    user = models.ForeignKey('Users', models.DB_CASCADE)
    role = models.CharField(max_length=20)
    permissions = models.JSONField()
    status = models.CharField(max_length=20)
    invited_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'shop_members'
        verbose_name = 'Shop member'
        verbose_name_plural = 'Shop members'


class Shops(models.Model):
    id = models.UUIDField(primary_key=True)
    owner_user = models.ForeignKey('Users', models.DO_NOTHING)
    shop_id_code = models.CharField(unique=True, max_length=12)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=60, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    timezone = models.CharField(max_length=40)
    language = models.CharField(max_length=5)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'shops'
        verbose_name = 'Shop'
        verbose_name_plural = 'Shops'


class SignatureEvidence(models.Model):
    id = models.UUIDField(primary_key=True)
    confirmation_event = models.ForeignKey(ConfirmationEvents, models.DO_NOTHING)
    object_key = models.TextField()
    file_hash = models.CharField(max_length=64)
    captured_at = models.DateTimeField()
    device_metadata = models.JSONField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'signature_evidence'
        verbose_name = 'Signature evidence'
        verbose_name_plural = 'Signature evidence'


class SubscriptionAuditEvents(models.Model):
    id = models.UUIDField(primary_key=True)
    subscription = models.ForeignKey('Subscriptions', models.DO_NOTHING)
    actor = models.CharField(max_length=80)
    event_type = models.CharField(max_length=60)
    old_state = models.CharField(max_length=16, blank=True, null=True)
    new_state = models.CharField(max_length=16, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'subscription_audit_events'
        verbose_name = 'Subscription audit event'
        verbose_name_plural = 'Subscription audit events'


class SubscriptionInvoices(models.Model):
    id = models.UUIDField(primary_key=True)
    subscription = models.ForeignKey('Subscriptions', models.DO_NOTHING)
    payment = models.OneToOneField(Payments, models.DO_NOTHING, blank=True, null=True)
    invoice_number = models.CharField(unique=True, max_length=30)
    amount_paise = models.BigIntegerField()
    tax_amount_paise = models.BigIntegerField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=10)
    file_ref = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'subscription_invoices'
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'


class SubscriptionPlans(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.CharField(unique=True, max_length=40)
    name = models.CharField(max_length=80)
    amount_paise = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    billing_interval = models.CharField(max_length=10)
    trial_months = models.SmallIntegerField()
    grace_days = models.SmallIntegerField()
    active = models.BooleanField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'subscription_plans'
        verbose_name = 'Subscription plan'
        verbose_name_plural = 'Subscription plans'


class Subscriptions(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.OneToOneField(Shops, models.DO_NOTHING)
    plan = models.ForeignKey(SubscriptionPlans, models.DO_NOTHING)
    status = models.CharField(max_length=16)
    trial_started_at = models.DateTimeField(blank=True, null=True)
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    grace_ends_at = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'subscriptions'
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'


class SupportCases(models.Model):
    id = models.UUIDField(primary_key=True)
    account = models.ForeignKey('Users', models.DO_NOTHING, blank=True, null=True)
    issue_type = models.CharField(max_length=40)
    status = models.CharField(max_length=12)
    assigned_to = models.ForeignKey('Users', models.DO_NOTHING, db_column='assigned_to', related_name='supportcases_assigned_to_set', blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'support_cases'
        verbose_name = 'Support case'
        verbose_name_plural = 'Support cases'


class SyncCursors(models.Model):
    id = models.UUIDField(primary_key=True)
    shop = models.ForeignKey(Shops, models.DO_NOTHING)
    device_id = models.UUIDField()
    last_server_cursor = models.BigIntegerField()
    last_sync_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sync_cursors'
        verbose_name = 'Sync cursor'
        verbose_name_plural = 'Sync cursors'
        unique_together = (('shop', 'device_id'),)


class SyncReceipts(models.Model):
    pk = models.CompositePrimaryKey('shop_id', 'idempotency_key')
    shop = models.ForeignKey(Shops, models.DO_NOTHING)
    idempotency_key = models.CharField(max_length=120)
    entity = models.CharField(max_length=30)
    status = models.CharField(max_length=12)
    server_id = models.UUIDField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    device_id = models.UUIDField(blank=True, null=True)
    processed_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'sync_receipts'
        verbose_name = 'Sync receipt'
        verbose_name_plural = 'Sync receipts'


class TransactionItems(models.Model):
    id = models.UUIDField(primary_key=True)
    ledger_event = models.ForeignKey(LedgerEvents, models.DO_NOTHING)
    item_name = models.CharField(max_length=200)
    quantity_milli = models.BigIntegerField()
    unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price_paise = models.BigIntegerField()
    line_total_paise = models.BigIntegerField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'transaction_items'
        verbose_name = 'Ledger line item'
        verbose_name_plural = 'Ledger line items'


class TrialGrants(models.Model):
    user = models.OneToOneField('Users', models.DO_NOTHING, primary_key=True)
    shop = models.ForeignKey(Shops, models.DO_NOTHING)
    granted_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'trial_grants'
        verbose_name = 'Trial grant'
        verbose_name_plural = 'Trial grants'


class UserRoles(models.Model):
    pk = models.CompositePrimaryKey('user_id', 'role')
    user = models.ForeignKey('Users', models.DB_CASCADE)
    role = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'user_roles'
        verbose_name = 'App user role'
        verbose_name_plural = 'App user roles'


class Users(models.Model):
    id = models.UUIDField(primary_key=True)
    mobile_e164 = models.CharField(unique=True, max_length=16)
    email = models.TextField(blank=True, null=True)  # This field type is a guess.
    password_hash = models.TextField()
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20)
    preferred_language = models.CharField(max_length=5)
    mobile_verified_at = models.DateTimeField(blank=True, null=True)
    accepted_terms_version = models.CharField(max_length=20, blank=True, null=True)
    accepted_terms_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return _label(self)

    class Meta:
        managed = False
        db_table = 'users'
        verbose_name = 'App user'
        verbose_name_plural = 'App users (mobile app)'
