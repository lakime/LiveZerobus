# 7-minute demo flow — Vertical-Farm Seed Procurement

Open the app in a browser tab (URL shown in Databricks UI → Compute →
Apps → `livezerobus`).

> Before the demo: confirm the Lakeflow pipeline is running, the four
> simulators are running (or `run_all.py` is up locally), and the header
> `● LIVE` pulse ticks every 3 seconds. Navigate to the **Dashboard** tab.

## Minute 1 — the story

"This is a lakehouse-native Auto Procurement app for a vertical farm.
Every number on this screen is real, computed by Databricks in the last
few seconds from four simulated data streams, and the negotiation emails
you're about to see are drafted by an LLM on Databricks Foundation Model
API. Let me walk through it."

Point at the footer:
*Zerobus → Delta (Lakeflow SDP) → Lakebase · Foundation Model API for agents*.

## Minute 2 — ingestion (Zerobus)

Switch to a terminal and start a simulator:

```bash
cd simulators && python demand_simulator.py --rate 20
```

"Each simulator opens a gRPC stream directly to Databricks via Zerobus.
Rows are durably written to a Bronze Delta table at millisecond latency —
no Kafka, no connectors. We're streaming four feeds: seed inventory
movements in grams, rolling supplier quotes, the planting schedule
(trays/hour), and grow-input prices — coco coir, peat, rockwool, nutrient
packs, kWh."

Flip back to the app — the **Planting (last 24h · trays)** bars should
start moving.

## Minute 3 — transformations (Lakeflow SDP)

In the Databricks UI, open the pipeline `livezerobus_procurement_sdp`.
Highlight the DAG:

- 4 Bronze tables on the left (`bz_inventory_events`, `bz_supplier_quotes`,
  `bz_demand_events`, `bz_commodity_prices`).
- `sv_*` Silver tables in the middle (with `@dp.expect_or_drop` rules).
- `gd_*` Gold tables on the right, ending in `gd_supplier_leaderboard`
  and `gd_procurement_recommendations`.

"This is Lakeflow Spark Declarative Pipelines — the open-source
`pyspark.pipelines` API. The whole DAG is declarative Python: `@dp.table`
functions plus quality rules. Photon runs it continuously."

## Minute 4 — ML-scored seed buying

Back in the app, point at **Supplier leaderboard — ML-ranked**. "For
every seed SKU, the pipeline joins all currently valid seed-house quotes
with a 1-hour planting demand and the 24h trend on the dominant
grow-input, then calls our MLflow model from Unity Catalog to produce a
score. The #1 supplier per SKU feeds the recommendations table below."

Show one **BUY_NOW** row in *Procurement recommendations* and read the
rationale aloud:

> `on_hand_g=380 · reorder_g=700 · input24h=+1.42% · ml_score=0.912`

"Packs column is rounded up — we never short-order seed. The model is
`livezerobus.procurement.supplier_scoring_model` at alias `@prod`.
Re-training is a single script: `python ml/train_supplier_model.py`."

## Minute 5 — negotiation with suppliers (Foundation Model API)

Click the **Run agent cycle** button in the header.

Switch to the **Emails** tab. "The negotiator agent just looked at any
recommendation without an open RFQ, drafted a quote request, and wrote
it to the outbox. Here's the thread it just opened with Rijk Zwaan for
Butterhead lettuce."

Open a thread, then click **Simulate reply**. "That round-trips through
a second LLM persona that role-plays as the supplier — counter-offer,
quote, rejection, out-of-office. When a real reply arrives, the extraction
LLM pulls the numeric fields out of the prose and marks the thread
actionable."

Key point: "No hard-coded templates. All four seed-house replies you'll
see are different because they're written by `databricks-meta-llama-3-3-
70b-instruct` given the supplier's persona as context."

## Minute 6 — admin agents

Walk the remaining tabs in order — each is one agent.

**POs & Budget** — "PO drafter promoted two negotiation threads into
drafts. Budget gate allocated $25 000 for April's SEED budget and
approved or rejected each against the balance."

**Supplier onboarding** — "Submit a new supplier using the form."
Fill it in live: `Pacific Microgreens`, `hello@pacmicro.demo`, `US`,
`microgreens, lettuce`, organic ✓, 3 years. Click submit. Point at the
new row: the LLM has already scored the application against a weighted
rubric (40 % SKU relevance, 25 % organic, 20 % years, 15 % country) and
set a verdict.

**Invoices** — "Invoice reconciler compares invoiced vs. expected PO
amount and flags variances > 1 %, > 5 % disputes."

**Agent runs** — "Every LLM call is logged here with prompt/output
tokens, agent name, input and output refs. Full observability into
what the agents just did."

## Minute 7 — how the app sees the data (Lakebase)

Open `schemas/lakebase_schema.sql` and `lakebase_sync/synced_tables.yml`.
"The Gold Delta tables are **synced** continuously into Lakebase —
managed Postgres. The app is a React SPA served by FastAPI on Databricks
Apps. Backend reads from `live.*` with a short-lived OAuth token as the
Postgres password — single-digit ms reads, zero egress."

"The agent-state tables are *Postgres-native* in Lakebase rather than
synced from Delta — they need UPDATE semantics (negotiation status,
budget balance) which Zerobus can't offer."

Refresh the page and point to `● LIVE`. "End-to-end freshness:
Zerobus → Delta → Lakebase → React ≈ 5–10 seconds. FM API
calls are < 2 seconds per agent."

## Good questions to be ready for

- **Why Zerobus, not Autoloader?** Zerobus is for *server-side producers*
  that need millisecond durable writes. Autoloader is for files in cloud
  storage.
- **Why Lakebase and not Delta for the app?** App endpoints need
  single-digit ms reads for interactive dashboards; Lakebase gives us
  Postgres latency while keeping Delta as the source of truth.
- **Can SDP run serverless?** Yes; swap `clusters:` for `serverless: true`
  in the pipeline definition.
- **Which model is the agent using?** `databricks-meta-llama-3-3-70b-instruct`
  via the Foundation Model API (`/serving-endpoints/…/invocations`). Same
  SP identity as the app, no extra API key.
- **How do you move this to a real mailbox?** Swap the `email_outbox`
  writer for an SMTP/Gmail/Outlook connector; inbound would poll or
  webhook to `email_inbox`.
- **What's the SLA from a stock dip to an RFQ sent?** Simulator publish
  → Zerobus → Bronze → Silver → Gold → Lakebase sync → `/api/agents/cycle`
  → outbox: ≈ 10–15 seconds with continuous SDP.
