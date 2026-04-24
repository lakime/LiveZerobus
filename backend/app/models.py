"""Pydantic response models for the API (seed-procurement schema)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class InventoryRow(BaseModel):
    sku: str
    room_id: str
    on_hand_g: float
    last_event_ts: datetime
    reorder_point_g: Optional[float] = None
    target_stock_g: Optional[float] = None


class SupplierQuoteRow(BaseModel):
    sku: str
    supplier_id: str
    supplier_name: Optional[str] = None
    pack_size_g: Optional[float] = None
    unit_price_usd: float
    usd_per_gram: Optional[float] = None
    lead_time_days: int
    min_qty: int
    organic: Optional[bool] = None
    score: float
    rank: int
    quote_ts: datetime


class CommodityRow(BaseModel):
    input_key: str
    price_usd: float
    unit: Optional[str] = None
    event_ts: datetime
    pct_1h: Optional[float] = None
    pct_24h: Optional[float] = None


class DemandHourRow(BaseModel):
    sku: str
    hour_ts: datetime
    trays: int
    grams_req: float


class RecommendationRow(BaseModel):
    recommendation_id: str
    created_ts: datetime
    sku: str
    room_id: str
    reorder_grams: float
    recommended_supplier_id: str
    recommended_supplier_name: Optional[str] = None
    pack_size_g: Optional[float] = None
    packs: Optional[int] = None
    unit_price_usd: float
    total_cost_usd: float
    expected_lead_days: int
    ml_score: float
    input_pct_24h: Optional[float] = None
    decision: str
    rationale: Optional[str] = None
