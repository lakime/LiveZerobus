"""Apply synced_tables.yml against Lakebase.

Usage (from the bundle or notebook):
    databricks bundle run lakebase_sync -t dev

Creates `live.*` tables in Lakebase Postgres (via schemas/lakebase_schema.sql),
then creates/updates a Lakebase Synced Table per entry in synced_tables.yml.
"""
from __future__ import annotations

import os
import pathlib
import re
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

    The SDK exposes statement execution against Lakebase via the
    DatabaseAPI / query endpoint. If your SDK version doesn't expose it,
    run the file manually in the Databricks SQL editor against the
    `databricks_postgres` connection.
    """
    sql_file = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "lakebase_schema.sql"
    sql = sql_file.read_text()
    statements = [s.strip() for s in re.split(r";\s*\n", sql) if s.strip()]

    for stmt in statements:
        print(f"  [postgres] {stmt.splitlines()[0][:100]}…")
        w.database.execute_database_query(
            instance_name=instance,
            branch=branch,
            query=stmt,
        )


def main() -> int:
    catalog = os.environ.get("UC_CATALOG", "main")
    schema = os.environ.get("UC_SCHEMA", "procurement")
    instance = os.environ.get("LAKEBASE_INSTANCE", "databricks_postgres")
    branch = os.environ.get("LAKEBASE_BRANCH", "production")

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

        try:
            w.database.create_synced_database_table(
                name=synced_name,
                database_instance_name=cfg["instance"],
                logical_database_name=cfg["target_branch"],
                spec=spec,
            )
        except Exception as e:
            # Fall back to update if already exists
            if "already exists" in str(e).lower():
                w.database.update_synced_database_table(
                    name=synced_name,
                    database_instance_name=cfg["instance"],
                    logical_database_name=cfg["target_branch"],
                    spec=spec,
                )
            else:
                raise

    print("✔ Lakebase sync configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
