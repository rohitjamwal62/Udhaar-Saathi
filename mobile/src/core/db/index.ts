import * as SQLite from 'expo-sqlite';
import { MIGRATIONS, SCHEMA_VERSION } from './schema';

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

async function init(): Promise<SQLite.SQLiteDatabase> {
  const db = await SQLite.openDatabaseAsync('udhaarsaathi.db');
  await db.execAsync('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');
  const row = await db.getFirstAsync<{ user_version: number }>('PRAGMA user_version');
  let current = row?.user_version ?? 0;
  while (current < SCHEMA_VERSION) {
    const next = current + 1;
    await db.withTransactionAsync(async () => {
      await db.execAsync(MIGRATIONS[next]);
      await db.execAsync(`PRAGMA user_version = ${next}`);
    });
    current = next;
  }
  return db;
}

export function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) dbPromise = init();
  return dbPromise;
}

/** Wipe all local data (used on logout of the last account / demo reset). */
export async function resetDb(): Promise<void> {
  const db = await getDb();
  await db.execAsync(`
    DELETE FROM outbox; DELETE FROM sale_returns; DELETE FROM sale_payments;
    DELETE FROM sale_items; DELETE FROM sales; DELETE FROM ledger_items;
    DELETE FROM ledger_events; DELETE FROM customers; DELETE FROM shop; DELETE FROM meta;
  `);
}
