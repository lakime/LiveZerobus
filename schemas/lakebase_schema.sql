-- Target schema in the Lakebase Postgres (databricks_postgres / production).
--
-- Two flavors of tables live in this schema:
--
--  1. Synced-from-Delta (read-only in Postgres) — maintained by the jobs in
--     lakebase_sync/synced_tables.yml. These mirror Gold Delta tables built
--     by the Lakeflow pipeline:
--       inventory_snapshot, supplier_leaderboard,
--       commodity_prices_latest, demand_1h, procurement_recommendations.
--
--  2. Agent-state (read-write in Postgres) — the FastAPI agents write to
--     these Postgres tables directly. They are NOT synced from Delta
--     because agents need UPDATE semantics that Zerobus / Delta append-only
--     cannot offer:
--       email_outbox, email_inbox, po_drafts, budget_ledger,
--       supplier_applications, invoice_reconciliations, agent_runs.
--
-- Run this file once against databricks_postgres/production in the Lakebase
-- SQL editor after creating the Lakebase instance.

CREATE SCHEMA IF NOT EXISTS liveoltp;


-- =================== Seed inventory / planting / market ===================

-- Latest seed-stock snapshot per SKU / grow-room, in grams. The Lakebase
-- synced table materialises the full superset of Gold columns; reference
-- DDL below is for documentation only — Synced Tables manage their own
-- target schema at apply time.
CREATE TABLE IF NOT EXISTS liveoltp.inventory_snapshot (
  sku               TEXT NOT NULL,
  room_id           TEXT NOT NULL,
  on_hand_g         DOUBLE PRECISION NOT NULL,
  last_event_ts     TIMESTAMPTZ NOT NULL,
  sku_name          TEXT,
  crop_type         TEXT,
  reorder_point_g   DOUBLE PRECISION,
  safety_stock_g    DOUBLE PRECISION,
  target_stock_g    DOUBLE PRECISION,
  organic_preferred BOOLEAN,
  PRIMARY KEY (sku, room_id)
);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshot_ts
  ON liveoltp.inventory_snapshot (last_event_ts DESC);

-- Current best N quotes per SKU, ranked by the ML model.
CREATE TABLE IF NOT EXISTS liveoltp.supplier_leaderboard (
  sku             TEXT NOT NULL,
  supplier_id     TEXT NOT NULL,
  supplier_name   TEXT,
  pack_size_g     DOUBLE PRECISION,
  unit_price_usd  DOUBLE PRECISION,
  usd_per_gram    DOUBLE PRECISION,
  lead_time_days  INT,
  min_qty         INT,
  organic         BOOLEAN,
  score           DOUBLE PRECISION,   -- from supplier_scoring_model
  rank            INT,
  quote_ts        TIMESTAMPTZ,
  PRIMARY KEY (sku, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_sku_rank
  ON liveoltp.supplier_leaderboard (sku, rank);

-- Latest input price per grow-input (coco_coir, nutrient_pack, kwh, ...).
CREATE TABLE IF NOT EXISTS liveoltp.commodity_prices_latest (
  input_key   TEXT PRIMARY KEY,
  price_usd   DOUBLE PRECISION,
  unit        TEXT,
  event_ts    TIMESTAMPTZ,
  pct_1h      DOUBLE PRECISION,
  pct_24h     DOUBLE PRECISION
);

-- 1-hour planting aggregates (grams seeded per SKU per hour).
CREATE TABLE IF NOT EXISTS liveoltp.demand_1h (
  sku         TEXT NOT NULL,
  hour_ts     TIMESTAMPTZ NOT NULL,
  trays       INT NOT NULL,
  grams_req   DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (sku, hour_ts)
);
CREATE INDEX IF NOT EXISTS idx_demand_1h_hour
  ON liveoltp.demand_1h (hour_ts DESC);

-- Final procurement recommendations (scored & ranked).
CREATE TABLE IF NOT EXISTS liveoltp.procurement_recommendations (
  recommendation_id TEXT PRIMARY KEY,
  created_ts        TIMESTAMPTZ NOT NULL,
  sku               TEXT NOT NULL,
  room_id           TEXT NOT NULL,
  reorder_grams     DOUBLE PRECISION NOT NULL,
  recommended_supplier_id TEXT NOT NULL,
  recommended_supplier_name TEXT,
  pack_size_g       DOUBLE PRECISION,
  packs             INT,
  unit_price_usd    DOUBLE PRECISION,
  total_cost_usd    DOUBLE PRECISION,
  expected_lead_days INT,
  ml_score          DOUBLE PRECISION,
  input_pct_24h     DOUBLE PRECISION,
  decision          TEXT,                -- 'BUY_NOW','WAIT','REVIEW'
  rationale         TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_ts
  ON liveoltp.procurement_recommendations (created_ts DESC);
CREATE INDEX IF NOT EXISTS idx_recs_sku
  ON liveoltp.procurement_recommendations (sku);


-- =================== Agent state (email + PO + budget + ops) ===================

CREATE TABLE IF NOT EXISTS liveoltp.email_outbox (
  email_id        TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  created_ts      TIMESTAMPTZ NOT NULL,
  supplier_id     TEXT,
  supplier_email  TEXT,
  subject         TEXT,
  body_md         TEXT,
  sku             TEXT,
  intent          TEXT,       -- RFQ | COUNTER | CONFIRM | ONBOARD | DUNNING
  sent_by         TEXT,       -- agent name
  status          TEXT        -- DRAFT | SENT | BOUNCED
);
CREATE INDEX IF NOT EXISTS idx_outbox_thread ON liveoltp.email_outbox (thread_id, created_ts);

CREATE TABLE IF NOT EXISTS liveoltp.email_inbox (
  email_id        TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  received_ts     TIMESTAMPTZ NOT NULL,
  supplier_id     TEXT,
  supplier_email  TEXT,
  subject         TEXT,
  body_md         TEXT,
  sku             TEXT,
  intent_detected TEXT,       -- QUOTE | COUNTER | ACCEPT | REJECT | OOF
  extracted_json  TEXT,
  processed       BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_inbox_thread ON liveoltp.email_inbox (thread_id, received_ts);

CREATE TABLE IF NOT EXISTS liveoltp.po_drafts (
  po_id           TEXT PRIMARY KEY,
  created_ts      TIMESTAMPTZ NOT NULL,
  thread_id       TEXT,
  sku             TEXT,
  supplier_id     TEXT,
  packs           INT,
  pack_size_g     DOUBLE PRECISION,
  total_grams     DOUBLE PRECISION,
  unit_price_usd  DOUBLE PRECISION,
  total_cost_usd  DOUBLE PRECISION,
  needed_by       DATE,
  status          TEXT,       -- DRAFT | APPROVED | REJECTED | SENT | RECEIVED
  rationale       TEXT
);
CREATE INDEX IF NOT EXISTS idx_po_status ON liveoltp.po_drafts (status, created_ts DESC);

CREATE TABLE IF NOT EXISTS liveoltp.budget_ledger (
  ledger_id       TEXT PRIMARY KEY,
  entry_ts        TIMESTAMPTZ NOT NULL,
  period_ym       TEXT,
  category        TEXT,       -- SEED | SUBSTRATE | NUTRIENTS | OVERHEAD
  delta_usd       DOUBLE PRECISION,
  balance_usd     DOUBLE PRECISION,
  po_id           TEXT,
  note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_budget_period ON liveoltp.budget_ledger (period_ym, entry_ts DESC);

CREATE TABLE IF NOT EXISTS liveoltp.supplier_applications (
  application_id  TEXT PRIMARY KEY,
  submitted_ts    TIMESTAMPTZ NOT NULL,
  supplier_name   TEXT,
  contact_email   TEXT,
  country         TEXT,
  offered_skus    TEXT,
  organic_cert    BOOLEAN,
  years_in_biz    INT,
  status          TEXT,        -- NEW | SCREENING | APPROVED | REJECTED
  score           DOUBLE PRECISION,
  agent_notes     TEXT
);

CREATE TABLE IF NOT EXISTS liveoltp.invoice_reconciliations (
  reconciliation_id TEXT PRIMARY KEY,
  received_ts       TIMESTAMPTZ NOT NULL,
  po_id             TEXT,
  supplier_id       TEXT,
  invoiced_amount_usd DOUBLE PRECISION,
  expected_amount_usd DOUBLE PRECISION,
  variance_usd        DOUBLE PRECISION,
  variance_pct        DOUBLE PRECISION,
  status              TEXT,    -- OK | REVIEW | DISPUTE | PAID
  agent_notes         TEXT
);

CREATE TABLE IF NOT EXISTS liveoltp.agent_runs (
  run_id        TEXT PRIMARY KEY,
  started_ts    TIMESTAMPTZ NOT NULL,
  finished_ts   TIMESTAMPTZ,
  agent_name    TEXT,
  input_ref     TEXT,
  output_ref    TEXT,
  prompt_tokens INT,
  output_tokens INT,
  status        TEXT,
  error_msg     TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_ts ON liveoltp.agent_runs (started_ts DESC);

-- IoT sensor latest (synced from gd_iot_sensor_latest via lakebase_sync)
CREATE TABLE IF NOT EXISTS liveoltp.iot_sensor_latest (
  room_id       TEXT             NOT NULL,
  sensor_type   TEXT             NOT NULL,
  value         DOUBLE PRECISION,
  unit          TEXT,
  alert_min     DOUBLE PRECISION,
  alert_max     DOUBLE PRECISION,
  warn_min      DOUBLE PRECISION,
  warn_max      DOUBLE PRECISION,
  disp_min      DOUBLE PRECISION,
  disp_max      DOUBLE PRECISION,
  status        TEXT,
  event_ts      TIMESTAMPTZ,
  PRIMARY KEY (room_id, sensor_type)
);

-- SAP PO lines (synced from gd_sap_open_po_lines via lakebase_sync)
CREATE TABLE IF NOT EXISTS liveoltp.sap_po_lines (
  po_number          TEXT        NOT NULL,
  po_item            INT         NOT NULL,
  event_type         TEXT,
  supplier_id        TEXT,
  supplier_name      TEXT,
  supplier_tier      TEXT,
  sku                TEXT,
  quantity_g         DOUBLE PRECISION,
  unit_price_usd     DOUBLE PRECISION,
  net_value_usd      DOUBLE PRECISION,
  delivery_date_ts   TIMESTAMPTZ,
  qty_received_g     DOUBLE PRECISION,
  qty_outstanding_g  DOUBLE PRECISION,
  po_status          TEXT,
  event_ts           TIMESTAMPTZ,
  PRIMARY KEY (po_number, po_item)
);

-- SAP 3-way invoice match (synced from gd_sap_invoice_matching via lakebase_sync)
CREATE TABLE IF NOT EXISTS liveoltp.sap_invoice_matching (
  invoice_doc_number TEXT        PRIMARY KEY,
  po_number          TEXT,
  po_item            INT,
  supplier_id        TEXT,
  sku                TEXT,
  net_amount_usd     DOUBLE PRECISION,
  po_net_value_usd   DOUBLE PRECISION,
  gr_qty_g           DOUBLE PRECISION,
  variance_usd       DOUBLE PRECISION,
  status             TEXT,
  match_status       TEXT,
  event_ts           TIMESTAMPTZ
);
