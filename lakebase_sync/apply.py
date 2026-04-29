"""Apply synced_tables.yml against Lakebase (Projects API).

Usage (from the bundle or notebook):
    databricks bundle run lakebase_sync -t dev

Creates synced tables in Lakebase Postgres via the Projects API
(w.postgres.create_synced_table), then creates/updates the Postgres schema
(schemas/lakebase_schema.sql) manually beforehand.

Env vars:
    LAKEBASE_INSTANCE or LAKEBASE_PROJECT  — Lakebase project name (e.g. myzerobus)
    LAKEBASE_BRANCH                        — branch name (e.g. production)
    PGDATABASE                             — Postgres DB name (default: databricks_postgres)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import postgres as pg


def _render(text: str, params: dict[str, str]) -> str:
    for k, v in params.items():
        text = text.replace(f"${{{k}}}", v)
    return text


def _apply_postgres_schema(w: WorkspaceClient, instance: str, branch: str) -> None:
    """Remind the user to apply lakebase_schema.sql before running synced tables."""
    sql_file = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "lakebase_schema.sql"
    if not sql_file.exists():
        raise FileNotFoundError(sql_file)
    print(
        "  [postgres] Skipping Postgres DDL — apply schemas/lakebase_schema.sql "
        "manually via the Lakebase SQL editor before running this script."
    )


def main() -> int:
    # Accept LAKEBASE_INSTANCE for backward compat (same as LAKEBASE_PROJECT)
    default_project = os.environ.get("LAKEBASE_INSTANCE") or os.environ.get("LAKEBASE_PROJECT", "databricks_postgres")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog",           default=os.environ.get("UC_CATALOG", "livezerobus"))
    parser.add_argument("--schema",            default=os.environ.get("UC_SCHEMA", "procurement"))
    parser.add_argument("--lakebase-instance", default=default_project)
    parser.add_argument("--lakebase-branch",   default=os.environ.get("LAKEBASE_BRANCH", "production"))
    args = parser.parse_args()

    catalog  = args.catalog
    schema   = args.schema
    project  = args.lakebase_instance   # Lakebase project name
    branch   = args.lakebase_branch

    cfg_path = pathlib.Path(__file__).with_name("synced_tables.yml")
    cfg = yaml.safe_load(_render(cfg_path.read_text(), {
        "catalog": catalog, "schema": schema,
        "lakebase_instance": project, "lakebase_branch": branch,
    }))

    w = WorkspaceClient()

    print("Applying Lakebase Postgres schema…")
    _apply_postgres_schema(w, project, branch)

    branch_resource = f"projects/{project}/branches/{branch}"
    pg_database     = os.environ.get("PGDATABASE", "databricks_postgres")
    target_schema   = cfg["target_schema"]   # e.g. "procurement"

    print("Reconciling Synced Tables…")
    for t in cfg["tables"]:
        source   = t["source"]
        target   = t["target"]
        scheduling = t["scheduling_policy"]

        # synced_table_id = "{uc_catalog}.{pg_schema}.{table}"
        # → creates UC view livezerobus.procurement.{target}
        # → creates Postgres table {target} in schema procurement
        synced_table_id = f"{catalog}.{target_schema}.{target}"

        spec = pg.SyncedTableSyncedTableSpec(
            source_table_full_name=source,
            primary_key_columns=t["primary_keys"],
            scheduling_policy=pg.SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy(scheduling),
            timeseries_key=t.get("timeseries_key"),
            branch=branch_resource,
            postgres_database=pg_database,
            create_database_objects_if_missing=True,
        )
        synced_table_obj = pg.SyncedTable(spec=spec)

        print(f"  [sync] {source}  →  {project}/{branch}/{target_schema}.{target} [{scheduling}]")

        try:
            op = w.postgres.create_synced_table(
                synced_table=synced_table_obj,
                synced_table_id=synced_table_id,
            )
            print(f"         ✓ created")
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "alreadyexists" in msg:
                print(f"         ↳ already configured — skipped")
            elif "does not exist" in msg or "not found" in msg:
                print(f"         ⚠ source table not found in UC — skipped (run pipeline first)")
            elif "does not have view permissions on pipeline" in msg or "does not have manage permissions on pipeline" in msg:
                print(f"         ↳ pipeline already exists (configured by admin) — skipped")
            else:
                raise

    print("✔ Lakebase sync configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
