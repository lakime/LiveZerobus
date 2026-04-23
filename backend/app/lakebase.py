"""Lakebase Postgres connection pool.

Lakebase auth: the Postgres password is a short-lived OAuth token issued
for the caller (or the service principal running the Databricks App).
Tokens are rotated automatically before they expire.

Locally: set DATABRICKS_HOST / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET.
In Databricks Apps: the SDK picks up the app's injected identity credentials.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Iterable

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

from .config import Settings

_TOKEN_REFRESH_MARGIN_S = 60        # refresh 60s before expiry
_POOL: ConnectionPool | None = None
_TOKEN: tuple[str, float] = ("", 0.0)
_LOCK = threading.Lock()


def _fetch_token() -> tuple[str, float]:
    """Return (token, expiry_epoch_seconds)."""
    w = WorkspaceClient()
    # `database.generate_database_credential` returns a short-lived token
    # usable as the Postgres password.
    cred = w.database.generate_database_credential(request_id="livezerobus-app", instance_names=[])
    exp = time.time() + (cred.expiration_time.timestamp() - time.time() if cred.expiration_time else 900)
    return cred.token, exp


def _current_password() -> str:
    global _TOKEN
    with _LOCK:
        token, exp = _TOKEN
        if not token or exp - time.time() < _TOKEN_REFRESH_MARGIN_S:
            token, exp = _fetch_token()
            _TOKEN = (token, exp)
        return token


def _connect_factory(settings: Settings):
    def _connect(conn_kwargs: dict | None = None) -> psycopg.Connection:
        password = _current_password()
        return psycopg.connect(
            host=settings.pghost,
            port=settings.pgport,
            dbname=settings.pgdatabase,
            user=settings.pguser,
            password=password,
            sslmode="require",
            application_name="livezerobus-app",
            row_factory=psycopg.rows.dict_row,
        )
    return _connect


def get_pool(settings: Settings) -> ConnectionPool:
    global _POOL
    if _POOL is None:
        with _LOCK:
            if _POOL is None:
                _POOL = ConnectionPool(
                    min_size=1, max_size=8,
                    connection_class=psycopg.Connection,
                    configure=lambda conn: conn.execute(f"SET search_path TO {settings.schema}, public"),
                    kwargs={},
                )
                # ConnectionPool doesn't accept a factory directly in all versions;
                # we monkey-patch the connect.
                _POOL.connection_class = type("_Conn", (), {"connect": staticmethod(_connect_factory(settings))})
    return _POOL


# -------------------------- Query helpers --------------------------


def query(settings: Settings, sql: str, params: Iterable[Any] | None = None) -> list[dict]:
    """Run a query and return list of dict rows."""
    connect = _connect_factory(settings)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params) if params else None)
        return list(cur.fetchall())
