"""Read/write Delta Lake tables using the deltalake (delta-rs) package."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa  # needed for arro3 → pyarrow conversion
from deltalake import DeltaTable, write_deltalake


def _add_actions_dict(dt: DeltaTable) -> dict:
    """Convert get_add_actions result to plain dict regardless of deltalake version."""
    actions = dt.get_add_actions(flatten=True)
    if hasattr(actions, "to_pydict"):
        return actions.to_pydict()
    # deltalake 1.x returns an arro3 Table — convert via Arrow C stream
    arrow_table = pa.RecordBatchReader.from_stream(actions).read_all()
    return arrow_table.to_pydict()

from .config import Settings


def _table_path(settings: Settings, name: str) -> Path:
    return settings.data_dir / name


def write_table(settings: Settings, name: str, df: pd.DataFrame) -> None:
    path = str(_table_path(settings, name))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    write_deltalake(path, df, mode="overwrite", schema_mode="overwrite")


def read_table(settings: Settings, name: str) -> pd.DataFrame:
    path = _table_path(settings, name)
    if not path.exists():
        return pd.DataFrame()
    dt = DeltaTable(str(path))
    return dt.to_pandas()


def table_version(settings: Settings, name: str) -> int:
    path = _table_path(settings, name)
    if not path.exists():
        return 0
    return DeltaTable(str(path)).version()


def table_metadata(settings: Settings, name: str) -> dict[str, Any]:
    path = _table_path(settings, name)
    if not path.exists():
        return {}
    dt = DeltaTable(str(path))
    fields = []
    for field in dt.schema().fields:
        fields.append({
            "name": field.name,
            "type": _delta_type_str(str(field.type)),
            "nullable": field.nullable,
            "metadata": {},
        })
    schema_str = json.dumps({"type": "struct", "fields": fields})
    return {
        "id": str(dt.metadata().id),
        "format": {"provider": "parquet", "options": {}},
        "schemaString": schema_str,
        "partitionColumns": dt.metadata().partition_columns,
        "configuration": {},
    }


def list_table_names(settings: Settings) -> list[str]:
    if not settings.data_dir.exists():
        return []
    return sorted(
        p.name for p in settings.data_dir.iterdir()
        if p.is_dir() and (p / "_delta_log").exists()
    )


def table_files(settings: Settings, name: str) -> list[dict[str, Any]]:
    """Return list of Parquet file metadata for Delta Sharing query response."""
    path = _table_path(settings, name)
    if not path.exists():
        return []
    dt = DeltaTable(str(path))
    add_actions = _add_actions_dict(dt)
    files = []
    for i, rel_path in enumerate(add_actions.get("path", [])):
        size = add_actions.get("size_bytes", [0] * (i + 1))[i] or 0
        num_records = add_actions.get("num_records", [0] * (i + 1))[i] or 0
        files.append({
            "path": rel_path,
            "size": int(size),
            "num_records": int(num_records),
        })
    return files


def table_row_count(settings: Settings, name: str) -> int:
    path = _table_path(settings, name)
    if not path.exists():
        return 0
    try:
        actions = _add_actions_dict(DeltaTable(str(path)))
        return int(sum(actions.get("num_records", []) or [0]))
    except Exception:
        return 0


def _delta_type_str(type_repr: str) -> str:
    """Convert deltalake PrimitiveType string repr to Delta Sharing type name."""
    # type_repr looks like: PrimitiveType("long"), PrimitiveType("string"), etc.
    import re
    m = re.search(r'"([^"]+)"', type_repr)
    if m:
        return m.group(1)
    return "string"
