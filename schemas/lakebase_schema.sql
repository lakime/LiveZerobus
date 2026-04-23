-- Target schema in the Lakebase Postgres (databricks_postgres / production).
-- Synced-tables jobs defined in lakebase_sync/synced_tables.yml land data here.
-- The FastAPI backend reads only from these tables.

CREATE SCHEMA IF NOT EXISTS live;

-- Latest inventory snapshot per SKU / DC.
CREATE TABLE IF NOT EXISTS live.inventory_snapshot (
  sku           TEXT NOT NULL,
  dc_id         TEXT NOT NULL,
  on_hand       INT  NOT NULL,
  last_event_ts TIMESTAMPTZ NOT NULL,
  reorder_point INT,
  target_stock  INT,
  PRIMARY KEY (sku, dc_id)
);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshot_ts
  ON live.inventory_snapshot (last_event_ts DESC);

-- Current best N quotes per SKU, ranked by the ML model.
CREATE TABLE IF NOT EXISTS live.supplier_leaderboard (
  sku             TEXT NOT NULL,
  supplier_id     TEXT NOT NULL,
  supplier_name   TEXT,
  unit_price_usd  DOUBLE PRECISION,
  lead_time_days  INT,
  min_qty         INT,
  score           DOUBLE PRECISION,   -- from supplier_scoring_model
  rank            INT,
  quote_ts        TIMESTAMPTZ,
  PRIMARY KEY (sku, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_sku_rank
  ON live.supplier_leaderboard (sku, rank);

-- Latest commodity price per commodity.
CREATE TABLE IF NOT EXISTS live.commodity_prices_latest (
  commodity   TEXT PRIMARY KEY,
  price_usd   DOUBLE PRECISION,
  event_ts    TIMESTAMPTZ,
  pct_1h      DOUBLE PRECISION,
  pct_24h     DOUBLE PRECISION
);

-- 1-hour demand aggregates.
CREATE TABLE IF NOT EXISTS live.demand_1h (
  sku         TEXT NOT NULL,
  hour_ts     TIMESTAMPTZ NOT NULL,
  qty         INT NOT NULL,
  revenue_usd DOUBLE PRECISION,
  PRIMARY KEY (sku, hour_ts)
);
CREATE INDEX IF NOT EXISTS idx_demand_1h_hour
  ON live.demand_1h (hour_ts DESC);

-- Final procurement recommendations (scored & ranked).
CREATE TABLE IF NOT EXISTS live.procurement_recommendations (
  recommendation_id TEXT PRIMARY KEY,
  created_ts        TIMESTAMPTZ NOT NULL,
  sku               TEXT NOT NULL,
  dc_id             TEXT NOT NULL,
  reorder_qty       INT NOT NULL,
  recommended_supplier_id TEXT NOT NULL,
  recommended_supplier_name TEXT,
  unit_price_usd    DOUBLE PRECISION,
  total_cost_usd    DOUBLE PRECISION,
  expected_lead_days INT,
  ml_score          DOUBLE PRECISION,
  commodity_pct_24h DOUBLE PRECISION,
  decision          TEXT,                -- 'BUY_NOW','WAIT','REVIEW'
  rationale         TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_ts
  ON live.procurement_recommendations (created_ts DESC);
CREATE INDEX IF NOT EXISTS idx_recs_sku
  ON live.procurement_recommendations (sku);
