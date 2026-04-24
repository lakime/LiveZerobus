-- =============================================================================
-- LiveZerobus — one-shot setup SQL (Vertical-Farm Seed Procurement).
--
-- Paste this whole file into the Databricks SQL editor on the workspace that
-- hosts the `livezerobus` app and Run.
--
-- What it does:
--   1. Creates catalog `livezerobus` (if missing) and schema
--      `livezerobus.procurement`.
--   2. Creates the four Bronze tables that Zerobus writes into
--      (append-only + columnMapping=name are the two Zerobus requirements).
--   3. Creates + seeds `dim_sku` (seed varieties) and `dim_supplier`
--      (seed houses) with realistic vertical-farm data.
--   4. Creates the agent-state Delta tables that the app + agents read
--      from (these get Synced to Lakebase).
--
-- After running the block above, scroll to the GRANTS section at the bottom,
-- replace <SP_APP_ID> with the Application (client) ID of service principal
-- `app-3dxwqo livezerobus`, and run that block too.
--
-- NOTE: there is no separate "enable Zerobus" SQL command. Zerobus is a
-- gRPC ingestion path that writes into any Delta table that already
-- satisfies the two table requirements below. The only workspace-level
-- step (if your workspace isn't already enabled) is toggling the Zerobus
-- preview in Admin Console → Previews.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS livezerobus;

CREATE SCHEMA IF NOT EXISTS livezerobus.procurement
  COMMENT 'LiveZerobus — Vertical-Farm Seed Procurement demo';

USE CATALOG livezerobus;
USE SCHEMA  procurement;


-- ---------------------------------------------------------------------------
-- Bronze tables (Zerobus ingestion targets)
--
-- Required Delta properties for Zerobus:
--   * delta.appendOnly = true          (Zerobus only appends)
--   * delta.columnMapping.mode = name  (enables schema evolution by name)
-- A monotonically increasing event-time column (event_ts) is expected by
-- downstream pipelines.
-- ---------------------------------------------------------------------------

-- Seed inventory movements per SKU per grow room. `delta_grams` can be
-- negative (planting/seed-out) or positive (receipts / adjustments).
CREATE TABLE IF NOT EXISTS bz_inventory_events (
  event_id     STRING    NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  sku          STRING    NOT NULL,
  room_id      STRING    NOT NULL,     -- grow room / cold-storage vault
  lot_id       STRING,                 -- supplier lot for traceability
  delta_grams  DOUBLE    NOT NULL,
  on_hand_g    DOUBLE    NOT NULL,
  reason       STRING                  -- PLANT|RECEIVE|ADJUST|EXPIRY|WASTE
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- Rolling supplier quotes. `pack_size_g` + `unit_price_usd` lets us compare
-- suppliers fairly even when they sell different pack sizes.
CREATE TABLE IF NOT EXISTS bz_supplier_quotes (
  event_id         STRING    NOT NULL,
  event_ts         TIMESTAMP NOT NULL,
  supplier_id      STRING    NOT NULL,
  sku              STRING    NOT NULL,
  pack_size_g      DOUBLE    NOT NULL,
  unit_price_usd   DOUBLE    NOT NULL, -- price per pack
  min_qty          INT       NOT NULL, -- min packs per order
  lead_time_days   INT       NOT NULL,
  valid_until_ts   TIMESTAMP NOT NULL,
  organic          BOOLEAN,
  currency         STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- Planting schedule = demand. One event per scheduled tray/flat seeding.
CREATE TABLE IF NOT EXISTS bz_demand_events (
  event_id    STRING    NOT NULL,
  event_ts    TIMESTAMP NOT NULL,
  sku         STRING    NOT NULL,
  zone_id     STRING    NOT NULL,     -- grow zone
  trays       INT       NOT NULL,     -- number of trays seeded
  grams_req   DOUBLE    NOT NULL,     -- grams of seed required total
  crop_plan_id STRING                 -- links to production plan
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);

-- Input/commodity price feed — substrate, nutrients, power. Drives
-- make-vs-buy and recommended-quantity logic in the Gold layer.
CREATE TABLE IF NOT EXISTS bz_commodity_prices (
  event_id   STRING    NOT NULL,
  event_ts   TIMESTAMP NOT NULL,
  input_key  STRING    NOT NULL,     -- coco_coir|peat|rockwool|nutrient_pack|kwh
  price_usd  DOUBLE    NOT NULL,
  unit       STRING,                 -- per_L | per_kg | per_kwh
  currency   STRING,
  source     STRING
)
USING DELTA
TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.feature.allowColumnDefaults' = 'supported'
);


-- ---------------------------------------------------------------------------
-- Reference / dimension tables (regular Delta)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_sku (
  sku               STRING NOT NULL,
  sku_name          STRING,                 -- "Butterhead 'Rex'"
  crop_type         STRING,                 -- lettuce|basil|kale|microgreens|...
  variety           STRING,
  days_to_harvest   INT,
  tray_yield_g      DOUBLE,                 -- grams of finished product per tray
  germination_rate  DOUBLE,                 -- 0..1
  seed_per_tray_g   DOUBLE,                 -- avg grams of seed per tray
  reorder_point_g   DOUBLE,
  safety_stock_g    DOUBLE,
  target_stock_g    DOUBLE,
  unit_cost_hint    DOUBLE,                 -- internal cost estimate, usd per gram
  organic_preferred BOOLEAN
) USING DELTA;

CREATE TABLE IF NOT EXISTS dim_supplier (
  supplier_id    STRING NOT NULL,
  supplier_name  STRING,
  country        STRING,
  tier           STRING,             -- 'preferred','qualified','probation'
  on_time_pct    DOUBLE,
  quality_score  DOUBLE,
  organic_cert   BOOLEAN,
  email          STRING,             -- demo-only simulated mailbox
  notes          STRING
) USING DELTA;


-- ---------------------------------------------------------------------------
-- Seed the reference tables (idempotent — uses MERGE)
-- ---------------------------------------------------------------------------

MERGE INTO dim_sku t
USING (
  SELECT * FROM VALUES
    ('SEED-LETT-BUT-01','Butterhead "Rex"',            'lettuce',     'Rex',              32, 200.0, 0.95, 0.35, 120.0, 40.0, 400.0, 0.35, true),
    ('SEED-LETT-RED-01','Red Oakleaf "Salanova"',      'lettuce',     'Salanova',         35, 180.0, 0.92, 0.32, 110.0, 35.0, 380.0, 0.42, true),
    ('SEED-LETT-ROM-01','Romaine "Dragoon"',           'lettuce',     'Dragoon',          28, 220.0, 0.94, 0.30, 130.0, 40.0, 420.0, 0.30, false),
    ('SEED-BAS-GEN-01', 'Genovese Basil "Nufar"',      'basil',       'Nufar',            25, 150.0, 0.90, 0.55,  90.0, 25.0, 300.0, 0.85, true),
    ('SEED-BAS-THA-01', 'Thai Basil "Siam Queen"',     'basil',       'Siam Queen',       27, 140.0, 0.88, 0.58,  85.0, 25.0, 280.0, 1.10, false),
    ('SEED-KALE-LAC-01','Lacinato Kale "Nero di Toscana"','kale',     'Nero di Toscana',  30, 170.0, 0.91, 0.40, 100.0, 30.0, 340.0, 0.48, true),
    ('SEED-KALE-RED-01','Red Russian Kale',            'kale',        'Red Russian',      30, 165.0, 0.89, 0.38, 100.0, 30.0, 330.0, 0.55, true),
    ('SEED-ARU-AST-01', 'Astro Arugula',               'arugula',     'Astro',            21, 160.0, 0.93, 0.45, 115.0, 35.0, 380.0, 0.38, true),
    ('SEED-SPIN-SPA-01','Space Spinach',               'spinach',     'Space',            26, 190.0, 0.87, 0.80, 140.0, 45.0, 460.0, 0.52, false),
    ('SEED-MG-RAD-01',  'Radish Microgreens "Rambo"',  'microgreens', 'Rambo',             8, 320.0, 0.96, 7.50, 350.0,100.0,1100.0, 0.18, true),
    ('SEED-MG-PEA-01',  'Pea Shoots "Speckled"',       'microgreens', 'Speckled Pea',     12, 450.0, 0.97,18.00, 700.0,200.0,2200.0, 0.12, true),
    ('SEED-MG-SUN-01',  'Sunflower Microgreens',       'microgreens', 'Black Oil',        10, 380.0, 0.95,14.00, 600.0,170.0,1900.0, 0.15, true),
    ('SEED-MG-BROC-01', 'Broccoli Microgreens',        'microgreens', 'Waltham 29',        9, 300.0, 0.94, 6.00, 300.0, 90.0,1000.0, 0.22, true),
    ('SEED-MG-AMA-01',  'Amaranth Microgreens "Red Garnet"','microgreens','Red Garnet',   11, 260.0, 0.91, 2.80, 200.0, 60.0, 700.0, 0.34, false),
    ('SEED-HERB-CIL-01','Cilantro "Calypso"',          'herb',        'Calypso',          30, 145.0, 0.85, 3.60, 220.0, 65.0, 720.0, 0.58, true),
    ('SEED-HERB-PAR-01','Parsley "Giant of Italy"',    'herb',        'Giant of Italy',   35, 130.0, 0.82, 2.50, 180.0, 55.0, 600.0, 0.44, true),
    ('SEED-HERB-DIL-01','Dill "Bouquet"',              'herb',        'Bouquet',          35, 120.0, 0.83, 2.20, 170.0, 50.0, 560.0, 0.36, false),
    ('SEED-BOK-SHA-01', 'Shanghai Bok Choy',           'asian-green', 'Shanghai',         30, 210.0, 0.93, 0.40, 120.0, 35.0, 400.0, 0.40, true),
    ('SEED-MUST-WAS-01','Wasabi Mustard',              'asian-green', 'Wasabina',         22, 175.0, 0.90, 0.70, 110.0, 30.0, 360.0, 0.68, false),
    ('SEED-TAT-RED-01', 'Red Tatsoi',                  'asian-green', 'Rosie',            25, 180.0, 0.89, 0.65, 115.0, 30.0, 380.0, 0.62, true)
  AS s(sku, sku_name, crop_type, variety, days_to_harvest, tray_yield_g, germination_rate,
       seed_per_tray_g, reorder_point_g, safety_stock_g, target_stock_g, unit_cost_hint, organic_preferred)
) s
ON t.sku = s.sku
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

MERGE INTO dim_supplier t
USING (
  SELECT * FROM VALUES
    ('SUP-JOHNNY',   'Johnny''s Selected Seeds',  'US', 'preferred', 0.97, 0.95, true,  'orders@johnnyseeds.demo',   'Maine-based. Strong on lettuce + herbs.'),
    ('SUP-HIGHMOW',  'High Mowing Organic Seeds', 'US', 'preferred', 0.96, 0.96, true,  'sales@highmowing.demo',     '100% certified organic.'),
    ('SUP-TRUELEAF', 'True Leaf Market',          'US', 'qualified', 0.91, 0.89, false, 'wholesale@trueleaf.demo',   'Bulk microgreens specialist.'),
    ('SUP-KITAZAWA', 'Kitazawa Seed Co',          'US', 'qualified', 0.92, 0.91, false, 'orders@kitazawa.demo',      'Asian greens leader.'),
    ('SUP-RIJK',     'Rijk Zwaan',                'NL', 'preferred', 0.98, 0.97, false, 'accounts@rijkzwaan.demo',   'Premium greenhouse breeder.'),
    ('SUP-ENZA',     'Enza Zaden',                'NL', 'preferred', 0.95, 0.96, true,  'orders@enzazaden.demo',     'Vertical-farm focus.'),
    ('SUP-VITALIS',  'Vitalis Organic Seeds',     'NL', 'qualified', 0.93, 0.94, true,  'eu@vitalis.demo',           'Organic arm of Enza.'),
    ('SUP-WESTCOAST','West Coast Seeds',          'CA', 'qualified', 0.89, 0.88, true,  'sales@westcoast.demo',      'Pacific NW regional.'),
    ('SUP-KOPPERT',  'Koppert Cress',             'NL', 'probation', 0.82, 0.90, false, 'b2b@koppertcress.demo',     'Specialty microgreens, new partner.'),
    ('SUP-VILMORIN', 'Vilmorin',                  'FR', 'qualified', 0.90, 0.92, false, 'international@vilmorin.demo','Long-standing French breeder.')
  AS s(supplier_id, supplier_name, country, tier, on_time_pct, quality_score, organic_cert, email, notes)
) s
ON t.supplier_id = s.supplier_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;


-- ---------------------------------------------------------------------------
-- Agent-state tables (Delta) — written by the app + agents; synced to
-- Lakebase so the React UI reads them over Postgres. Not append-only so we
-- can update rows (e.g. negotiation status). Zerobus is NOT used here.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS email_outbox (
  email_id        STRING NOT NULL,
  thread_id       STRING NOT NULL,
  created_ts      TIMESTAMP,
  supplier_id     STRING,
  supplier_email  STRING,
  subject         STRING,
  body_md         STRING,
  sku             STRING,
  intent          STRING,      -- RFQ | COUNTER | CONFIRM | ONBOARD | DUNNING
  sent_by         STRING,      -- agent name
  status          STRING       -- DRAFT | SENT | BOUNCED
) USING DELTA;

CREATE TABLE IF NOT EXISTS email_inbox (
  email_id        STRING NOT NULL,
  thread_id       STRING NOT NULL,
  received_ts     TIMESTAMP,
  supplier_id     STRING,
  supplier_email  STRING,
  subject         STRING,
  body_md         STRING,
  sku             STRING,
  intent_detected STRING,      -- QUOTE | COUNTER | ACCEPT | REJECT | OOF
  extracted_json  STRING,      -- LLM-extracted structured fields
  processed       BOOLEAN
) USING DELTA;

CREATE TABLE IF NOT EXISTS po_drafts (
  po_id           STRING NOT NULL,
  created_ts      TIMESTAMP,
  thread_id       STRING,
  sku             STRING,
  supplier_id     STRING,
  packs           INT,
  pack_size_g     DOUBLE,
  total_grams     DOUBLE,
  unit_price_usd  DOUBLE,
  total_cost_usd  DOUBLE,
  needed_by       DATE,
  status          STRING,      -- DRAFT | APPROVED | REJECTED | SENT | RECEIVED
  rationale       STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS budget_ledger (
  ledger_id       STRING NOT NULL,
  entry_ts        TIMESTAMP,
  period_ym       STRING,      -- e.g. 2026-04
  category        STRING,      -- SEED | SUBSTRATE | NUTRIENTS | OVERHEAD
  delta_usd       DOUBLE,      -- negative = spend, positive = allocation
  balance_usd     DOUBLE,
  po_id           STRING,
  note            STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS supplier_applications (
  application_id  STRING NOT NULL,
  submitted_ts    TIMESTAMP,
  supplier_name   STRING,
  contact_email   STRING,
  country         STRING,
  offered_skus    STRING,      -- comma-sep
  organic_cert    BOOLEAN,
  years_in_biz    INT,
  status          STRING,      -- NEW | SCREENING | APPROVED | REJECTED
  score           DOUBLE,
  agent_notes     STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS invoice_reconciliations (
  reconciliation_id STRING NOT NULL,
  received_ts       TIMESTAMP,
  po_id             STRING,
  supplier_id       STRING,
  invoiced_amount_usd DOUBLE,
  expected_amount_usd DOUBLE,
  variance_usd        DOUBLE,
  variance_pct        DOUBLE,
  status              STRING,  -- OK | REVIEW | DISPUTE | PAID
  agent_notes         STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS agent_runs (
  run_id        STRING NOT NULL,
  started_ts    TIMESTAMP,
  finished_ts   TIMESTAMP,
  agent_name    STRING,       -- negotiator | po_drafter | budget_gate | ...
  input_ref     STRING,       -- e.g. thread_id or po_id
  output_ref    STRING,
  prompt_tokens INT,
  output_tokens INT,
  status        STRING,       -- OK | ERROR
  error_msg     STRING
) USING DELTA;


-- ---------------------------------------------------------------------------
-- Sanity check — you should see the four bz_*, two dim_*, and seven
-- agent-state tables.
-- ---------------------------------------------------------------------------
SHOW TABLES IN livezerobus.procurement;


-- =============================================================================
-- GRANTS — run this block SEPARATELY after replacing <SP_APP_ID>.
--
-- <SP_APP_ID> = Application (client) ID of service principal
--               `app-3dxwqo livezerobus`
-- Find it in Databricks UI → Settings → Identity and access
--   → Service principals → app-3dxwqo livezerobus → Application ID
--   (e.g. 1a2b3c4d-5678-90ab-cdef-1234567890ab)
--
-- MODIFY on the four bz_* tables is what lets Zerobus clients
-- authenticating as the SP append events. MODIFY on the agent-state
-- tables lets the app write drafts / PO rows.
-- =============================================================================

-- GRANT USE CATALOG ON CATALOG livezerobus TO `<SP_APP_ID>`;
-- GRANT USE SCHEMA, SELECT ON SCHEMA livezerobus.procurement TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.bz_inventory_events      TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.bz_supplier_quotes       TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.bz_demand_events         TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.bz_commodity_prices      TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.email_outbox             TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.email_inbox              TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.po_drafts                TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.budget_ledger            TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.supplier_applications    TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.invoice_reconciliations  TO `<SP_APP_ID>`;
-- GRANT MODIFY ON TABLE livezerobus.procurement.agent_runs               TO `<SP_APP_ID>`;
