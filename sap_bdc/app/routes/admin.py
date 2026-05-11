from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..config import Settings
from ..delta_store import list_table_names, table_row_count
from ..generator import TABLE_ORDER, generate_all

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["admin"])


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
    return {
        "share": s.share_name,
        "schema": s.schema_name,
        "endpoint": f"{s.host}/delta-sharing",
        "host": s.host,
        "tables_ready": len(names),
        "tables_total": len(TABLE_ORDER),
    }
