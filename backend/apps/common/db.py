"""Tiny SQL helpers. The schema is owned by database/create_tables.py, so we use plain SQL."""
from typing import Any, Iterable

from django.db import connection, transaction

atomic = transaction.atomic


def _rows(cur) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def q(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    """Run a statement and return rows as dicts (empty list if it returns nothing)."""
    with connection.cursor() as cur:
        cur.execute(sql, list(params))
        return _rows(cur) if cur.description else []


def q1(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: Iterable[Any] = ()) -> int:
    """Run a statement and return the affected row count."""
    with connection.cursor() as cur:
        cur.execute(sql, list(params))
        return cur.rowcount
