# Architecture — LiveZerobus Auto Procurement

## Data flow

```
  Simulators (Python)                    Databricks Lakehouse                  Databricks App
  ┌───────────────┐                ┌──────────────────────────────┐         ┌──────────────┐
  │ inventory_sim │                │  Zerobus gRPC ingest endpoint │         │  React SPA   │
  │ supplier_sim  │ ─ TLS+OAuth ─► │                              │         │   (Vite)     │
  │ demand_sim    │   Zerobus SDK  │  ┌──────────────────────────┐ │         └─────┬────────┘
  │ commodity_sim │                │  │ Bronze Delta (bz_*)      │ │               │ /api/*
  └───────────────┘                │  └──────────┬───────────────┘ │         ┌─────▼────────┐
                                   │             ▼                 │         │  FastAPI     │
                                   │  ┌──────────────────────────┐ │         │  backend     │
                                   │  │ Silver (sv_*) — SDP       │ │         └─────┬────────┘
                                   │  └──────────┬───────────────┘ │               │ psycopg
                                   │             ▼                 │               │ + OAuth
                                   │  ┌──────────────────────────┐ │         ┌─────▼────────┐
                                   │  │ Gold (gd_*) — SDP + MLflow│─────────►│ Lakebase     │
                                   │  └──────────────────────────┘ │ synced  │ Postgres     │
                                   │                               │ tables  │  live.*      │
                                   └──────────────────────────────┘         └──────────────┘
```

Every arrow is typed: gRPC (Zerobus), Delta (lake), Delta Sync (Lakebase), psql+TLS (app).

## Zerobus

Four Bronze Delta tables (`bz_inventory_events`, `bz_supplier_quotes`, `bz_demand_events`, `bz_commodity_prices`) are created once by `scripts/setup_unity_catalog.py`. They have `delta.appendOnly=true` and column-mapping `name`, the two properties Zerobus requires.

Each simulator opens a long-lived gRPC stream via the **Zerobus SDK** (`databricks-zerobus-sdk`), authenticating with the service-principal client id/secret. The endpoint is region-specific (see `.env.example`). Rows are plain Python dicts matching the table columns; the SDK compiles a protobuf descriptor at stream open.

Designed so you can swap any simulator for a real producer by re-implementing the tiny `zerobus_stream(...)` + `stream.send(row)` contract in `simulators/common.py`.

## Lakeflow Spark Declarative Pipelines (SDP)

All Silver and Gold tables are declared with `pyspark.pipelines` (the open-source Spark Declarative Pipelines API):

| File | Layer | Tables |
|---|---|---|
| `pipelines/bronze_to_silver.py` | Silver | `sv_inventory_events`, `sv_supplier_quotes`, `sv_demand_events`, `sv_commodity_prices` |
| `pipelines/silver_to_gold.py`   | Gold   | `gd_inventory_snapshot`, `gd_commodity_latest`, `gd_demand_1h`, `gd_supplier_quotes_current` |
| `pipelines/auto_procurement_scoring.py` | Gold | `gd_supplier_leaderboard`, `gd_procurement_recommendations` |

The pipeline is declared in `resources/pipelines.yml` and runs **continuously** with Photon. Expectations (`@dp.expect_or_drop`) enforce schema/quality. Catalog + schema are passed in via `pipelines.catalog` / `pipelines.schema` config.

## ML — supplier scoring

`ml/train_supplier_model.py` trains a Gradient-Boosting regressor on synthetic but realistically-shaped procurement data, then registers it as **`main.procurement.supplier_scoring_model`** in Unity Catalog with alias `@prod`.

The Gold pipeline calls `mlflow.pyfunc.spark_udf(...)` once per executor, vectorizing inference across every (sku, supplier) pair on the pipeline cluster. Features:

- `unit_price_usd`, `lead_time_days`, `min_qty`
- Supplier reliability: `on_time_pct`, `quality_score`
- Demand urgency: `demand_1h_qty`
- Market context: `commodity_pct_24h`

Output: a 0..1 score. Top-ranked supplier per SKU is chosen for the recommendation.

## Lakebase sync

`lakebase_sync/apply.py` reads `synced_tables.yml` and creates one **Synced Table** per Gold table in the `databricks_postgres` instance / `production` branch:

```
gd_inventory_snapshot          → live.inventory_snapshot          CONTINUOUS
gd_supplier_leaderboard        → live.supplier_leaderboard        CONTINUOUS
gd_commodity_latest            → live.commodity_prices_latest     CONTINUOUS
gd_demand_1h                   → live.demand_1h                   SNAPSHOT 60s
gd_procurement_recommendations → live.procurement_recommendations CONTINUOUS
```

Postgres DDL (`schemas/lakebase_schema.sql`) creates primary keys + indexes that back the app's read path.

## FastAPI backend

- One small file per concern: `config.py`, `lakebase.py`, `routes/data.py`, `main.py`.
- Auth: `databricks.sdk.WorkspaceClient().database.generate_database_credential(...)` returns a short-lived token used as the Postgres password. A background refresh happens 60s before expiry.
- Single connection pool (`psycopg_pool.ConnectionPool`) with `search_path TO live, public`.
- Endpoints: `/api/summary`, `/api/inventory`, `/api/suppliers/leaderboard`, `/api/commodity/latest`, `/api/demand/hourly`, `/api/recommendations`.
- Serves the built React bundle from `frontend/dist` as SPA fallback.

## React frontend

Vite + TypeScript + Recharts. One component per panel; every component polls its endpoint on the shared `tick` prop (every 3s). Dark dashboard theme in `styles.css`. No external state store needed — the app is read-only.

## Databricks Asset Bundle

`databricks.yml` + `resources/*.yml` define five runnables:

- `setup_unity_catalog` (job) — UC DDL + grants
- `train_supplier_model` (job) — MLflow register + alias
- `procurement_dlt` (pipeline) — the SDP pipeline
- `lakebase_sync` (job) — synced-table reconciliation
- `simulators_job` (job) — optional; otherwise run simulators locally
- `deploy_app` (app) — builds and ships the Databricks App

## Security boundaries

- Simulators authenticate to Zerobus with the app service principal (`app-3dxwqo`). Consider a separate "ingest" SP for a real deployment.
- The app reads Lakebase via a short-lived OAuth token unique to its own SP, with `CAN_CONNECT_AND_CREATE` on `databricks_postgres`.
- The app has `SELECT` on the Delta schema but never writes to it.
