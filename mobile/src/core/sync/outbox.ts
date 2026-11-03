import type { SQLiteDatabase } from 'expo-sqlite';
import { newId, nowIso } from '../ids';

/** Next monotonically increasing outbox sequence (kept in meta so it survives an empty outbox). */
export async function nextSeq(db: SQLiteDatabase, key = 'outbox_seq'): Promise<number> {
  await db.runAsync(
    `INSERT INTO meta(key, value) VALUES (?, '1')
     ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1`,
    key,
  );
  const row = await db.getFirstAsync<{ value: string }>('SELECT value FROM meta WHERE key = ?', key);
  return Number(row?.value ?? 1);
}

/**
 * Queue an immutable mutation. MUST be called inside the same transaction that
 * wrote the local row, so a crash can never leave a row without its outbox entry.
 */
export async function enqueue(
  db: SQLiteDatabase,
  entity: string,
  entityId: string,
  op: string,
  payload: unknown,
  idempotencyKey: string,
): Promise<void> {
  const seq = await nextSeq(db);
  await db.runAsync(
    `INSERT INTO outbox(id, entity, entity_id, op, payload, idempotency_key, seq, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    newId(),
    entity,
    entityId,
    op,
    JSON.stringify(payload),
    idempotencyKey,
    seq,
    nowIso(),
  );
}
