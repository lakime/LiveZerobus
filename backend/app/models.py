"""Pydantic response models for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class InventoryRow(BaseModel):
    sku: str
    dc_id: str
    on_hand: int
    last_event_ts: datetime
    reorder_point: Optional[int] = None
    target_stock: Optional[int] = None


class SupplierQuoteRow(BaseModel):
    sku: str
    supplier_id: str
    supplier_name: Optional[str]
    unit_price_usd: float
    lead_time_days: int
    min_qty: int
    score: float
    rank: int
    quote_ts: datetime


class CommodityRow(BaseModel):
    commodity: str
    price_usd: float
    event_ts: datetime
    pct_1h: Optional[float] = None
    pct_24h: Optional[float] = None


class DemandHourRow(BaseModel):
    sku: str
    hour_ts: datetime
    qty: int
    revenue_usd: float


class RecommendationRow(BaseModel):
    recommendation_id: str
    created_ts: datetime
    sku: str
    dc_id: str
    reorder_qty: int
    recommended_supplier_id: str
    recommended_supplier_name: Optional[str]
    unit_price_usd: float
    total_cost_usd: float
    expected_lead_days: int
    ml_score: float
    commodity_pct_24h: Optional[float]
    decision: str
    rationale: Optional[str]
