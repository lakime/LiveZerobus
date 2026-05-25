"""Self-healing for the livezerobus dashboard data path.

The dashboard reads from Lakebase Postgres synced tables. Two things go wrong
without manual intervention:

1. The Lakeflow pipeline auto-terminates after idle and Gold MVs stop
   refreshing. Cold-start takes 7-10 min.
2. The Lakebase synced tables (SNAPSHOT policy) randomly stop snapshotting
   and lock onto an old version — Gold can be fresh but Lakebase stays
   stuck.

This module runs both checks on backend startup and again every 5 minutes
in the background. When it detects either failure mode it triggers the
appropriate recovery (pipeline start-update / synced-table recreate).

All work happens in a background thread so the FastAPI app boot is never
blocked. Failures are swallowed and logged — the dashboard keeps working
even if recovery is unavailable.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Constants (mirror scripts/reset_synced_tables.py) ─────────────────────

PIPELINE_ID = "4cef05ca-ea6f-4217-af60-6b75a6b1a3f4"
CATALOG = "livezerobus"
SCHEMA = "procurement"
PGHOST = "ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net"
PGDATABASE = "databricks_postgres"
ENDPOINT = "projects/myzerobus/branches/production/endpoints/primary"
BRANCH = "projects/myzerobus/branches/production"
APP_SP = "c4352007-a55b-4da5-b5c9-f4c8df89e58a"

# How stale Gold MV freshness has to be before we trigger the pipeline.
GOLD_STALE_THRESHOLD = timedelta(minutes=15)

# How stale Lakebase tables have to be relative to Gold before we reset.
SYNC_STALE_THRESHOLD = timedelta(minutes=15)

# Interval between background heal cycles.
LOOP_INTERVAL_S = 300  # 5 min

# Map of Lakebase synced table → (source Gold MV, primary key columns).
TABLES: dict[str, tuple[str, list[str]]] = {
    "commodity_prices_latest":     ("gd_commodity_latest",            ["input_key"]),
    "demand_1h":                   ("gd_demand_1h",                   ["sku", "hour_ts"]),
    "inventory_snapshot":          ("gd_inventory_snapshot",          ["sku", "room_id"]),
    "supplier_leaderboard":        ("gd_supplier_leaderboard",        ["sku", "supplier_id"]),
    "procurement_recommendations": ("gd_procurement_recommendations", ["recommendation_id"]),
    "iot_sensor_latest":           ("gd_iot_sensor_latest",           ["room_id", "sensor_type"]),
    "sap_po_lines":                ("gd_sap_open_po_lines",           ["po_number", "po_item"]),
    "sap_invoice_matching":        ("gd_sap_invoice_matching",        ["invoice_doc_number"]),
}

# The timestamp column on each Gold MV / synced table we compare to detect drift.
TIMESTAMP_COL: dict[str, str] = {
    "commodity_prices_latest":     "event_ts",
    "demand_1h":                   "hour_ts",
    "inventory_snapshot":          "last_event_ts",
    "supplier_leaderboard":        "quote_ts",
    "procurement_recommendations": "scored_at",
    "iot_sensor_latest":           "event_ts",
    "sap_po_lines":                "po_creation_ts",
    "sap_invoice_matching":        "invoice_creation_ts",
}


# ── Public state for /api/admin/recovery/status ───────────────────────────

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": True,
    "last_cycle_started": None,
    "last_cycle_finished": None,
    "last_action": None,
    "last_error": None,
    "actions": [],   # last 20 actions (timestamp + message)
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


# ── Workspace client (lazy) ───────────────────────────────────────────────

def _client():
    """Lazy-import to keep main app boot fast and avoid import-time errors
    if databricks-sdk is misconfigured."""
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient()


# ── Pipeline ──────────────────────────────────────────────────────────────

def pipeline_state() -> dict[str, Any]:
    """Return state of the Lakeflow pipeline."""
    p = _client().pipelines.get(PIPELINE_ID)
    latest = (p.latest_updates or [None])[0]
    return {
        "name": p.name,
        "state": str(p.state) if p.state else None,
        "latest_update_state": str(latest.state) if latest else None,
        "latest_update_id": latest.update_id if latest else None,
    }


def trigger_pipeline_if_needed() -> bool:
    """If the pipeline has no recent successful update, kick a new one.
    Returns True if a new update was triggered."""
    try:
        w = _client()
        p = w.pipelines.get(PIPELINE_ID)
        # If a non-failed update is already in flight, leave it.
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
        _record_error(e)
        return False


# ── Lakebase synced tables ────────────────────────────────────────────────

def _delete_synced_table(name: str) -> None:
    host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    # Mint a fresh PAT-ish token via the WorkspaceClient config.
    w = _client()
    auth = w.config.authenticate()
    token = auth.get("Authorization", "").removeprefix("Bearer ")
    url = f"{host}/api/2.0/database/synced_tables/{CATALOG}.{SCHEMA}.{name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def _drop_pg_table(name: str) -> None:
    import psycopg
    w = _client()
    pg_user = os.environ.get("PGUSER", APP_SP)
    cred = w.postgres.generate_database_credential(name=ENDPOINT).token
    with psycopg.connect(
        host=PGHOST, port=5432, dbname=PGDATABASE,
        user=pg_user, password=cred, sslmode="require",
    ) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{name} CASCADE")
        conn.commit()


def reset_synced_table(name: str) -> bool:
    """Full DELETE + DROP + CREATE recovery for one synced table.
    Returns True if recreate was issued."""
    if name not in TABLES:
        return False
    source_mv, pks = TABLES[name]
    try:
        _delete_synced_table(name)
        _drop_pg_table(name)
        from databricks.sdk.service import postgres as pg
        spec = pg.SyncedTableSyncedTableSpec(
            source_table_full_name=f"{CATALOG}.{SCHEMA}.{source_mv}",
            primary_key_columns=pks,
            scheduling_policy=pg.SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy("SNAPSHOT"),
            branch=BRANCH,
            postgres_database=PGDATABASE,
            create_database_objects_if_missing=True,
        )
        _client().postgres.create_synced_table(
            synced_table=pg.SyncedTable(spec=spec),
            synced_table_id=f"{CATALOG}.{SCHEMA}.{name}",
        )
        _record(f"reset stuck synced table: {name}")
        return True
    except Exception as e:
        _record_error(e)
        return False


# ── Freshness checks via SQL warehouse ────────────────────────────────────

def _run_sql(sql: str) -> list[dict]:
    """Run a SELECT against the SQL warehouse. Returns list-of-dicts."""
    warehouse_id = os.environ.get("SAP_BDC_WAREHOUSE_ID") or "6a1fb3b32b00f1cd"
    w = _client()
    from databricks.sdk.service.sql import StatementState
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


def check_freshness() -> dict[str, Any]:
    """Compare Gold MV latest_ts vs Lakebase synced table latest_ts.
    Returns dict with per-table drift info."""
    pieces = []
    for name, (mv, _pks) in TABLES.items():
        ts = TIMESTAMP_COL.get(name)
        if not ts:
            continue
        pieces.append(
            f"SELECT '{name}' AS t, '{ts}' AS col, "
            f"(SELECT MAX({ts}) FROM {CATALOG}.{SCHEMA}.{mv}) AS gold_ts, "
            f"(SELECT MAX({ts}) FROM {CATALOG}.{SCHEMA}.{name}) AS sync_ts"
        )
    sql = " UNION ALL ".join(pieces)
    rows = _run_sql(sql)
    out: dict[str, Any] = {}
    for r in rows:
        out[r["t"]] = {
            "gold_ts": r.get("gold_ts"),
            "sync_ts": r.get("sync_ts"),
        }
    return out


# ── Heal cycle ────────────────────────────────────────────────────────────

def _parse(ts) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        s = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def run_recovery_cycle() -> dict[str, Any]:
    """One pass of: (1) trigger pipeline if Gold stale, (2) reset stuck
    synced tables. Safe to call concurrently or repeatedly."""
    with _state_lock:
        _state["last_cycle_started"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _state["last_error"] = None
    summary: dict[str, Any] = {"pipeline_kicked": False, "tables_reset": []}

    try:
        ps = pipeline_state()
        summary["pipeline"] = ps

        # Pipeline trigger if Gold is stale.
        freshness = check_freshness()
        summary["freshness"] = freshness
        now = datetime.now(timezone.utc)

        gold_stale = False
        for name, info in freshness.items():
            gold = _parse(info.get("gold_ts"))
            if gold is None or (now - gold) > GOLD_STALE_THRESHOLD:
                gold_stale = True
                break
        if gold_stale:
            _record(f"Gold MV is stale (> {GOLD_STALE_THRESHOLD}); triggering pipeline")
            if trigger_pipeline_if_needed():
                summary["pipeline_kicked"] = True

        # Reset stuck synced tables.
        for name, info in freshness.items():
            gold = _parse(info.get("gold_ts"))
            sync = _parse(info.get("sync_ts"))
            if gold is None:
                continue
            drift = (gold - sync) if sync else timedelta(days=365)
            if drift > SYNC_STALE_THRESHOLD:
                _record(f"Lakebase {name} drifted by {drift}; resetting")
                if reset_synced_table(name):
                    summary["tables_reset"].append(name)
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
    """Idempotent — only starts the heal thread once per process."""
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True

    def _loop():
        # First run after a small delay so app boot completes first.
        time.sleep(20)
        while True:
            if _state.get("enabled"):
                try:
                    run_recovery_cycle()
                except Exception as e:
                    _record_error(e)
            time.sleep(LOOP_INTERVAL_S)

    threading.Thread(target=_loop, daemon=True, name="auto-recovery").start()
    _record("background loop started")
