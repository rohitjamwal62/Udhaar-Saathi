#!/usr/bin/env python3
"""
Copy ALL data from your local PostgreSQL database to a hosted one (Neon).

    python create_tables.py            # 1) with DATABASE_URL set: creates the empty schema on Neon
    python copy_data.py                # 2) dry run: shows what would be copied (changes nothing)
    python copy_data.py --go           # 3) copies the rows, then verifies the counts

SOURCE = the local PG* settings (PGHOST, PGUSER, PGPASSWORD, PGDATABASE) from database/.env.
TARGET = DATABASE_URL (database/.env or the environment) or --target-url.
The source is only ever read. Re-running is safe: rows that already exist on the target are skipped
(ON CONFLICT DO NOTHING), so nothing is duplicated or overwritten. Tables are copied in foreign-key order.
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover
    sys.exit("psycopg2 is missing. Run:  pip install psycopg2-binary")

import create_tables as ct

BATCH = 500
SKIP = {"schema_migrations"}  # written by create_tables.py on each side
# Tables whose rows must be inserted oldest-first because a row can reference an earlier row of the same table.
ORDER_BY = {"ledger_events": "server_created_at, id"}


def source_config() -> dict:
    """The source is ALWAYS the local PostgreSQL (PG* settings), never DATABASE_URL (that is the target)."""
    ct.load_env()  # fills os.environ from database/.env
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": os.environ.get("SOURCE_PGDATABASE") or os.environ.get("PGDATABASE", "udhaar_saathi"),
        "extra": {},
        "hosted": False,
    }


def target_config(url: str | None) -> dict:
    url = (url or os.environ.get("DATABASE_URL", "")).strip()
    if not url:
        sys.exit("No target: set DATABASE_URL in database/.env (your Neon connection string) or pass --target-url.")
    return ct.parse_database_url(url)


def fk_order(conn) -> list[str]:
    """Tables sorted so every table comes after the tables it references."""
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
        tables = {r[0] for r in cur.fetchall()} - SKIP
        cur.execute("""SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
                         FROM pg_constraint c WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace""")
        deps = {t: set() for t in tables}
        for child, parent in cur.fetchall():
            child, parent = child.strip('"'), parent.strip('"')
            if child in tables and parent in tables and child != parent:
                deps[child].add(parent)
    ordered: list[str] = []
    while deps:
        ready = sorted(t for t, d in deps.items() if not (d - set(ordered)))
        if not ready:
            sys.exit(f"Foreign-key cycle between: {sorted(deps)}")
        ordered += ready
        for t in ready:
            del deps[t]
    return ordered


def columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s "
                    "ORDER BY ordinal_position", (table,))
        return [r[0] for r in cur.fetchall()]


def count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{table}"')
        return cur.fetchone()[0]


def adapt(v):
    return psycopg2.extras.Json(v) if isinstance(v, (dict, list)) else v


def copy_table(src, dst, table: str) -> int:
    cols = columns(src, table)
    missing = set(cols) - set(columns(dst, table))
    if missing:
        sys.exit(f"Target table {table} lacks columns {sorted(missing)}. Run create_tables.py against the target first.")
    col_sql = ", ".join(f'"{c}"' for c in cols)
    order = f" ORDER BY {ORDER_BY[table]}" if table in ORDER_BY else ""
    copied = 0
    with src.cursor(name=f"read_{table}") as read:  # server-side cursor: constant memory
        read.execute(f'SELECT {col_sql} FROM "{table}"{order}')
        while True:
            rows = read.fetchmany(BATCH)
            if not rows:
                break
            with dst.cursor() as w:
                psycopg2.extras.execute_values(
                    w, f'INSERT INTO "{table}" ({col_sql}) VALUES %s ON CONFLICT DO NOTHING',
                    [tuple(adapt(v) for v in r) for r in rows])
                copied += w.rowcount
    return copied


def align_seed_ids(src, dst) -> None:
    """The seeded plan gets a random UUID in every database. Subscriptions copied from the source point at the
    SOURCE plan id, so give the target's (still unreferenced) seed row that same id before copying."""
    with src.cursor() as s, dst.cursor() as d:
        s.execute("SELECT id, code FROM subscription_plans")
        for plan_id, code in s.fetchall():
            d.execute("SELECT id FROM subscription_plans WHERE code = %s", (code,))
            row = d.fetchone()
            if row and str(row[0]) != str(plan_id):
                d.execute("SELECT count(*) FROM subscriptions WHERE plan_id = %s", (row[0],))
                if d.fetchone()[0]:
                    sys.exit(f"Plan '{code}' on the target is already used by subscriptions with a different id; "
                             "refusing to rewrite it.")
                d.execute("UPDATE subscription_plans SET id = %s WHERE code = %s", (plan_id, code))


def fix_sequences(dst) -> None:
    with dst.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM audit_logs")
        top = cur.fetchone()[0]
        if top:
            cur.execute("SELECT setval(pg_get_serial_sequence('audit_logs', 'id'), %s)", (top,))
        cur.execute("""SELECT COALESCE(MAX(NULLIF(regexp_replace(invoice_number, '^.*-', ''), '')::bigint), 0)
                         FROM subscription_invoices""")
        top = cur.fetchone()[0]
        if top:
            cur.execute("SELECT setval('invoice_number_seq', %s)", (top,))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true", help="really copy (default is a dry run)")
    ap.add_argument("--target-url", help="override DATABASE_URL for the target")
    args = ap.parse_args()

    s_cfg, t_cfg = source_config(), target_config(args.target_url)
    if (s_cfg["host"], s_cfg["port"], s_cfg["dbname"]) == (t_cfg["host"], t_cfg["port"], t_cfg["dbname"]):
        sys.exit("Source and target are the same database.")
    print(f"SOURCE: {s_cfg['dbname']} on {s_cfg['host']} (read only)\nTARGET: {t_cfg['dbname']} on {t_cfg['host']}")
    src, dst = ct.connect(s_cfg), ct.connect(t_cfg)
    src.set_session(readonly=True)
    missing = [t for t in ct.EXPECTED_TABLES if t not in ct.existing_tables(dst)]
    if missing:
        sys.exit("The target has no schema yet (missing: " + ", ".join(missing[:5]) + "...). Run create_tables.py first.")

    tables = fk_order(src)
    print(f"\n{'table':28} {'source':>8} {'target':>8}")
    plan = [(t, count(src, t), count(dst, t)) for t in tables]
    for t, s, d in plan:
        if s or d:
            print(f"{t:28} {s:>8} {d:>8}")
    total = sum(s for _, s, _ in plan)
    print(f"\n{total} rows in the source.")
    if not args.go:
        print("Dry run only. Add --go to copy.")
        return
    if not total:
        print("Nothing to copy: the source has no rows. (The schema and the seed data are already on the target.)")
        return

    try:
        align_seed_ids(src, dst)
        for t in tables:
            n = copy_table(src, dst, t)
            if n:
                print(f"  copied {n:>6} into {t}")
        fix_sequences(dst)
        dst.commit()  # all or nothing
    except Exception:
        dst.rollback()
        raise

    bad = []
    print(f"\n{'table':28} {'source':>8} {'target':>8}")
    for t in tables:
        s, d = count(src, t), count(dst, t)
        if s or d:
            print(f"{t:28} {s:>8} {d:>8}  {'OK' if d >= s else 'MISSING ROWS'}")
        if d < s:
            bad.append(t)
    sys.exit("Some tables are short: " + ", ".join(bad) if bad else print("\nVERIFIED: every source row exists on the target.") or 0)


if __name__ == "__main__":
    main()
