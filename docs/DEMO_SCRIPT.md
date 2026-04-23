# 5-minute demo flow

Open the app in a browser tab: <https://livezerobus-5347428297913551.11.azure.databricksapps.com>

> Before the demo: make sure the pipeline is running, `simulators_job` is running (or you're running `run_all.py` locally), and you can see the header `● LIVE` pulse every 3 seconds.

## Minute 1 — the story

"This is a lakehouse-native Auto Procurement demo. Every number on this screen is real, computed by Databricks in the last few seconds from four simulated data streams. Let me show you how data gets here."

Point at the footer: *Zerobus → Delta (Lakeflow Spark Declarative Pipelines) → Lakebase*.

## Minute 2 — ingestion (Zerobus)

Switch to a terminal and start a simulator:

```bash
cd simulators && python demand_simulator.py --rate 20
```

"Each simulator opens a gRPC stream directly to Databricks via Zerobus. Rows are durably written to a Bronze Delta table at millisecond latency — no Kafka, no connectors."

Flip back to the app — the **Demand (last 24h)** bars should start moving.

## Minute 3 — transformations (SDP)

In the Databricks UI, open the pipeline named `livezerobus_procurement_sdp`. Highlight the DAG:

- 4 Bronze tables on the left.
- `sv_*` Silver tables in the middle (with expectations).
- `gd_*` Gold tables on the right, including `gd_supplier_leaderboard` and `gd_procurement_recommendations`.

"This is Lakeflow Spark Declarative Pipelines — the open-source `pyspark.pipelines` API. The whole DAG is declarative Python: `@dp.table` functions plus `@dp.expect_or_drop` quality rules. No scheduling glue, no orchestrator, no tests-as-infra. The pipeline runs continuously with Photon."

## Minute 4 — ML-scored decisions

Point at the **Supplier leaderboard** panel. "For every SKU, the pipeline joins all currently valid supplier quotes with commodity trends and 1-hour demand, then calls our MLflow model from Unity Catalog to produce a score. The #1 supplier per SKU feeds the recommendations table."

Show one **BUY_NOW** row and read the rationale:

> `on_hand=138 · reorder=200 · trend24h=+1.42% · ml_score=0.912`

"The model is `main.procurement.supplier_scoring_model` at alias `@prod`. Re-training it is one job: `databricks bundle run train_supplier_model`."

## Minute 5 — how the app sees data (Lakebase)

Open `schemas/lakebase_schema.sql` and `lakebase_sync/synced_tables.yml`. "The Gold Delta tables are **synced** continuously into Lakebase, which is Databricks-managed Postgres. The app itself is a React SPA served by a FastAPI backend running in Databricks Apps. It reads from `live.*` Postgres tables using a short-lived OAuth token as the password — millisecond reads, zero data movement out of the lakehouse."

Refresh the page and point to the ``● LIVE`` indicator. "What you're seeing is fresh data end-to-end: Zerobus → Delta → Lakebase → React, every few seconds."

## Good questions to be ready for

- **Why Zerobus and not Autoloader?** — Zerobus is for **server-side producers** that need millisecond durable writes. Autoloader is for landing files into cloud storage.
- **Why Lakebase instead of querying Delta directly?** — App endpoints need single-digit ms reads for interactive dashboards; Lakebase gives us Postgres latency while keeping Delta as the source of truth.
- **Can SDP run on serverless?** — Yes; swap `clusters:` in `resources/pipelines.yml` for `serverless: true`.
- **What's the SLA for recommendations after a stock dip?** — End-to-end: simulator publish → Zerobus → Bronze → Silver → Gold → Lakebase sync → app poll ≈ 5–10 seconds with continuous SDP + CONTINUOUS synced tables.
