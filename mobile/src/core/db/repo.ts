import { getDb } from './index';
import { enqueue, nextSeq } from '../sync/outbox';
import { newId, nowIso } from '../ids';
import { dayStamp, type DateRange } from '../dates';
import type {
  Customer,
  CustomerWithBalance,
  LedgerEvent,
  LedgerItem,
  LedgerRow,
  PayMethod,
  Sale,
  SaleItem,
  SaleListRow,
  SalePayMethod,
  SalePayment,
  SaleReturn,
  Shop,
} from './types';

type Db = Awaited<ReturnType<typeof getDb>>;

// ───────────────────────── Shop ─────────────────────────

export async function getShop(): Promise<Shop | null> {
  const db = await getDb();
  return db.getFirstAsync<Shop>('SELECT * FROM shop LIMIT 1');
}

export interface ShopInput {
  name: string;
  category: string;
  address: string;
  ownerName: string;
  ownerMobile: string;
  language: string;
}

export async function createShop(input: ShopInput): Promise<Shop> {
  const db = await getDb();
  const shop: Shop = {
    id: newId(),
    name: input.name.trim(),
    category: input.category.trim() || null,
    address: input.address.trim() || null,
    owner_name: input.ownerName.trim() || null,
    owner_mobile: input.ownerMobile.trim() || null,
    timezone: 'Asia/Kolkata',
    language: input.language,
    created_at: nowIso(),
    sync_status: 'pending',
  };
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      `INSERT INTO shop(id,name,category,address,owner_name,owner_mobile,timezone,language,created_at,sync_status)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
      shop.id, shop.name, shop.category, shop.address, shop.owner_name,
      shop.owner_mobile, shop.timezone, shop.language, shop.created_at, shop.sync_status,
    );
    await enqueue(db, 'shop', shop.id, 'create', shop, `shop:${shop.id}`);
  });
  return shop;
}

// ───────────────────────── Customers ─────────────────────────

export async function listCustomers(search = ''): Promise<CustomerWithBalance[]> {
  const db = await getDb();
  const q = `%${search.trim().toLowerCase()}%`;
  return db.getAllAsync<CustomerWithBalance>(
    `SELECT c.*,
            COALESCE(SUM(e.delta_paise), 0) AS balance_paise,
            MAX(e.occurred_at) AS last_activity_at
       FROM customers c
       LEFT JOIN ledger_events e ON e.customer_id = c.id
      WHERE c.archived = 0
        AND (LOWER(c.name) LIKE ? OR COALESCE(c.mobile, '') LIKE ?)
      GROUP BY c.id
      ORDER BY balance_paise DESC, c.name COLLATE NOCASE`,
    q, q,
  );
}

export async function getCustomer(id: string): Promise<CustomerWithBalance | null> {
  const db = await getDb();
  return db.getFirstAsync<CustomerWithBalance>(
    `SELECT c.*, COALESCE(SUM(e.delta_paise), 0) AS balance_paise, MAX(e.occurred_at) AS last_activity_at
       FROM customers c LEFT JOIN ledger_events e ON e.customer_id = c.id
      WHERE c.id = ? GROUP BY c.id`,
    id,
  );
}

/** Possible duplicates by phone or exact (case-insensitive) name. Never auto-merged. */
export async function findDuplicateCustomers(name: string, mobile: string): Promise<Customer[]> {
  const db = await getDb();
  const m = mobile.trim();
  return db.getAllAsync<Customer>(
    `SELECT * FROM customers WHERE archived = 0
        AND (LOWER(name) = LOWER(?) OR (? <> '' AND mobile = ?))`,
    name.trim(), m, m,
  );
}

export interface CustomerInput {
  name: string;
  mobile: string;
  notes?: string;
  openingBalancePaise?: number;
}

export async function addCustomer(input: CustomerInput): Promise<Customer> {
  const db = await getDb();
  const c: Customer = {
    id: newId(),
    name: input.name.trim(),
    mobile: input.mobile.trim() || null,
    notes: input.notes?.trim() || null,
    archived: 0,
    created_at: nowIso(),
    sync_status: 'pending',
  };
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      `INSERT INTO customers(id,name,mobile,notes,archived,created_at,sync_status) VALUES (?,?,?,?,0,?,?)`,
      c.id, c.name, c.mobile, c.notes, c.created_at, c.sync_status,
    );
    await enqueue(db, 'customer', c.id, 'create', c, `customer:${c.id}`);
    if (input.openingBalancePaise && input.openingBalancePaise > 0) {
      await insertEvent(db, {
        customerId: c.id,
        type: 'opening',
        amountPaise: input.openingBalancePaise,
        deltaPaise: input.openingBalancePaise,
        occurredAt: c.created_at,
        note: 'Opening balance (migrated from existing records)',
      });
    }
  });
  return c;
}

export async function archiveCustomer(id: string): Promise<void> {
  // Archive, never delete, so posted financial history is preserved.
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync('UPDATE customers SET archived = 1 WHERE id = ?', id);
    await enqueue(db, 'customer', id, 'archive', { id }, `customer:${id}:archive`);
  });
}

// ───────────────────────── Ledger ─────────────────────────

interface EventDraft {
  customerId: string;
  type: LedgerEvent['type'];
  amountPaise: number;
  deltaPaise: number;
  occurredAt: string;
  note?: string | null;
  paymentMethod?: PayMethod | null;
  paymentReference?: string | null;
  saleId?: string | null;
  reversalOfId?: string | null;
  reason?: string | null;
  evidenceUri?: string | null;
  idempotencyKey?: string;
  items?: Omit<LedgerItem, 'id' | 'event_id'>[];
}

/** Must run inside a transaction. Writes the event, its items and its outbox entry together. */
async function insertEvent(db: Db, d: EventDraft): Promise<LedgerEvent> {
  const ev: LedgerEvent = {
    id: newId(),
    customer_id: d.customerId,
    type: d.type,
    amount_paise: d.amountPaise,
    delta_paise: d.deltaPaise,
    occurred_at: d.occurredAt,
    created_at: nowIso(),
    note: d.note ?? null,
    payment_method: d.paymentMethod ?? null,
    payment_reference: d.paymentReference ?? null,
    sale_id: d.saleId ?? null,
    reversal_of_id: d.reversalOfId ?? null,
    reason: d.reason ?? null,
    // A shopkeeper-created entry is never "confirmed"; only the server can set that.
    confirmation_status: 'shopkeeper_recorded',
    evidence_uri: d.evidenceUri ?? null,
    idempotency_key: d.idempotencyKey ?? `ledger:${newId()}`,
    sync_status: 'pending',
  };
  await db.runAsync(
    `INSERT INTO ledger_events(id,customer_id,type,amount_paise,delta_paise,occurred_at,created_at,note,
       payment_method,payment_reference,sale_id,reversal_of_id,reason,confirmation_status,evidence_uri,
       idempotency_key,sync_status)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    ev.id, ev.customer_id, ev.type, ev.amount_paise, ev.delta_paise, ev.occurred_at, ev.created_at,
    ev.note, ev.payment_method, ev.payment_reference, ev.sale_id, ev.reversal_of_id, ev.reason,
    ev.confirmation_status, ev.evidence_uri, ev.idempotency_key, ev.sync_status,
  );
  const items: LedgerItem[] = (d.items ?? []).map((i) => ({ ...i, id: newId(), event_id: ev.id }));
  for (const it of items) {
    await db.runAsync(
      `INSERT INTO ledger_items(id,event_id,item_name,quantity_milli,unit,unit_price_paise,line_total_paise)
       VALUES (?,?,?,?,?,?,?)`,
      it.id, it.event_id, it.item_name, it.quantity_milli, it.unit, it.unit_price_paise, it.line_total_paise,
    );
  }
  await enqueue(db, 'ledger_event', ev.id, 'post', { ...ev, items }, ev.idempotency_key);
  return ev;
}

export interface CreditInput {
  customerId: string;
  occurredAt: string;
  items: Omit<LedgerItem, 'id' | 'event_id'>[]; // empty => total-only entry
  totalPaise: number;
  paidNowPaise: number;
  paidNowMethod: PayMethod;
  note: string;
  evidenceUri: string | null;
}

export async function addCredit(input: CreditInput): Promise<void> {
  if (input.totalPaise <= 0) throw new Error('Amount must be greater than zero');
  if (input.items.length) {
    const sum = input.items.reduce((s, i) => s + i.line_total_paise, 0);
    if (sum !== input.totalPaise) throw new Error('Item totals do not match the bill total');
  }
  if (input.paidNowPaise < 0 || input.paidNowPaise > input.totalPaise) {
    throw new Error('Paid-now amount must be between zero and the total');
  }
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await insertEvent(db, {
      customerId: input.customerId,
      type: 'credit',
      amountPaise: input.totalPaise,
      deltaPaise: input.totalPaise,
      occurredAt: input.occurredAt,
      note: input.note || (input.items.length ? null : 'Non-itemized entry'),
      evidenceUri: input.evidenceUri,
      items: input.items,
    });
    if (input.paidNowPaise > 0) {
      await insertEvent(db, {
        customerId: input.customerId,
        type: 'payment',
        amountPaise: input.paidNowPaise,
        deltaPaise: -input.paidNowPaise,
        occurredAt: input.occurredAt,
        note: 'Paid at time of purchase',
        paymentMethod: input.paidNowMethod,
      });
    }
  });
}

export interface PaymentInput {
  customerId: string;
  amountPaise: number;
  occurredAt: string;
  method: PayMethod;
  reference: string;
  note: string;
}

export async function addPayment(input: PaymentInput): Promise<void> {
  if (input.amountPaise <= 0) throw new Error('Amount must be greater than zero');
  const db = await getDb();
  const cust = await getCustomer(input.customerId);
  if (!cust) throw new Error('Customer not found');
  // Overpayment would create an advance balance, which V1 does not support yet.
  if (input.amountPaise > cust.balance_paise) {
    throw new Error('Payment is more than the outstanding balance');
  }
  await db.withTransactionAsync(async () => {
    await insertEvent(db, {
      customerId: input.customerId,
      type: 'payment',
      amountPaise: input.amountPaise,
      deltaPaise: -input.amountPaise,
      occurredAt: input.occurredAt,
      note: input.note || null,
      paymentMethod: input.method,
      paymentReference: input.reference || null,
    });
  });
}

/** Correct a posted event by posting a reversal. The original row is left untouched. */
export async function reverseEvent(eventId: string, reason: string): Promise<void> {
  if (!reason.trim()) throw new Error('A reason is required');
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    const orig = await db.getFirstAsync<LedgerEvent>('SELECT * FROM ledger_events WHERE id = ?', eventId);
    if (!orig) throw new Error('Entry not found');
    if (orig.type === 'reversal') throw new Error('A reversal cannot be reversed');
    const already = await db.getFirstAsync<{ id: string }>(
      'SELECT id FROM ledger_events WHERE reversal_of_id = ?', eventId);
    if (already) throw new Error('This entry has already been reversed');
    await insertEvent(db, {
      customerId: orig.customer_id,
      type: 'reversal',
      amountPaise: orig.amount_paise,
      deltaPaise: -orig.delta_paise,
      occurredAt: nowIso(),
      reversalOfId: orig.id,
      reason: reason.trim(),
      idempotencyKey: `reversal:${orig.id}`,
    });
  });
}

export async function getLedger(customerId: string): Promise<LedgerRow[]> {
  const db = await getDb();
  const events = await db.getAllAsync<LedgerEvent>(
    'SELECT * FROM ledger_events WHERE customer_id = ? ORDER BY occurred_at, created_at', customerId);
  const items = await db.getAllAsync<LedgerItem>(
    `SELECT i.* FROM ledger_items i JOIN ledger_events e ON e.id = i.event_id WHERE e.customer_id = ?`,
    customerId);
  const reversed = new Set(events.filter((e) => e.reversal_of_id).map((e) => e.reversal_of_id));
  let running = 0;
  return events.map((e) => {
    running += e.delta_paise;
    return {
      ...e,
      running_balance_paise: running,
      items: items.filter((i) => i.event_id === e.id),
      reversed: reversed.has(e.id),
    };
  });
}

/**
 * Reconciliation: every event's delta must match its type/amount rules, and reversals
 * must exactly negate their original. Returns human-readable mismatches (empty = OK).
 */
export async function reconcileLedger(): Promise<string[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<LedgerEvent>('SELECT * FROM ledger_events');
  const byId = new Map(rows.map((r) => [r.id, r]));
  const problems: string[] = [];
  for (const r of rows) {
    if (r.type === 'credit' || r.type === 'opening') {
      if (r.delta_paise !== r.amount_paise) problems.push(`${r.id}: ${r.type} delta mismatch`);
    } else if (r.type === 'payment') {
      if (r.delta_paise !== -r.amount_paise) problems.push(`${r.id}: payment delta mismatch`);
    } else if (r.type === 'reversal') {
      const o = r.reversal_of_id ? byId.get(r.reversal_of_id) : undefined;
      if (!o || o.delta_paise !== -r.delta_paise) problems.push(`${r.id}: reversal mismatch`);
    }
  }
  return problems;
}

// ───────────────────────── Sales ─────────────────────────

export interface SaleItemInput {
  itemName: string;
  quantityMilli: number;
  unit: string;
  unitPricePaise: number;
  discountPaise: number;
  lineTotalPaise: number; // qty*price - item discount
  lineGrossPaise: number; // qty*price
}

export interface SaleInput {
  customerId: string | null;
  saleAt: string;
  items: SaleItemInput[]; // empty => quick sale
  quickTotalPaise: number; // used when items is empty
  billDiscountPaise: number;
  payments: { method: SalePayMethod; amountPaise: number; reference: string }[];
  note: string;
}

export function computeSaleTotals(
  input: Pick<SaleInput, 'items' | 'quickTotalPaise' | 'billDiscountPaise'>,
) {
  const itemized = input.items.length > 0;
  const gross = itemized ? input.items.reduce((s, i) => s + i.lineGrossPaise, 0) : input.quickTotalPaise;
  const itemDisc = input.items.reduce((s, i) => s + i.discountPaise, 0);
  const discount = itemDisc + input.billDiscountPaise;
  return { gross, discount, payable: gross - discount };
}

export async function createSale(input: SaleInput): Promise<Sale> {
  const { gross, discount, payable } = computeSaleTotals(input);
  if (gross <= 0) throw new Error('Sale amount must be greater than zero');
  if (payable <= 0) throw new Error('Discount cannot be equal to or more than the sale amount');
  const paid = input.payments.reduce((s, p) => s + p.amountPaise, 0);
  if (paid !== payable) throw new Error('Payments must add up to the amount payable');
  const creditPaise = input.payments
    .filter((p) => p.method === 'credit')
    .reduce((s, p) => s + p.amountPaise, 0);
  if (creditPaise > 0 && !input.customerId) throw new Error('Choose a customer for a credit sale');

  const db = await getDb();
  const id = newId();
  let sale!: Sale;
  await db.withTransactionAsync(async () => {
    const counter = await nextSeq(db, 'sale_counter');
    sale = {
      id,
      sale_number: `S-${dayStamp()}-${String(counter).padStart(4, '0')}`,
      customer_id: input.customerId,
      sale_type: input.items.length ? 'itemized' : 'quick',
      sale_at: input.saleAt,
      created_at: nowIso(),
      gross_paise: gross,
      discount_paise: discount,
      note: input.note.trim() || null,
      idempotency_key: `sale:${id}`,
      sync_status: 'pending',
    };
    await db.runAsync(
      `INSERT INTO sales(id,sale_number,customer_id,sale_type,sale_at,created_at,gross_paise,discount_paise,note,idempotency_key,sync_status)
       VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
      sale.id, sale.sale_number, sale.customer_id, sale.sale_type, sale.sale_at, sale.created_at,
      sale.gross_paise, sale.discount_paise, sale.note, sale.idempotency_key, sale.sync_status,
    );
    const items: SaleItem[] = input.items.map((i) => ({
      id: newId(), sale_id: id, item_name: i.itemName, quantity_milli: i.quantityMilli,
      unit: i.unit || null, unit_price_paise: i.unitPricePaise, discount_paise: i.discountPaise,
      line_total_paise: i.lineTotalPaise,
    }));
    for (const it of items) {
      await db.runAsync(
        `INSERT INTO sale_items(id,sale_id,item_name,quantity_milli,unit,unit_price_paise,discount_paise,line_total_paise)
         VALUES (?,?,?,?,?,?,?,?)`,
        it.id, it.sale_id, it.item_name, it.quantity_milli, it.unit, it.unit_price_paise,
        it.discount_paise, it.line_total_paise,
      );
    }
    const payments: SalePayment[] = input.payments.map((p) => ({
      id: newId(), sale_id: id, method: p.method, amount_paise: p.amountPaise,
      reference: p.reference.trim() || null, paid_at: input.saleAt,
    }));
    for (const p of payments) {
      await db.runAsync(
        `INSERT INTO sale_payments(id,sale_id,method,amount_paise,reference,paid_at) VALUES (?,?,?,?,?,?)`,
        p.id, p.sale_id, p.method, p.amount_paise, p.reference, p.paid_at,
      );
    }
    await enqueue(db, 'sale', id, 'post', { ...sale, items, payments }, sale.idempotency_key);
    // Exactly one linked khata credit per credit sale (shared sale_id + deterministic key).
    if (creditPaise > 0 && input.customerId) {
      await insertEvent(db, {
        customerId: input.customerId,
        type: 'credit',
        amountPaise: creditPaise,
        deltaPaise: creditPaise,
        occurredAt: input.saleAt,
        note: `Credit sale ${sale.sale_number}`,
        saleId: id,
        idempotencyKey: `sale:${id}:credit`,
      });
    }
  });
  return sale;
}

export async function listSales(range: DateRange): Promise<SaleListRow[]> {
  const db = await getDb();
  return db.getAllAsync<SaleListRow>(
    `SELECT s.*, c.name AS customer_name,
            COALESCE((SELECT SUM(return_paise) FROM sale_returns r WHERE r.sale_id = s.id), 0) AS returned_paise,
            s.gross_paise - s.discount_paise
              - COALESCE((SELECT SUM(return_paise) FROM sale_returns r WHERE r.sale_id = s.id), 0) AS net_paise
       FROM sales s LEFT JOIN customers c ON c.id = s.customer_id
      WHERE s.sale_at >= ? AND s.sale_at < ?
      ORDER BY s.sale_at DESC`,
    range.fromIso, range.toIso,
  );
}

export interface SaleDetail {
  sale: Sale;
  customerName: string | null;
  items: SaleItem[];
  payments: SalePayment[];
  returns: SaleReturn[];
  netPaise: number;
}

export async function getSaleDetail(id: string): Promise<SaleDetail | null> {
  const db = await getDb();
  const sale = await db.getFirstAsync<Sale>('SELECT * FROM sales WHERE id = ?', id);
  if (!sale) return null;
  const items = await db.getAllAsync<SaleItem>('SELECT * FROM sale_items WHERE sale_id = ?', id);
  const payments = await db.getAllAsync<SalePayment>('SELECT * FROM sale_payments WHERE sale_id = ?', id);
  const returns = await db.getAllAsync<SaleReturn>(
    'SELECT * FROM sale_returns WHERE sale_id = ? ORDER BY returned_at', id);
  const cust = sale.customer_id
    ? await db.getFirstAsync<{ name: string }>('SELECT name FROM customers WHERE id = ?', sale.customer_id)
    : null;
  const returned = returns.reduce((s, r) => s + r.return_paise, 0);
  return {
    sale, items, payments, returns,
    customerName: cust?.name ?? null,
    netPaise: sale.gross_paise - sale.discount_paise - returned,
  };
}

export async function addReturn(
  saleId: string,
  amountPaise: number,
  reason: string,
  method: PayMethod | 'khata',
): Promise<void> {
  const detail = await getSaleDetail(saleId);
  if (!detail) throw new Error('Sale not found');
  if (amountPaise <= 0) throw new Error('Return amount must be greater than zero');
  if (amountPaise > detail.netPaise) throw new Error('Return is more than the remaining sale value');
  if (method === 'khata' && !detail.sale.customer_id) throw new Error('Khata adjustment needs a customer');
  const db = await getDb();
  const ret: SaleReturn = {
    id: newId(), sale_id: saleId, return_paise: amountPaise, reason: reason.trim() || null,
    refund_method: method, returned_at: nowIso(), idempotency_key: `return:${newId()}`,
    sync_status: 'pending',
  };
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      `INSERT INTO sale_returns(id,sale_id,return_paise,reason,refund_method,returned_at,idempotency_key,sync_status)
       VALUES (?,?,?,?,?,?,?,?)`,
      ret.id, ret.sale_id, ret.return_paise, ret.reason, ret.refund_method, ret.returned_at,
      ret.idempotency_key, ret.sync_status,
    );
    await enqueue(db, 'sale_return', ret.id, 'post', ret, ret.idempotency_key);
    if (method === 'khata' && detail.sale.customer_id) {
      await insertEvent(db, {
        customerId: detail.sale.customer_id,
        type: 'adjustment',
        amountPaise,
        deltaPaise: -amountPaise,
        occurredAt: ret.returned_at,
        note: `Return against ${detail.sale.sale_number}`,
        reason: ret.reason ?? 'Sale return',
        saleId,
        idempotencyKey: `return:${ret.id}:khata`,
      });
    }
  });
}

// ───────────────────────── Dashboards ─────────────────────────

export interface KhataSummary {
  totalReceivablePaise: number;
  customersWithBalance: number;
  advancePaise: number;
  creditByStatus: Record<string, number>;
}

export async function getKhataSummary(): Promise<KhataSummary> {
  const db = await getDb();
  const balances = await db.getAllAsync<{ b: number }>(
    `SELECT COALESCE(SUM(e.delta_paise),0) AS b FROM customers c
       LEFT JOIN ledger_events e ON e.customer_id = c.id WHERE c.archived = 0 GROUP BY c.id`);
  const statuses = await db.getAllAsync<{ s: string; t: number }>(
    `SELECT confirmation_status AS s, SUM(amount_paise) AS t FROM ledger_events e
      WHERE type = 'credit'
        AND NOT EXISTS (SELECT 1 FROM ledger_events r WHERE r.reversal_of_id = e.id)
      GROUP BY confirmation_status`);
  return {
    totalReceivablePaise: balances.filter((x) => x.b > 0).reduce((s, x) => s + x.b, 0),
    customersWithBalance: balances.filter((x) => x.b > 0).length,
    advancePaise: -balances.filter((x) => x.b < 0).reduce((s, x) => s + x.b, 0),
    creditByStatus: Object.fromEntries(statuses.map((x) => [x.s, x.t])),
  };
}

export interface SalesSummary {
  grossPaise: number;
  discountPaise: number;
  returnsPaise: number;
  netPaise: number;
  collectedPaise: number; // money received at sale time (excludes credit portion)
  creditSalesPaise: number;
  oldDuesCollectedPaise: number; // ledger payments: NOT sales
  byMethod: Record<string, number>;
  saleCount: number;
}

export async function getSalesSummary(range: DateRange): Promise<SalesSummary> {
  const db = await getDb();
  const one = async (sql: string) =>
    (await db.getFirstAsync<{ v: number }>(sql, range.fromIso, range.toIso))?.v ?? 0;

  const gross = await one(`SELECT COALESCE(SUM(gross_paise),0) AS v FROM sales WHERE sale_at >= ? AND sale_at < ?`);
  const disc = await one(`SELECT COALESCE(SUM(discount_paise),0) AS v FROM sales WHERE sale_at >= ? AND sale_at < ?`);
  const count = await one(`SELECT COUNT(*) AS v FROM sales WHERE sale_at >= ? AND sale_at < ?`);
  const returns = await one(
    `SELECT COALESCE(SUM(return_paise),0) AS v FROM sale_returns WHERE returned_at >= ? AND returned_at < ?`);
  const methodRows = await db.getAllAsync<{ method: string; t: number }>(
    `SELECT p.method AS method, SUM(p.amount_paise) AS t
       FROM sale_payments p JOIN sales s ON s.id = p.sale_id
      WHERE s.sale_at >= ? AND s.sale_at < ? GROUP BY p.method`,
    range.fromIso, range.toIso);
  const byMethod = Object.fromEntries(methodRows.map((r) => [r.method, r.t]));
  const credit = byMethod.credit ?? 0;
  const collected = methodRows.filter((r) => r.method !== 'credit').reduce((s, r) => s + r.t, 0);
  // Collections against old khata: payment events not created by a sale.
  const oldDues = await one(
    `SELECT COALESCE(SUM(amount_paise),0) AS v FROM ledger_events e
      WHERE type = 'payment' AND occurred_at >= ? AND occurred_at < ?
        AND NOT EXISTS (SELECT 1 FROM ledger_events r WHERE r.reversal_of_id = e.id)`);
  return {
    grossPaise: gross,
    discountPaise: disc,
    returnsPaise: returns,
    netPaise: gross - disc - returns,
    collectedPaise: collected,
    creditSalesPaise: credit,
    oldDuesCollectedPaise: oldDues,
    byMethod,
    saleCount: count,
  };
}

export async function getDailyNet(range: DateRange): Promise<{ day: string; net: number }[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<{ day: string; v: number }>(
    `SELECT date(sale_at, 'localtime') AS day, SUM(gross_paise - discount_paise) AS v
       FROM sales WHERE sale_at >= ? AND sale_at < ? GROUP BY day ORDER BY day`,
    range.fromIso, range.toIso);
  const rets = await db.getAllAsync<{ day: string; v: number }>(
    `SELECT date(returned_at, 'localtime') AS day, SUM(return_paise) AS v
       FROM sale_returns WHERE returned_at >= ? AND returned_at < ? GROUP BY day`,
    range.fromIso, range.toIso);
  const map = new Map<string, number>();
  rows.forEach((r) => map.set(r.day, (map.get(r.day) ?? 0) + r.v));
  rets.forEach((r) => map.set(r.day, (map.get(r.day) ?? 0) - r.v));
  return [...map.entries()].sort().map(([day, net]) => ({ day, net }));
}

export async function getTopItems(range: DateRange, limit = 5) {
  const db = await getDb();
  return db.getAllAsync<{ item_name: string; qty_milli: number; value_paise: number }>(
    `SELECT i.item_name AS item_name, SUM(i.quantity_milli) AS qty_milli, SUM(i.line_total_paise) AS value_paise
       FROM sale_items i JOIN sales s ON s.id = i.sale_id
      WHERE s.sale_at >= ? AND s.sale_at < ?
      GROUP BY LOWER(i.item_name) ORDER BY value_paise DESC LIMIT ?`,
    range.fromIso, range.toIso, limit);
}
