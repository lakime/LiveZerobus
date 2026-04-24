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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            pghost=os.environ.get("PGHOST", "localhost"),
            pgport=int(os.environ.get("PGPORT", "5432")),
            pgdatabase=os.environ.get("PGDATABASE", "databricks_postgres"),
            pguser=os.environ.get("PGUSER", "app"),
            schema=os.environ.get("PG_SCHEMA", "live"),
            # Default matches the deployed layout where the React bundle has
            # been copied into backend/static/ by scripts/build_frontend.sh.
            # For local dev (`uvicorn app.main:app --reload` from backend/),
            # override with FRONTEND_DIST=../frontend/dist.
            frontend_dist=os.environ.get("FRONTEND_DIST", "static"),
            refresh_interval_s=int(os.environ.get("REFRESH_INTERVAL_S", "3")),
        )
