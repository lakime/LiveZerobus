"""Lakebase Postgres connection pool (Autoscaling / Projects API).

Lakebase auth: the Postgres password is a short-lived OAuth token issued
for the caller (or the service principal running the Databricks App).
Tokens are rotated automatically before they expire.

Locally: set DATABRICKS_HOST / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET.
In Databricks Apps: the SDK picks up the app's injected identity credentials.

Lakebase Autoscaling (Projects) addresses endpoints hierarchically:
    projects/{project}/branches/{branch}/endpoints/{endpoint}

We build that resource name from three env vars:
    LAKEBASE_PROJECT    e.g. myzerobus
    LAKEBASE_BRANCH     e.g. production
    LAKEBASE_ENDPOINT   e.g. primary

and pass it to `w.postgres.generate_database_credential`.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Iterable

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

from .config import Settings

_TOKEN_REFRESH_MARGIN_S = 60        # refresh 60s before expiry
_DEFAULT_TOKEN_TTL_S = 3600         # Lakebase tokens default ~1h
_POOL: ConnectionPool | None = None
_TOKEN: tuple[str, float] = ("", 0.0)
_LOCK = threading.Lock()


def _resource_name() -> str:
    project = os.environ.get("LAKEBASE_PROJECT", "").strip()
    branch = os.environ.get("LAKEBASE_BRANCH", "").strip()
    endpoint = os.environ.get("LAKEBASE_ENDPOINT", "").strip()
    missing = [k for k, v in (
        ("LAKEBASE_PROJECT", project),
        ("LAKEBASE_BRANCH", branch),
        ("LAKEBASE_ENDPOINT", endpoint),
    ) if not v]
    if missing:
        raise RuntimeError(
            f"Missing Lakebase env vars: {', '.join(missing)}. "
            "Expected LAKEBASE_PROJECT (e.g. myzerobus), "
            "LAKEBASE_BRANCH (e.g. production), "
            "LAKEBASE_ENDPOINT (e.g. primary)."
        )
    return f"projects/{project}/branches/{branch}/endpoints/{endpoint}"


def _fetch_token() -> tuple[str, float]:
    """Return (token, expiry_epoch_seconds).

    Uses the Lakebase Autoscaling (Projects) API:
        w.postgres.generate_database_credential(name="projects/.../endpoints/primary")
    """
    resource = _resource_name()
    w = WorkspaceClient()
    # SDK signature (databricks-sdk 0.6x+):
    #   generate_database_credential(endpoint: str, *, claims=None) -> DatabaseCredential
    # `endpoint` wants the full resource name:
    #   projects/{project}/branches/{branch}/endpoints/{endpoint}
    cred = w.postgres.generate_database_credential(endpoint=resource)
    token = getattr(cred, "token", None) or ""
    if not token:
        raise RuntimeError(
            f"generate_database_credential returned no token for {resource}"
        )
    # The response may or may not carry an expiration — default to 1h if not.
    exp_attr = getattr(cred, "expiration_time", None)
    if exp_attr and hasattr(exp_attr, "timestamp"):
        exp = exp_attr.timestamp()
    else:
        exp = time.time() + _DEFAULT_TOKEN_TTL_S
    return token, exp


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
