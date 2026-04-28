# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

LiveZerobus is a full-stack Databricks demo: four streaming simulators feed data into Delta Lake via Zerobus, a medallion ETL pipeline (Bronze→Silver→Gold) produces analytics tables, an ML model scores procurement options, and a FastAPI backend exposes five LLM-powered procurement agents plus live query endpoints. A React frontend provides 6 tabs of dashboards and agent controls. All state lives in Delta Lake (read-only via Lakebase Postgres synced tables) and Lakebase Postgres native tables (agent state: email threads, PO drafts, budget ledger, invoices).

## Commands

### Frontend
```bash
cd frontend
npm install
npm run dev         # Vite hot-reload on :5173
npm run build       # TypeScript check + Vite bundle → dist/
```

### Backend
```bash
cd backend
pip install -r requirements.txt
# Set env vars: DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET,
#               PGHOST, PGPORT, PGDATABASE, PGUSER, PG_SCHEMA, LAKEBASE_BRANCH, LAKEBASE_ENDPOINT, FM_MODEL
uvicorn app.main:app --reload --port 8000
```

### Simulators
```bash
cd simulators
pip install -r requirements.txt
# Set: DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, ZEROBUS_ENDPOINT
python run_all.py --catalog livezerobus --schema procurement --rate 20
```

### Linting
```bash
ruff check backend/ simulators/ pipelines/ ml/ scripts/ lakebase_sync/
```

### Build + deploy to Databricks
```bash
scripts/build_frontend.sh   # npm build → stages dist into backend/static/
scripts/deploy_app.sh       # build frontend + databricks sync + databricks apps deploy
```

### Bootstrap Unity Catalog (one-shot)
```bash
python scripts/setup_unity_catalog.py --host $DATABRICKS_HOST ...
```

## Architecture

### Data flow
```
Simulators → Zerobus → Bronze Delta tables (bz_*)
                     → Silver streaming tables (sv_*)   [bronze_to_silver.py]
                     → Gold materialized views (gd_*)   [silver_to_gold.py + ML scoring]
                     → Lakebase Postgres (synced read-only + native agent-state tables)
                     → FastAPI backend → React frontend
```

### Backend (`backend/app/`)
- **main.py** — FastAPI app; mounts React SPA static files; registers routes
- **config.py** — Settings loaded from environment
- **lakebase.py** — Async Postgres connection pool; short-lived OAuth tokens refreshed before expiry
- **models.py** — Pydantic response models for all API payloads
- **routes/data.py** — `/api/*` read-only queries against Lakebase (inventory, suppliers, commodity, demand, recommendations)
- **routes/agents.py** — `/api/agents/*` endpoints for reading agent state and triggering agent ticks
- **agents/llm.py** — Thin OpenAI-compatible wrapper calling Databricks Foundation Model API; mints OAuth tokens via `WorkspaceClient`
- **agents/*.py** — Five procurement agents: `negotiator`, `po_drafter`, `budget_gate`, `invoice_reconciler`, `supplier_onboarding`
- **agents/db.py** — Postgres query helpers shared by agents

### Frontend (`frontend/src/`)
- **App.tsx** — Root component with 6 tabs wiring all panels together
- **api.ts** — All `fetch` calls to the backend `/api/*` endpoints
- **components/** — One file per panel (InventoryPanel, SupplierLeaderboard, CommodityChart, PoDraftsPanel, EmailPanel, OnboardingPanel, etc.)

### Pipelines (`pipelines/`)
- **bronze_to_silver.py** — Streaming reads from 4 Bronze tables → schema-enforced Silver tables with dedup/quality gates
- **silver_to_gold.py** — Materialized Views: inventory snapshot, supplier leaderboard, commodity latest, demand 1h, procurement recommendations
- **auto_procurement_scoring.py** — Loads MLflow model as `spark_udf` applied in the Gold recommendations MV

### ML (`ml/`)
- **train_supplier_model.py** — Trains supplier scoring model; registers to UC at `livezerobus.procurement.supplier_scoring_model@prod`

### Schemas (`schemas/`)
- **setup.sql / bronze_tables.sql** — Unity Catalog DDL (catalog, schema, Bronze + dimension tables)
- **lakebase_schema.sql** — Postgres DDL for 5 synced Gold tables + 7 native agent-state tables

### Lakebase tables (Postgres)
**Synced from Gold (read-only):** `inventory_snapshot`, `supplier_leaderboard`, `commodity_latest`, `demand_1h`, `procurement_recommendations`  
**Native agent state (read-write):** `email_inbox`, `email_outbox`, `po_drafts`, `budget_ledger`, `supplier_applications`, `invoice_reconciliations`, `agent_runs`

## CI/CD (`.github/workflows/`)
- **ci.yml** — On every push/PR: TypeScript check (`npx tsc --noEmit`), frontend build, `ruff check`
- **deploy.yml** — On push to `main` or manual: build frontend → sync pipelines/ + backend/ to workspace → `databricks apps deploy`
- **bootstrap.yml** — Manual one-shot UC initialization
- **train-model.yml** — Weekly cron + manual dispatch to retrain the supplier scoring model

## Key runtime dependencies
- Python 3.11+, Node 20+, Databricks CLI v0.240+
- Databricks workspace with: Unity Catalog, Lakebase, Foundation Model API, a Lakeflow pipeline, an App runtime
- Service principal with MODIFY grants on Bronze tables + CAN_CONNECT_AND_CREATE on Lakebase
- Default FM model endpoint: `databricks-meta-llama-3-3-70b-instruct` (configurable via `FM_MODEL` env var)
- Lakebase instance name: `databricks_postgres`, branch `production`, endpoint `primary`

## Important conventions
- The React build must be staged into `backend/static/` before deploying — `build_frontend.sh` handles this. Stale `.js` files alongside `.tsx` are cleaned before every build.
- Lakebase Postgres auth uses OAuth tokens (not passwords); `lakebase.py` rotates them transparently.
- Agents are tick-based: each `/api/agents/<name>/tick` call runs one agent iteration; the frontend polls on a timer.
- Unity Catalog path: `livezerobus.procurement.*` for all Delta tables.
