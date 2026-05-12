"""Delta Sharing REST endpoints — implements the Delta Sharing Protocol v1."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ..config import Settings
from ..delta_store import (
    list_table_names, table_files, table_metadata, table_version,
)
from .auth import sign_file_token, verify_bearer, verify_file_token
from .protocol import PROTOCOL_LINE, file_line, metadata_line, ndjson

log = logging.getLogger(__name__)
router = APIRouter(tags=["delta-sharing"])

NDJSON = "application/x-ndjson; charset=utf-8"
SHARE_ID = "sap-procurement-share-v1"
SCHEMA_ID = "procurement-schema-v1"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# ── Authentication dependency ─────────────────────────────────────────────────

def _auth(request: Request) -> None:
    s = _settings(request)
    verify_bearer(request, s.token)


# ── Shares ────────────────────────────────────────────────────────────────────

@router.get("/shares")
def list_shares(request: Request):
    _auth(request)
    s = _settings(request)
    return {"items": [{"name": s.share_name, "id": SHARE_ID}], "nextPageToken": None}


@router.get("/shares/{share}")
def get_share(share: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    return {"share": {"name": s.share_name, "id": SHARE_ID}}


# ── Schemas ───────────────────────────────────────────────────────────────────

@router.get("/shares/{share}/schemas")
def list_schemas(share: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    return {"items": [{"name": s.schema_name, "share": s.share_name}], "nextPageToken": None}


# ── Tables ────────────────────────────────────────────────────────────────────

@router.get("/shares/{share}/schemas/{schema}/tables")
def list_tables(share: str, schema: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    names = list_table_names(s)
    items = [
        {"name": name, "schema": s.schema_name, "share": s.share_name,
         "id": _table_id(name), "shareId": SHARE_ID}
        for name in names
    ]
    return {"items": items, "nextPageToken": None}


@router.get("/shares/{share}/all-tables")
def list_all_tables(share: str, request: Request):
    """Delta Sharing v1: lists all tables across all schemas in a share."""
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    names = list_table_names(s)
    items = [
        {"name": name, "schema": s.schema_name, "share": s.share_name,
         "id": _table_id(name), "shareId": SHARE_ID}
        for name in names
    ]
    return {"items": items, "nextPageToken": None}


@router.get("/shares/{share}/schemas/{schema}/tables/{table}/version")
def table_ver(share: str, schema: str, table: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    _assert_table(table, s)
    return Response(
        content="",
        headers={"Delta-Table-Version": str(table_version(s, table))},
    )


@router.get("/shares/{share}/schemas/{schema}/tables/{table}/metadata")
def table_meta(share: str, schema: str, table: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    _assert_table(table, s)
    meta = table_metadata(s, table)
    body = ndjson(PROTOCOL_LINE, metadata_line(meta))
    return Response(
        content=body, media_type=NDJSON,
        headers={"Delta-Table-Version": str(table_version(s, table))},
    )


@router.post("/shares/{share}/schemas/{schema}/tables/{table}/query")
def query_table(share: str, schema: str, table: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    _assert_table(table, s)

    meta = table_metadata(s, table)
    files = table_files(s, table)

    lines = [PROTOCOL_LINE, metadata_line(meta)]
    for f in files:
        basename = Path(f["path"]).name
        token = sign_file_token(s.token, table, basename)
        url = f"{s.host}/delta-sharing/files/{table}/{token}/{basename}"
        fid = hashlib.md5(f["path"].encode()).hexdigest()
        lines.append(file_line(url, fid, f["size"], f["num_records"]))

    body = ndjson(*lines)
    return Response(
        content=body, media_type=NDJSON,
        headers={"Delta-Table-Version": str(table_version(s, table))},
    )


# ── File serving ──────────────────────────────────────────────────────────────

@router.get("/files/{table}/{token}/{filename}")
def serve_file(table: str, token: str, filename: str, request: Request):
    s = _settings(request)
    # File tokens are self-authenticating (HMAC-signed), no bearer needed here.
    if not verify_file_token(s.token, token, table, filename):
        raise HTTPException(status_code=403, detail="Invalid or expired file token")

    # Walk all parquet files in the table directory to find the matching one.
    table_dir = s.data_dir / table
    matched: Path | None = None
    for p in table_dir.rglob("*.parquet"):
        if p.name == filename:
            matched = p
            break
    if matched is None or not matched.exists():
        raise HTTPException(status_code=404, detail="File not found")

    def _stream():
        with open(matched, "rb") as fh:
            while chunk := fh.read(65536):
                yield chunk

    return StreamingResponse(
        _stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_share(share: str, s: Settings) -> None:
    if share != s.share_name:
        raise HTTPException(status_code=404, detail=f"Share '{share}' not found")


def _assert_schema(schema: str, s: Settings) -> None:
    if schema != s.schema_name:
        raise HTTPException(status_code=404, detail=f"Schema '{schema}' not found")


def _assert_table(table: str, s: Settings) -> None:
    tables = list_table_names(s)
    if table not in tables:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found")


def _table_id(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()


# Catch-all for any unknown /delta-sharing/* path so clients always get
# a proper JSON 404 instead of the React SPA's HTML.
@router.get("/{rest:path}", include_in_schema=False)
def sharing_not_found(rest: str):
    raise HTTPException(status_code=404, detail=f"Unknown Delta Sharing endpoint: /{rest}")
