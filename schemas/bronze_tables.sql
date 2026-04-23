-- Bronze Delta tables backing the Zerobus ingestion streams.
-- Zerobus writes append-only rows directly into these tables via gRPC.
-- Run from scripts/setup_unity_catalog.py (or the SQL editor).
--
-- NOTE: Zerobus-ingested tables must satisfy:
--   * APPEND_ONLY = true
--   * delta.feature.allowColumnDefaults + delta.columnMapping.mode = 'name'
--   * a monotonically increasing event-time column (event_ts)

CREATE CATALOG IF NOT EXISTS ${catalog};
CREATE SCHEMA   IF NOT EXISTS ${catalog}.${schema}
  COMMENT 'LiveZerobus — Auto Procurement demo';

-- --------------------------------------------------------------------
-- 1. Inventory events
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_inventory_events (
  event_id     STRING  NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  sku          STRING  NOT NULL,
  dc_id        STRING  NOT NULL,            -- distribution center
  delta_units  INT     NOT NULL,            -- +inbound / -outbound
  on_hand      INT     NOT NULL,            -- snapshot after the event
  reason       STRING                       -- 'shipment','pick','adjust',...
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- --------------------------------------------------------------------
-- 2. Supplier quotes
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_supplier_quotes (
  event_id         STRING    NOT NULL,
  event_ts         TIMESTAMP NOT NULL,
  supplier_id      STRING    NOT NULL,
  sku              STRING    NOT NULL,
  unit_price_usd   DOUBLE    NOT NULL,
  min_qty          INT       NOT NULL,
  lead_time_days   INT       NOT NULL,
  valid_until_ts   TIMESTAMP NOT NULL,
  currency         STRING                   -- ISO-4217
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- --------------------------------------------------------------------
-- 3. Demand / sales events
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_demand_events (
  event_id     STRING    NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  sku          STRING    NOT NULL,
  store_id     STRING    NOT NULL,
  qty          INT       NOT NULL,
  unit_price   DOUBLE,
  channel      STRING                       -- 'web','retail','b2b'
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- --------------------------------------------------------------------
-- 4. Commodity / market prices
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_commodity_prices (
  event_id      STRING    NOT NULL,
  event_ts      TIMESTAMP NOT NULL,
  commodity     STRING    NOT NULL,         -- 'steel','copper','oil','wheat'
  price_usd     DOUBLE    NOT NULL,
  currency      STRING,
  source        STRING                      -- exchange symbol
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- --------------------------------------------------------------------
-- Reference / dimension tables
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dim_sku (
  sku              STRING  NOT NULL,
  sku_name         STRING,
  commodity        STRING,          -- links SKU to a commodity feed
  reorder_point    INT,
  safety_stock     INT,
  target_stock     INT,
  unit_cost_hint   DOUBLE
) USING DELTA;

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dim_supplier (
  supplier_id   STRING NOT NULL,
  supplier_name STRING,
  country       STRING,
  tier          STRING,                     -- 'gold','silver','bronze'
  on_time_pct   DOUBLE,
  quality_score DOUBLE
) USING DELTA;

-- Grants for the app service principal
GRANT USE CATALOG ON CATALOG ${catalog} TO `${service_principal}`;
GRANT USE SCHEMA, SELECT
  ON SCHEMA ${catalog}.${schema} TO `${service_principal}`;
