#!/usr/bin/env python3
"""Apply schemas/lakebase_schema.sql to the Lakebase Postgres database.

The Lakebase synced tables (Gold → Postgres) are created by
`lakebase_sync/apply.py`. The agent-state native tables (po_drafts,
budget_ledger, email_inbox, ...) live in the same schema but their DDL
is in `schemas/lakebase_schema.sql` and was historically applied
manually. This script applies it idempotently — every CREATE TABLE in
the schema file uses `IF NOT EXISTS`, so re-runs are safe.

Usage (from repo root):
  pip install psycopg[binary] databricks-sdk
  DATABRICKS_HOST=https://adb-...azuredatabricks.net \\
  DATABRICKS_CLIENT_ID=<sp-uuid> \\
  DATABRICKS_CLIENT_SECRET=<secret> \\
  python scripts/apply_lakebase_schema.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from databricks.sdk import WorkspaceClient

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "schemas" / "lakebase_schema.sql"

PGHOST = os.environ.get("PGHOST", "ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGDATABASE = os.environ.get("PGDATABASE", "databricks_postgres")
PGUSER = os.environ.get("PGUSER", "c4352007-a55b-4da5-b5c9-f4c8df89e58a")
PG_SCHEMA = os.environ.get("PG_SCHEMA", "procurement")
LAKEBASE_PROJECT = os.environ.get("LAKEBASE_PROJECT", "myzerobus")
LAKEBASE_BRANCH = os.environ.get("LAKEBASE_BRANCH", "production")
LAKEBASE_ENDPOINT = os.environ.get("LAKEBASE_ENDPOINT", "primary")


def mint_token() -> str:
    """Generate a short-lived Postgres OAuth token via Databricks SDK."""
    w = WorkspaceClient()
    resource = (
        f"projects/{LAKEBASE_PROJECT}"
        f"/branches/{LAKEBASE_BRANCH}"
        f"/endpoints/{LAKEBASE_ENDPOINT}"
    )
    cred = w.postgres.generate_database_credential(endpoint=resource)
    if not cred.token:
        raise RuntimeError(f"No token returned for {resource}")
    return cred.token


def main() -> int:
    if not SCHEMA_SQL.exists():
        print(f"ERROR: {SCHEMA_SQL} not found", file=sys.stderr)
        return 1

    sql = SCHEMA_SQL.read_text()
    print(f"Connecting to {PGHOST}:{PGPORT}/{PGDATABASE} as {PGUSER}")
    print(f"Minting Lakebase Postgres OAuth token …")
    password = mint_token()
    print(f"  token len={len(password)} (truncated for logs)")

    print(f"Applying {SCHEMA_SQL.name} ({len(sql)} bytes) …")
    with psycopg.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=password,
        sslmode="require",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("OK")

    # Verify by listing the procurement schema's tables.
    with psycopg.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=password,
        sslmode="require",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (PG_SCHEMA,),
            )
            tables = [row[0] for row in cur.fetchall()]

    print(f"\nTables in '{PG_SCHEMA}' now ({len(tables)}):")
    for t in tables:
        print(f"  {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
