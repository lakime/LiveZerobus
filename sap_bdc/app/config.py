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
        return cls(
            token=os.environ.get("SAP_BDC_TOKEN", "changeme"),
            host=os.environ.get("HOST", "http://localhost:8080").rstrip("/"),
            data_dir=Path(data_dir),
        )

    @property
    def share_name(self) -> str:
        return "sap-procurement"

    @property
    def schema_name(self) -> str:
        return "procurement"
