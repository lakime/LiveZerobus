"""Delta Sharing Protocol v1 — NDJSON serialization helpers."""
from __future__ import annotations

import json
from typing import Any


PROTOCOL_LINE = json.dumps({"protocol": {"minReaderVersion": 1}})


def metadata_line(meta: dict[str, Any]) -> str:
    return json.dumps({"metaData": meta})


def file_line(url: str, file_id: str, size: int, num_records: int) -> str:
    return json.dumps({
        "file": {
            "url": url,
            "id": file_id,
            "partitionValues": {},
            "size": size,
            "stats": json.dumps({"numRecords": num_records}),
            "version": 0,
            "timestamp": None,
        }
    })


def ndjson(*lines: str) -> str:
    return "\n".join(lines) + "\n"
