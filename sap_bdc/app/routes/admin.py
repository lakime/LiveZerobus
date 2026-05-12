from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..config import Settings
from ..delta_store import list_table_names, table_row_count
from ..generator import TABLE_ORDER, generate_all
from ..sharing import visibility

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["admin"])


class SharingToggle(BaseModel):
    enabled: bool


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/regenerate")
def regenerate(request: Request) -> dict:
    s = _settings(request)
    log.info("Regenerating all SAP tables (forced)…")
    generate_all(s, force=True)
    names = list_table_names(s)
    return {
        "ok": True,
        "tables": [{"name": n, "rows": table_row_count(s, n)} for n in TABLE_ORDER if n in names],
    }


@router.get("/profile.json")
def download_profile(request: Request) -> Response:
    s = _settings(request)
    profile = {
        "shareCredentialsVersion": 1,
        "endpoint": f"{s.host}/delta-sharing",
        "bearerToken": s.token,
        "expirationTime": None,
    }
    return Response(
        content=json.dumps(profile, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sap-bdc-profile.json"'},
    )


@router.get("/info")
def info(request: Request) -> dict:
    s = _settings(request)
    names = list_table_names(s)
    enabled = visibility.list_enabled(s)
    return {
        "share": s.share_name,
        "schema": s.schema_name,
        "endpoint": f"{s.host}/delta-sharing",
        "host": s.host,
        "tables_ready": len(names),
        "tables_total": len(TABLE_ORDER),
        "tables_shared": len(enabled),
    }


# ── Per-table sharing controls ──────────────────────────────────────────────

@router.get("/sharing")
def sharing_status(request: Request) -> dict:
    """Return per-table sharing state. enabled[] are the tables currently
    visible over the Delta Sharing protocol; disabled[] are present on
    disk but not shared."""
    s = _settings(request)
    enabled = set(visibility.list_enabled(s))
    on_disk = list_table_names(s)
    return {
        "tables": [
            {"name": n, "enabled": n in enabled} for n in TABLE_ORDER if n in on_disk
        ],
        "enabled_count": len(enabled),
        "total_count": len([n for n in TABLE_ORDER if n in on_disk]),
    }


# Bulk endpoints MUST come before the parameterized `/sharing/{table}`,
# otherwise FastAPI matches them against {table} and demands the JSON body
# the per-table endpoint requires, returning 422.
@router.post("/sharing/enable-all")
def sharing_enable_all(request: Request) -> dict:
    s = _settings(request)
    names = list_table_names(s)
    visibility.enable_all(s, names)
    return {"enabled": names}


@router.post("/sharing/disable-all")
def sharing_disable_all(request: Request) -> dict:
    s = _settings(request)
    visibility.disable_all(s)
    return {"enabled": []}


@router.post("/sharing/{table}")
def sharing_set(table: str, body: SharingToggle, request: Request) -> dict:
    s = _settings(request)
    # Resolve case so user can POST /api/sharing/ekko and it toggles EKKO.
    on_disk = list_table_names(s)
    target = table.lower()
    canonical = next((n for n in on_disk if n.lower() == target), None)
    if canonical is None:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found")
    if body.enabled:
        visibility.enable(s, canonical)
    else:
        visibility.disable(s, canonical)
    return {"name": canonical, "enabled": body.enabled}
