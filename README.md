# LiveZerobus — Auto Procurement Demo on Databricks

Live, end-to-end Auto Procurement demo built with **Databricks Apps** (React + FastAPI), **Zerobus** ingestion, **Delta Lake** medallion storage via **Lakeflow Spark Declarative Pipelines** (`pyspark.pipelines`), **MLflow-registered** supplier scoring in Unity Catalog, and **Lakebase** (managed Postgres) for millisecond reads from the app.

```
                                ┌─────────────────────────────────────────┐
┌──────────────┐   gRPC         │      DATABRICKS LAKEHOUSE               │
│ 4 Simulators │──────────────► │  Zerobus ingest → Bronze Delta          │
│ (Python)     │   Zerobus SDK  │              │                          │
└──────────────┘                │              ▼                          │
                                │  SDP Silver  (pyspark.pipelines)        │
                                │              │                          │
                                │              ▼                          │
                                │  SDP Gold + MLflow supplier scoring     │
                                │              │                          │
                                │              ▼                          │
                                │  Synced Tables  ──►  Lakebase (Postgres)│
                                └──────────────────────────────┬──────────┘
                                                               │ SQL
                                                               ▼
                                                    ┌─────────────────────┐
                                                    │ Databricks App      │
                                                    │ FastAPI + React     │
                                                    │ (livezerobus...)    │
                                                    └─────────────────────┘
```

## What you get

Four simulated data streams → Zerobus → Delta Bronze → Silver → Gold (all Silver/Gold declared with Lakeflow **Spark Declarative Pipelines** using `pyspark.pipelines`) with ML-scored procurement decisions → Lakebase Postgres → FastAPI → React dashboard.

| Stream | What it simulates | Zerobus table |
|---|---|---|
| `inventory_events` | Warehouse stock movement per SKU/DC | `main.procurement.bz_inventory_events` |
| `supplier_quotes` | Rolling price+lead-time quotes from N suppliers per SKU | `main.procurement.bz_supplier_quotes` |
| `demand_events` | POS / order events driving demand | `main.procurement.bz_demand_events` |
| `commodity_prices` | Raw-material market prices (steel, copper, oil, wheat) | `main.procurement.bz_commodity_prices` |

## Prerequisites

You already have:

- GitHub repo: <https://github.com/lakime/LiveZerobus>
- Databricks App: `livezerobus` at <https://livezerobus-5347428297913551.11.azure.databricksapps.com>
- Service principal: `app-3dxwqo livezerobus`
- SQL warehouse: `StandardSqlWarehouse`
- Lakebase Postgres: `databricks_postgres`, branch `production`

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

### 1. Clone and push this scaffold

```bash
git clone https://github.com/lakime/LiveZerobus.git
cd LiveZerobus
# (copy every file from this scaffold into the clone)
git add .
git commit -m "Initial Auto Procurement scaffold"
git push origin main
```

### 2. Configure the bundle

Edit `databricks.yml` and set:

- `workspace.host` — your workspace URL
- `variables.catalog.default` — Unity Catalog catalog (default `main`)
- `variables.schema.default` — schema (default `procurement`)
- `variables.warehouse_id.default` — ID of `StandardSqlWarehouse`
- `variables.app_name.default` — `livezerobus`
- `variables.lakebase_instance.default` — name of your Lakebase instance

Find the warehouse ID with:

```bash
databricks warehouses list -o json | jq '.[] | select(.name=="StandardSqlWarehouse") | .id'
```

### 3. Create Unity Catalog schema + Zerobus tables

```bash
databricks bundle deploy -t dev
databricks bundle run setup_unity_catalog -t dev
```

This runs `scripts/setup_unity_catalog.py` which creates:

- Catalog/schema (if missing)
- 4 Bronze Zerobus-ingestible Delta tables (`bz_*`) with append-only properties
- Grants for the app service principal `app-3dxwqo`

### 4. Train + register the supplier-scoring model

```bash
databricks bundle run train_supplier_model -t dev
```

Registers `main.procurement.supplier_scoring_model` in Unity Catalog (MLflow).

### 5. Start the Lakeflow Spark Declarative Pipeline

```bash
databricks bundle run procurement_dlt -t dev   # bundle key kept for continuity
```

It runs continuously (all tables declared with `pyspark.pipelines`):

- Bronze → Silver (cleanse, dedupe, schema-enforce)
- Silver → Gold (rolling inventory, supplier leaderboards, demand aggregates)
- Gold → `gd_procurement_recommendations` (ML-scored reorder decisions via MLflow Unity-Catalog model)

### 6. Provision Lakebase sync

```bash
databricks bundle run lakebase_sync -t dev
```

Creates synced tables in `databricks_postgres` (production branch) for:

- `inventory_snapshot`
- `supplier_leaderboard`
- `commodity_prices_latest`
- `demand_1h`
- `procurement_recommendations`

### 7. Run the simulators (locally or as a Databricks Job)

**Locally** (easiest for demo iteration):

```bash
cd simulators
pip install -r requirements.txt
export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_CLIENT_ID=<service-principal-client-id>
export DATABRICKS_CLIENT_SECRET=<service-principal-secret>
export ZEROBUS_ENDPOINT=<workspace>.zerobus.<region>.azuredatabricks.net:443
python run_all.py --catalog main --schema procurement --rate 20
```

Or run as a Databricks Job (already wired in `resources/jobs.yml`):

```bash
databricks bundle run simulators_job -t dev
```

### 8. Deploy the Databricks App

```bash
# Build the React frontend
cd frontend && npm install && npm run build && cd ..

# Deploy the app source + start it
databricks bundle run deploy_app -t dev
databricks apps start livezerobus
```

Open <https://livezerobus-5347428297913551.11.azure.databricksapps.com> — you should see live tiles updating every few seconds.

## Layout

```
LiveZerobus/
├── README.md                  ← you are here
├── databricks.yml             ← Databricks Asset Bundle root
├── app.yaml                   ← Databricks Apps manifest
├── backend/                   ← FastAPI + Lakebase connection
├── frontend/                  ← React + Vite + TypeScript
├── simulators/                ← 4 Zerobus data producers
├── schemas/                   ← SQL DDL for Bronze / Lakebase
├── pipelines/                 ← Spark Declarative Pipelines medallion + ML scoring
├── ml/                        ← Train & register supplier model
├── lakebase_sync/             ← Delta → Postgres synced-table config
├── resources/                 ← DAB jobs / pipelines / app YAML
├── scripts/                   ← Bootstrap + setup scripts
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
uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev           # Vite serves on :5173 with a proxy to :8000
```

## Clean up

```bash
databricks bundle destroy -t dev
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a deeper walk-through and [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for a 5-minute live demo flow.
