#!/usr/bin/env python3
"""
Is the live Neon database reachable and healthy?   python check_neon.py

Checks: DATABASE_URL is set, TLS is on, login works, speed, write access (rolled back, leaves nothing behind),
required extensions, all 38 tables, append-only rules, the seeded Rs 49 plan, and that a dropped connection
(Neon pauses idle databases) can be re-opened. Exit code 0 = everything OK. Never prints the password.
"""
from __future__ import annotations

import statistics
import sys
import time

import create_tables as ct

results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> bool:
    results.append((ok, msg))
    print(f"{'PASS' if ok else 'FAIL'}  {msg}")
    return ok


def main() -> int:
    cfg = ct.load_env()
    if not check(cfg["hosted"], "DATABASE_URL is set (live hosted database, no local fallback)"):
        return 1
    print(f"      host {cfg['host']}  database {cfg['dbname']}  user {cfg['user']}")
    check("neon.tech" in cfg["host"], "host is a Neon endpoint")
    check(cfg["extra"].get("sslmode") in ("require", "verify-ca", "verify-full"), f"TLS required (sslmode={cfg['extra'].get('sslmode')})")

    t0 = time.time()
    conn = ct.connect(cfg)  # exits with a clear message if it cannot connect
    connect_s = time.time() - t0
    check(True, f"connected in {connect_s:.2f}s (the first connect after idle can take a few seconds while Neon wakes)")
    cur = conn.cursor()

    cur.execute("SELECT version()")
    version = cur.fetchone()[0]
    tls = conn.info.ssl_in_use
    check(tls, f"connection is encrypted: TLS {conn.info.ssl_attribute('protocol')}, {conn.info.ssl_attribute('cipher')} ({version.split(',')[0]})")

    times = []
    for _ in range(8):
        t = time.time()
        cur.execute("SELECT 1")
        cur.fetchone()
        times.append((time.time() - t) * 1000)
    med = statistics.median(times)
    check(med < 1500, f"query round trip median {med:.0f} ms (best {min(times):.0f} ms, worst {max(times):.0f} ms)")

    # write access, proven inside a transaction that is rolled back
    try:
        cur.execute("CREATE TEMP TABLE _probe(x int)")
        cur.execute("INSERT INTO _probe VALUES (1)")
        cur.execute("SELECT count(*) FROM _probe")
        ok = cur.fetchone()[0] == 1
    except Exception as e:  # noqa: BLE001
        ok = False
        print("      ", str(e).splitlines()[0])
    conn.rollback()
    check(ok, "can write (test row created and rolled back)")

    cur.execute("SELECT extname FROM pg_extension")
    exts = {r[0] for r in cur.fetchall()}
    check({"pgcrypto", "citext"} <= exts, f"extensions installed: pgcrypto, citext (have {sorted(exts)})")

    have = ct.existing_tables(conn)
    missing = [t for t in ct.EXPECTED_TABLES if t not in have]
    check(not missing, f"all {len(ct.EXPECTED_TABLES)} tables exist" + (f" (missing: {missing[:4]})" if missing else ""))

    cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_ledger_events_guard','trg_audit_logs_append_only',"
                "'trg_sale_returns_append_only','trg_transaction_items_append_only','trg_sub_audit_append_only')")
    check(cur.fetchone()[0] == 5, "append-only protection triggers are in place (posted money cannot be edited or deleted)")

    cur.execute("SELECT amount_paise FROM subscription_plans WHERE code = 'udhaarsaathi_monthly'")
    row = cur.fetchone()
    check(bool(row) and row[0] == 4900, "seeded plan: Rs 49 / month")
    cur.execute("SELECT count(*) FROM app_config")
    check(cur.fetchone()[0] == 1, "app_config row present")

    cur.execute("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM shops), (SELECT count(*) FROM ledger_events)")
    u, s, e = cur.fetchone()
    print(f"      data on Neon now: {u} users, {s} shops, {e} ledger entries")

    # reconnect: cut the socket the way a network failure or Neon suspending the database would
    import socket
    sock = socket.socket(fileno=conn.fileno())
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.detach()  # the connection object still owns the handle
    dropped = False
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:  # noqa: BLE001
        dropped = True
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    check(dropped, "a dropped connection is detected (queries on it fail instead of hanging)")
    t = time.time()
    fresh = ct.connect(cfg)
    fresh.cursor().execute("SELECT 1")
    fresh.close()
    check(True, f"a fresh connection works right after a drop ({time.time() - t:.2f}s)")

    bad = [m for ok, m in results if not ok]
    print("\n" + ("ALL CHECKS PASSED: Neon is reachable and ready." if not bad else f"{len(bad)} CHECK(S) FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
