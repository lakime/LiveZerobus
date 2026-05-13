"""SAP BDC integration — queries the Delta-Shared SAP catalog directly via
the SQL warehouse. Disabled gracefully if SAP_BDC_WAREHOUSE_ID is unset."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings
from ..warehouse import WarehouseNotConfigured, catalog_available, execute

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sap-bdc", tags=["sap-bdc"])

# 15 SAP tables exposed by the BDC share. Order matches the BDC service.
SAP_TABLES = [
    "bkpf", "eban", "ekbe", "eket", "ekko", "ekpo",
    "lfa1", "mara", "mkpf", "mseg", "rbkp",
    "t001", "t001w", "t023", "t024",
]


def get_settings() -> Settings:
    return Settings.from_env()


def _qualify(settings: Settings, table: str) -> str:
    return f"`{settings.sap_bdc_catalog}`.`{settings.sap_bdc_schema}`.`{table}`"


# ── Sync state ──────────────────────────────────────────────────────────────
# Single global state — the livezerobus backend is single-instance.

_sync_lock = threading.Lock()
_sync_state: dict[str, Any] = {
    "running": False,
    "stage": "idle",
    "started_at": None,
    "finished_at": None,
    "current_table": None,
    "succeeded": [],
    "failed": [],
    "total_tables": len(SAP_TABLES),
    "log": [],
}


def _log(msg: str) -> None:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    log.info("[sync] %s", msg)
    _sync_state["log"].append(f"{ts}  {msg}")
    if len(_sync_state["log"]) > 200:
        _sync_state["log"] = _sync_state["log"][-200:]


def _execute_with_retry(settings: Settings, sql: str, retries: int = 12, sleep: float = 3.0) -> None:
    """Execute a statement with retries (no result) — UC's Delta Sharing
    connector has intermittent RPC failures we need to ride out."""
    _execute_with_retry_returning(settings, sql, retries=retries, sleep=sleep, parameters=None)


def _execute_with_retry_returning(
    settings: Settings,
    sql: str,
    retries: int = 5,
    sleep: float = 1.5,
    parameters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Like _execute_with_retry but returns the rows; used by data endpoints
    that need the result (vendors, purchase-orders) — fewer retries / shorter
    sleeps so the user-facing request doesn't take ages."""
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            return execute(settings, sql, parameters=parameters)
        except Exception as e:
            last_err = str(e)
            if any(s in last_err for s in ["PERMISSION_DENIED", "SYNTAX_ERROR", "UNAUTHORIZED", "INVALID_SHARE"]):
                raise
            log.warning("retry %d/%d on UC flake: %s", attempt, retries, last_err[:120])
            time.sleep(sleep)
    raise RuntimeError(f"Statement failed after {retries} retries: {last_err[:200]}")


def _do_sync(settings: Settings) -> None:
    """Background worker: drop + recreate catalog + warm every table."""
    cat = settings.sap_bdc_catalog
    sch = settings.sap_bdc_schema
    try:
        with _sync_lock:
            _sync_state["running"] = True
            _sync_state["stage"] = "starting"
            _sync_state["started_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            _sync_state["finished_at"] = None
            _sync_state["current_table"] = None
            _sync_state["succeeded"] = []
            _sync_state["failed"] = []
            _sync_state["log"] = []

        _log(f"Refreshing {cat}.{sch}")

        _sync_state["stage"] = "drop_catalog"
        _log("DROP CATALOG …")
        _execute_with_retry(settings, f"DROP CATALOG IF EXISTS {cat} CASCADE")

        _sync_state["stage"] = "create_catalog"
        _log("CREATE CATALOG …")
        _execute_with_retry(settings, f"CREATE CATALOG {cat} USING SHARE `sapsofts`.`sap-procurement`")

        _sync_state["stage"] = "materialise_schema"
        _log("SHOW SCHEMAS / SHOW TABLES …")
        _execute_with_retry(settings, f"SHOW SCHEMAS IN {cat}")
        _execute_with_retry(settings, f"SHOW TABLES IN {cat}.{sch}")

        _sync_state["stage"] = "warm_tables"
        for t in SAP_TABLES:
            _sync_state["current_table"] = t
            _log(f"warming {t} …")
            try:
                _execute_with_retry(settings, f"DESCRIBE TABLE {cat}.{sch}.{t}")
                _sync_state["succeeded"].append(t)
                _log(f"  ✓ {t}")
            except Exception as e:
                _sync_state["failed"].append({"table": t, "error": str(e)[:200]})
                _log(f"  ✗ {t}: {e}")

        _sync_state["current_table"] = None
        _sync_state["stage"] = "completed" if not _sync_state["failed"] else "completed_with_errors"
        _log(f"Done — {len(_sync_state['succeeded'])}/{len(SAP_TABLES)} tables warmed")
    except Exception as e:
        _sync_state["stage"] = "failed"
        _log(f"FATAL: {e}")
    finally:
        with _sync_lock:
            _sync_state["running"] = False
            _sync_state["finished_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ── Sync endpoints ──────────────────────────────────────────────────────────

@router.post("/sync")
def start_sync(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Trigger a catalog refresh in the background.

    Returns immediately; clients should poll /api/sap-bdc/sync/status to
    watch progress.
    """
    if not settings.sap_bdc_warehouse_id:
        raise HTTPException(503, detail="SAP_BDC_WAREHOUSE_ID not configured")
    with _sync_lock:
        if _sync_state["running"]:
            raise HTTPException(409, detail="A sync is already running")
    threading.Thread(target=_do_sync, args=(settings,), daemon=True).start()
    return {"started": True}


@router.get("/sync/status")
def sync_status() -> dict[str, Any]:
    """Current state of the sync worker."""
    # Return a shallow copy — lists are still references but for read-only
    # use this is fine; lifetime of the response is short.
    with _sync_lock:
        return dict(_sync_state)


# ── Status / info ───────────────────────────────────────────────────────────

@router.get("/info")
def info(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Whether the BDC catalog is reachable and how many tables are present."""
    if not settings.sap_bdc_warehouse_id:
        return {
            "connected": False,
            "reason": "SAP_BDC_WAREHOUSE_ID not configured",
            "catalog": settings.sap_bdc_catalog,
            "schema": settings.sap_bdc_schema,
        }
    try:
        tables = execute(
            settings,
            f"SHOW TABLES IN {settings.sap_bdc_catalog}.{settings.sap_bdc_schema}",
        )
        return {
            "connected": True,
            "catalog": settings.sap_bdc_catalog,
            "schema": settings.sap_bdc_schema,
            "table_count": len(tables),
            "tables": [r.get("tableName", "") for r in tables],
        }
    except Exception as e:
        return {
            "connected": False,
            "reason": str(e),
            "catalog": settings.sap_bdc_catalog,
            "schema": settings.sap_bdc_schema,
        }


# ── Vendors (LFA1) ──────────────────────────────────────────────────────────

@router.get("/vendors")
def vendors(
    q: str = Query("", description="Free-text search on name / country / city"),
    limit: int = Query(100, ge=1, le=500),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    """Vendor master records (LFA1)."""
    if not catalog_available(settings):
        return []
    lfa1 = _qualify(settings, "lfa1")
    where = ""
    params = []
    if q:
        where = """
            WHERE LOWER(NAME1) LIKE :pat
               OR LOWER(LAND1) LIKE :pat
               OR LOWER(ORT01) LIKE :pat
               OR LIFNR LIKE :pat
        """
        params = [{"name": "pat", "value": f"%{q.lower()}%"}]
    try:
        return _execute_with_retry_returning(
            settings,
            f"""
            SELECT LIFNR, NAME1, LAND1, ORT01, STRAS, TELF1, SPRAS, KTOKK
              FROM {lfa1}
              {where}
              ORDER BY LIFNR
              LIMIT {int(limit)}
            """,
            parameters=params,
        )
    except Exception as e:
        log.warning("vendors query failed: %s", e)
        raise HTTPException(503, detail=f"SAP BDC unreachable: {e}")


@router.get("/vendor-lookup")
def vendor_lookup(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Mapping LIFNR → vendor name. Returned as a small dict so the frontend
    can enrich SAP P2P rows without round-tripping per-row.

    Returns empty dict (not an error) when BDC isn't configured — callers
    should treat missing keys as "vendor name unknown" and fall back to the
    raw LIFNR. This keeps the SAP P2P tab functional even when BDC is offline.
    """
    if not catalog_available(settings):
        return {}
    lfa1 = _qualify(settings, "lfa1")
    try:
        rows = _execute_with_retry_returning(settings, f"SELECT LIFNR, NAME1 FROM {lfa1}")
        return {r["LIFNR"]: r.get("NAME1", "") for r in rows if r.get("LIFNR")}
    except Exception as e:
        log.warning("vendor-lookup failed: %s", e)
        return {}


# ── Purchase orders (EKKO + EKPO joined) ────────────────────────────────────

@router.get("/purchase-orders")
def purchase_orders(
    q: str = Query("", description="Free text on EBELN, LIFNR, vendor name, material"),
    limit: int = Query(100, ge=1, le=500),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    """Purchase order header joined with its line items and vendor name."""
    if not catalog_available(settings):
        return []
    ekko = _qualify(settings, "ekko")
    ekpo = _qualify(settings, "ekpo")
    lfa1 = _qualify(settings, "lfa1")
    where = ""
    params = []
    if q:
        where = """
            WHERE LOWER(h.EBELN) LIKE :pat
               OR LOWER(h.LIFNR) LIKE :pat
               OR LOWER(v.NAME1) LIKE :pat
               OR LOWER(i.MATNR) LIKE :pat
        """
        params = [{"name": "pat", "value": f"%{q.lower()}%"}]
    try:
        return _execute_with_retry_returning(
            settings,
            f"""
            SELECT
                h.EBELN     AS po_number,
                h.BSART     AS po_type,
                h.LIFNR     AS vendor_id,
                v.NAME1     AS vendor_name,
                v.LAND1     AS vendor_country,
                h.WAERS     AS currency,
                h.BUKRS     AS company_code,
                h.BEDAT     AS po_date,
                i.EBELP     AS item,
                i.MATNR     AS material,
                i.WERKS     AS plant,
                i.MENGE     AS quantity,
                i.MEINS     AS uom,
                i.NETPR     AS net_price,
                i.NETWR     AS net_value,
                i.EINDT     AS delivery_date
              FROM {ekko} h
              LEFT JOIN {ekpo} i ON h.EBELN = i.EBELN
              LEFT JOIN {lfa1} v ON h.LIFNR = v.LIFNR
              {where}
              ORDER BY h.BEDAT DESC, h.EBELN, i.EBELP
              LIMIT {int(limit)}
            """,
            parameters=params,
        )
    except Exception as e:
        log.warning("purchase-orders query failed: %s", e)
        raise HTTPException(503, detail=f"SAP BDC unreachable: {e}")
