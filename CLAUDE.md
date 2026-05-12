# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

LiveZerobus is a full-stack Databricks demo: **six streaming simulators** feed data into Delta Lake via Zerobus, a medallion ETL pipeline (Bronze→Silver→Gold) produces analytics tables, an ML model scores procurement options, and a FastAPI backend exposes five LLM-powered procurement agents plus live query endpoints. A React frontend provides 9 tabs of dashboards and agent controls. All state lives in Delta Lake (read-only via Lakebase Postgres synced tables) and Lakebase Postgres native tables (agent state: email threads, PO drafts, budget ledger, invoices).

The six simulators cover:
- **Procurement** — inventory events, supplier quotes, commodity prices, demand/planting events
- **SAP P2P** — full procure-to-pay cycle (Purchase Orders → Goods Receipts → Invoice Documents)
- **IoT** — 6 grow rooms × 7 sensor types (temperature, humidity, soil moisture, light, CO₂, pH, EC) with fault injection and status thresholds (NOMINAL / CAUTION / ALERT)

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

# Or launch the GUI control panel (starts/stops all sims, shows live logs,
# manages config, triggers the Lakeflow pipeline every 10 min while running):
python sim_ui.py
```

Copy `simulators/.env.example` → `simulators/.env` and fill in credentials before running.

### Linting
```bash
ruff check backend/ simulators/ pipelines/ ml/ scripts/ lakebase_sync/
```

### Build + deploy to Databricks

**IMPORTANT — always deploy via GitHub Actions, never via `scripts/deploy_app.sh` directly.**

The Databricks App `livezerobus` is owned by the service principal `c4352007-a55b-4da5-b5c9-f4c8df89e58a`. Only deployments made by that SP become the "Active" deployment that actually serves traffic. Running `databricks apps deploy` with personal user credentials (i.e. running `deploy_app.sh` locally) creates a deployment record that shows `SUCCEEDED` in the CLI but does **not** replace the SP-owned active deployment — the app continues to serve the old version.

**Correct deploy path:**
1. Merge changes to `main` and push to GitHub.
2. The `.github/workflows/deploy.yml` CI/CD workflow runs automatically, builds the frontend, syncs `pipelines/` and `backend/` to the workspace, then calls `databricks apps deploy` using SP credentials from GitHub secrets.
3. Watch progress at `https://github.com/lakime/LiveZerobus/actions`.

```bash
# Local scripts — for development/testing only, NOT for production deploys
scripts/build_frontend.sh   # npm build → stages dist into backend/static/
scripts/deploy_app.sh       # build frontend + databricks sync (user credentials — does NOT update the live app)
```

If you need to trigger a deploy without a code change, use the GitHub Actions **workflow_dispatch** (manual trigger) on `deploy.yml`.

### Bootstrap Unity Catalog (one-shot)
```bash
python scripts/setup_unity_catalog.py --host $DATABRICKS_HOST ...
```

## Architecture

### Data flow
```
Simulators (6) → Zerobus → Bronze Delta tables (bz_*)
                          → Silver streaming tables (sv_*)   [bronze_to_silver.py]
                          → Gold materialized views (gd_*)   [silver_to_gold.py + ML scoring]
                          → Lakebase Postgres (synced read-only + native agent-state tables)
                          → FastAPI backend → React frontend

Simulator streams and their Bronze tables:
  inventory_simulator   → bz_inventory_events
  supplier_simulator    → bz_supplier_quotes
  commodity_simulator   → bz_commodity_prices
  demand_simulator      → bz_demand_events
  sap_simulator         → bz_sap_purchase_orders, bz_sap_goods_receipts, bz_sap_invoice_documents
  iot_simulator         → bz_iot_sensor_events
```

### Backend (`backend/app/`)
- **main.py** — FastAPI app; mounts React SPA static files; serves `index.html` with `Cache-Control: no-store`; registers routes
- **config.py** — Settings loaded from environment
- **lakebase.py** — Postgres connection pool; short-lived OAuth tokens rotated via `w.postgres.generate_database_credential`
- **models.py** — Pydantic response models for all API payloads
- **routes/data.py** — `/api/*` read-only queries: inventory, suppliers, commodity, demand, recommendations, **IoT sensors** (`/api/iot/sensors`), **SAP PO lines** (`/api/sap/po-lines`), **SAP invoice matching** (`/api/sap/invoice-matching`)
- **routes/agents.py** — `/api/agents/*` endpoints for reading agent state and triggering agent ticks
- **agents/llm.py** — Thin OpenAI-compatible wrapper calling Databricks Foundation Model API; mints OAuth tokens via `WorkspaceClient`
- **agents/*.py** — Five procurement agents: `negotiator`, `po_drafter`, `budget_gate`, `invoice_reconciler`, `supplier_onboarding`
- **agents/db.py** — Postgres query helpers shared by agents

### Frontend (`frontend/src/`)
- **App.tsx** — Root component with **9 tabs**: Dashboard, Emails, POs & Budget, Supplier Onboarding, Invoices, Agent Runs, SAP P2P, IoT Fields, Pipeline. Every tab has a `↻ Refresh` button (manual re-fetch).
- **api.ts** — All `fetch` calls to the backend `/api/*` endpoints
- **components/**
  - `InventoryPanel`, `SupplierLeaderboard`, `CommodityChart`, `DemandChart`, `RecommendationsTable` — Dashboard tab
  - `EmailPanel`, `PoDraftsPanel`, `BudgetPanel`, `OnboardingPanel`, `InvoicesPanel`, `AgentRunsPanel` — Agent tabs
  - **`SapPanel`** — SAP P2P tab: two tables (Open PO Lines + 3-way Invoice Match), filterable by status
  - **`IotFieldsPanel`** — IoT Fields tab: farm overview header + per-room cards with SVG arc-gauge speedometers + sparklines for all 7 sensor types; colour-coded NOMINAL/CAUTION/ALERT
  - **`PipelinePanel`** — Pipeline tab: Lakeflow pipeline status + manual trigger

### Simulators (`simulators/`)
- **inventory_simulator.py** — Emits seed stock changes per grow room
- **supplier_simulator.py** — Emits supplier quote updates
- **commodity_simulator.py** — Emits commodity price ticks
- **demand_simulator.py** — Emits planting/demand events
- **sap_simulator.py** — Full SAP procure-to-pay cycle:
  - Generates Purchase Orders (`bz_sap_purchase_orders`) with realistic SAP doc numbers
  - After `GR_DELAY_S` (~30 s), posts a Goods Receipt (`bz_sap_goods_receipts`); occasionally emits a movement-122 reversal
  - After `INV_DELAY_S` (~15 s), posts an Invoice Document (`bz_sap_invoice_documents`); invoices with >2% variance are automatically blocked
- **iot_simulator.py** — 6 grow rooms × 7 sensors (temperature, humidity, soil moisture, light, CO₂, pH, EC):
  - Each sensor slow-mean-reverts to its nominal value between cycles
  - Random fault injection drifts a sensor out of bounds; faults self-recover after ~5 min
  - Emits to `bz_iot_sensor_events` with room ID, sensor type, value, unit
- **sim_ui.py** — FastAPI-based GUI control panel (Tkinter-free, runs in the browser at `:8765`):
  - Start / Stop all simulators or individual ones
  - Live log viewer with per-simulator colour coding
  - Config tab to read/write `.env` settings (DATABRICKS_HOST, LAKEBASE_INSTANCE, etc.)
  - Pipeline panel: triggers `livezerobus_procurement_sdp` every 10 min while sims are running; manual "▶ Run now" button

### Pipelines (`pipelines/`)
- **bronze_to_silver.py** — Streaming reads from **6 Bronze tables** → schema-enforced Silver tables with dedup/quality gates:
  - Procurement: `sv_inventory_events`, `sv_supplier_quotes`, `sv_commodity_prices`, `sv_demand_events`
  - SAP: `sv_sap_purchase_orders`, `sv_sap_goods_receipts`, `sv_sap_invoice_documents`
  - IoT: `sv_iot_sensor_events`
- **silver_to_gold.py** — Materialized Views (Gold):
  - Procurement: `gd_inventory_snapshot`, `gd_supplier_leaderboard`, `gd_commodity_latest`, `gd_demand_1h`, `gd_procurement_recommendations`
  - SAP: `gd_sap_open_po_lines` (latest PO event per line + GR status), `gd_sap_invoice_matching` (3-way match PO × GR × Invoice)
  - IoT: `gd_iot_sensor_latest` (latest reading per room/sensor with NOMINAL/CAUTION/ALERT threshold join)
- **auto_procurement_scoring.py** — Loads MLflow model as `spark_udf` applied in the Gold recommendations MV

> **Pipeline glob path** (Databricks DLT pipeline `livezerobus_procurement_sdp`, ID `4cef05ca-ea6f-4217-af60-6b75a6b1a3f4`):  
> `/Workspace/Users/puzar@devsoftserveinc.com/livezerobus/pipelines/**`  
> If the pipeline is recreated, ensure this glob is set correctly — a wrong path means no tables are materialised.

### ML (`ml/`)
- **train_supplier_model.py** — Trains supplier scoring model; registers to UC at `livezerobus.procurement.supplier_scoring_model@prod`

### Schemas (`schemas/`)
- **setup.sql / bronze_tables.sql** — Unity Catalog DDL (catalog, schema, Bronze + dimension tables)
- **lakebase_schema.sql** — Postgres DDL for 5 synced Gold tables + 7 native agent-state tables

### Lakebase tables (Postgres, schema: `procurement`)
**Synced from Gold (read-only):**
| Table | Source Gold MV | Key columns |
|---|---|---|
| `inventory_snapshot` | `gd_inventory_snapshot` | `sku`, `room_id`, `on_hand_g` |
| `supplier_leaderboard` | `gd_supplier_leaderboard` | `supplier_id`, `sku`, `score`, `rank` |
| `commodity_prices_latest` | `gd_commodity_latest` | `input_key`, `price_usd`, `pct_1h`, `pct_24h` |
| `demand_1h` | `gd_demand_1h` | `sku`, `hour_ts`, `trays` |
| `procurement_recommendations` | `gd_procurement_recommendations` | `sku`, `decision`, `ml_score` |
| `sap_po_lines` | `gd_sap_open_po_lines` | `po_number`, `po_item`, `po_status`, `qty_outstanding_g` |
| `sap_invoice_matching` | `gd_sap_invoice_matching` | `invoice_doc_number`, `match_status`, `variance_usd` |
| `iot_sensor_latest` | `gd_iot_sensor_latest` | `room_id`, `sensor_type`, `value`, `status` |

**Native agent state (read-write):** `email_inbox`, `email_outbox`, `po_drafts`, `budget_ledger`, `supplier_applications`, `invoice_reconciliations`, `agent_runs`

## CI/CD (`.github/workflows/`)
- **ci.yml** — On every push/PR: TypeScript check (`npx tsc --noEmit`), frontend build, `ruff check`
- **deploy.yml** — On push to `main` or manual: build frontend → sync pipelines/ + backend/ to workspace → `databricks apps deploy`
- **bootstrap.yml** — Manual one-shot UC initialization
- **train-model.yml** — Weekly cron + manual dispatch to retrain the supplier scoring model

## Key runtime dependencies
- Python 3.11+, Node 20+, Databricks CLI v0.240+
- Databricks workspace with: Unity Catalog, Lakebase, Foundation Model API, a Lakeflow pipeline, an App runtime
- Service principal with MODIFY grants on **all 6 Bronze tables** (`bz_inventory_events`, `bz_supplier_quotes`, `bz_commodity_prices`, `bz_demand_events`, `bz_sap_purchase_orders`, `bz_sap_goods_receipts`, `bz_sap_invoice_documents`, `bz_iot_sensor_events`) + CAN_CONNECT_AND_CREATE on Lakebase
- Default FM model endpoint: `databricks-meta-llama-3-3-70b-instruct` (configurable via `FM_MODEL` env var)
- Lakebase project name: `myzerobus`, branch `production`, endpoint `primary`
- Lakebase Postgres host: `ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net`
- Lakebase Postgres database: `databricks_postgres`, user: service principal UUID `c4352007-a55b-4da5-b5c9-f4c8df89e58a`
- Postgres schema for all tables (synced + native agent state): `procurement`

## Lakebase API — critical notes

This workspace uses the **Lakebase Autoscaling (Projects) API**, NOT the old database-instances API.

**Never use** `w.database.list_database_instances()`, `w.database.create_synced_database_table()`, or `SyncedDatabaseTable` from `databricks.sdk.service.database` — these return empty / raise "Database instance is not found" because this workspace uses the newer Projects API.

**Always use** `w.postgres.*` methods:
```python
from databricks.sdk.service import postgres as pg

# List Lakebase projects
projects = list(w.postgres.list_projects())
names = [p.name.split("/")[-1] for p in projects]  # → ["myzerobus"]

# Create a synced table (Delta Gold → Postgres)
spec = pg.SyncedTableSyncedTableSpec(
    source_table_full_name="livezerobus.procurement.gd_inventory_snapshot",
    primary_key_columns=["sku", "room_id"],
    scheduling_policy=pg.SyncedTableSyncedTableSpecSyncedTableSchedulingPolicy("SNAPSHOT"),
    branch="projects/myzerobus/branches/production",
    postgres_database="databricks_postgres",
    create_database_objects_if_missing=True,
)
w.postgres.create_synced_table(
    synced_table=pg.SyncedTable(spec=spec),
    synced_table_id="livezerobus.procurement.inventory_snapshot",
    # synced_table_id format: "{uc_catalog}.{pg_schema}.{table_name}"
    # → creates Postgres table `inventory_snapshot` in schema `procurement`
)

# Generate OAuth token for Postgres password
token = w.postgres.generate_database_credential(
    name="projects/myzerobus/branches/production/endpoints/primary"
)
```

Env var names: use `LAKEBASE_PROJECT` (or `LAKEBASE_INSTANCE` as backward-compat alias) for the project name.

**Required UC permissions for the service principal** (`c4352007-a55b-4da5-b5c9-f4c8df89e58a`):
- `USE SCHEMA, CREATE TABLE, SELECT` on `livezerobus.procurement`
- `CAN_MANAGE` on all Lakeflow pipelines (each synced table creates its own pipeline)

**Postgres schema**: all tables live in `procurement` — both synced Gold tables and native agent-state tables. `PG_SCHEMA=procurement`. Do not use `liveoltp`; that schema was replaced.

## SAP BDC Delta Sharing host (`sap_bdc/`)

A standalone FastAPI service that mocks SAP Business Data Cloud and exposes 15 SAP procurement tables (EKKO, LFA1, MARA, etc.) over the **Delta Sharing Protocol v1**, allowing Databricks Unity Catalog to consume them zero-copy. The data is generated at startup as plain Parquet files (no Delta transaction logs — just `part-0.parquet` per table directory) and served with HMAC-signed time-limited URLs.

### Where it runs

**Not on Databricks Apps.** Databricks Apps wraps every route in an OAuth proxy that intercepts requests with `Authorization: Bearer <token>` headers (even Databricks SP M2M tokens) and 302-redirects them to OAuth login. Delta Sharing clients cannot follow OAuth redirects — they only know how to send the profile.json bearer token. The OAuth proxy has no path-allowlist mechanism. **The only way to run a Delta Sharing server reachable by Databricks UC is outside Databricks Apps.**

Current production deployment: **Docker container on a self-hosted VPS, behind an external Nginx reverse proxy that terminates Let's Encrypt TLS**. See `sap_bdc/Dockerfile`, `sap_bdc/docker-compose.yml`, `sap_bdc/nginx.conf.example`. Public URL: `https://photop.uzar.pl`.

### Required Nginx settings for Delta Sharing

In addition to standard TLS + proxy_pass headers, parquet downloads need:
- `proxy_buffering off;` — stream large parquet files without buffering through nginx
- `proxy_read_timeout 600s;` / `proxy_send_timeout 600s;` — large downloads
- `client_max_body_size 100m;` — precaution for large payloads
- `large_client_header_buffers 4 16k;` — signed Delta Sharing URLs are long

### Required Delta Sharing Protocol v1 endpoints

Implemented in `sap_bdc/app/sharing/router.py`:

| Method | Path | Returns |
|--------|------|---------|
| GET | `/delta-sharing/shares` | JSON `{items:[{name,id}], nextPageToken}` |
| GET | `/delta-sharing/shares/{share}` | JSON `{share:{name,id}}` |
| GET | `/delta-sharing/shares/{share}/schemas` | JSON list |
| GET | `/delta-sharing/shares/{share}/schemas/{schema}/tables` | JSON list (15 tables) |
| GET | `/delta-sharing/shares/{share}/all-tables` | JSON list — **critical**, UC calls this during catalog import |
| GET | `…/tables/{table}/version` | Empty body, `Delta-Table-Version` header |
| GET | `…/tables/{table}/metadata` | NDJSON: `protocol` line + `metaData` line |
| POST | `…/tables/{table}/query` | NDJSON: `protocol` + `metaData` + `file` line per parquet |
| GET | `/delta-sharing/files/{table}/{token}/{filename}` | Raw parquet bytes (HMAC-signed URL, no bearer needed) |

NDJSON format: lines separated by `\n`, terminated by `\n`. Each line is a single JSON object. Order matters: `protocol` first, then `metaData`, then `file` lines.

### Databricks UC compatibility gotchas (hard-learned)

1. **Entity IDs must be canonical UUIDs**, not raw md5 hex.
   ```python
   import uuid, hashlib
   uuid_str = str(uuid.UUID(bytes=hashlib.md5(name.encode()).digest()))
   ```
   UC errors: `Responded entity id(…) needs to be a UUID`.

2. **Table names must be matched case-insensitively.** UC lowercases all identifiers — when you list table `EKKO`, UC stores it as `ekko` and asks back via `/tables/ekko/metadata`. Resolve incoming names against the stored set with `name.lower()` matching.

3. **File responses must not include `null` optional fields** like `timestamp`. UC rejects null values silently. Omit the field instead.

4. **Use `FileResponse`, not `StreamingResponse`, for parquet downloads.** UC's Apache HttpClient rejects chunked transfer encoding (`Transfer-Encoding: chunked`) even on HTTP 200. `FileResponse` sets a proper `Content-Length` header.

5. **The `HOST` env var must include `https://` scheme.** Signed file URLs are built from `f"{HOST}/delta-sharing/files/..."` — without a scheme, UC's HttpClient throws `ClientProtocolException`. `app/config.py` defensively prepends `https://` for non-localhost values.

6. **The catch-all SPA route must come AFTER all Delta Sharing routes.** If a `/delta-sharing/foo` URL falls through to the React SPA, UC gets HTML and errors with `DS_INVALID_RESPONSE_FROM_DS_SERVER: invalid json`. The sharing router has its own JSON 404 catch-all for any unmatched `/delta-sharing/*` path.

7. **UC caches the share's schema list at catalog-creation time.** If the share was empty or broken when you ran `CREATE CATALOG … USING SHARE …`, fixing the server later doesn't auto-resync. You must `DROP CATALOG … CASCADE` and re-create.

### Test plan when adapting to a new data domain

```bash
TOKEN=<server bearer token>
HOST=https://your-public-host

# 1. Auth + share enumeration
curl -H "Authorization: Bearer $TOKEN" $HOST/delta-sharing/shares

# 2. Schema enumeration
curl -H "Authorization: Bearer $TOKEN" $HOST/delta-sharing/shares/<share>/schemas
curl -H "Authorization: Bearer $TOKEN" $HOST/delta-sharing/shares/<share>/all-tables

# 3. Table metadata — use lowercase to confirm case-insensitive lookup
curl -H "Authorization: Bearer $TOKEN" \
  $HOST/delta-sharing/shares/<share>/schemas/<schema>/tables/<lowercase_name>/metadata

# 4. Query for file URLs — verify Content-Length on the parquet download
URL=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  $HOST/delta-sharing/shares/<share>/schemas/<schema>/tables/<table>/query \
  | tail -1 | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['file']['url'])")
curl -I "$URL"
# Headers MUST include: content-length: <bytes>
# Headers MUST NOT include: transfer-encoding: chunked
```

If any step fails, the matching gotcha above is usually the cause. UC's error messages are often misleading (`HTTP 200 OK` reported as "request failed", etc.) — always check the actual headers and response body directly with curl before changing code.

### Reusing this for a different data domain

Replace these layers; the protocol code stays as-is:
1. `app/generator/` — generators that produce pandas DataFrames per table
2. `app/config.py` — `share_name` and `schema_name` properties
3. `app/routes/tables.py` table descriptions / module codes for the GUI
4. Frontend `App.tsx` t-codes and labels

Everything in `app/sharing/`, `app/delta_store.py`, the Dockerfile, and the nginx config is data-domain-agnostic.

## Important conventions
- The React build must be staged into `backend/static/` before deploying — `build_frontend.sh` handles this. Stale `.js` files alongside `.tsx` are cleaned before every build.
- Lakebase Postgres auth uses OAuth tokens (not passwords); `lakebase.py` rotates them transparently via `w.postgres.generate_database_credential`.
- Agents are tick-based: each `/api/agents/<name>/tick` call runs one agent iteration; the frontend polls on a timer.
- Unity Catalog path: `livezerobus.procurement.*` for all Delta tables.
