"""Parquet-backed table storage for the SAP BDC mock service.

We don't use the deltalake package here — just plain Parquet files — but we
keep the Delta Sharing protocol semantics for compatibility with Databricks
Unity Catalog. The module is named delta_store for historical reasons.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import Settings


def _table_dir(settings: Settings, name: str) -> Path:
    return settings.data_dir / name


def _parquet_path(settings: Settings, name: str) -> Path:
    return _table_dir(settings, name) / "part-0.parquet"


def _version_path(settings: Settings, name: str) -> Path:
    return _table_dir(settings, name) / "_version.json"


def write_table(settings: Settings, name: str, df: pd.DataFrame) -> None:
    tdir = _table_dir(settings, name)
    tdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   _parquet_path(settings, name))
    vp = _version_path(settings, name)
    next_v = 0
    if vp.exists():
        next_v = int(json.loads(vp.read_text()).get("version", 0)) + 1
    vp.write_text(json.dumps({"version": next_v}))


def read_table(settings: Settings, name: str) -> pd.DataFrame:
    p = _parquet_path(settings, name)
    if not p.exists():
        return pd.DataFrame()
    return pq.read_table(p).to_pandas()


def table_version(settings: Settings, name: str) -> int:
    vp = _version_path(settings, name)
    if not vp.exists():
        return 0
    return int(json.loads(vp.read_text()).get("version", 0))


def table_metadata(settings: Settings, name: str) -> dict[str, Any]:
    p = _parquet_path(settings, name)
    if not p.exists():
        return {}
    schema = pq.read_schema(p)
    pmeta = pq.read_metadata(p)
    fields = [
        {"name": f.name, "type": _arrow_to_delta_type(f.type),
         "nullable": True, "metadata": {}}
        for f in schema
    ]
    # Optional fields populated for richer Catalog Explorer display.
    # `name` shows in the catalog header; `size` and `numFiles` populate
    # the overview / stats pane. UC's SQL engine ignores these but its
    # Catalog UI uses them.
    return {
        "id": str(uuid.UUID(bytes=hashlib.md5(name.encode()).digest())),
        "name": name,
        "format": {"provider": "parquet", "options": {}},
        "schemaString": json.dumps({"type": "struct", "fields": fields}),
        "partitionColumns": [],
        "configuration": {},
        "size": p.stat().st_size,
        "numFiles": 1,
    }


def list_table_names(settings: Settings) -> list[str]:
    if not settings.data_dir.exists():
        return []
    return sorted(
        p.name for p in settings.data_dir.iterdir()
        if p.is_dir() and (p / "part-0.parquet").exists()
    )


def table_files(settings: Settings, name: str) -> list[dict[str, Any]]:
    p = _parquet_path(settings, name)
    if not p.exists():
        return []
    meta = pq.read_metadata(p)
    return [{
        "path": "part-0.parquet",
        "size": p.stat().st_size,
        "num_records": meta.num_rows,
    }]


def table_row_count(settings: Settings, name: str) -> int:
    p = _parquet_path(settings, name)
    if not p.exists():
        return 0
    return pq.read_metadata(p).num_rows


def _arrow_to_delta_type(t: pa.DataType) -> str:
    """Map pyarrow types → Delta Lake schema type strings.

    Delta primitive type names (per the Delta Sharing v1 spec) are narrower
    than `long` / `double` — Catalog Explorer uses these to render column
    badges and may reject responses that overstate widths.
    """
    if pa.types.is_int8(t):
        return "byte"
    if pa.types.is_int16(t):
        return "short"
    if pa.types.is_int32(t):
        return "integer"
    if pa.types.is_int64(t):
        return "long"
    if pa.types.is_float32(t):
        return "float"
    if pa.types.is_float64(t):
        return "double"
    if pa.types.is_boolean(t):
        return "boolean"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "timestamp"
    if pa.types.is_binary(t):
        return "binary"
    return "string"
