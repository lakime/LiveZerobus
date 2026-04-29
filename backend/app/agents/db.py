"""Agent-side DB helpers.

Agents both read and write Lakebase. The existing `app.lakebase.query` helper
is read-only; here we add an `execute` helper that commits. All writes land
in the `procurement.*` schema that the synced Delta source tables back.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..config import Settings
from ..lakebase import _connect_factory  # reuse the OAuth-token connector


def execute(
    settings: Settings,
    sql: str,
    params: Iterable[Any] | None = None,
) -> None:
    connect = _connect_factory(settings)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        conn.commit()


def execute_many(
    settings: Settings,
    sql: str,
    rows: Iterable[Iterable[Any]],
) -> None:
    connect = _connect_factory(settings)
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(sql, [tuple(r) for r in rows])
        conn.commit()


def fetchone(
    settings: Settings,
    sql: str,
    params: Iterable[Any] | None = None,
) -> dict | None:
    connect = _connect_factory(settings)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        row = cur.fetchone()
        return dict(row) if row else None


def fetchall(
    settings: Settings,
    sql: str,
    params: Iterable[Any] | None = None,
) -> list[dict]:
    connect = _connect_factory(settings)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        return [dict(r) for r in cur.fetchall()]
