"""Background self-heal for the dashboard data path.

After the dashboard read path was moved to query Gold MVs directly via the
SQL warehouse, the only remaining failure mode is the Lakeflow pipeline
auto-terminating after idle — Gold MVs then stop refreshing. This module
detects that and kicks a new pipeline update.

Lakebase synced tables are no longer in the read path (data.py + the
agents both go warehouse → Gold MV directly), so this module doesn't
manage them.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

PIPELINE_ID = "4cef05ca-ea6f-4217-af60-6b75a6b1a3f4"
CATALOG = "livezerobus"
SCHEMA = "procurement"

# Trigger a pipeline update if MAX(Gold.event_ts) lags more than this.
GOLD_STALE_THRESHOLD = timedelta(minutes=10)

LOOP_INTERVAL_S = 300  # 5 min

# A representative Gold MV used to detect staleness — picks up new
# simulator output within seconds of the pipeline running.
HEALTH_TABLE = "gd_commodity_latest"
HEALTH_TS_COL = "event_ts"


# ── Public state for /api/admin/recovery/status ───────────────────────────

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": True,
    "last_cycle_started": None,
    "last_cycle_finished": None,
    "last_action": None,
    "last_error": None,
    "actions": [],   # last 20 actions
}


def get_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def _record(msg: str) -> None:
    log.info("[auto-recovery] %s", msg)
    with _state_lock:
        _state["last_action"] = msg
        _state["actions"].append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "msg": msg,
        })
        if len(_state["actions"]) > 20:
            _state["actions"] = _state["actions"][-20:]


def _record_error(e: Exception) -> None:
    log.exception("[auto-recovery] %s", e)
    with _state_lock:
        _state["last_error"] = f"{type(e).__name__}: {e}"


def _client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient()


# ── Pipeline ──────────────────────────────────────────────────────────────

def pipeline_state() -> dict[str, Any]:
    p = _client().pipelines.get(PIPELINE_ID)
    latest = (p.latest_updates or [None])[0]
    return {
        "name": p.name,
        "state": str(p.state) if p.state else None,
        "latest_update_state": str(latest.state) if latest else None,
        "latest_update_id": latest.update_id if latest else None,
    }


def trigger_pipeline_if_needed() -> bool:
    """Trigger a new update if none is already running."""
    try:
        w = _client()
        p = w.pipelines.get(PIPELINE_ID)
        latest = (p.latest_updates or [None])[0]
        if latest and str(latest.state) in (
            "UpdateInfoState.WAITING_FOR_RESOURCES",
            "UpdateInfoState.INITIALIZING",
            "UpdateInfoState.RESETTING",
            "UpdateInfoState.SETTING_UP_TABLES",
            "UpdateInfoState.RUNNING",
            "UpdateInfoState.CREATED",
        ):
            _record(f"pipeline already running ({latest.state})")
            return False
        w.pipelines.start_update(pipeline_id=PIPELINE_ID, full_refresh=False)
        _record("kicked Lakeflow pipeline update")
        return True
    except Exception as e:
        # ResourceConflict on start_update means a pipeline update was started
        # between our check and our trigger — race condition, harmless.
        if "ResourceConflict" in type(e).__name__ or "already exists" in str(e):
            _record(f"pipeline race: another update started concurrently")
            return False
        _record_error(e)
        return False


# ── Gold freshness via SQL warehouse ──────────────────────────────────────

def _run_sql(sql: str) -> list[dict[str, Any]]:
    import os
    from databricks.sdk.service.sql import StatementState
    warehouse_id = os.environ.get("SAP_BDC_WAREHOUSE_ID") or "6a1fb3b32b00f1cd"
    w = _client()
    r = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout="30s",
    )
    if r.status and r.status.state != StatementState.SUCCEEDED:
        msg = (r.status.error.message if r.status.error else str(r.status.state))[:200]
        raise RuntimeError(f"SQL failed: {msg}")
    if not r.result or not r.manifest:
        return []
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def gold_freshness() -> dict[str, Any]:
    """Return latest_ts on the canary Gold MV."""
    try:
        rows = _run_sql(f"SELECT MAX({HEALTH_TS_COL}) AS latest FROM {CATALOG}.{SCHEMA}.{HEALTH_TABLE}")
        return {"latest": rows[0].get("latest") if rows else None}
    except Exception as e:
        return {"error": str(e)[:200]}


# ── Heal cycle ────────────────────────────────────────────────────────────

def _parse(ts) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def run_recovery_cycle() -> dict[str, Any]:
    """One pass: kick the pipeline if Gold MVs are stale. Idempotent."""
    with _state_lock:
        _state["last_cycle_started"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _state["last_error"] = None

    summary: dict[str, Any] = {"pipeline_kicked": False}

    try:
        fr = gold_freshness()
        summary["gold_freshness"] = fr
        latest = _parse(fr.get("latest"))
        now = datetime.now(timezone.utc)
        if latest is None or (now - latest) > GOLD_STALE_THRESHOLD:
            _record(
                f"Gold MV is stale (latest={fr.get('latest')}, threshold={GOLD_STALE_THRESHOLD});"
                " triggering pipeline"
            )
            if trigger_pipeline_if_needed():
                summary["pipeline_kicked"] = True
        else:
            _record(f"Gold MV is fresh ({fr.get('latest')}); no action")
    except Exception as e:
        _record_error(e)
    finally:
        with _state_lock:
            _state["last_cycle_finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return summary


# ── Background loop ───────────────────────────────────────────────────────

_loop_started = False
_loop_lock = threading.Lock()


def start_background_loop() -> None:
    """Idempotent — start the heal thread once per process."""
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True

    def _loop():
        time.sleep(20)  # let app finish boot
        while True:
            if _state.get("enabled"):
                try:
                    run_recovery_cycle()
                except Exception as e:
                    _record_error(e)
            time.sleep(LOOP_INTERVAL_S)

    threading.Thread(target=_loop, daemon=True, name="auto-recovery").start()
    _record("background loop started")
