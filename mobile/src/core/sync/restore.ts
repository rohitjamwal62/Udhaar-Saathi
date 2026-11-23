import { getDb } from '../db';
import { api } from '../api/client';

// Rebuilds this phone's local copy from the server after a fresh login or reinstall, so the shop (and its khata)
// is never asked for twice. The server is the source of truth for anything already synced.

type Row = Record<string, unknown>;
interface RestoreShop {
  id: string; name: string; category: string | null; address: string | null; owner_name: string | null;
  owner_mobile: string | null; timezone: string; language: string; created_at: string;
}
interface RestorePayload {
  shop: RestoreShop | null;
  customers?: { id: string; name: string; mobile: string | null; notes: string | null; archived: boolean; created_at: string }[];
  ledger_events?: Row[];
  ledger_items?: Row[];
  sales?: Row[];
  sale_items?: Row[];
  sale_payments?: Row[];
  sale_returns?: Row[];
}

export type RestoreResult = 'restored' | 'none';

const s = (v: unknown) => (v === undefined || v === null ? null : String(v));
const n = (v: unknown) => Number(v ?? 0);

export async function restoreFromServer(): Promise<RestoreResult> {
  const p = await api<RestorePayload>('/restore');   // network errors propagate: the caller offers a retry
  if (!p.shop) return 'none';
  const sh = p.shop;
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      `INSERT OR REPLACE INTO shop(id,name,category,address,owner_name,owner_mobile,timezone,language,created_at,sync_status)
       VALUES (?,?,?,?,?,?,?,?,?,'synced')`,
      sh.id, sh.name, sh.category, sh.address, sh.owner_name, sh.owner_mobile, sh.timezone, sh.language, sh.created_at);
    for (const c of p.customers ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO customers(id,name,mobile,notes,archived,created_at,sync_status) VALUES (?,?,?,?,?,?,'synced')`,
        c.id, c.name, c.mobile, c.notes, c.archived ? 1 : 0, c.created_at);
    }
    // originals before the reversals that point at them
    const events = [...(p.ledger_events ?? [])].sort((a, b) => Number(!!a.reversal_of_id) - Number(!!b.reversal_of_id));
    for (const e of events) {
      await db.runAsync(
        `INSERT OR IGNORE INTO ledger_events(id,customer_id,type,amount_paise,delta_paise,occurred_at,created_at,note,payment_method,
           payment_reference,sale_id,reversal_of_id,reason,confirmation_status,idempotency_key,sync_status)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'synced')`,
        s(e.id), s(e.customer_id), s(e.type), n(e.amount_paise), n(e.delta_paise), s(e.occurred_at), s(e.created_at),
        s(e.note), s(e.payment_method), s(e.payment_reference), s(e.sale_id), s(e.reversal_of_id), s(e.reason),
        s(e.confirmation_status) ?? 'shopkeeper_recorded', s(e.idempotency_key));
    }
    for (const i of p.ledger_items ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO ledger_items(id,event_id,item_name,quantity_milli,unit,unit_price_paise,line_total_paise) VALUES (?,?,?,?,?,?,?)`,
        s(i.id), s(i.event_id), s(i.item_name), n(i.quantity_milli), s(i.unit), n(i.unit_price_paise), n(i.line_total_paise));
    }
    for (const r of p.sales ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO sales(id,sale_number,customer_id,sale_type,sale_at,created_at,gross_paise,discount_paise,note,idempotency_key,sync_status)
         VALUES (?,?,?,?,?,?,?,?,?,?,'synced')`,
        s(r.id), s(r.sale_number), s(r.customer_id), s(r.sale_type), s(r.sale_at), s(r.created_at),
        n(r.gross_paise), n(r.discount_paise), s(r.note), s(r.idempotency_key));
    }
    for (const i of p.sale_items ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO sale_items(id,sale_id,item_name,quantity_milli,unit,unit_price_paise,discount_paise,line_total_paise) VALUES (?,?,?,?,?,?,?,?)`,
        s(i.id), s(i.sale_id), s(i.item_name), n(i.quantity_milli), s(i.unit), n(i.unit_price_paise), n(i.discount_paise), n(i.line_total_paise));
    }
    for (const x of p.sale_payments ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO sale_payments(id,sale_id,method,amount_paise,reference,paid_at) VALUES (?,?,?,?,?,?)`,
        s(x.id), s(x.sale_id), s(x.payment_method), n(x.amount_paise), s(x.reference), s(x.paid_at));
    }
    for (const r of p.sale_returns ?? []) {
      await db.runAsync(
        `INSERT OR IGNORE INTO sale_returns(id,sale_id,return_paise,reason,refund_method,returned_at,idempotency_key,sync_status)
         VALUES (?,?,?,?,?,?,?,'synced')`,
        s(r.id), s(r.sale_id), n(r.return_paise), s(r.reason), s(r.refund_method), s(r.returned_at), s(r.idempotency_key));
    }
  });
  return 'restored';
}
