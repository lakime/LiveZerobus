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
            frontend_dist=os.environ.get("FRONTEND_DIST", "../frontend/dist"),
            refresh_interval_s=int(os.environ.get("REFRESH_INTERVAL_S", "3")),
        )
