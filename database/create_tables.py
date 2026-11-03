#!/usr/bin/env python3
"""
UdhaarSaathi - create the complete PostgreSQL schema in ONE file.

Usage (from this folder):
    pip install psycopg2-binary
    python create_tables.py            # create database (if missing) + all tables
    python create_tables.py --check    # only verify that every table exists
    python create_tables.py --reset    # DROP everything and recreate (asks to confirm)

Connection settings come from environment variables or a `.env` file next to this script:
    PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
Nothing secret is stored in this file.

Design rules (from the blueprint):
  * UUID primary keys, UTC timestamptz, money as integer paise (BIGINT), never floats.
  * Every shop-owned row carries shop_id (tenant isolation).
  * ledger_events / sale_returns / audit_logs are append-only: UPDATE and DELETE are blocked
    by triggers, so corrections must be new reversal/adjustment rows.
  * (shop_id, idempotency_key) unique constraints make offline sync retry-safe.
  * Running this script twice is safe (everything is IF NOT EXISTS / upsert).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:  # pragma: no cover
    sys.exit("psycopg2 is missing. Run:  pip install psycopg2-binary")

SCHEMA_VERSION = 1


def load_env() -> dict:
    """Read .env (if present) without overriding real environment variables."""
    env_file = Path(__file__).with_name(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return parse_database_url(url)
    if os.environ.get("USE_LOCAL_DB") != "1":
        sys.exit("DATABASE_URL is not set. Put your Neon connection string in database/.env "
                 "(DATABASE_URL=postgresql://...). Local PostgreSQL is only used when USE_LOCAL_DB=1.")
    cfg = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": os.environ.get("PGDATABASE", "udhaar_saathi"),
        "extra": {},
        "hosted": False,
    }
    return cfg


def parse_database_url(url: str) -> dict:
    """postgresql://user:pass@host/dbname?sslmode=require  (what Neon and other hosts give you)."""
    from urllib.parse import parse_qsl, unquote, urlparse

    u = urlparse(url)
    if u.scheme not in ("postgres", "postgresql") or not u.hostname:
        sys.exit("DATABASE_URL must look like postgresql://user:password@host/dbname?sslmode=require")
    extra = {k: v for k, v in parse_qsl(u.query) if k in ("sslmode", "channel_binding", "sslrootcert", "options")}
    extra.setdefault("sslmode", "require")  # hosted databases must use TLS
    return {
        "host": u.hostname,
        "port": u.port or 5432,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "dbname": (u.path or "/").lstrip("/") or "postgres",
        "extra": extra,
        "hosted": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA_SQL = r"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================ ACCOUNTS & AUTH ===============================
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mobile_e164         VARCHAR(16)  NOT NULL UNIQUE CHECK (mobile_e164 ~ '^\+[1-9][0-9]{7,14}$'),
    email               CITEXT,
    password_hash       TEXT         NOT NULL,          -- Argon2id/PBKDF2 hash, never plaintext
    name                VARCHAR(120) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','active','suspended','deleted')),
    preferred_language  VARCHAR(5)   NOT NULL DEFAULT 'en' CHECK (preferred_language IN ('en','hi','pa')),
    mobile_verified_at  TIMESTAMPTZ,
    accepted_terms_version VARCHAR(20),
    accepted_terms_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role     VARCHAR(20) NOT NULL CHECK (role IN ('shopkeeper','customer','platform_admin','support')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role)
);

-- OTP is stored only as a hash; raw OTP is never persisted or logged.
CREATE TABLE IF NOT EXISTS otp_challenges (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mobile_e164   VARCHAR(16) NOT NULL,
    purpose       VARCHAR(20) NOT NULL CHECK (purpose IN ('signup','login','recovery','confirmation')),
    code_hash     TEXT        NOT NULL,
    attempts      SMALLINT    NOT NULL DEFAULT 0,
    max_attempts  SMALLINT    NOT NULL DEFAULT 5,
    expires_at    TIMESTAMPTZ NOT NULL,
    consumed_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_otp_mobile_created ON otp_challenges(mobile_e164, created_at DESC);

CREATE TABLE IF NOT EXISTS devices_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id           UUID NOT NULL,
    device_name         VARCHAR(120),
    refresh_token_hash  TEXT NOT NULL,
    fcm_token           TEXT,
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON devices_sessions(user_id) WHERE revoked_at IS NULL;

-- ================================= SHOPS ====================================
CREATE TABLE IF NOT EXISTS shops (
    id              UUID PRIMARY KEY,                 -- client generated (offline-first), validated server side
    owner_user_id   UUID NOT NULL REFERENCES users(id),
    shop_id_code    VARCHAR(12) NOT NULL UNIQUE DEFAULT upper(substr(replace(gen_random_uuid()::text,'-',''),1,8)),
    name            VARCHAR(160) NOT NULL,
    category        VARCHAR(60),
    address         TEXT,
    timezone        VARCHAR(40) NOT NULL DEFAULT 'Asia/Kolkata',
    language        VARCHAR(5)  NOT NULL DEFAULT 'en',
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shops_owner ON shops(owner_user_id);

CREATE TABLE IF NOT EXISTS shop_members (
    shop_id     UUID NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('owner','staff')),
    permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      VARCHAR(20) NOT NULL DEFAULT 'invited' CHECK (status IN ('invited','active','removed')),
    invited_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (shop_id, user_id)
);

-- ============================== CUSTOMERS ===================================
CREATE TABLE IF NOT EXISTS customers (
    id              UUID PRIMARY KEY,
    shop_id         UUID NOT NULL REFERENCES shops(id),
    linked_user_id  UUID REFERENCES users(id),        -- set only after customer authenticates and consents
    name            VARCHAR(160) NOT NULL,
    mobile_e164     VARCHAR(16),
    notes           TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, shop_id)
);
CREATE INDEX IF NOT EXISTS idx_customers_shop ON customers(shop_id, status);
CREATE INDEX IF NOT EXISTS idx_customers_mobile ON customers(shop_id, mobile_e164);

-- A phone-number match alone never links data; the customer must approve.
CREATE TABLE IF NOT EXISTS shop_customer_links (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id     UUID NOT NULL REFERENCES shops(id),
    customer_id UUID NOT NULL REFERENCES customers(id),
    user_id     UUID NOT NULL REFERENCES users(id),
    method      VARCHAR(20) NOT NULL CHECK (method IN ('qr','shop_id','invite','mobile_match')),
    link_status VARCHAR(20) NOT NULL DEFAULT 'requested'
                CHECK (link_status IN ('requested','approved','rejected','unlinked')),
    consent_at  TIMESTAMPTZ,
    linked_by   UUID REFERENCES users(id),
    unlinked_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shop_id, customer_id, user_id)
);

-- ================================ LEDGER ====================================
CREATE TABLE IF NOT EXISTS ledger_events (
    id                  UUID PRIMARY KEY,
    shop_id             UUID NOT NULL REFERENCES shops(id),
    customer_id         UUID NOT NULL,
    type                VARCHAR(12) NOT NULL CHECK (type IN ('opening','credit','payment','adjustment','reversal')),
    amount_paise        BIGINT NOT NULL CHECK (amount_paise >= 0),
    delta_paise         BIGINT NOT NULL,                -- signed effect on customer balance
    occurred_at         TIMESTAMPTZ NOT NULL,
    client_created_at   TIMESTAMPTZ,
    server_created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          UUID REFERENCES users(id),
    device_id           UUID,
    idempotency_key     VARCHAR(120) NOT NULL,
    note                TEXT,
    payment_method      VARCHAR(10) CHECK (payment_method IN ('cash','upi','card','bank','other')),
    payment_reference   VARCHAR(120),
    sale_id             UUID,                           -- shared id with sales for credit sales
    reversal_of_id      UUID REFERENCES ledger_events(id),
    reason              TEXT,
    -- Only the server may move this beyond 'shopkeeper_recorded' (customer evidence required).
    confirmation_status VARCHAR(24) NOT NULL DEFAULT 'shopkeeper_recorded'
                        CHECK (confirmation_status IN ('shopkeeper_recorded','awaiting_confirmation',
                                                       'customer_confirmed','disputed','expired')),
    evidence_note       TEXT,
    FOREIGN KEY (customer_id, shop_id) REFERENCES customers(id, shop_id),
    UNIQUE (shop_id, idempotency_key),
    CHECK (type <> 'reversal' OR (reversal_of_id IS NOT NULL AND reason IS NOT NULL)),
    CHECK (type NOT IN ('credit','opening') OR delta_paise = amount_paise),
    CHECK (type <> 'payment' OR delta_paise = -amount_paise)
);
CREATE INDEX IF NOT EXISTS idx_ledger_customer ON ledger_events(shop_id, customer_id, occurred_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_one_reversal ON ledger_events(reversal_of_id) WHERE reversal_of_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_one_credit_per_sale ON ledger_events(sale_id) WHERE sale_id IS NOT NULL AND type = 'credit';

CREATE TABLE IF NOT EXISTS transaction_items (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_event_id  UUID NOT NULL REFERENCES ledger_events(id),
    item_name        VARCHAR(200) NOT NULL,
    quantity_milli   BIGINT NOT NULL CHECK (quantity_milli > 0),  -- 1.5 kg = 1500
    unit             VARCHAR(20),
    unit_price_paise BIGINT NOT NULL CHECK (unit_price_paise >= 0),
    line_total_paise BIGINT NOT NULL CHECK (line_total_paise >= 0),
    description      TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_event ON transaction_items(ledger_event_id);

CREATE TABLE IF NOT EXISTS evidence_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id         UUID NOT NULL REFERENCES shops(id),
    ledger_event_id UUID REFERENCES ledger_events(id),
    object_key      TEXT NOT NULL,                      -- private object storage key, never a public URL
    file_type       VARCHAR(40) NOT NULL,
    size_bytes      BIGINT CHECK (size_bytes >= 0),
    sha256          CHAR(64) NOT NULL,
    uploaded_by     UUID REFERENCES users(id),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    scan_status     VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','infected','failed'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_event ON evidence_files(ledger_event_id);

-- ======================= CONFIRMATION, SIGNATURE, DISPUTES ==================
CREATE TABLE IF NOT EXISTS confirmation_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id           UUID NOT NULL REFERENCES shops(id),
    ledger_event_id   UUID NOT NULL REFERENCES ledger_events(id),
    customer_user_id  UUID REFERENCES users(id),
    method            VARCHAR(12) NOT NULL CHECK (method IN ('otp','signature','both')),
    snapshot          JSONB NOT NULL,                   -- exact details shown to the customer
    snapshot_sha256   CHAR(64) NOT NULL,
    token_hash        TEXT NOT NULL UNIQUE,             -- link token stored hashed only
    expires_at        TIMESTAMPTZ NOT NULL,
    status            VARCHAR(12) NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','confirmed','disputed','expired','revoked')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS confirmation_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id           UUID NOT NULL REFERENCES confirmation_requests(id),
    status               VARCHAR(12) NOT NULL CHECK (status IN ('confirmed','disputed')),
    method               VARCHAR(12) NOT NULL CHECK (method IN ('otp','signature','both')),
    consent_text_version VARCHAR(20) NOT NULL,
    verified_at          TIMESTAMPTZ,
    server_timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address           INET,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS signature_evidence (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    confirmation_event_id UUID NOT NULL REFERENCES confirmation_events(id),
    object_key            TEXT NOT NULL,
    file_hash             CHAR(64) NOT NULL,
    captured_at           TIMESTAMPTZ NOT NULL,
    device_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS disputes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id             UUID NOT NULL REFERENCES shops(id),
    ledger_event_id     UUID NOT NULL REFERENCES ledger_events(id),
    raised_by           UUID REFERENCES users(id),
    reason_code         VARCHAR(40) NOT NULL,
    description         TEXT,
    status              VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open','responded','resolved','closed')),
    resolution_event_id UUID REFERENCES ledger_events(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);

-- =============================== SALES ======================================
CREATE TABLE IF NOT EXISTS sales (
    id               UUID PRIMARY KEY,
    shop_id          UUID NOT NULL REFERENCES shops(id),
    sale_number      VARCHAR(40) NOT NULL,
    customer_id      UUID,
    sale_type        VARCHAR(10) NOT NULL CHECK (sale_type IN ('quick','itemized')),
    sale_at          TIMESTAMPTZ NOT NULL,
    gross_paise      BIGINT NOT NULL CHECK (gross_paise >= 0),
    discount_paise   BIGINT NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
    note             TEXT,
    status           VARCHAR(12) NOT NULL DEFAULT 'posted' CHECK (status IN ('posted','void')),
    created_by       UUID REFERENCES users(id),
    device_id        UUID,
    idempotency_key  VARCHAR(120) NOT NULL,
    server_created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (customer_id, shop_id) REFERENCES customers(id, shop_id),
    UNIQUE (shop_id, idempotency_key),
    UNIQUE (id, shop_id),
    CHECK (discount_paise < gross_paise)
);
CREATE INDEX IF NOT EXISTS idx_sales_shop_date ON sales(shop_id, sale_at);

CREATE TABLE IF NOT EXISTS sale_items (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sale_id           UUID NOT NULL REFERENCES sales(id),
    item_name         VARCHAR(200) NOT NULL,
    quantity_milli    BIGINT NOT NULL CHECK (quantity_milli > 0),
    unit              VARCHAR(20),
    unit_price_paise  BIGINT NOT NULL CHECK (unit_price_paise >= 0),
    discount_paise    BIGINT NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
    line_total_paise  BIGINT NOT NULL CHECK (line_total_paise >= 0)
);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(sale_id);

-- method 'credit' = portion put on the customer's khata; it is NOT a collection.
CREATE TABLE IF NOT EXISTS sale_payments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sale_id        UUID NOT NULL REFERENCES sales(id),
    payment_method VARCHAR(10) NOT NULL CHECK (payment_method IN ('cash','upi','card','bank','other','credit')),
    amount_paise   BIGINT NOT NULL CHECK (amount_paise > 0),
    reference      VARCHAR(120),
    paid_at        TIMESTAMPTZ NOT NULL,
    status         VARCHAR(10) NOT NULL DEFAULT 'posted' CHECK (status IN ('posted','void'))
);
CREATE INDEX IF NOT EXISTS idx_sale_payments_sale ON sale_payments(sale_id);

CREATE TABLE IF NOT EXISTS sale_returns (
    id               UUID PRIMARY KEY,
    shop_id          UUID NOT NULL REFERENCES shops(id),
    sale_id          UUID NOT NULL REFERENCES sales(id),
    return_paise     BIGINT NOT NULL CHECK (return_paise > 0),
    reason           TEXT,
    refund_method    VARCHAR(10) NOT NULL CHECK (refund_method IN ('cash','upi','card','bank','other','khata')),
    returned_at      TIMESTAMPTZ NOT NULL,
    actor_id         UUID REFERENCES users(id),
    idempotency_key  VARCHAR(120) NOT NULL,
    UNIQUE (shop_id, idempotency_key)
);

-- Exactly-once link between a credit sale and its khata credit event.
CREATE TABLE IF NOT EXISTS sale_ledger_links (
    sale_id               UUID NOT NULL REFERENCES sales(id),
    ledger_transaction_id UUID NOT NULL REFERENCES ledger_events(id),
    idempotency_key       VARCHAR(120) NOT NULL,
    PRIMARY KEY (sale_id, ledger_transaction_id),
    UNIQUE (sale_id),
    UNIQUE (ledger_transaction_id)
);

-- ============================ OFFLINE SYNC ==================================
CREATE TABLE IF NOT EXISTS sync_cursors (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id          UUID NOT NULL REFERENCES shops(id),
    device_id        UUID NOT NULL,
    last_server_cursor BIGINT NOT NULL DEFAULT 0,
    last_sync_at     TIMESTAMPTZ,
    UNIQUE (shop_id, device_id)
);

-- Remembers the answer for every processed outbox item so retries return the same result.
CREATE TABLE IF NOT EXISTS sync_receipts (
    shop_id          UUID NOT NULL REFERENCES shops(id),
    idempotency_key  VARCHAR(120) NOT NULL,
    entity           VARCHAR(30) NOT NULL,
    status           VARCHAR(12) NOT NULL CHECK (status IN ('accepted','duplicate','conflict','rejected')),
    server_id        UUID,
    error            TEXT,
    device_id        UUID,
    processed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (shop_id, idempotency_key)
);

-- ============================ COMMUNICATIONS ================================
CREATE TABLE IF NOT EXISTS communication_consents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES users(id),
    customer_id  UUID REFERENCES customers(id),
    shop_id      UUID REFERENCES shops(id),
    channel      VARCHAR(12) NOT NULL CHECK (channel IN ('sms','email','whatsapp','push')),
    purpose      VARCHAR(16) NOT NULL CHECK (purpose IN ('transactional','reminder','marketing')),
    status       VARCHAR(12) NOT NULL CHECK (status IN ('granted','withdrawn')),
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    withdrawn_at TIMESTAMPTZ,
    evidence_ref TEXT
);

CREATE TABLE IF NOT EXISTS message_jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id          UUID NOT NULL REFERENCES shops(id),
    customer_id      UUID REFERENCES customers(id),
    ledger_event_id  UUID REFERENCES ledger_events(id),
    channel          VARCHAR(12) NOT NULL CHECK (channel IN ('sms','email','whatsapp','push')),
    template_id      VARCHAR(80),
    -- delivery is only recorded when the provider reports it; never inferred
    status           VARCHAR(12) NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','submitted','sent','delivered','failed','clicked')),
    provider_ref     VARCHAR(160),
    idempotency_key  VARCHAR(120) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shop_id, idempotency_key)
);

-- ============== SUBSCRIPTIONS & PAYMENTS (Razorpay Pay-as-you-go) ===========
CREATE TABLE IF NOT EXISTS subscription_plans (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code             VARCHAR(40) NOT NULL UNIQUE,
    name             VARCHAR(80) NOT NULL,
    amount_paise     BIGINT NOT NULL CHECK (amount_paise >= 0),
    currency         CHAR(3) NOT NULL DEFAULT 'INR',
    billing_interval VARCHAR(10) NOT NULL DEFAULT 'month' CHECK (billing_interval IN ('month')),
    trial_months     SMALLINT NOT NULL DEFAULT 3,
    grace_days       SMALLINT NOT NULL DEFAULT 7,
    active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id              UUID NOT NULL UNIQUE REFERENCES shops(id),
    plan_id              UUID NOT NULL REFERENCES subscription_plans(id),
    status               VARCHAR(16) NOT NULL DEFAULT 'TRIALING'
                         CHECK (status IN ('TRIALING','ACTIVE','PAYMENT_PENDING','PAST_DUE',
                                           'GRACE_PERIOD','CANCELED','EXPIRED','SUSPENDED')),
    trial_started_at     TIMESTAMPTZ,
    trial_ends_at        TIMESTAMPTZ,
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    grace_ends_at        TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One free trial per verified owner account: reinstalling or adding shops cannot repeat it.
CREATE TABLE IF NOT EXISTS trial_grants (
    user_id     UUID PRIMARY KEY REFERENCES users(id),
    shop_id     UUID NOT NULL REFERENCES shops(id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_customers (
    shop_id             UUID NOT NULL REFERENCES shops(id),
    gateway             VARCHAR(20) NOT NULL DEFAULT 'razorpay',
    gateway_customer_id VARCHAR(80) NOT NULL,
    PRIMARY KEY (shop_id, gateway)
);

CREATE TABLE IF NOT EXISTS payment_orders (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id   UUID NOT NULL REFERENCES subscriptions(id),
    gateway           VARCHAR(20) NOT NULL DEFAULT 'razorpay',
    gateway_order_id  VARCHAR(80) NOT NULL UNIQUE,
    amount_paise      BIGINT NOT NULL CHECK (amount_paise > 0),   -- decided by the server, not the client
    currency          CHAR(3) NOT NULL DEFAULT 'INR',
    status            VARCHAR(12) NOT NULL DEFAULT 'created' CHECK (status IN ('created','paid','failed','expired')),
    idempotency_key   VARCHAR(120) NOT NULL UNIQUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES payment_orders(id),
    gateway_payment_id  VARCHAR(80) NOT NULL UNIQUE,                -- duplicate webhooks cannot double-post
    amount_paise        BIGINT NOT NULL CHECK (amount_paise > 0),
    status              VARCHAR(12) NOT NULL CHECK (status IN ('pending','success','failed','refunded')),
    method              VARCHAR(20),
    paid_at             TIMESTAMPTZ,
    failure_code        VARCHAR(80),
    gateway_fee_paise   BIGINT,                                     -- internal cost reporting only
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_mandates (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id    UUID NOT NULL REFERENCES subscriptions(id),
    gateway_mandate_id VARCHAR(80) UNIQUE,
    method             VARCHAR(20) NOT NULL,
    status             VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','paused','revoked','failed')),
    consent_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ
);

CREATE SEQUENCE IF NOT EXISTS invoice_number_seq START 1;
CREATE TABLE IF NOT EXISTS subscription_invoices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id  UUID NOT NULL REFERENCES subscriptions(id),
    payment_id       UUID UNIQUE REFERENCES payments(id),
    invoice_number   VARCHAR(30) NOT NULL UNIQUE DEFAULT ('US-' || to_char(now(),'YYYY') || '-' || lpad(nextval('invoice_number_seq')::text, 6, '0')),
    amount_paise     BIGINT NOT NULL CHECK (amount_paise >= 0),
    tax_amount_paise BIGINT NOT NULL DEFAULT 0 CHECK (tax_amount_paise >= 0),
    period_start     TIMESTAMPTZ NOT NULL,
    period_end       TIMESTAMPTZ NOT NULL,
    status           VARCHAR(10) NOT NULL DEFAULT 'paid' CHECK (status IN ('open','paid','void','refunded')),
    file_ref         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gateway_webhook_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gateway       VARCHAR(20) NOT NULL DEFAULT 'razorpay',
    event_id      VARCHAR(120) NOT NULL,
    event_type    VARCHAR(60) NOT NULL,
    signature_valid BOOLEAN NOT NULL,
    payload       JSONB NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ,
    UNIQUE (gateway, event_id)                                       -- duplicate deliveries are ignored
);

CREATE TABLE IF NOT EXISTS subscription_audit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id),
    actor           VARCHAR(80) NOT NULL,                            -- user id, 'system' or 'webhook'
    event_type      VARCHAR(60) NOT NULL,
    old_state       VARCHAR(16),
    new_state       VARCHAR(16),
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_config (
    id                         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    latest_version             VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    minimum_supported_version  VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    force_update               BOOLEAN NOT NULL DEFAULT FALSE,
    update_message             TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================== AUDIT & SUPPORT ================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    shop_id     UUID REFERENCES shops(id),
    actor_id    UUID REFERENCES users(id),
    action      VARCHAR(60) NOT NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id   UUID,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_audit_shop_time ON audit_logs(shop_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS support_cases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID REFERENCES users(id),
    issue_type  VARCHAR(40) NOT NULL,
    status      VARCHAR(12) NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','closed')),
    assigned_to UUID REFERENCES users(id),
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- ======================= APPEND-ONLY ENFORCEMENT ============================
CREATE OR REPLACE FUNCTION forbid_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed. Post a reversal/adjustment instead.', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

-- ledger_events: only the confirmation_status / evidence_note columns may change (server-side
-- confirmation workflow); amounts, dates, owners and links are frozen.
CREATE OR REPLACE FUNCTION ledger_events_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ledger_events rows cannot be deleted. Post a reversal instead.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.id, NEW.shop_id, NEW.customer_id, NEW.type, NEW.amount_paise, NEW.delta_paise, NEW.occurred_at,
        NEW.idempotency_key, NEW.sale_id, NEW.reversal_of_id, NEW.created_by)
       IS DISTINCT FROM
       (OLD.id, OLD.shop_id, OLD.customer_id, OLD.type, OLD.amount_paise, OLD.delta_paise, OLD.occurred_at,
        OLD.idempotency_key, OLD.sale_id, OLD.reversal_of_id, OLD.created_by) THEN
        RAISE EXCEPTION 'Posted ledger events are immutable. Post a reversal or adjustment instead.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ledger_events_guard') THEN
        CREATE TRIGGER trg_ledger_events_guard BEFORE UPDATE OR DELETE ON ledger_events
            FOR EACH ROW EXECUTE FUNCTION ledger_events_guard();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_transaction_items_append_only') THEN
        CREATE TRIGGER trg_transaction_items_append_only BEFORE UPDATE OR DELETE ON transaction_items
            FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sale_returns_append_only') THEN
        CREATE TRIGGER trg_sale_returns_append_only BEFORE UPDATE OR DELETE ON sale_returns
            FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_logs_append_only') THEN
        CREATE TRIGGER trg_audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sub_audit_append_only') THEN
        CREATE TRIGGER trg_sub_audit_append_only BEFORE UPDATE OR DELETE ON subscription_audit_events
            FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
    END IF;
END $$;

-- ============================ BALANCE VIEWS =================================
-- Balance is always derivable from the ledger, so it can be reconciled at any time.
DROP VIEW IF EXISTS customer_balances;
CREATE VIEW customer_balances AS
SELECT c.shop_id,
       c.id                         AS customer_id,
       c.name,
       COALESCE(SUM(e.delta_paise), 0)::bigint AS balance_paise,
       MAX(e.occurred_at)           AS last_activity_at
FROM customers c
LEFT JOIN ledger_events e ON e.customer_id = c.id AND e.shop_id = c.shop_id
WHERE c.status = 'active'
GROUP BY c.shop_id, c.id, c.name;

-- ============================== SEED DATA ===================================
INSERT INTO subscription_plans (code, name, amount_paise, trial_months, grace_days)
VALUES ('udhaarsaathi_monthly', 'UdhaarSaathi', 4900, 3, 7)
ON CONFLICT (code) DO NOTHING;

INSERT INTO app_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
"""

EXPECTED_TABLES = [
    "schema_migrations", "users", "user_roles", "otp_challenges", "devices_sessions", "shops", "shop_members",
    "customers", "shop_customer_links", "ledger_events", "transaction_items", "evidence_files",
    "confirmation_requests", "confirmation_events", "signature_evidence", "disputes", "sales", "sale_items",
    "sale_payments", "sale_returns", "sale_ledger_links", "sync_cursors", "sync_receipts",
    "communication_consents", "message_jobs", "subscription_plans", "subscriptions", "trial_grants",
    "payment_customers", "payment_orders", "payments", "payment_mandates", "subscription_invoices",
    "gateway_webhook_events", "subscription_audit_events", "app_config", "audit_logs", "support_cases",
]

DROP_SQL = "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"


def connect(cfg: dict, dbname: str | None = None):
    try:
        return psycopg2.connect(
            host=cfg["host"], port=cfg["port"], user=cfg["user"],
            password=cfg["password"], dbname=dbname or cfg["dbname"], connect_timeout=15,
            **cfg.get("extra", {}),
        )
    except psycopg2.OperationalError as e:
        sys.exit(f"Could not connect to PostgreSQL at {cfg['host']}:{cfg['port']} "
                 f"(db '{dbname or cfg['dbname']}', user '{cfg['user']}'):\n  {str(e).strip()}")


def ensure_database(cfg: dict) -> None:
    if cfg.get("hosted"):
        # Hosted databases (Neon, ...) already exist and the login usually cannot create databases.
        print(f"Using hosted database '{cfg['dbname']}' on {cfg['host']} (not creating it).")
        return
    conn = connect(cfg, dbname="postgres")
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["dbname"],))
        if cur.fetchone():
            print(f"Database '{cfg['dbname']}' already exists.")
        else:
            cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(cfg["dbname"])))
            print(f"Created database '{cfg['dbname']}'.")
    conn.close()


def existing_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
        return {r[0] for r in cur.fetchall()}


def check(cfg: dict) -> bool:
    conn = connect(cfg)
    have = existing_tables(conn)
    missing = [t for t in EXPECTED_TABLES if t not in have]
    conn.close()
    if missing:
        print("Missing tables:", ", ".join(missing))
        return False
    print(f"OK: all {len(EXPECTED_TABLES)} tables exist in '{cfg['dbname']}'.")
    return True


def create(cfg: dict) -> None:
    ensure_database(cfg)
    conn = connect(cfg)
    try:
        with conn, conn.cursor() as cur:          # one transaction: all or nothing
            cur.execute(SCHEMA_SQL)
            cur.execute("INSERT INTO schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING", (SCHEMA_VERSION,))
    finally:
        conn.close()
    print(f"Schema version {SCHEMA_VERSION} applied.")
    check(cfg)


def main() -> None:
    cfg = load_env()
    args = set(sys.argv[1:])
    if "--check" in args:
        sys.exit(0 if check(cfg) else 1)
    if "--reset" in args:
        if input(f"This DELETES ALL DATA in '{cfg['dbname']}'. Type the database name to confirm: ") != cfg["dbname"]:
            sys.exit("Cancelled.")
        ensure_database(cfg)
        conn = connect(cfg)
        with conn, conn.cursor() as cur:
            cur.execute(DROP_SQL)
        conn.close()
        print("Dropped all objects.")
    create(cfg)


if __name__ == "__main__":
    main()
