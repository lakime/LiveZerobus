# LiveZerobus — Vertical-Farm Seed Procurement Demo on Databricks

Live, end-to-end Auto Procurement demo for a vertical farm built with
**Databricks Apps** (React + FastAPI), **Zerobus** ingestion, **Delta Lake**
medallion storage via **Lakeflow Spark Declarative Pipelines**
(`pyspark.pipelines`), **MLflow-registered** seed-house scoring in Unity
Catalog, **Lakebase** (managed Postgres) for millisecond reads, and an
agent layer backed by the **Databricks Foundation Model API** for
supplier negotiation and admin tasks.

```
                                ┌─────────────────────────────────────────┐
┌──────────────┐   gRPC         │      DATABRICKS LAKEHOUSE               │
│ 4 Simulators │──────────────► │  Zerobus ingest → Bronze Delta          │
│ (Python)     │   Zerobus SDK  │              │                          │
└──────────────┘                │              ▼                          │
                                │  SDP Silver  (pyspark.pipelines)        │
                                │              │                          │
                                │              ▼                          │
                                │  SDP Gold + MLflow seed-house scoring   │
                                │              │                          │
                                │              ▼                          │
                                │  Synced Tables ──► Lakebase (Postgres)  │
                                │                      │                  │
                                │                      ▼                  │
                                │       ┌───────────────────────┐         │
                                │       │  Databricks App       │         │
                                │       │  FastAPI + React      │         │
                                │       │  + Agents (FM API)    │         │
                                │       └───────────────────────┘         │
                                └─────────────────────────────────────────┘
```

## What you get

Four simulated data streams → Zerobus → Delta Bronze → Silver → Gold (all
Silver/Gold declared with Lakeflow **Spark Declarative Pipelines** using
`pyspark.pipelines`) with ML-scored reorder decisions → Lakebase Postgres
→ FastAPI → React dashboard, plus five agents that handle email
negotiation, PO drafting, budget gating, supplier onboarding, and invoice
reconciliation.

| Stream | What it simulates | Zerobus table |
|---|---|---|
| `inventory_events` | Seed-stock movements (grams) per SKU / grow-room | `livezerobus.procurement.bz_inventory_events` |
| `supplier_quotes` | Rolling seed-pack quotes from 10 seed houses | `livezerobus.procurement.bz_supplier_quotes` |
| `demand_events` | Planting schedule (trays + grams required) | `livezerobus.procurement.bz_demand_events` |
| `commodity_prices` | Grow-input prices (coco coir, peat, rockwool, nutrient packs, kWh) | `livezerobus.procurement.bz_commodity_prices` |

### Agents

| Agent | Trigger | Output |
|---|---|---|
| `negotiator` | Open recommendation w/o RFQ; inbound supplier email | Outbox RFQs / extracted inbound intent |
| `po_drafter` | Thread with QUOTE / ACCEPT | `po_drafts` rows (`DRAFT`) |
| `budget_gate` | New DRAFT PO | `APPROVED` or `REJECTED` with rationale |
| `supplier_onboarding` | New application via UI | 0–1 score, verdict |
| `invoice_reconciler` | Invoice vs. PO | `OK` / `REVIEW` / `DISPUTE` |

## Prerequisites

You already have:

- GitHub repo: <https://github.com/lakime/LiveZerobus>
- Databricks App: `livezerobus` (URL shown in your workspace under Compute → Apps)
- Service principal: `app-3dxwqo livezerobus`
- SQL warehouse: `StandardSqlWarehouse`
- Lakebase Postgres: `databricks_postgres`, branch `production`
- Foundation Model API enabled on the workspace
  (`databricks-meta-llama-3-3-70b-instruct` serving endpoint)

Install locally (one-time):

```bash
# 1. Databricks CLI ≥ v0.240 (needed for Apps + Lakebase + Zerobus)
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
databricks -v

# 2. Authenticate against your workspace
databricks auth login --host https://<your-workspace>.azuredatabricks.net

# 3. Python 3.11 + Node 20 for local simulator/frontend work
python3 --version   # 3.11+
node --version      # 20+
```

## Step-by-step: from empty repo to live demo

### 1. Create Unity Catalog schema + Zerobus tables + agent-state tables

Open the Databricks **SQL Editor**, paste the contents of
`schemas/setup.sql`, and Run. This creates:

- Catalog `livezerobus`, schema `procurement`
- Four Bronze Zerobus-ingestible Delta tables (`bz_*`) with
  `appendOnly=true` + `columnMapping=name`
- Two dimension tables (`dim_sku` with 20 seed varieties,
  `dim_supplier` with 10 seed houses) pre-seeded via `MERGE`
- Seven agent-state Delta tables for email / PO / budget / onboarding /
  invoices / runs

Then scroll to the `GRANTS` block at the bottom of the file, replace
`<SP_APP_ID>` with the Application (client) ID of service principal
`app-3dxwqo livezerobus`, and run that block too.

### 2. Train + register the seed-house scoring model

```bash
cd ml
pip install mlflow scikit-learn numpy pandas databricks-sdk
python train_supplier_model.py
```

Registers `livezerobus.procurement.supplier_scoring_model` in Unity
Catalog at alias `@prod`. Features: `usd_per_gram`, `pack_size_g`,
`lead_time_days`, `min_qty`, `on_time_pct`, `quality_score`,
`demand_1h_trays`, `input_pct_24h`, `organic_cert_int`.

### 3. Create the Lakeflow Spark Declarative Pipeline

In the Databricks UI → **Pipelines → Create pipeline**:

- **Source**: point at the `pipelines/` folder in this repo
- **Target catalog**: `livezerobus`, **target schema**: `procurement`
- **Configuration**:
  - `pipelines.catalog` = `livezerobus`
  - `pipelines.schema`  = `procurement`
  - `livezerobus.model_name` = `livezerobus.procurement.supplier_scoring_model`
- **Channel**: `preview` (for `pyspark.pipelines`)

Start it. The pipeline runs continuously:

- Bronze → Silver (`sv_*`, cleanse + dedupe + expect)
- Silver → Gold (`gd_*`, inventory snapshot, supplier leaderboard, 1h demand)
- Gold → `gd_procurement_recommendations` (ML-scored reorder decisions)

### 4. Provision Lakebase synced tables

```bash
cd lakebase_sync
pip install -r ../backend/requirements.txt
python apply.py \
  --catalog livezerobus \
  --schema procurement \
  --lakebase-instance databricks_postgres \
  --lakebase-branch production
```

Creates synced tables for `inventory_snapshot`, `supplier_leaderboard`,
`commodity_prices_latest`, `demand_1h`, `procurement_recommendations`.

Then apply the Postgres-side DDL from `schemas/lakebase_schema.sql` via
the Lakebase SQL editor — it creates the seven **agent-state** tables
(`email_inbox`, `email_outbox`, `po_drafts`, `budget_ledger`,
`supplier_applications`, `invoice_reconciliations`, `agent_runs`) that
are written directly by the FastAPI agents.

### 5. Run the simulators (locally)

```bash
cd simulators
pip install -r requirements.txt
export DATABRICKS_HOST=https://<your-workspace>.azuredatabricks.net
export DATABRICKS_CLIENT_ID=<service-principal-client-id>
export DATABRICKS_CLIENT_SECRET=<service-principal-secret>
export ZEROBUS_ENDPOINT=<workspace>.zerobus.<region>.azuredatabricks.net:443
python run_all.py --catalog livezerobus --schema procurement --rate 20
```

### 6. Deploy the Databricks App

```bash
./scripts/deploy_app.sh
```

That runs `scripts/build_frontend.sh` (which does `npm install + build`
in `frontend/` and copies `frontend/dist/` into `backend/static/`),
`databricks sync` into the app's workspace path, then
`databricks apps deploy livezerobus`.

Open the App's URL (from the Databricks UI → Compute → Apps → `livezerobus`)
— you should see live tiles updating every few seconds, six tabs, and the
**Run agent cycle** button in the header.

See [`DEPLOY.md`](DEPLOY.md) for troubleshooting and env-var overrides.

## Layout

```
LiveZerobus/
├── README.md                  ← you are here
├── DEPLOY.md                  ← one-command app deploy runbook
├── backend/                   ← FastAPI + Lakebase + agents
│   ├── app.yaml               ← Databricks Apps manifest
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── lakebase.py
│       ├── routes/{data,agents}.py
│       └── agents/            ← FM API client + 5 agents
├── frontend/                  ← React + Vite + TypeScript (6 tabs)
├── simulators/                ← 4 Zerobus data producers
├── schemas/
│   ├── setup.sql              ← one-shot UC setup
│   ├── bronze_tables.sql      ← parameterized Bronze + dims
│   ├── seed_dimensions.sql    ← 20 seeds + 10 seed houses
│   └── lakebase_schema.sql    ← Postgres side (Gold mirrors + agent state)
├── pipelines/                 ← Spark Declarative Pipelines medallion + ML
├── ml/                        ← Train & register seed-house model
├── lakebase_sync/             ← Delta → Postgres synced-table config
├── scripts/                   ← build_frontend.sh, deploy_app.sh, setup_unity_catalog.py
└── docs/                      ← Architecture & demo walkthrough
```

## Local development

Run the backend against Lakebase and the React frontend with hot-reload:

```bash
# Terminal 1 — backend
cd backend
pip install -r requirements.txt
export DATABRICKS_HOST=...
export DATABRICKS_CLIENT_ID=...
export DATABRICKS_CLIENT_SECRET=...
export PGHOST=<lakebase-host>
export PGDATABASE=databricks_postgres
export PGUSER=<sp-uuid>
export FM_MODEL=databricks-meta-llama-3-3-70b-instruct
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev           # Vite serves on :5173 with a proxy to :8000
```

## Clean up

Stop/delete the pipeline in the UI, drop synced tables from Lakebase,
and `databricks apps stop livezerobus`. The Delta tables in Unity
Catalog are append-only historical data — drop the schema if you want a
clean slate.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a deeper walkthrough
and [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for a 7-minute demo flow.
