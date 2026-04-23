export type InventoryRow = {
  sku: string;
  dc_id: string;
  on_hand: number;
  last_event_ts: string;
  reorder_point: number | null;
  target_stock: number | null;
};

export type SupplierRow = {
  sku: string;
  supplier_id: string;
  supplier_name: string | null;
  unit_price_usd: number;
  lead_time_days: number;
  min_qty: number;
  score: number;
  rank: number;
  quote_ts: string;
};

export type CommodityRow = {
  commodity: string;
  price_usd: number;
  event_ts: string;
  pct_1h: number | null;
  pct_24h: number | null;
};

export type DemandHourRow = {
  sku: string;
  hour_ts: string;
  qty: number;
  revenue_usd: number;
};

export type RecommendationRow = {
  recommendation_id: string;
  created_ts: string;
  sku: string;
  dc_id: string;
  reorder_qty: number;
  recommended_supplier_id: string;
  recommended_supplier_name: string | null;
  unit_price_usd: number;
  total_cost_usd: number;
  expected_lead_days: number;
  ml_score: number;
  commodity_pct_24h: number | null;
  decision: "BUY_NOW" | "WAIT" | "REVIEW";
  rationale: string | null;
};

export type Summary = {
  skus_below_reorder: number;
  buy_now_last_5m: number;
  spend_pending_1h_usd: number;
  last_market_tick: string | null;
};

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  summary: () => getJSON<Summary>("/api/summary"),
  inventory: () => getJSON<InventoryRow[]>("/api/inventory"),
  leaderboard: (top = 3) => getJSON<SupplierRow[]>(`/api/suppliers/leaderboard?top=${top}`),
  commodity: () => getJSON<CommodityRow[]>("/api/commodity/latest"),
  demand: (hours = 24) => getJSON<DemandHourRow[]>(`/api/demand/hourly?hours=${hours}`),
  recommendations: (limit = 25) =>
    getJSON<RecommendationRow[]>(`/api/recommendations?limit=${limit}`),
};
