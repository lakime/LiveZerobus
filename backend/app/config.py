"""Runtime configuration read from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    pghost: str
    pgport: int
    pgdatabase: str
    pguser: str
    schema: str
    frontend_dist: str
    refresh_interval_s: int
    # SAP BDC integration — Delta Sharing catalog mounted in UC.
    sap_bdc_warehouse_id: str
    sap_bdc_catalog: str
    sap_bdc_schema: str
    # Genie embed: workspace host (for iframe URL) and space id.
    databricks_host: str
    genie_space_id: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            pghost=os.environ.get("PGHOST", "localhost"),
            pgport=int(os.environ.get("PGPORT", "5432")),
            pgdatabase=os.environ.get("PGDATABASE", "databricks_postgres"),
            pguser=os.environ.get("PGUSER", "app"),
            schema=os.environ.get("PG_SCHEMA", "procurement"),
            # Default matches the deployed layout where the React bundle has
            # been copied into backend/static/ by scripts/build_frontend.sh.
            # For local dev (`uvicorn app.main:app --reload` from backend/),
            # override with FRONTEND_DIST=../frontend/dist.
            frontend_dist=os.environ.get("FRONTEND_DIST", "static"),
            refresh_interval_s=int(os.environ.get("REFRESH_INTERVAL_S", "3")),
            # Optional. If unset, the SAP BDC tab shows "not connected".
            sap_bdc_warehouse_id=os.environ.get("SAP_BDC_WAREHOUSE_ID", ""),
            sap_bdc_catalog=os.environ.get("SAP_BDC_CATALOG", "sapsofts"),
            sap_bdc_schema=os.environ.get("SAP_BDC_SCHEMA", "procurement"),
            # Genie iframe embed. If GENIE_SPACE_ID is empty, the Genie tab
            # shows setup instructions instead of an iframe.
            databricks_host=os.environ.get("DATABRICKS_HOST", "").rstrip("/"),
            genie_space_id=os.environ.get("GENIE_SPACE_ID", ""),
        )
