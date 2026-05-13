"""Delta Sharing REST endpoints — implements the Delta Sharing Protocol v1."""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..config import Settings
from ..delta_store import (
    list_table_names, table_files, table_metadata, table_version,
)
from .auth import sign_file_token, verify_bearer, verify_file_token
from .protocol import PROTOCOL_LINE, file_line, metadata_line, ndjson
from .visibility import is_shared

log = logging.getLogger(__name__)
router = APIRouter(tags=["delta-sharing"])

NDJSON = "application/x-ndjson; charset=utf-8"

# Delta Sharing requires entity IDs to be valid UUIDs. We derive them
# deterministically from stable names (md5 → 16 bytes → UUID).
def _stable_uuid(name: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(name.encode()).digest()))

SHARE_ID = _stable_uuid("share:sap-procurement")
SCHEMA_ID = _stable_uuid("schema:procurement")


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
    names = [n for n in list_table_names(s) if is_shared(s, n)]
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
    names = [n for n in list_table_names(s) if is_shared(s, n)]
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
    actual = _assert_table(table, s)
    return Response(
        content="",
        headers={"Delta-Table-Version": str(table_version(s, actual))},
    )


@router.get("/shares/{share}/schemas/{schema}/tables/{table}/metadata")
def table_meta(share: str, schema: str, table: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    actual = _assert_table(table, s)
    meta = table_metadata(s, actual)
    body = ndjson(PROTOCOL_LINE, metadata_line(meta))
    return Response(
        content=body, media_type=NDJSON,
        headers={"Delta-Table-Version": str(table_version(s, actual))},
    )


@router.post("/shares/{share}/schemas/{schema}/tables/{table}/query")
def query_table(share: str, schema: str, table: str, request: Request):
    _auth(request)
    s = _settings(request)
    _assert_share(share, s)
    _assert_schema(schema, s)
    actual = _assert_table(table, s)

    meta = table_metadata(s, actual)
    files = table_files(s, actual)

    lines = [PROTOCOL_LINE, metadata_line(meta)]
    for f in files:
        basename = Path(f["path"]).name
        token = sign_file_token(s.token, actual, basename)
        url = f"{s.host}/delta-sharing/files/{actual}/{token}/{basename}"
        fid = _stable_uuid(f"file:{actual}:{f['path']}")
        lines.append(file_line(url, fid, f["size"], f["num_records"]))

    body = ndjson(*lines)
    return Response(
        content=body, media_type=NDJSON,
        headers={"Delta-Table-Version": str(table_version(s, actual))},
    )


# ── File serving ──────────────────────────────────────────────────────────────

@router.api_route("/files/{table}/{token}/{filename}", methods=["GET", "HEAD"])
def serve_file(table: str, token: str, filename: str, request: Request):
    s = _settings(request)
    # File tokens are self-authenticating (HMAC-signed), no bearer needed here.
    if not verify_file_token(s.token, token, table, filename):
        log.warning("file-token-invalid-or-expired: table=%r filename=%r", table, filename)
        raise HTTPException(status_code=403, detail="Invalid or expired file token")

    # _resolve_table enforces visibility. A token issued before the table
    # was disabled becomes inert — the file can't be fetched while disabled.
    try:
        actual_table = _resolve_table(table, s)
    except HTTPException:
        raise HTTPException(status_code=404, detail="File not found")

    table_dir = s.data_dir / actual_table
    matched: Path | None = None
    for p in table_dir.rglob("*.parquet"):
        if p.name == filename:
            matched = p
            break
    if matched is None or not matched.exists():
        log.warning("file-not-found: table=%r filename=%r", actual_table, filename)
        raise HTTPException(status_code=404, detail="File not found")

    # FileResponse sets Content-Length automatically — required by Databricks
    # UC's Apache HttpClient (chunked transfer encoding gets rejected).
    return FileResponse(
        str(matched),
        media_type="application/octet-stream",
        filename=filename,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_share(share: str, s: Settings) -> None:
    if share != s.share_name:
        raise HTTPException(status_code=404, detail=f"Share '{share}' not found")


def _assert_schema(schema: str, s: Settings) -> None:
    if schema != s.schema_name:
        raise HTTPException(status_code=404, detail=f"Schema '{schema}' not found")


def _resolve_table(table: str, s: Settings) -> str:
    """Case-insensitive table lookup that also enforces the visibility flag.
    Databricks UC lowercases names (`ekko` → must resolve to `EKKO`).
    Tables that exist but are not currently shared return the same 404
    so external clients can't distinguish "exists but disabled" from
    "doesn't exist"."""
    tables = list_table_names(s)
    target = table.lower()
    for t in tables:
        if t.lower() == target:
            if not is_shared(s, t):
                log.warning("table-not-shared lookup: client asked for %r (resolved to %r) but it is disabled", table, t)
                raise HTTPException(status_code=404, detail=f"Table '{table}' not found")
            return t
    log.warning("table-not-found lookup: client asked for %r; on disk: %s", table, sorted(tables))
    raise HTTPException(status_code=404, detail=f"Table '{table}' not found")


def _assert_table(table: str, s: Settings) -> str:
    return _resolve_table(table, s)


def _table_id(name: str) -> str:
    return _stable_uuid(f"table:{name}")


# Catch-all for any unknown /delta-sharing/* path so clients always get
# a proper JSON 404 instead of the React SPA's HTML.
@router.get("/{rest:path}", include_in_schema=False)
def sharing_not_found(rest: str):
    log.warning("unknown-delta-sharing-path: GET /%s", rest)
    raise HTTPException(status_code=404, detail=f"Unknown Delta Sharing endpoint: /{rest}")
