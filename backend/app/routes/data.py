"""All live-data API endpoints (seed-procurement schema).

Reads go directly against Gold MVs in Unity Catalog via the SQL warehouse —
no Lakebase synced-table layer. Eliminates the "stuck snapshot" failure
mode that previously made dashboard panels go stale.

Agent-state tables (po_drafts, email_*, budget_ledger, ...) still live
in Lakebase Postgres — they're written by the agents at runtime and
that requires a writable DB.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings
from ..lakebase import query as pg_query
from ..models import (
    CommodityRow,
    DemandHourRow,
    InventoryRow,
    IotSensorRow,
    RecommendationRow,
    SapInvoiceMatchRow,
    SapPoLineRow,
    SupplierQuoteRow,
)
from ..warehouse import execute as wh_execute

router = APIRouter(prefix="/api", tags=["live"])

CATALOG = "livezerobus"
SCHEMA = "procurement"


def get_settings() -> Settings:
    return Settings.from_env()


def _coerce(v: Any) -> Any:
    """Statement-Execution returns every value as str. Coerce numeric-
    looking strings to int/float so Pydantic response_model validation
    (and the frontend) doesn't barf."""
    if not isinstance(v, str):
        return v
    if v == "" or v.lower() in ("null", "none"):
        return None
    # Cheap numeric detection — `123`, `12.3`, `-12.3e+5`.
    s = v.strip()
    if not s:
        return v
    if s[0] in "-+0123456789" and any(c.isdigit() for c in s):
        try:
            if "." in s or "e" in s or "E" in s:
                return float(s)
            return int(s)
        except ValueError:
            pass
    return v


def wq(settings: Settings, sql: str, params: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Warehouse query against Gold MVs. Swallows transient errors so a
    stale Gold layer never crashes the API — endpoint returns [].
    Coerces stringified numerics back to int/float on the way out."""
    try:
        rows = wh_execute(settings, sql, parameters=params)
        return [{k: _coerce(v) for k, v in row.items()} for row in rows]
    except Exception:
        return []


# -------------------- Seed inventory --------------------

@router.get("/inventory", response_model=list[InventoryRow])
def inventory(
    sku: str | None = Query(default=None),
    room_id: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
):
    where, params = [], []
    if sku:
        where.append("sku = :sku"); params.append({"name": "sku", "value": sku})
    if room_id:
        where.append("room_id = :room_id"); params.append({"name": "room_id", "value": room_id})
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return wq(settings, f"""
        SELECT sku, room_id, on_hand_g, last_event_ts,
               reorder_point_g, target_stock_g
          FROM {CATALOG}.{SCHEMA}.gd_inventory_snapshot
          {w}
         ORDER BY sku, room_id
    """, params)


# -------------------- Supplier leaderboard --------------------

@router.get("/suppliers/leaderboard", response_model=list[SupplierQuoteRow])
def supplier_leaderboard(
    sku: str | None = None,
    top: int = Query(5, ge=1, le=20),
    settings: Settings = Depends(get_settings),
):
    # `top` is integer-bounded by Query() — safe to inline. SDK named
    # parameters were being typed as STRING, so `WHERE rank <= '3'`
    # returned empty even though rank IS an int.
    params = []
    where = f"WHERE rank <= {int(top)}"
    if sku:
        where += " AND sku = :sku"
        params.append({"name": "sku", "value": sku})
    return wq(settings, f"""
        SELECT sku, supplier_id, supplier_name, pack_size_g,
               unit_price_usd, usd_per_gram, lead_time_days, min_qty,
               organic, score, rank, quote_ts
          FROM {CATALOG}.{SCHEMA}.gd_supplier_leaderboard
          {where}
         ORDER BY sku, rank
    """, params)


# -------------------- Grow-input prices --------------------

@router.get("/commodity/latest", response_model=list[CommodityRow])
def commodity_latest(settings: Settings = Depends(get_settings)):
    return wq(settings, f"""
        SELECT input_key, price_usd, unit, event_ts, pct_1h, pct_24h
          FROM {CATALOG}.{SCHEMA}.gd_commodity_latest
         ORDER BY input_key
    """)


@router.get("/commodity/history")
def commodity_history(
    minutes: int = Query(30, ge=1, le=240),
    settings: Settings = Depends(get_settings),
):
    """Per-minute commodity price ticks straight from Bronze for the last
    N minutes. Used by the chart to show a curve immediately on page
    refresh instead of accumulating samples in browser memory."""
    return wq(settings, f"""
        SELECT
            input_key,
            date_trunc('MINUTE', event_ts) AS event_ts,
            AVG(price_usd) AS price_usd
          FROM {CATALOG}.{SCHEMA}.bz_commodity_prices
         WHERE event_ts >= current_timestamp() - INTERVAL {int(minutes)} MINUTE
         GROUP BY input_key, date_trunc('MINUTE', event_ts)
         ORDER BY event_ts ASC
    """)


# -------------------- Planting / demand --------------------

@router.get("/demand/hourly", response_model=list[DemandHourRow])
def demand_hourly(
    sku: str | None = None,
    hours: int = Query(24, ge=1, le=168),
    settings: Settings = Depends(get_settings),
):
    params = []
    where = f"WHERE hour_ts >= current_timestamp() - INTERVAL {int(hours)} HOUR"
    if sku:
        where += " AND sku = :sku"
        params.append({"name": "sku", "value": sku})
    return wq(settings, f"""
        SELECT sku, hour_ts, trays, grams_req
          FROM {CATALOG}.{SCHEMA}.gd_demand_1h
          {where}
         ORDER BY hour_ts ASC
    """, params)


# -------------------- Procurement recommendations --------------------

@router.get("/recommendations", response_model=list[RecommendationRow])
def recommendations(
    decision: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
):
    params = []
    where = ""
    if decision:
        where = "WHERE decision = :decision"
        params.append({"name": "decision", "value": decision.upper()})
    return wq(settings, f"""
        SELECT *
          FROM {CATALOG}.{SCHEMA}.gd_procurement_recommendations
          {where}
         ORDER BY created_ts DESC
         LIMIT {int(limit)}
    """, params)


# -------------------- IoT sensor latest --------------------

@router.get("/iot/sensors", response_model=list[IotSensorRow])
def iot_sensors(settings: Settings = Depends(get_settings)):
    return wq(settings, f"""
        SELECT room_id, sensor_type, value, unit,
               alert_min, alert_max, warn_min, warn_max, disp_min, disp_max,
               status, event_ts
          FROM {CATALOG}.{SCHEMA}.gd_iot_sensor_latest
         ORDER BY room_id, sensor_type
    """)


# -------------------- SAP PO lines --------------------

@router.get("/sap/po-lines", response_model=list[SapPoLineRow])
def sap_po_lines(
    status: str | None = Query(default=None),
    supplier_id: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
):
    where, params = [], []
    if status:
        where.append("po_status = :status"); params.append({"name": "status", "value": status.upper()})
    if supplier_id:
        where.append("supplier_id = :supplier_id"); params.append({"name": "supplier_id", "value": supplier_id})
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return wq(settings, f"""
        SELECT po_number, po_item, event_type, supplier_id, supplier_name,
               supplier_tier, sku, quantity_g, unit_price_usd, net_value_usd,
               delivery_date_ts, qty_received_g, qty_outstanding_g, po_status, event_ts
          FROM {CATALOG}.{SCHEMA}.gd_sap_open_po_lines
          {w}
         ORDER BY event_ts DESC
         LIMIT {int(limit)}
    """, params)


# -------------------- SAP invoice matching --------------------

@router.get("/sap/invoice-matching", response_model=list[SapInvoiceMatchRow])
def sap_invoice_matching(
    match_status: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
):
    where, params = [], []
    if match_status:
        where.append("match_status = :ms"); params.append({"name": "ms", "value": match_status.upper()})
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return wq(settings, f"""
        SELECT invoice_doc_number, po_number, po_item, supplier_id, sku,
               net_amount_usd, po_net_value_usd, gr_qty_g, variance_usd,
               status, match_status, event_ts
          FROM {CATALOG}.{SCHEMA}.gd_sap_invoice_matching
          {w}
         ORDER BY event_ts DESC
         LIMIT {int(limit)}
    """, params)


# -------------------- Summary --------------------

@router.get("/summary")
def summary(settings: Settings = Depends(get_settings)):
    """Aggregates from both warehouse (Gold) and Lakebase (agent state)."""
    gold: dict[str, Any] = {}
    try:
        rows = wh_execute(settings, f"""
            SELECT
              (SELECT COUNT(*) FROM {CATALOG}.{SCHEMA}.gd_inventory_snapshot
                 WHERE on_hand_g <= reorder_point_g)                    AS skus_below_reorder,
              (SELECT COUNT(*) FROM {CATALOG}.{SCHEMA}.gd_procurement_recommendations
                 WHERE decision = 'BUY_NOW'
                   AND created_ts > current_timestamp() - interval 5 minutes) AS buy_now_last_5m,
              (SELECT COALESCE(SUM(total_cost_usd), 0)
                 FROM {CATALOG}.{SCHEMA}.gd_procurement_recommendations
                 WHERE created_ts > current_timestamp() - interval 1 hour) AS spend_pending_1h_usd,
              (SELECT MAX(event_ts) FROM {CATALOG}.{SCHEMA}.gd_commodity_latest) AS last_market_tick
        """)
        if rows:
            gold = {k: _coerce(v) for k, v in rows[0].items()}
    except Exception:
        pass

    # Native Lakebase agent-state tables stay in Postgres.
    pg: dict[str, Any] = {}
    try:
        rows = pg_query(settings, """
            SELECT
              (SELECT COUNT(*) FROM procurement.po_drafts WHERE status='DRAFT')                    AS po_drafts_open,
              (SELECT COUNT(*) FROM procurement.email_inbox WHERE processed IS NOT TRUE)           AS inbound_unprocessed
        """)
        if rows:
            pg = rows[0]
    except Exception:
        pass

    return {**gold, **pg}
