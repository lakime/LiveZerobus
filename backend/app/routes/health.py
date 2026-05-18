"""Demo-day health check endpoints.

Mirrors the CLI script `scripts/pre_demo_warmup.py` so operators can see and
heal the data pipeline from the UI instead of dropping to a shell.

Read endpoint:
  GET  /api/health/status         — per-layer freshness across Bronze, Gold,
                                    Lakebase, SAP BDC. Cached ~30 s server-side
                                    so the polling tab doesn't hammer the
                                    warehouse / Postgres pool.

Write endpoint:
  POST /api/health/trigger-pipeline — kick the Lakeflow pipeline if Gold is
                                      stale. Read-only relative to data; just
                                      requests an update.

Synced-table reset (the destructive recovery in reset_synced_tables.py) is
deliberately NOT exposed here — the operator should run that from the CLI.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Any

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings
from ..lakebase import query as lakebase_query
from ..warehouse import WarehouseNotConfigured, execute as warehouse_execute

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])

MAIN_PIPELINE_ID = "4cef05ca-ea6f-4217-af60-6b75a6b1a3f4"

# Per-layer freshness thresholds (minutes). Anything older is "stale".
BRONZE_MAX_AGE_MIN = 10
GOLD_MAX_AGE_MIN = 30
LAKEBASE_MAX_AGE_MIN = 30

# Bronze tables to sample. event_ts is the canonical Zerobus timestamp.
BRONZE_TABLES = [
    ("bz_commodity_prices", "event_ts"),
    ("bz_inventory_events", "event_ts"),
    ("bz_iot_sensor_events", "event_ts"),
]

# Gold tables to sample (those most often empty when something is wrong).
GOLD_TABLES = [
    ("gd_commodity_latest", "event_ts"),
    ("gd_demand_1h", "hour_ts"),
    ("gd_procurement_recommendations", "created_ts"),
]

# Lakebase synced tables to sample.
LAKEBASE_TABLES = [
    ("commodity_prices_latest", "event_ts"),
    ("demand_1h", "hour_ts"),
    ("inventory_snapshot", "last_event_ts"),
    ("iot_sensor_latest", "event_ts"),
    ("procurement_recommendations", "created_ts"),
]

# In-process cache so the polling Health tab doesn't trigger a warehouse hit
# every 3 seconds. 30 s is short enough to feel live during demo prep.
_CACHE_TTL_S = 30.0
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"value": None, "ts": 0.0}


def get_settings() -> Settings:
    return Settings.from_env()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _age_min(ts: dt.datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return (_now() - ts).total_seconds() / 60.0


def _classify(age_min: float | None, max_age_min: int, count: int | None = None) -> str:
    if age_min is None:
        return "no_data"
    if count is not None and count == 0:
        return "no_data"
    return "fresh" if age_min <= max_age_min else "stale"


def _parse_ts(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    s = str(value)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _check_delta_layer(
    settings: Settings,
    layer: str,
    tables: list[tuple[str, str]],
    max_age_min: int,
) -> dict[str, Any]:
    """Run one SELECT-max statement per table via the SQL warehouse."""
    out_tables: list[dict[str, Any]] = []
    overall_fresh = True
    if not settings.sap_bdc_warehouse_id:
        # warehouse module is shared with sap-bdc — same env var gates both
        return {
            "name": layer,
            "status": "unknown",
            "error": "SAP_BDC_WAREHOUSE_ID not configured — can't query Delta tables",
            "tables": [],
        }
    for tbl, ts_col in tables:
        try:
            rows = warehouse_execute(
                settings,
                f"SELECT count(*) AS n, max({ts_col}) AS ts "
                f"FROM livezerobus.procurement.{tbl}",
            )
            row = rows[0] if rows else {}
            count = int(row.get("n") or 0)
            ts = _parse_ts(row.get("ts"))
            age = _age_min(ts)
            status = _classify(age, max_age_min, count)
            if status != "fresh":
                overall_fresh = False
            out_tables.append({
                "table": tbl,
                "count": count,
                "age_min": age,
                "status": status,
            })
        except Exception as e:  # noqa: BLE001
            overall_fresh = False
            out_tables.append({
                "table": tbl,
                "count": None,
                "age_min": None,
                "status": "error",
                "error": str(e)[:160],
            })
    return {
        "name": layer,
        "status": "fresh" if overall_fresh else "stale",
        "tables": out_tables,
    }


def _check_lakebase(settings: Settings) -> dict[str, Any]:
    out_tables: list[dict[str, Any]] = []
    overall_fresh = True
    for tbl, ts_col in LAKEBASE_TABLES:
        try:
            rows = lakebase_query(
                settings,
                f"SELECT count(*) AS n, max({ts_col}) AS ts FROM {settings.schema}.{tbl}",
            )
            row = rows[0] if rows else {}
            count = int(row.get("n") or 0)
            ts = _parse_ts(row.get("ts"))
            age = _age_min(ts)
            status = _classify(age, LAKEBASE_MAX_AGE_MIN, count)
            if status != "fresh":
                overall_fresh = False
            out_tables.append({
                "table": tbl,
                "count": count,
                "age_min": age,
                "status": status,
            })
        except Exception as e:  # noqa: BLE001
            overall_fresh = False
            out_tables.append({
                "table": tbl,
                "count": None,
                "age_min": None,
                "status": "error",
                "error": str(e)[:160],
            })
    return {
        "name": "lakebase",
        "status": "fresh" if overall_fresh else "stale",
        "tables": out_tables,
    }


def _check_sap_bdc(settings: Settings) -> dict[str, Any]:
    if not settings.sap_bdc_warehouse_id:
        return {
            "name": "sap_bdc",
            "status": "disabled",
            "tables": [],
            "table_count": 0,
        }
    try:
        rows = warehouse_execute(
            settings,
            f"SHOW TABLES IN {settings.sap_bdc_catalog}.{settings.sap_bdc_schema}",
        )
        n = len(rows)
        return {
            "name": "sap_bdc",
            "status": "fresh" if n > 0 else "stale",
            "table_count": n,
            "tables": [],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": "sap_bdc",
            "status": "error",
            "error": str(e)[:200],
            "table_count": 0,
            "tables": [],
        }


def _build_status(settings: Settings) -> dict[str, Any]:
    bronze = _check_delta_layer(settings, "bronze", BRONZE_TABLES, BRONZE_MAX_AGE_MIN)
    gold = _check_delta_layer(settings, "gold", GOLD_TABLES, GOLD_MAX_AGE_MIN)
    lakebase = _check_lakebase(settings)
    sap_bdc = _check_sap_bdc(settings)
    return {
        "generated_at": _now().isoformat(timespec="seconds"),
        "layers": [bronze, gold, lakebase, sap_bdc],
        "pipeline_id": MAIN_PIPELINE_ID,
    }


@router.get("/status")
def get_status(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    import time
    with _cache_lock:
        if _cache["value"] is not None and (time.time() - _cache["ts"]) < _CACHE_TTL_S:
            return _cache["value"]
    value = _build_status(settings)
    with _cache_lock:
        _cache["value"] = value
        _cache["ts"] = time.time()
    return value


@router.post("/trigger-pipeline")
def trigger_pipeline() -> dict[str, Any]:
    """Kick the Lakeflow pipeline. No full-refresh — incremental update only."""
    try:
        w = WorkspaceClient()
        # First peek at current state so we don't double-trigger a running update.
        p = w.pipelines.get(pipeline_id=MAIN_PIPELINE_ID)
        state = getattr(p, "state", None)
        state_str = state.value if hasattr(state, "value") else str(state) if state else "UNKNOWN"
        if state_str == "RUNNING":
            return {
                "triggered": False,
                "already_running": True,
                "state": state_str,
                "update_id": getattr(p, "latest_updates", [None])[0].update_id if getattr(p, "latest_updates", None) else None,
            }
        u = w.pipelines.start_update(pipeline_id=MAIN_PIPELINE_ID, full_refresh=False)
        return {
            "triggered": True,
            "already_running": False,
            "update_id": u.update_id,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("trigger-pipeline failed: %s", e)
        raise HTTPException(status_code=500, detail=f"trigger failed: {e}")


@router.post("/refresh")
def refresh_cache() -> dict[str, bool]:
    """Force a re-check on the next /status call (clears the 30 s cache)."""
    with _cache_lock:
        _cache["value"] = None
        _cache["ts"] = 0.0
    return {"cleared": True}
