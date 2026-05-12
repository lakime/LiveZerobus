"""Synchronous SQL warehouse query helper using the Databricks SDK.

Used by the SAP BDC routes to query Delta tables in `${SAP_BDC_CATALOG}.${SAP_BDC_SCHEMA}.*`.
Lakebase Postgres handles all other read paths — see `lakebase.py`.
"""
from __future__ import annotations

import logging
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from .config import Settings

log = logging.getLogger(__name__)


class WarehouseNotConfigured(RuntimeError):
    pass


def _client() -> WorkspaceClient:
    # WorkspaceClient picks up DATABRICKS_HOST / CLIENT_ID / CLIENT_SECRET
    # the same way `lakebase.py` does.
    return WorkspaceClient()


def execute(
    settings: Settings,
    sql: str,
    parameters: list[dict[str, Any]] | None = None,
    wait_timeout: str = "30s",
) -> list[dict[str, Any]]:
    """Run a SQL statement against the configured warehouse, return list-of-dicts.

    `parameters` follows the SDK convention: `[{"name": "lifnr", "value": "..."}, ...]`
    paired with `:lifnr` style placeholders in the SQL.
    """
    if not settings.sap_bdc_warehouse_id:
        raise WarehouseNotConfigured(
            "SAP_BDC_WAREHOUSE_ID is not set — SAP BDC features are disabled."
        )

    w = _client()
    r = w.statement_execution.execute_statement(
        warehouse_id=settings.sap_bdc_warehouse_id,
        statement=sql,
        parameters=parameters,
        wait_timeout=wait_timeout,
        catalog=settings.sap_bdc_catalog,
        schema=settings.sap_bdc_schema,
    )

    if r.status and r.status.state not in (StatementState.SUCCEEDED, None):
        msg = r.status.error.message if r.status.error else f"state={r.status.state}"
        raise RuntimeError(f"SQL query failed: {msg}")

    if not r.result or not r.manifest or not r.manifest.schema:
        return []

    columns = [c.name for c in r.manifest.schema.columns]
    data_array = r.result.data_array or []
    return [dict(zip(columns, row)) for row in data_array]


def catalog_available(settings: Settings) -> bool:
    """Check whether the SAP BDC catalog/schema actually exist and have tables."""
    if not settings.sap_bdc_warehouse_id:
        return False
    try:
        rows = execute(
            settings,
            f"SHOW TABLES IN {settings.sap_bdc_catalog}.{settings.sap_bdc_schema}",
        )
        return len(rows) > 0
    except Exception as e:
        log.warning("SAP BDC catalog check failed: %s", e)
        return False
