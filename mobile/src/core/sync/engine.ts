import { getDb } from '../db';
import { syncApi, type SyncResult } from '../api/endpoints';
import { ApiError } from '../api/client';
import { tokenStore } from '../auth/tokenStore';
import { config } from '../config';
import type { OutboxRow } from '../db/types';

const TABLE_BY_ENTITY: Record<string, string> = {
  shop: 'shop',
  customer: 'customers',
  ledger_event: 'ledger_events',
  sale: 'sales',
  sale_return: 'sale_returns',
};

const BATCH = 50;
const MAX_BACKOFF_MS = 15 * 60 * 1000;

export interface SyncCounts { pending: number; failed: number; conflict: number }
export type SyncState = SyncCounts & { running: boolean; lastSyncAt: string | null; lastError: string | null };

let state: SyncState = { pending: 0, failed: 0, conflict: 0, running: false, lastSyncAt: null, lastError: null };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
export const syncStore = {
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
  getSnapshot: () => state,
};

export async function refreshCounts(): Promise<void> {
  const db = await getDb();
  const rows = await db.getAllAsync<{ status: string; n: number }>(
    'SELECT status, COUNT(*) AS n FROM outbox GROUP BY status');
  const c = { pending: 0, failed: 0, conflict: 0 };
  rows.forEach((r) => { (c as Record<string, number>)[r.status] = r.n; });
  state = { ...state, ...c };
  emit();
}

const backoff = (attempts: number) =>
  Math.min(2 ** attempts * 1000, MAX_BACKOFF_MS) * (0.75 + Math.random() * 0.5);

/** Apply one server acknowledgement. The outbox row is only removed once the local row is updated. */
async function applyResult(row: OutboxRow, r: SyncResult | undefined): Promise<void> {
  const db = await getDb();
  const table = TABLE_BY_ENTITY[row.entity];
  if (!r) return; // not acknowledged: keep it queued
  await db.withTransactionAsync(async () => {
    if (r.status === 'accepted' || r.status === 'duplicate') {
      if (table) await db.runAsync(`UPDATE ${table} SET sync_status = 'synced' WHERE id = ?`, row.entity_id);
      await db.runAsync('DELETE FROM outbox WHERE id = ?', row.id);
    } else if (r.status === 'conflict') {
      if (table) await db.runAsync(`UPDATE ${table} SET sync_status = 'conflict' WHERE id = ?`, row.entity_id);
      await db.runAsync(`UPDATE outbox SET status = 'conflict', last_error = ? WHERE id = ?`, r.error ?? 'Conflict', row.id);
    } else {
      if (table) await db.runAsync(`UPDATE ${table} SET sync_status = 'failed' WHERE id = ?`, row.entity_id);
      await db.runAsync(`UPDATE outbox SET status = 'failed', last_error = ? WHERE id = ?`, r.error ?? 'Rejected', row.id);
    }
  });
}

let inFlight: Promise<void> | null = null;

/** Single-flight sync. Safe to call from any trigger (resume, network, timer, manual). */
export function runSync(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    if (config.demoMode || !(await tokenStore.getAccess())) { await refreshCounts(); return; }
    state = { ...state, running: true, lastError: null };
    emit();
    try {
      const db = await getDb();
      const deviceId = await tokenStore.deviceId();
      for (;;) {
        const rows = await db.getAllAsync<OutboxRow>(
          `SELECT * FROM outbox WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY seq LIMIT ?`,
          Date.now(), BATCH);
        if (!rows.length) break;
        try {
          const res = await syncApi.batch({
            device_id: deviceId,
            items: rows.map((r) => ({
              idempotency_key: r.idempotency_key, entity: r.entity, op: r.op, payload: JSON.parse(r.payload),
            })),
          });
          const byKey = new Map(res.results.map((x) => [x.idempotency_key, x]));
          for (const row of rows) await applyResult(row, byKey.get(row.idempotency_key));
          if (res.results.length === 0) break;
        } catch (e) {
          const msg = e instanceof Error ? e.message : 'Sync failed';
          for (const row of rows) {
            await db.runAsync(
              'UPDATE outbox SET attempts = attempts + 1, next_attempt_at = ?, last_error = ? WHERE id = ?',
              Date.now() + backoff(row.attempts + 1), msg, row.id);
          }
          state = { ...state, lastError: e instanceof ApiError && e.isNetwork ? 'Offline' : msg };
          break;
        }
      }
      if (!state.lastError) state = { ...state, lastSyncAt: new Date().toISOString() };
    } finally {
      state = { ...state, running: false };
      await refreshCounts();
    }
  })().finally(() => { inFlight = null; });
  return inFlight;
}

/** Put failed items back in the queue after the user reviewed them. */
export async function retryFailed(): Promise<void> {
  const db = await getDb();
  await db.runAsync(`UPDATE outbox SET status = 'pending', next_attempt_at = 0 WHERE status = 'failed'`);
  await refreshCounts();
  void runSync();
}
