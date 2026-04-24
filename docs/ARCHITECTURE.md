# Architecture — LiveZerobus Seed Procurement

A vertical-farm demo that runs end-to-end on Databricks: four Zerobus feeds land
in Delta, a Lakeflow pipeline materialises the reorder picture, Lakebase
serves the live data to a React app, and an agent layer (Databricks
Foundation Model API) negotiates with seed houses and handles admin tasks.

## Data flow

```
  Simulators (Python)                    Databricks Lakehouse                   Databricks App
  ┌───────────────┐                ┌──────────────────────────────┐          ┌──────────────┐
  │ inventory_sim │                │  Zerobus gRPC ingest endpoint │          │  React SPA   │
  │ supplier_sim  │ ─ TLS+OAuth ─► │                               │          │   (Vite)     │
  │ demand_sim    │   Zerobus SDK  │  ┌──────────────────────────┐ │          └─────┬────────┘
  │ commodity_sim │                │  │ Bronze Delta (bz_*)      │ │                │ /api/*
  └───────────────┘                │  └──────────┬───────────────┘ │          ┌─────▼────────┐
                                   │             ▼                 │          │  FastAPI     │
                                   │  ┌──────────────────────────┐ │          │  backend     │
                                   │  │ Silver (sv_*) — SDP      │ │          │  + Agents    │
                                   │  └──────────┬───────────────┘ │          │ (FM API)     │
                                   │             ▼                 │          └─────┬────────┘
                                   │  ┌──────────────────────────┐ │                │ psycopg
                                   │  │ Gold (gd_*) — SDP+MLflow │─────────────────►│ + OAuth
                                   │  └──────────────────────────┘ │ synced   ┌─────▼────────┐
                                   │                               │ tables   │  Lakebase    │
                                   │                               │          │  Postgres    │
                                   │                               │          │   live.*     │
                                   └──────────────────────────────┘          └──────────────┘
```

Every arrow is typed: gRPC (Zerobus), Delta (lake), Delta Sync (Lakebase),
psql+TLS (app), HTTPS (Foundation Model API).

## Zerobus

Four Bronze Delta tables, created once by `scripts/setup_unity_catalog.py`:

| Table | Purpose |
|---|---|
| `bz_inventory_events` | Seed stock movements — grams per SKU per grow-room |
| `bz_supplier_quotes` | Rolling quotes from seed houses (pack_size_g + unit_price_usd) |
| `bz_demand_events` | Planting schedule — trays seeded, grams of seed required |
| `bz_commodity_prices` | Grow-input prices (`coco_coir`, `peat`, `rockwool`, `nutrient_pack`, `kwh`) |

All four have `delta.appendOnly=true` and `delta.columnMapping.mode=name`,
which are the two properties Zerobus requires.

Each simulator opens a long-lived gRPC stream via the **Zerobus SDK**
(`databricks-zerobus-sdk`), authenticating with the service-principal
client id/secret. The endpoint is region-specific (see `.env.example`).
Rows are Python dataclasses matching the table columns; the SDK compiles a
protobuf descriptor at stream open.

Designed so you can swap any simulator for a real producer (a PLC in a grow
room, a nursery ERP) by re-implementing the tiny
`zerobus_stream(...)` + `stream.send(row)` contract in `simulators/common.py`.

## Lakeflow Spark Declarative Pipelines (SDP)

Silver + Gold tables are declared with `pyspark.pipelines`:

| File | Layer | Tables |
|---|---|---|
| `pipelines/bronze_to_silver.py` | Silver | `sv_inventory_events`, `sv_supplier_quotes`, `sv_demand_events`, `sv_commodity_prices` |
| `pipelines/silver_to_gold.py`   | Gold   | `gd_inventory_snapshot`, `gd_commodity_latest`, `gd_demand_1h`, `gd_supplier_quotes_current` |
| `pipelines/auto_procurement_scoring.py` | Gold | `gd_supplier_leaderboard`, `gd_procurement_recommendations` |

Silver adds the derived `usd_per_gram` column to each supplier quote; Gold
joins seed SKUs to their dominant grow-input (microgreens → `coco_coir`,
leafy greens → `rockwool`) and computes `reorder_grams = max(target_stock_g
- on_hand_g, 0)` for anything below `reorder_point_g`.

Expectations (`@dp.expect_or_drop`) enforce schema/quality. Catalog + schema
are passed in via `pipelines.catalog` / `pipelines.schema` config.

## ML — seed-house supplier scoring

`ml/train_supplier_model.py` trains a Gradient-Boosting regressor on
synthetic but realistically-shaped seed-buying data, then registers it as
**`livezerobus.procurement.supplier_scoring_model`** in Unity Catalog with
alias `@prod`.

The Gold pipeline calls `mlflow.pyfunc.spark_udf(...)` once per executor,
vectorizing inference across every (sku, supplier) pair. Features:

- Pricing: `usd_per_gram`, `pack_size_g`
- Logistics: `lead_time_days`, `min_qty`
- Seed-house reliability: `on_time_pct`, `quality_score`
- Planting urgency: `demand_1h_trays`
- Market context: `input_pct_24h` (grow-input 24h trend)
- Organic fit: `organic_cert_int`

Output: a 0..1 score. Top-ranked supplier per SKU is chosen for the
recommendation.

## Lakebase sync

`lakebase_sync/apply.py` reads `synced_tables.yml` and creates one
**Synced Table** per Gold table in the `databricks_postgres` instance /
`production` branch:

```
gd_inventory_snapshot          → live.inventory_snapshot          CONTINUOUS
gd_supplier_leaderboard        → live.supplier_leaderboard        CONTINUOUS
gd_commodity_latest            → live.commodity_prices_latest     CONTINUOUS
gd_demand_1h                   → live.demand_1h                   SNAPSHOT 60s
gd_procurement_recommendations → live.procurement_recommendations CONTINUOUS
```

Postgres DDL (`schemas/lakebase_schema.sql`) creates:
- The five Gold-mirror tables (read-only, populated by Synced Tables)
- Seven **agent-state** tables (read-write, populated directly by the
  FastAPI agents): `email_inbox`, `email_outbox`, `po_drafts`,
  `budget_ledger`, `supplier_applications`, `invoice_reconciliations`,
  `agent_runs`.

The agent-state tables never travel through Zerobus — Lakebase is their
system of record, because agents UPDATE rows (negotiation status, budget
balance, reconciliation verdicts) and Zerobus is append-only.

## Agent layer (Databricks Foundation Model API)

Five agents live under `backend/app/agents/`:

| Agent | Trigger | What it does |
|---|---|---|
| `negotiator` | Open recommendation with no RFQ sent yet, OR unprocessed inbound email | Drafts an RFQ (or reads a supplier reply), writes to `email_outbox` / updates `email_inbox.extracted_json` |
| `po_drafter` | Thread has a QUOTE / ACCEPT reply | Creates a `DRAFT` row in `po_drafts` with pack count + unit price |
| `budget_gate` | New `DRAFT` PO | Lazy-seeds a monthly SEED budget ($25 000), approves ≤ balance, else REJECTED |
| `supplier_onboarding` | New application submitted via UI | Scores 0–1 against a weighted rubric, verdict APPROVED/SCREENING/REJECTED |
| `invoice_reconciler` | Received invoice row | Computes variance vs. PO total, OK/REVIEW/DISPUTE |

All five use `FoundationModelClient`, which posts OpenAI-compatible chat
completions to `/serving-endpoints/databricks-meta-llama-3-3-70b-instruct/invocations`
with the app's own OAuth token (`WorkspaceClient().config.authenticate()`).

Every run is logged to `live.agent_runs` with prompt/output token counts,
status, and input/output refs — this is what powers the "Agent runs" tab.

The `Run agent cycle` button in the UI calls `/api/agents/cycle`, which
chains negotiator → po_drafter → budget_gate → reconciler in a single
pass — handy for the demo narrative.

## FastAPI backend

- One file per concern: `config.py`, `lakebase.py`, `models.py`,
  `routes/data.py`, `routes/agents.py`, `main.py`.
- Auth: `databricks.sdk.WorkspaceClient().database.generate_database_credential(...)`
  returns a short-lived token used as the Postgres password. A background
  refresh happens 60s before expiry.
- Single `psycopg_pool.ConnectionPool` with `search_path TO live, public`.
- Endpoints (read): `/api/summary`, `/api/inventory`, `/api/suppliers/leaderboard`,
  `/api/commodity/latest`, `/api/demand/hourly`, `/api/recommendations`.
- Endpoints (agents): `/api/agents/email/threads`, `/po_drafts`, `/budget`,
  `/applications`, `/invoices`, `/runs`, plus `POST` `/applications`,
  `/negotiator/tick`, `/negotiator/simulate-reply`, `/po_drafter/tick`,
  `/budget_gate/tick`, `/onboarding/tick`, `/reconciler/tick`, `/cycle`.
- Serves the built React bundle from `frontend/dist` as SPA fallback.

## React frontend

Vite + TypeScript + Recharts. Six tabs:
`Dashboard`, `Emails`, `POs & Budget`, `Supplier onboarding`, `Invoices`,
`Agent runs`. Every component polls its endpoint on the shared `tick`
prop (every 3s). Dark theme in `styles.css`. No external state store —
the app is almost entirely read-only except for the application form and
the tick-the-agents buttons.

## Security boundaries

- Simulators authenticate to Zerobus with the app service principal
  (`app-3dxwqo`). In a real deployment, use a separate "ingest" SP.
- The app reads Lakebase via a short-lived OAuth token unique to its own
  SP, with `CAN_CONNECT_AND_CREATE` on `databricks_postgres`.
- The app has `SELECT` + `MODIFY` on the agent-state Delta schema so it
  can both read Gold and write outbox/PO/budget rows via the FM agents.
- The Foundation Model API call uses the same SP identity; no separate
  API key to manage.
