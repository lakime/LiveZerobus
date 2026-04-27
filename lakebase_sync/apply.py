"""Apply synced_tables.yml against Lakebase.

Usage (from the bundle or notebook):
    databricks bundle run lakebase_sync -t dev

Creates `live.*` tables in Lakebase Postgres (via schemas/lakebase_schema.sql),
then creates/updates a Lakebase Synced Table per entry in synced_tables.yml.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import database as db


def _render(text: str, params: dict[str, str]) -> str:
    for k, v in params.items():
        text = text.replace(f"${{{k}}}", v)
    return text


def _apply_postgres_schema(w: WorkspaceClient, instance: str, branch: str) -> None:
    """Apply lakebase_schema.sql against the Lakebase database.

    The current databricks-sdk doesn't expose a generic "run arbitrary SQL
    against Lakebase" helper on DatabaseAPI, so this script expects you to
    have already applied schemas/lakebase_schema.sql manually via the
    Lakebase SQL editor (see README.md step 5a). We just sanity-check the
    file exists and move on.
    """
    sql_file = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "lakebase_schema.sql"
    if not sql_file.exists():
        raise FileNotFoundError(sql_file)
    print(
        "  [postgres] Skipping Postgres DDL — apply schemas/lakebase_schema.sql "
        "manually via the Lakebase SQL editor before running this script."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog",           default=os.environ.get("UC_CATALOG", "livezerobus"))
    parser.add_argument("--schema",            default=os.environ.get("UC_SCHEMA", "procurement"))
    parser.add_argument("--lakebase-instance", default=os.environ.get("LAKEBASE_INSTANCE", "databricks_postgres"))
    parser.add_argument("--lakebase-branch",   default=os.environ.get("LAKEBASE_BRANCH", "production"))
    args = parser.parse_args()

    catalog  = args.catalog
    schema   = args.schema
    instance = args.lakebase_instance
    branch   = args.lakebase_branch

    cfg_path = pathlib.Path(__file__).with_name("synced_tables.yml")
    cfg = yaml.safe_load(_render(cfg_path.read_text(), {
        "catalog": catalog, "schema": schema,
        "lakebase_instance": instance, "lakebase_branch": branch,
    }))

    w = WorkspaceClient()

    print("Applying Lakebase Postgres schema…")
    _apply_postgres_schema(w, cfg["instance"], cfg["target_branch"])

    print("Reconciling Synced Tables…")
    for t in cfg["tables"]:
        source = t["source"]
        target = t["target"]
        scheduling = t["scheduling_policy"]

        spec = db.SyncedTableSpec(
            source_table_full_name=source,
            primary_key_columns=t["primary_keys"],
            scheduling_policy=db.SyncedTableSchedulingPolicy(scheduling),
            timeseries_key=t.get("timeseries_key"),
        )

        synced_name = f"{cfg['target_schema']}.{target}"
        print(f"  [sync] {source}  →  {instance}/{branch}/{synced_name} [{scheduling}]")

        synced_table = db.SyncedDatabaseTable(
            name=synced_name,
            database_instance_name=cfg["instance"],
            logical_database_name=cfg["target_branch"],
            spec=spec,
        )

        try:
            w.database.create_synced_database_table(synced_table=synced_table)
        except Exception as e:
            msg = str(e).lower()
            # Fall back to update if already exists
            if "already exists" in msg or "alreadyexists" in msg:
                w.database.update_synced_database_table(
                    name=synced_name,
                    synced_table=synced_table,
                    update_mask="spec",
                )
            else:
                raise

    print("✔ Lakebase sync configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
