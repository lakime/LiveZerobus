"""SAP BDC integration — queries the Delta-Shared SAP catalog directly via
the SQL warehouse. Disabled gracefully if SAP_BDC_WAREHOUSE_ID is unset."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings
from ..warehouse import WarehouseNotConfigured, catalog_available, execute

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sap-bdc", tags=["sap-bdc"])


def get_settings() -> Settings:
    return Settings.from_env()


def _qualify(settings: Settings, table: str) -> str:
    return f"`{settings.sap_bdc_catalog}`.`{settings.sap_bdc_schema}`.`{table}`"


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
        return execute(
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
        rows = execute(settings, f"SELECT LIFNR, NAME1 FROM {lfa1}")
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
        return execute(
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
