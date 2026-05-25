"""Admin endpoints for inspecting / triggering the self-heal recovery."""
from __future__ import annotations

import threading

from fastapi import APIRouter

from .. import auto_recovery

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/recovery/status")
def recovery_status() -> dict:
    """Current self-healer state + last 20 actions."""
    s = auto_recovery.get_status()
    try:
        s["pipeline"] = auto_recovery.pipeline_state()
    except Exception as e:
        s["pipeline_error"] = str(e)[:200]
    return s


@router.get("/recovery/freshness")
def recovery_freshness() -> dict:
    """Per-table drift between Gold MV and Lakebase synced table."""
    try:
        return {"freshness": auto_recovery.check_freshness()}
    except Exception as e:
        return {"error": str(e)[:300]}


@router.post("/recovery/run")
def recovery_run() -> dict:
    """Force a recovery cycle now (returns immediately; work happens in
    a background thread)."""
    threading.Thread(target=auto_recovery.run_recovery_cycle, daemon=True).start()
    return {"started": True}
