from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    token: str
    host: str
    data_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = os.environ.get("DATA_DIR", "./data/delta")
        raw_host = os.environ.get("HOST", "http://localhost:8080").rstrip("/")
        # Tolerate HOST without a scheme — assume https for any non-localhost.
        if not raw_host.startswith(("http://", "https://")):
            raw_host = ("http://" if raw_host.startswith("localhost") else "https://") + raw_host
        return cls(
            token=os.environ.get("SAP_BDC_TOKEN", "changeme"),
            host=raw_host,
            data_dir=Path(data_dir),
        )

    @property
    def share_name(self) -> str:
        return "sap-procurement"

    @property
    def schema_name(self) -> str:
        return "procurement"
