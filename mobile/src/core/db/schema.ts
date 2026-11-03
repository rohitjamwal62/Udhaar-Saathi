// Local SQLite schema (offline-first). Money = integer paise, ids = UUIDs.
// Posted financial rows are never updated or deleted; corrections are new rows.
export const SCHEMA_VERSION = 1;

export const MIGRATIONS: Record<number, string> = {
  1: `
  CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

  CREATE TABLE IF NOT EXISTS shop (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    address TEXT,
    owner_name TEXT,
    owner_mobile TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    language TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL,
    sync_status TEXT NOT NULL DEFAULT 'pending'
  );

  CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mobile TEXT,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sync_status TEXT NOT NULL DEFAULT 'pending'
  );
  CREATE INDEX IF NOT EXISTS idx_customers_mobile ON customers(mobile);

  -- delta_paise is signed: credit/opening +, payment -, reversal = -(original delta).
  -- Balance = SUM(delta_paise), which makes reconciliation trivial.
  CREATE TABLE IF NOT EXISTS ledger_events (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    type TEXT NOT NULL CHECK (type IN ('opening','credit','payment','adjustment','reversal')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
    delta_paise INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT,
    payment_method TEXT,
    payment_reference TEXT,
    sale_id TEXT,
    reversal_of_id TEXT REFERENCES ledger_events(id),
    reason TEXT,
    confirmation_status TEXT NOT NULL DEFAULT 'shopkeeper_recorded',
    evidence_uri TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    sync_status TEXT NOT NULL DEFAULT 'pending'
  );
  CREATE INDEX IF NOT EXISTS idx_ledger_customer ON ledger_events(customer_id, occurred_at);
  CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_reversal ON ledger_events(reversal_of_id) WHERE reversal_of_id IS NOT NULL;
  CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_sale ON ledger_events(sale_id) WHERE sale_id IS NOT NULL AND type = 'credit';

  CREATE TABLE IF NOT EXISTS ledger_items (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES ledger_events(id),
    item_name TEXT NOT NULL,
    quantity_milli INTEGER NOT NULL,
    unit TEXT,
    unit_price_paise INTEGER NOT NULL,
    line_total_paise INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS sales (
    id TEXT PRIMARY KEY,
    sale_number TEXT NOT NULL,
    customer_id TEXT REFERENCES customers(id),
    sale_type TEXT NOT NULL CHECK (sale_type IN ('quick','itemized')),
    sale_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    gross_paise INTEGER NOT NULL CHECK (gross_paise >= 0),
    discount_paise INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    sync_status TEXT NOT NULL DEFAULT 'pending'
  );
  CREATE INDEX IF NOT EXISTS idx_sales_at ON sales(sale_at);

  CREATE TABLE IF NOT EXISTS sale_items (
    id TEXT PRIMARY KEY,
    sale_id TEXT NOT NULL REFERENCES sales(id),
    item_name TEXT NOT NULL,
    quantity_milli INTEGER NOT NULL,
    unit TEXT,
    unit_price_paise INTEGER NOT NULL,
    discount_paise INTEGER NOT NULL DEFAULT 0,
    line_total_paise INTEGER NOT NULL
  );

  -- method 'credit' is the portion put on the customer's khata; it is NOT a collection.
  CREATE TABLE IF NOT EXISTS sale_payments (
    id TEXT PRIMARY KEY,
    sale_id TEXT NOT NULL REFERENCES sales(id),
    method TEXT NOT NULL CHECK (method IN ('cash','upi','card','bank','other','credit')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    reference TEXT,
    paid_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS sale_returns (
    id TEXT PRIMARY KEY,
    sale_id TEXT NOT NULL REFERENCES sales(id),
    return_paise INTEGER NOT NULL CHECK (return_paise > 0),
    reason TEXT,
    refund_method TEXT NOT NULL CHECK (refund_method IN ('cash','upi','card','bank','other','khata')),
    returned_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    sync_status TEXT NOT NULL DEFAULT 'pending'
  );

  -- Durable outbox: a row is removed only after the server acknowledgement is stored.
  CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    op TEXT NOT NULL,
    payload TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','failed','conflict')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_outbox_seq ON outbox(seq);
  `,
};
