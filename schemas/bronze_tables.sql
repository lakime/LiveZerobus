-- Bronze Delta tables backing the Zerobus ingestion streams.
-- Zerobus writes append-only rows directly into these tables via gRPC.
-- Run from scripts/setup_unity_catalog.py (or the SQL editor).
--
-- NOTE: Zerobus-ingested tables must satisfy:
--   * delta.appendOnly = true
--   * a monotonically increasing event-time column (event_ts)
-- Zerobus REJECTS tables that have `delta.columnMapping.mode` set or the
-- `allowColumnDefaults` table feature enabled. Do not add those here.
--
-- This file is the parameterized variant of schemas/setup.sql and is used by
-- scripts/setup_unity_catalog.py. The vertical-farm Seed Procurement demo
-- uses these four streams:
--   * bz_inventory_events   — seed stock movements (grams per SKU per room)
--   * bz_supplier_quotes    — rolling quotes from seed houses
--   * bz_demand_events      — planting schedule (trays to be seeded)
--   * bz_commodity_prices   — grow-input prices (substrate, nutrients, kWh)

CREATE CATALOG IF NOT EXISTS ${catalog};
CREATE SCHEMA   IF NOT EXISTS ${catalog}.${schema}
  COMMENT 'LiveZerobus — Vertical-Farm Seed Procurement demo';

-- --------------------------------------------------------------------
-- 1. Seed-inventory movement events
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_inventory_events (
  event_id     STRING    NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  sku          STRING    NOT NULL,
  room_id      STRING    NOT NULL,            -- grow room / cold vault
  lot_id       STRING,
  delta_grams  DOUBLE    NOT NULL,            -- +receive / -plant
  on_hand_g    DOUBLE    NOT NULL,
  reason       STRING                         -- PLANT|RECEIVE|ADJUST|EXPIRY|WASTE
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- 2. Supplier seed quotes
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_supplier_quotes (
  event_id         STRING    NOT NULL,
  event_ts         TIMESTAMP NOT NULL,
  supplier_id      STRING    NOT NULL,
  sku              STRING    NOT NULL,
  pack_size_g      DOUBLE    NOT NULL,
  unit_price_usd   DOUBLE    NOT NULL,
  min_qty          INT       NOT NULL,
  lead_time_days   INT       NOT NULL,
  valid_until_ts   TIMESTAMP NOT NULL,
  organic          BOOLEAN,
  currency         STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- 3. Planting-schedule events (demand)
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_demand_events (
  event_id     STRING    NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  sku          STRING    NOT NULL,
  zone_id      STRING    NOT NULL,
  trays        INT       NOT NULL,
  grams_req    DOUBLE    NOT NULL,
  crop_plan_id STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- 4. Grow-input price feed
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_commodity_prices (
  event_id      STRING    NOT NULL,
  event_ts      TIMESTAMP NOT NULL,
  input_key     STRING    NOT NULL,         -- coco_coir|peat|rockwool|nutrient_pack|kwh
  price_usd     DOUBLE    NOT NULL,
  unit          STRING,                     -- per_L|per_kg|per_kwh
  currency      STRING,
  source        STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- Reference / dimension tables
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dim_sku (
  sku               STRING NOT NULL,
  sku_name          STRING,
  crop_type         STRING,
  variety           STRING,
  days_to_harvest   INT,
  tray_yield_g      DOUBLE,
  germination_rate  DOUBLE,
  seed_per_tray_g   DOUBLE,
  reorder_point_g   DOUBLE,
  safety_stock_g    DOUBLE,
  target_stock_g    DOUBLE,
  unit_cost_hint    DOUBLE,
  organic_preferred BOOLEAN
) USING DELTA;

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dim_supplier (
  supplier_id    STRING NOT NULL,
  supplier_name  STRING,
  country        STRING,
  tier           STRING,                   -- 'preferred','qualified','probation'
  on_time_pct    DOUBLE,
  quality_score  DOUBLE,
  organic_cert   BOOLEAN,
  email          STRING,
  notes          STRING
) USING DELTA;

-- --------------------------------------------------------------------
-- 5. SAP Purchase Order events (MM module)
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_sap_purchase_orders (
  event_id         STRING    NOT NULL,
  event_ts         TIMESTAMP NOT NULL,
  po_number        STRING    NOT NULL,
  po_item          INT       NOT NULL,
  event_type       STRING    NOT NULL,            -- CREATED|APPROVED|CHANGED|CANCELLED
  supplier_id      STRING    NOT NULL,
  sku              STRING    NOT NULL,
  quantity_g       DOUBLE    NOT NULL,
  unit_price_usd   DOUBLE    NOT NULL,
  net_value_usd    DOUBLE    NOT NULL,
  currency         STRING,
  delivery_date_ts TIMESTAMP,
  plant            STRING,
  company_code     STRING,
  purchase_org     STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- 6. SAP Goods Receipt events (MIGO — movement 101/122)
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_sap_goods_receipts (
  event_id         STRING    NOT NULL,
  event_ts         TIMESTAMP NOT NULL,
  gr_doc_number    STRING    NOT NULL,
  gr_item          INT       NOT NULL,
  po_number        STRING    NOT NULL,
  po_item          INT       NOT NULL,
  sku              STRING    NOT NULL,
  qty_received_g   DOUBLE    NOT NULL,            -- negative for movement_type 122 (reversal)
  room_id          STRING,
  movement_type    STRING    NOT NULL,            -- 101=GR vs PO, 122=reversal
  batch_id         STRING,
  posting_date_ts  TIMESTAMP,
  delivery_note    STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- --------------------------------------------------------------------
-- 7. SAP Invoice documents (LIV/MIRO — 3-way match)
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bz_sap_invoice_documents (
  event_id             STRING    NOT NULL,
  event_ts             TIMESTAMP NOT NULL,
  invoice_doc_number   STRING    NOT NULL,
  po_number            STRING    NOT NULL,
  po_item              INT       NOT NULL,
  supplier_id          STRING    NOT NULL,
  invoice_date_ts      TIMESTAMP,
  posting_date_ts      TIMESTAMP,
  quantity_invoiced_g  DOUBLE,
  unit_price_usd       DOUBLE,
  net_amount_usd       DOUBLE    NOT NULL,
  tax_amount_usd       DOUBLE,
  currency             STRING,
  payment_terms        STRING,
  status               STRING    NOT NULL,        -- POSTED|PARKED|BLOCKED|CLEARED
  variance_usd         DOUBLE
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true'
);

-- Grants for the app service principal
GRANT USE CATALOG ON CATALOG ${catalog} TO `${service_principal}`;
GRANT USE SCHEMA, SELECT
  ON SCHEMA ${catalog}.${schema} TO `${service_principal}`;
