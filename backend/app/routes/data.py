"""All live-data API endpoints (seed-procurement schema)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings
from ..lakebase import query
from ..models import (
    CommodityRow,
    DemandHourRow,
    InventoryRow,
    RecommendationRow,
    SapInvoiceMatchRow,
    SapPoLineRow,
    SupplierQuoteRow,
)

router = APIRouter(prefix="/api", tags=["live"])


def get_settings() -> Settings:
    return Settings.from_env()


# -------------------- Seed inventory --------------------


@router.get("/inventory", response_model=list[InventoryRow])
def inventory(
    sku: str | None = Query(default=None),
    room_id: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
):
    where, params = [], []
    if sku:
        where.append("sku = %s"); params.append(sku)
    if room_id:
        where.append("room_id = %s"); params.append(room_id)
    w = f"WHERE {' AND '.join(where)}" if where else ""

    return query(settings, f"""
        SELECT sku, room_id, on_hand_g, last_event_ts,
               reorder_point_g, target_stock_g
          FROM liveoltp.inventory_snapshot
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
    params: list = [top]
    where = "WHERE rank <= %s"
    if sku:
        where += " AND sku = %s"
        params.append(sku)
    return query(settings, f"""
        SELECT sku, supplier_id, supplier_name, pack_size_g,
               unit_price_usd, usd_per_gram, lead_time_days, min_qty,
               organic, score, rank, quote_ts
          FROM liveoltp.supplier_leaderboard
          {where}
         ORDER BY sku, rank
    """, params)


# -------------------- Grow-input prices --------------------


@router.get("/commodity/latest", response_model=list[CommodityRow])
def commodity_latest(settings: Settings = Depends(get_settings)):
    return query(settings, """
        SELECT input_key, price_usd, unit, event_ts, pct_1h, pct_24h
          FROM liveoltp.commodity_prices_latest
         ORDER BY input_key
    """)


# -------------------- Planting / demand --------------------


@router.get("/demand/hourly", response_model=list[DemandHourRow])
def demand_hourly(
    sku: str | None = None,
    hours: int = Query(24, ge=1, le=168),
    settings: Settings = Depends(get_settings),
):
    params: list = [hours]
    where = "WHERE hour_ts >= NOW() - (%s || ' hours')::interval"
    if sku:
        where += " AND sku = %s"
        params.append(sku)
    return query(settings, f"""
        SELECT sku, hour_ts, trays, grams_req
          FROM liveoltp.demand_1h
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
    params: list = []
    where = ""
    if decision:
        where = "WHERE decision = %s"
        params.append(decision.upper())
    params.append(limit)
    return query(settings, f"""
        SELECT *
          FROM liveoltp.procurement_recommendations
          {where}
         ORDER BY created_ts DESC
         LIMIT %s
    """, params)


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
        where.append("po_status = %s"); params.append(status.upper())
    if supplier_id:
        where.append("supplier_id = %s"); params.append(supplier_id)
    params.append(limit)
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return query(settings, f"""
        SELECT po_number, po_item, event_type, supplier_id, supplier_name,
               supplier_tier, sku, quantity_g, unit_price_usd, net_value_usd,
               delivery_date_ts, qty_received_g, qty_outstanding_g, po_status, event_ts
          FROM liveoltp.sap_po_lines
          {w}
         ORDER BY event_ts DESC
         LIMIT %s
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
        where.append("match_status = %s"); params.append(match_status.upper())
    params.append(limit)
    w = f"WHERE {' AND '.join(where)}" if where else ""
    return query(settings, f"""
        SELECT invoice_doc_number, po_number, po_item, supplier_id, sku,
               net_amount_usd, po_net_value_usd, gr_qty_g, variance_usd,
               status, match_status, event_ts
          FROM liveoltp.sap_invoice_matching
          {w}
         ORDER BY event_ts DESC
         LIMIT %s
    """, params)


# -------------------- Summary --------------------


@router.get("/summary")
def summary(settings: Settings = Depends(get_settings)):
    row = query(settings, """
        SELECT
          (SELECT COUNT(*) FROM liveoltp.inventory_snapshot
             WHERE on_hand_g <= reorder_point_g)                    AS skus_below_reorder,
          (SELECT COUNT(*) FROM liveoltp.procurement_recommendations
             WHERE decision = 'BUY_NOW'
               AND created_ts > NOW() - INTERVAL '5 minutes')        AS buy_now_last_5m,
          (SELECT COALESCE(SUM(total_cost_usd), 0)
             FROM liveoltp.procurement_recommendations
             WHERE created_ts > NOW() - INTERVAL '1 hour')          AS spend_pending_1h_usd,
          (SELECT MAX(event_ts) FROM liveoltp.commodity_prices_latest)   AS last_market_tick,
          (SELECT COUNT(*) FROM liveoltp.po_drafts
             WHERE status='DRAFT')                                   AS po_drafts_open,
          (SELECT COUNT(*) FROM liveoltp.email_inbox
             WHERE processed IS NOT TRUE)                            AS inbound_unprocessed
    """)
    return row[0] if row else {}
