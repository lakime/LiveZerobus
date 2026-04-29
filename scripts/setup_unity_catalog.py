"""Bootstrap Unity Catalog: catalog, schema, Bronze tables, seed dimensions.

Run via the bundle:
    databricks bundle run setup_unity_catalog -t dev

or directly as a Databricks notebook / job. It executes the SQL files under
`schemas/` against the configured SQL Warehouse.
"""
from __future__ import annotations

import os
import pathlib
import sys
import textwrap

from databricks.sdk import WorkspaceClient


def _render(sql_text: str, params: dict[str, str]) -> str:
    for k, v in params.items():
        sql_text = sql_text.replace(f"${{{k}}}", v)
    return sql_text


def _run_sql_file(w: WorkspaceClient, warehouse_id: str, path: pathlib.Path, params: dict[str, str]) -> None:
    print(f"--> Running {path.name}")
    sql = _render(path.read_text(), params)
    # Split on `;` at end of line — keeps it simple, none of our DDL uses semicolons inline.
    statements = [s.strip() for s in sql.split(";\n") if s.strip()]
    for stmt in statements:
        preview = textwrap.shorten(stmt.replace("\n", " "), width=120)
        print(f"    • {preview}")
        resp = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=stmt,
            wait_timeout="30s",
        )
        if resp.status and resp.status.state.value in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Statement failed: {resp.status.error}")


def main() -> int:
    catalog = os.environ.get("UC_CATALOG", "livezerobus")
    schema = os.environ.get("UC_SCHEMA", "procurement")
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    service_principal = os.environ.get("SERVICE_PRINCIPAL", "app-3dxwqo livezerobus")

    params = {
        "catalog": catalog,
        "schema": schema,
        "service_principal": service_principal,
    }

    w = WorkspaceClient()
    root = pathlib.Path(__file__).resolve().parents[1] / "schemas"

    for fname in ("bronze_tables.sql", "seed_dimensions.sql"):
        _run_sql_file(w, warehouse_id, root / fname, params)

    print("✔ Unity Catalog setup complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
