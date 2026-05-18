#!/usr/bin/env python3
"""Force-refresh stuck Lakebase synced tables.

The Lakebase synced tables are configured with `SNAPSHOT` scheduling and
*should* re-snapshot from Gold every 30-60s. In practice they sometimes
lock onto an old snapshot version and stop catching up — Dashboard panels
go empty despite Gold being fresh.

This script performs the full recovery for one or more synced tables:
  1. DELETE the UC synced-table object via REST  (clears UC's snapshot state)
  2. DROP the Postgres-side table                 (clears the Postgres rows)
  3. CREATE the synced table fresh via SDK         (triggers a new initial snapshot)
  4. Wait until the initial snapshot lands
  5. GRANT ALL on the new Postgres table to the app SP

Usage:
  # Reset the three tables that get stuck most often
  python scripts/reset_synced_tables.py commodity_prices_latest demand_1h procurement_recommendations

  # Reset every synced table defined in lakebase_sync/synced_tables.yml
  python scripts/reset_synced_tables.py --all

Env:
  DATABRICKS_HOST, DATABRICKS_TOKEN (or DATABRICKS_CONFIG_PROFILE)
  LIVEZEROBUS_SP   — defaults to the livezerobus app SP UUID
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import postgres as pg

HOST = os.environ.get("DATABRICKS_HOST", "https://adb-5347428297913551.11.azuredatabricks.net").rstrip("/")
PGHOST = "ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net"
PGDATABASE = "databricks_postgres"
CATALOG = "livezerobus"
SCHEMA = "procurement"
APP_SP = os.environ.get("LIVEZEROBUS_SP", "c4352007-a55b-4da5-b5c9-f4c8df89e58a")
ENDPOINT = "projects/myzerobus/branches/production/endpoints/primary"
BRANCH = "projects/myzerobus/branches/production"

# table_name → (source MV, primary key columns)
TABLES: dict[str, tuple[str, list[str]]] = {
    "commodity_prices_latest":      ("gd_commodity_latest",          ["input_key"]),
    "demand_1h":                    ("gd_demand_1h",                 ["sku", "hour_ts"]),
    "inventory_snapshot":           ("gd_inventory_snapshot",        ["sku", "room_id"]),
    "supplier_leaderboard":         ("gd_supplier_leaderboard",      ["sku", "supplier_id"]),
    "procurement_recommendations":  ("gd_procurement_recommendations", ["recommendation_id"]),
    "iot_sensor_latest":            ("gd_iot_sensor_latest",         ["room_id", "sensor_type"]),
    "sap_po_lines":                 ("gd_sap_open_po_lines",         ["po_number", "po_item"]),
    "sap_invoice_matching":         ("gd_sap_invoice_matching",      ["invoice_doc_number"]),
}


def _connect_pg(user: str, password: str) -> psycopg.Connection:
    return psycopg.connect(
        host=PGHOST, port=5432, dbname=PGDATABASE,
        user=user, password=password, sslmode="require",
    )


def _delete_synced_table(name: str, token: str) -> None:
    url = f"{HOST}/api/2.0/database/synced_tables/{CATALOG}.{SCHEMA}.{name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print(f"  ✓ DELETE synced object {name}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ↳ {name} not present (already deleted)")
        else:
            raise


def reset_one(name: str, w: WorkspaceClient, token: str, pg_user: str) -> None:
    if name not in TABLES:
        print(f"  ✗ unknown table {name}; valid: {list(TABLES)}")
        return
    source_mv, pks = TABLES[name]

    # 1. delete UC synced object
    _delete_synced_table(name, token)

    # 2. drop Postgres table (need a fresh credential per connection)
    cred = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
    with _connect_pg(pg_user, cred) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{name} CASCADE")
        conn.commit()
    print(f"  ✓ DROP Postgres {SCHEMA}.{name}")

    # 3. recreate synced table
    spec = pg.SyncedTableSyncedTableSpec(
        source_table_full_name=f"{CATALOG}.{SCHEMA}.{source_mv}",
        primary_key_columns=pks,
        scheduling_policy=pg.SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy("SNAPSHOT"),
        branch=BRANCH,
        postgres_database=PGDATABASE,
        create_database_objects_if_missing=True,
    )
    w.postgres.create_synced_table(
        synced_table=pg.SyncedTable(spec=spec),
        synced_table_id=f"{CATALOG}.{SCHEMA}.{name}",
    )
    print(f"  ✓ CREATE synced {name} from {source_mv}")


def wait_and_grant(names: list[str], w: WorkspaceClient, pg_user: str, timeout_s: int = 180) -> None:
    """Wait for tables to land, then GRANT to the app SP."""
    deadline = time.time() + timeout_s
    pending = set(names)
    while pending and time.time() < deadline:
        cred = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
        with _connect_pg(pg_user, cred) as conn, conn.cursor() as cur:
            for t in list(pending):
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s)",
                    (SCHEMA, t),
                )
                if cur.fetchone()[0]:
                    try:
                        cur.execute(f'GRANT ALL ON {SCHEMA}.{t} TO "{APP_SP}"')
                        print(f"  ✓ GRANT {t}")
                        pending.discard(t)
                    except Exception as e:
                        print(f"  ✗ GRANT {t}: {e}")
            conn.commit()
        if pending:
            print(f"  … still waiting for: {sorted(pending)}")
            time.sleep(15)

    if pending:
        print(f"  ⚠ Timed out waiting for: {sorted(pending)} (snapshot still running)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*", help="Table names to reset (e.g. commodity_prices_latest)")
    ap.add_argument("--all", action="store_true", help="Reset every synced table")
    ap.add_argument("--pg-user", default=os.environ.get("PGUSER", "puzar@devsoftserveinc.com"),
                    help="Postgres user (default: PGUSER env or puzar@devsoftserveinc.com)")
    args = ap.parse_args()

    selected = list(TABLES) if args.all else args.tables
    if not selected:
        ap.error("Specify table names or pass --all")

    w = WorkspaceClient()
    token = os.environ.get("DATABRICKS_TOKEN")
    if not token:
        # Mint via SDK config
        token = w.config.authenticate().get("Authorization", "").removeprefix("Bearer ")
    if not token:
        ap.error("Could not obtain a Databricks token. Set DATABRICKS_TOKEN or DATABRICKS_CONFIG_PROFILE.")

    print(f"Resetting {len(selected)} synced table(s): {selected}")
    print(f"Using Postgres user: {args.pg_user}")
    print()
    for name in selected:
        print(f"=== {name} ===")
        reset_one(name, w, token, args.pg_user)
        print()

    print("Waiting for initial snapshots to land + granting SP access…")
    wait_and_grant(selected, w, args.pg_user)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
