# LiveZerobus — Auto Procurement Architecture

A production-shaped demo running entirely on Databricks. Domain: **vertical-farm
seed procurement** — buy the right seed, in the right pack size, from the right
seed house, before any grow-room runs out.

Every layer of the modern Databricks data stack is exercised end-to-end:

- **Zerobus** for sub-second streaming ingest from synthetic producers
- **Delta Lake (Unity Catalog)** for raw → cleaned → analytical state, in a
  three-tier medallion
- **Lakeflow Spark Declarative Pipelines** for streaming Bronze → Silver and
  materialized Silver → Gold
- **MLflow + Unity Catalog model registry** for a `supplier_scoring_model`
  used inside a Lakeflow pipeline
- **Lakebase Postgres (Autoscaling / Projects)** as the live serving layer,
  fed by Lakebase Synced Tables on a SNAPSHOT schedule, plus native Postgres
  tables for agent state
- **Databricks Apps** hosting a FastAPI backend and a React (Vite + TS) SPA,
  authenticated to Lakebase with short-lived OAuth tokens
- **Foundation Model API** (`databricks-meta-llama-3-3-70b-instruct`) driving
  five agents that negotiate quotes, draft POs, gate against a budget,
  reconcile invoices, and onboard new seed houses

Catalog name: **`livezerobus`**, schema **`procurement`** (23 Delta tables),
Lakebase project **`myzerobus`**, branch **`production`**, endpoint
**`primary`**, schema **`liveoltp`**.

---

## 1. Topology

```
┌─────────────────────┐       ┌──────────────────────────────────────┐       ┌──────────────────┐
│  Simulators (Py)    │       │            Databricks Lakehouse       │       │  Databricks App  │
│  ───────────────    │       │  (Unity Catalog: livezerobus.procurement)    │  ──────────────  │
│  inventory_sim      │       │                                        │       │  React SPA       │
│  supplier_quotes_   │  gRPC │  ┌─────────────────────────────────┐  │       │  (Vite + TS)     │
│  demand_sim         │  TLS  │  │ Bronze (bz_*)  — Delta append    │  │       └──────┬───────────┘
│  commodity_sim      │ ────► │  │   bz_inventory_events           │  │              │ /api/*
│                     │ Zero  │  │   bz_supplier_quotes            │  │              ▼
│  run_all.py         │ bus   │  │   bz_demand_events              │  │       ┌──────────────────┐
└─────────────────────┘ SDK   │  │   bz_commodity_prices           │  │       │  FastAPI         │
                              │  └────────────────┬────────────────┘  │       │  + 5 Agents      │
                              │                   │ streamRead         │       │  (FM API caller) │
                              │  ┌────────────────▼────────────────┐  │       └──────┬───────────┘
                              │  │ Silver (sv_*) — Streaming Tables │  │              │ psycopg
                              │  │   schema-enforced + DQ-validated │  │              │ + OAuth
                              │  │   sv_inventory_events ...        │  │              │ token
                              │  └────────────────┬────────────────┘  │              ▼
                              │                   │                    │       ┌──────────────────┐
                              │  ┌────────────────▼────────────────┐  │       │  Lakebase        │
                              │  │ Gold (gd_*) — Materialized Views │  │       │  Postgres        │
                              │  │   gd_inventory_snapshot          │  │ Sync  │  myzerobus /    │
                              │  │   gd_supplier_leaderboard ◄──┐  │  │ Tables│  production /   │
                              │  │   gd_commodity_latest        │  │  │ ─────►│  primary         │
                              │  │   gd_demand_1h               │  │  │ 30-60s│   liveoltp.*    │
                              │  │   gd_supplier_quotes_current │  │  │       │   (5 synced +    │
                              │  │   gd_procurement_recs ◄──────┘  │  │       │    7 native)     │
                              │  └────────────────▲────────────────┘  │       └──────────────────┘
                              │                   │                    │
                              │  ┌────────────────┴────────────────┐  │
                              │  │ MLflow Model Registry            │  │
                              │  │   supplier_scoring_model @prod   │  │
                              │  │   (loaded as spark_udf in Gold)  │  │
                              │  └─────────────────────────────────┘  │
                              └──────────────────────────────────────┘
                                                                              ┌──────────────────┐
   FM API — /serving-endpoints/databricks-meta-llama-3-3-70b-instruct ◄──────┤  Agents          │
                                                                              │  negotiator,     │
                                                                              │  po_drafter,     │
                                                                              │  budget_gate,    │
                                                                              │  reconciler,     │
                                                                              │  onboarding      │
                                                                              └──────────────────┘
```

Every arrow is a typed channel: gRPC + TLS (Zerobus), Delta streaming reads
(Bronze→Silver), MV refresh (Silver→Gold), Lakebase Synced Tables (Gold→PG),
TLS+psycopg (App→PG), HTTPS+OAuth (App→FM API).

---

## 2. Data generation — simulators

Path: `simulators/`

Each of the four event streams has its own simulator, a small Python script
that opens a long-lived gRPC stream via the **Zerobus SDK**
(`databricks-zerobus-sdk`) and emits dataclass-shaped rows that match the
target Bronze schema:

| Simulator | Bronze target | Cadence | Shape |
|---|---|---|---|
| `inventory_simulator.py` | `bz_inventory_events` | continuous | `(event_id, event_ts, sku, room_id, event_type, delta_g, on_hand_g)` |
| `supplier_quotes_simulator.py` | `bz_supplier_quotes` | rolling | `(event_id, event_ts, supplier_id, sku, pack_size_g, unit_price_usd, lead_time_days, min_qty, organic_cert)` |
| `demand_simulator.py` | `bz_demand_events` | per-shift | `(event_id, event_ts, sku, room_id, trays, grams_req)` |
| `commodity_simulator.py` | `bz_commodity_prices` | hourly | `(event_id, event_ts, input_key, price_usd, pct_24h)` where `input_key ∈ {coco_coir, peat, rockwool, nutrient_pack, kwh}` |

`run_all.py` orchestrates all four. The shared `common.py` exposes a
`zerobus_stream(table)` context manager so a real producer (PLC, nursery ERP,
exchange feed) is a drop-in replacement — re-implement the
`stream.send(row)` contract and nothing downstream changes.

---

## 3. Ingestion — Zerobus

Zerobus is Databricks' native append-only streaming ingest. Properties:

- **gRPC + TLS**, OAuth-authenticated via the app's service principal
- **Sub-second latency** from `stream.send()` to query-visible row in Bronze
- **Region-pinned endpoint** — set in `.env` (`ZEROBUS_ENDPOINT`)
- **Bronze tables must be `delta.appendOnly=true` + `delta.columnMapping.mode=name`**
  before Zerobus can write to them; that's done once by
  `scripts/setup_unity_catalog.py`
- The SDK derives a Protobuf descriptor at stream open from the Python
  dataclass — schema is locked at session start, so renaming fields requires
  a fresh stream

Failure isolation: a simulator crash leaves Bronze rows already accepted
intact (Zerobus is at-least-once with `event_id`-based dedup downstream).

---

## 4. Storage — Delta medallion under Unity Catalog

Catalog: `livezerobus` · Schema: `procurement` · Layout (23 tables):

### Bronze (4) — raw Zerobus arrivals, append-only

| Table | Source | Notes |
|---|---|---|
| `bz_inventory_events` | Zerobus | grams per SKU per grow-room |
| `bz_supplier_quotes` | Zerobus | seed-house quotes + lead times |
| `bz_demand_events` | Zerobus | planting schedule (trays, grams_req) |
| `bz_commodity_prices` | Zerobus | grow-input prices + 24h trend |

### Silver (4) — deduped, schema-enforced streaming tables

Defined in `pipelines/bronze_to_silver.py` using `pyspark.pipelines`
(Spark Declarative Pipelines). Each is a `@dp.table` over
`spark.readStream.table(bz_*)`:

- `dropDuplicates(["event_id"])`
- adds `ingest_ts = current_timestamp()`
- enforces DQ via `@dp.expect_or_drop(...)`:
  - `event_ts IS NOT NULL`, `sku IS NOT NULL`
  - `unit_price_usd > 0`, `pack_size_g > 0`, `lead_time_days >= 0`
  - `trays > 0`, `grams_req > 0`
  - `price_usd > 0`, `input_key IS NOT NULL`
  - `on_hand_g >= 0` (no negative stock)

Silver also derives `usd_per_gram = unit_price_usd / pack_size_g` for quotes.

### Gold (6) — Materialized Views, analytics-ready

Defined in `pipelines/silver_to_gold.py` and
`pipelines/auto_procurement_scoring.py`:

| Gold table | Purpose | Built from |
|---|---|---|
| `gd_inventory_snapshot` | Current on-hand grams per (sku, room) | running sum on `sv_inventory_events` |
| `gd_demand_1h` | Trays & grams by SKU per rolling hour | window agg on `sv_demand_events` |
| `gd_commodity_latest` | Most recent price per `input_key` + 24h pct | last per group on `sv_commodity_prices` |
| `gd_supplier_quotes_current` | Active quote per (supplier, sku) | latest per group on `sv_supplier_quotes` |
| `gd_supplier_leaderboard` | ML-scored ranking of suppliers per SKU | join above + dim_supplier + dim_sku → `mlflow.spark_udf` → row_number window |
| `gd_procurement_recommendations` | Reorder actions per (sku, room) | inv where `on_hand_g <= reorder_point_g` × top-1 leaderboard × commodity-trend → BUY_NOW / WAIT / REVIEW decision |

### Dimension + agent state (9) — supporting tables

`dim_sku`, `dim_supplier`, plus seven Postgres-native agent-state tables
(see §6). The dim tables are seeded once via Spark SQL.

---

## 5. Transformation — Lakeflow Spark Declarative Pipelines

Three Python files, deployed as one **Lakeflow Pipeline** (Continuous mode):

```
pipelines/bronze_to_silver.py        ← 4 streaming tables
pipelines/silver_to_gold.py          ← 4 batch MVs (snapshot, demand_1h,
                                       commodity_latest, quotes_current)
pipelines/auto_procurement_scoring.py ← 2 ML-scored MVs
```

Pipeline config:

- **Channel**: Preview (required — `pyspark.pipelines` is the new SDP API)
- **Target catalog**: `livezerobus`
- **Target schema**: `procurement`
- **Mode**: Continuous (always-on streaming for Silver, MVs refresh as new
  Silver data arrives)
- **Pipeline parameters**: `pipelines.catalog`, `pipelines.schema`,
  `livezerobus.model_name`

DAG (post-deploy):

```
sv_inventory_events ──► gd_inventory_snapshot ─┐
sv_demand_events    ──► gd_demand_1h ──────────┼──► gd_supplier_leaderboard ──► gd_procurement_recommendations
sv_commodity_prices ──► gd_commodity_latest ──┤
sv_supplier_quotes  ──► gd_supplier_quotes_current ─┘
```

Every node is observable in the pipeline UI: row counts, expectation
drop rates, run duration, lineage. The pipeline event log is queryable:

```sql
SELECT * FROM event_log(TABLE(<pipeline_id>))
WHERE level = 'ERROR' ORDER BY timestamp DESC LIMIT 50;
```

---

## 6. ML — supplier scoring

The ML layer answers a single, narrow question for every (SKU, supplier)
combination at every refresh of the Gold layer:

> *Given current grow-input prices, planting urgency, this seed house's
> reliability and pricing, and our organic preference for this SKU — how
> good is it to buy this SKU from this supplier right now, on a 0–1 scale?*

It then feeds that score into a window function that ranks suppliers per
SKU, and the rank-1 supplier becomes the recommendation in
`gd_procurement_recommendations`.

The whole ML lifecycle lives in **one file** (`ml/train_supplier_model.py`)
and the model is consumed inside **one Lakeflow Gold MV**
(`gd_supplier_leaderboard` in `pipelines/auto_procurement_scoring.py`).
That tight loop is the point of the demo: ML on Databricks should not be a
separate kingdom, it should be a Spark UDF inside the same DAG that owns
the data.

### 6.1 What gets trained

A scikit-learn `Pipeline` with two stages:

```python
Pipeline([
    ("scaler", StandardScaler()),
    ("gbr",    GradientBoostingRegressor(
                  n_estimators=250,
                  max_depth=4,
                  learning_rate=0.05,
                  random_state=7,
              )),
])
```

- **`StandardScaler`** — features have very different scales (price is in
  cents, `demand_1h_trays` is in tens, `organic_cert_int` is 0/1). Scaling
  matters here mainly for numerical stability of the boosting tree splits;
  the model would still train without it but with slower convergence.
- **`GradientBoostingRegressor`** chosen over a single tree (too crude on
  the smooth target) and over a deep neural net (overkill, less explainable,
  worse on tabular data of this size). 250 shallow trees is a typical
  sweet spot — enough capacity to fit the multiplicative feature
  interactions in the synthetic label, shallow enough to resist overfitting
  and scoreable in microseconds per row.

Output: a continuous score in `[0, 1]`, which we interpret as an "ideal
procurement score" (higher = buy this).

### 6.2 Training data — synthetic but domain-grounded

There is no historical procurement ledger to train on (the demo runs on
fresh tenants), so `_synth()` generates **20 000 labelled rows** with
realistic seed-buying distributions:

| Feature | Distribution rationale |
|---|---|
| `usd_per_gram` | log-normal centered around microgreens-grade pricing, clipped to `[0.05, 4.0]` USD/g |
| `pack_size_g` | bimodal — microgreens are bulk (100–2000 g), regular seed is small (1–100 g); the model sees both |
| `lead_time_days` | uniform 1–30 days |
| `min_qty` | choice of `{1, 2, 5, 10}` packs |
| `on_time_pct` | normal `(μ=0.92, σ=0.06)`, clipped to `[0.4, 1.0]` |
| `quality_score` | normal `(μ=0.90, σ=0.06)`, clipped to `[0.3, 1.0]` |
| `demand_1h_trays` | Poisson `λ=20` — trays/hour planting cadence |
| `input_pct_24h` | normal `(μ=0, σ=0.02)` — daily grow-input price drift |
| `organic_cert_int` | Bernoulli `p=0.55` |

The label is **hand-crafted**, not observed — a weighted sum of seven
domain-meaningful terms:

```python
score =
    0.30 * price_term       # exp(-1.2 * (price/avg_price - 0.9))   # cheap is great, but not crazy-cheap
  + 0.10 * pack_term        # exp(-0.35 * (log10(pack_size_g) - 2.0)^2)  # sweet spot ~100 g, penalise tiny + bulk
  + 0.15 * lead_term        # exp(-lead/15)                          # short lead time wins
  + 0.20 * rel_term         # 0.6*on_time + 0.4*quality              # supplier reliability dominates
  + 0.10 * urgency_term     # tanh(demand/40)                        # buy harder when planting is heavy
  + 0.10 * trend_term       # 0.5 + 0.5*tanh(trend*20)               # buy ahead of rising input prices
  + 0.05 * organic_term     # 0.5 or 1.0                             # small bias toward certified organic
score += N(0, 0.02)         # noise so the GBR has to generalise
```

Why hand-craft? It gives the demo:
- **Explicit feature importances** — the model recovers the weight ordering
  (`price > reliability > lead_time > pack > demand ≈ trend > organic`),
  which lines up with how a real procurement officer thinks
- **Stable, reproducible scoring** — no real-world signal drift between
  demo runs
- **A drop-in replacement seam** — when a customer brings real labels (won
  POs, on-time invoice variance, dispute outcomes), only `_synth()` needs
  to be replaced. The pipeline, registry, and inference path do not change

Train/test split is 80/20. We log MAE on the held-out set as the headline
metric; on the synthetic data it lands around 0.02–0.03 (i.e. the model
recovers the score within ~2 percentage points on average).

### 6.3 MLflow logging + Unity Catalog registration

```python
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"/Shared/{catalog}.{schema}.supplier_scoring")
```

- **Registry URI = `databricks-uc`** routes the registered model into
  Unity Catalog rather than the legacy Workspace Model Registry. This is
  the modern path: models become first-class UC objects with lineage,
  permissions (`SELECT` / `EXECUTE`), and cross-workspace governance.
- **Experiment** lives under `/Shared/livezerobus.procurement.supplier_scoring`,
  so every training run (each invocation of `train_supplier_model.py`) is
  captured as an MLflow run with parameters, metrics, and artifacts side
  by side.

Inside `mlflow.start_run(...)`:

```python
mlflow.log_param("features", FEATURES)
mlflow.log_param("domain", "vertical-farm-seed-procurement")
mlflow.log_metric("mae", mae)

signature = mlflow.models.infer_signature(X_train.head(100), preds[:100])
info = mlflow.sklearn.log_model(
    sk_model=pipe,
    artifact_path="model",
    signature=signature,
    registered_model_name=f"{catalog}.{schema}.supplier_scoring_model",
    input_example=X_train.head(5),
)
```

Key behaviours:

- **`infer_signature`** locks the input/output schema into the model
  artifact. If a future training run drops a feature or changes its dtype,
  the signature will mismatch and the Spark UDF will refuse to load —
  saving us from silent column-misalignment bugs in production.
- **`registered_model_name`** is fully qualified (`catalog.schema.name`).
  Each successful run produces a new monotonically-numbered version.
- **`input_example`** ships 5 sample rows inside the artifact so the UC
  Models UI can render an inference playground.

### 6.4 Alias-based promotion (`@prod`)

After registration, the script promotes the new version to the `prod` alias:

```python
client = mlflow.tracking.MlflowClient()
client.set_registered_model_alias(
    name=model_name,
    alias="prod",
    version=info.registered_model_version,
)
```

**Aliases vs. version pinning.** The Lakeflow pipeline references the model
as `models:/livezerobus.procurement.supplier_scoring_model@prod` — *not* a
specific version number. That means:

1. **No code change to roll forward.** Train a better model →
   `set_registered_model_alias("prod", new_version)` → next pipeline
   refresh cycle picks it up automatically (because the spark_udf
   reloads at executor startup, or when the cluster restarts).
2. **One-line rollback.** If a new model regresses, point `prod` back at
   the previous version. No redeploy of the Lakeflow pipeline, no Apps
   redeploy.
3. **Stage-based deployment.** Add a `staging` alias for canary scoring
   on a separate pipeline branch before promoting to `prod`.

UC also tracks lineage between the registered model and any Lakeflow MV
that uses it — visible in the **Models** view of Catalog Explorer as
"downstream consumers".

### 6.5 Inference inside the Gold MV

In `pipelines/auto_procurement_scoring.py`, the model becomes a
**Spark vectorized UDF** loaded once per executor:

```python
_score_udf = mlflow.pyfunc.spark_udf(
    spark,
    model_uri=f"models:/{MODEL_NAME}@prod",
    result_type="double",
)
```

Why `pyfunc.spark_udf` and not a plain Pandas UDF?
- **MLflow handles the serialization round-trip** — pickled sklearn
  pipeline → executor-local cache → vectorised batch inference, all
  without us writing the Pandas UDF wrapper or worrying about cluster
  Python version drift.
- **Result type is enforced** — `result_type="double"` means malformed
  predictions surface immediately as a Spark schema error instead of
  silently downstream.
- **One model load per executor**, not per row or per partition. Each
  executor reads the artifact once on first call and caches it; for the
  ~30 000 quote rows the demo handles, scoring is sub-second.

The call site composes feature columns explicitly so the order matches
training:

```python
scored = enriched.withColumn(
    "score",
    _score_udf(
        F.col("usd_per_gram"),
        F.col("pack_size_g"),
        F.col("lead_time_days"),
        F.col("min_qty"),
        F.col("on_time_pct"),
        F.col("quality_score"),
        F.col("demand_1h_trays"),
        F.col("input_pct_24h"),
        F.col("organic_cert_int"),
    ),
)
```

If the column order ever drifted from `FEATURES` in the training script,
the model signature check would fail at first invocation — a nice tripwire.

### 6.6 Feature engineering at inference

The 9 features are not all sitting on `gd_supplier_quotes_current` — they
have to be assembled from four Gold/Silver/dim sources. The pipeline does
this inline:

```
gd_supplier_quotes_current  (q)        ─┐
dim_supplier                (s)         │  q × s on supplier_id   → reliability features
gd_demand_1h aggregated to sku (d)      │  × d on sku             → demand_1h_trays
gd_commodity_latest × dim_sku (input)   │  × input on sku         → input_pct_24h
                                        ▼
                                   enriched features
```

Three transforms worth calling out:

1. **`SKU_INPUT_MAP`** — a hard-coded mapping from `crop_type` to its
   dominant grow-input (`microgreens → coco_coir`, `lettuce/basil/kale → rockwool`).
   This is what lets the commodity feed (rockwool prices) influence the
   supplier score for SKUs that depend on it. In a real deployment this
   map would itself be a Delta table.
2. **`organic_cert_int`** — Spark booleans aren't directly model-friendly.
   `F.when(F.col("organic_cert"), F.lit(1.0)).otherwise(F.lit(0.0))`
   coerces to a numeric.
3. **`fillna(...)`** — when a quote arrives for a brand-new supplier with
   no track record, `on_time_pct` and `quality_score` are null. We fill
   with a neutral 0.85 prior so the model still scores them, just without
   reliability boost. Demand/trend nulls get 0 (no information ⇒ no
   contribution).

After scoring, a window function ranks within each SKU:

```python
w = Window.partitionBy("sku").orderBy(F.col("score").desc())
return scored.withColumn("rank", F.row_number().over(w))
```

`gd_procurement_recommendations` then keeps only `rank == 1` per SKU and
joins it against current inventory.

### 6.7 How the score becomes a decision

The ML score is one input to a rule-based decision in
`gd_procurement_recommendations`:

```
BUY_NOW  ← input_pct_24h > 1%               # input prices rising fast
       OR  on_hand_g < 0.5 * reorder_point_g # critically low stock
       OR  ml_score > 0.85                  # very high confidence buy
WAIT     ← input_pct_24h < -1%              # input prices falling
       AND  on_hand_g > 0.8 * reorder_point_g # not critical
REVIEW   ← otherwise
```

This is deliberately a **simple rule layer on top of the ML score** rather
than a second model:

- **Auditability** — a procurement officer can read the rule and trust why
  any single recommendation came out the way it did
- **Demo legibility** — the dashboard shows `BUY_NOW · ml_score=0.92 · input24h=+1.7%`
  and an audience instantly understands which signals triggered the call
- **Future swap-in** — when there's enough outcome data (won POs ↔ actual
  delivered cost vs. quoted cost in `invoice_reconciliations`), the rule
  layer becomes a second registered model trained on those outcomes. The
  feature inputs are already there.

### 6.8 Re-training and lifecycle

Today, retraining is manual:

```bash
python ml/train_supplier_model.py
# → logs new MLflow run, registers v2, sets prod alias to v2
```

Production-grade evolutions to consider:

| Step | Today | Production-shape |
|---|---|---|
| Trigger | Manual `python ml/...` | Databricks Job on schedule, or feature-store-driven retrain |
| Training data | Synthetic | Materialise a `gd_won_procurement_outcomes` table joining `po_drafts.APPROVED` with `invoice_reconciliations` to learn from real outcomes |
| Validation gate | None | Compare new MAE to current `prod`; only promote if non-regressing on a held-out time slice |
| Promotion | Direct alias swap to `prod` | Promote to `staging` first → run a canary pipeline branch → promote `staging→prod` after N hours of agreement |
| Monitoring | Pipeline metrics only | `gd_score_distribution_drift` MV comparing live score histogram vs. training-time histogram, alert on KS divergence |
| Lineage | UC auto-tracks pipeline → model | UC auto-tracks pipeline → model → bronze → simulator (all already there); add the Apps consumer to lineage too |

### 6.9 Why this design

A few choices that aren't obvious:

- **Sklearn over Spark MLlib.** The training set is 20 000 rows — fits in
  memory with room to spare. Sklearn's GBR is faster, more familiar to
  customers, and round-trips cleanly through MLflow as a `pyfunc`. We pay
  zero performance cost because inference is per-row vectorised on Spark.
- **One model, scoring all (sku, supplier) pairs.** We considered
  per-SKU models. They'd improve fit on heavy-hitter SKUs but completely
  fail on long-tail SKUs with few quotes. A single model with `pack_size_g`
  and `usd_per_gram` as features generalises across the catalog and gets
  the long tail for free.
- **Score, then rule.** A pure end-to-end model could output BUY_NOW
  directly. We deliberately split the smooth-score model from the
  hard-decision rule because the rule's thresholds (`> 0.85`,
  `> 1%`, `< 50%`) are the knobs a procurement officer actually wants to
  tune at runtime, without retraining anything. Today they're constants
  in the pipeline; trivial promotion: move them into a `procurement_policy`
  Delta table the rule reads.
- **No feature store.** With 9 features sourced from 3 Gold/dim tables in
  the same pipeline, a feature store is overkill — the joins are explicit,
  cheap, and live in the same DAG as the model. If/when features need to
  be shared across multiple models (e.g. demand_1h_trays also feeding a
  yield-prediction model), promoting them to a UC Feature Table is the
  next step.

---

## 7. Serving — Lakebase Postgres (Autoscaling / Projects)

The live serving layer is a **Lakebase Autoscaling** instance (the new
"Projects" model — *not* classic Provisioned Lakebase). Resource hierarchy:

```
projects/myzerobus
  └── branches/production
        └── endpoints/primary   ← TCP-reachable Postgres at
                                  ep-frosty-flower-e2o5hjfp.database.cloud.databricks.com:5432
```

Database: `databricks_postgres` · Schema: **`liveoltp`**.

### 7.1 Five Synced Tables (Delta → Postgres mirrors)

Defined in `lakebase_sync/synced_tables.yml`. Each mirrors one Gold MV into a
read-only Postgres table that the app queries:

| Source (Delta) | Target (Postgres) | PK | Schedule |
|---|---|---|---|
| `gd_inventory_snapshot` | `liveoltp.inventory_snapshot` | `(sku, room_id)` | SNAPSHOT 30s |
| `gd_supplier_leaderboard` | `liveoltp.supplier_leaderboard` | `(sku, supplier_id)` | SNAPSHOT 30s |
| `gd_commodity_latest` | `liveoltp.commodity_prices_latest` | `(input_key)` | SNAPSHOT 30s |
| `gd_demand_1h` | `liveoltp.demand_1h` | `(sku, hour_ts)` | SNAPSHOT 60s |
| `gd_procurement_recommendations` | `liveoltp.procurement_recommendations` | `(recommendation_id)` | SNAPSHOT 30s |

**Why SNAPSHOT, not CONTINUOUS?** All five Gold sources are Lakeflow
**materialized views**, not change-data-feed streaming tables. Lakebase
CONTINUOUS sync requires a CDC-capable source. SNAPSHOT does a full
table replace on every interval; with the simulators driving constant churn
upstream, a 30 s interval feels real-time to the UI.

> **Operational note.** `lakebase_sync/apply.py` in this repo predates the
> Projects API and uses `w.database.create_synced_database_table(...)`,
> which only works against classic Lakebase Provisioned. On Autoscaling /
> Projects it fails with "instance not found". Until the script is rewritten
> for `w.postgres.*`, **create the 5 Synced Tables manually in Catalog
> Explorer** (or via the `databricks postgres` CLI), and ensure each has
> `scheduling_policy: SNAPSHOT` with the interval above.

### 7.2 Seven native Postgres tables (agent state)

DDL: `schemas/lakebase_schema.sql`. These never travel through Zerobus —
Lakebase is their system of record because the agents *update* rows
(negotiation status, approved/rejected, budget balance, dispute outcomes)
and Zerobus is append-only.

| Table | Used by | What it holds |
|---|---|---|
| `email_inbox` | negotiator | Inbound supplier replies |
| `email_outbox` | negotiator | RFQs / acceptances drafted by the agent |
| `po_drafts` | po_drafter, budget_gate | Draft → Approved/Rejected POs |
| `budget_ledger` | budget_gate | Monthly $25k seed-budget rolling balance |
| `supplier_applications` | onboarding | New seed-house signup form submissions |
| `invoice_reconciliations` | reconciler | Variance vs. PO total, OK/REVIEW/DISPUTE |
| `agent_runs` | all agents | Per-run audit log: prompt/output tokens, status, refs |

### 7.3 Authentication — Lakebase OAuth

Lakebase Postgres does **not** use a long-lived password. The app mints a
short-lived OAuth token per connection via the Databricks SDK, and uses that
token *as* the Postgres password (Lakebase recognizes it via the
`databricks_auth` Postgres extension). Token TTL ≈ 1 hour, refreshed 60 s
before expiry. See §9 for the role-setup walkthrough.

---

## 8. Application — Databricks Apps

Path: `backend/`. App slot name: **`livezerobus`**.

### 8.1 FastAPI backend (`backend/app/`)

```
backend/
├── app.yaml              ← deploy manifest (env vars, command)
├── requirements.txt
├── app/
│   ├── main.py           ← FastAPI app, mounts routes + static
│   ├── config.py         ← Settings (PG host/db/user/schema, Lakebase project/branch/endpoint)
│   ├── lakebase.py       ← OAuth token mint + psycopg ConnectionPool
│   ├── models.py         ← Pydantic request/response shapes
│   ├── routes/
│   │   ├── data.py       ← Read endpoints (Gold mirrors)
│   │   └── agents.py     ← Agent endpoints (FM API + Postgres writes)
│   └── agents/           ← Five agent implementations
└── static/               ← Built React bundle (populated by build_frontend.sh)
```

**Lakebase connection layer** (`backend/app/lakebase.py`):

- `_resource_name()` builds `projects/{LAKEBASE_PROJECT}/branches/{LAKEBASE_BRANCH}/endpoints/{LAKEBASE_ENDPOINT}` from env
- `_fetch_token()` calls `WorkspaceClient().postgres.generate_database_credential(endpoint=resource)`, returns `(token, expiry_epoch)`
- `_current_password()` caches the token, refetches when within 60 s of expiry
- `_connect_factory()` returns a callable that opens a psycopg connection with `password = current OAuth token`, `sslmode=require`, `application_name=livezerobus-app`, dict rows
- `get_pool()` lazily builds a `ConnectionPool(min_size=1, max_size=8)` with `SET search_path TO liveoltp, public` on each connection

**Read endpoints** (consume `liveoltp.*`):

- `GET /api/summary` — top-line metrics for the dashboard hero
- `GET /api/inventory` — all rows of `inventory_snapshot`
- `GET /api/suppliers/leaderboard` — ranked supplier list (optional `sku=`)
- `GET /api/commodity/latest` — current grow-input prices + 24 h pct
- `GET /api/demand/hourly` — last N hours of demand aggregation
- `GET /api/recommendations` — current reorder recommendations

**Agent endpoints** (consume + write to native PG tables):

- `GET /api/agents/email/threads` · `/po_drafts` · `/budget` · `/applications` · `/invoices` · `/runs`
- `POST /api/agents/applications` (form submit) · `/negotiator/tick` · `/negotiator/simulate-reply` · `/po_drafter/tick` · `/budget_gate/tick` · `/onboarding/tick` · `/reconciler/tick`
- `POST /api/agents/cycle` — runs `negotiator → po_drafter → budget_gate → reconciler` in one pass (the demo button)

### 8.2 React frontend (`frontend/`)

Vite + TypeScript + Recharts. Six tabs:

1. **Dashboard** — KPIs, inventory snapshot, current recommendations, leaderboard, commodity trends
2. **Emails** — outbox/inbox threads
3. **POs & Budget** — draft → approved POs and the rolling budget ledger
4. **Supplier onboarding** — application form + agent verdicts
5. **Invoices** — reconciliation results vs. PO totals
6. **Agent runs** — audit log of every FM-API invocation

Every component polls its endpoint on a shared `tick` prop (default 3 s).
Dark theme via `frontend/src/styles.css`. No external state store — almost
entirely read-only except the application form and the per-agent "tick"
buttons.

`scripts/build_frontend.sh` runs `npm ci && npm run build` and copies
`frontend/dist/*` into `backend/static/` so the deployed FastAPI bundle is
fully self-contained.

### 8.3 Deployment

`scripts/deploy_app.sh` — three steps, no bundle, no Terraform:

```bash
# 1. Build the React SPA into backend/static/
./scripts/build_frontend.sh

# 2. Sync backend/ into the workspace at /Workspace/Users/<caller>/livezerobus
databricks sync --full ./backend /Workspace/Users/<me>/livezerobus

# 3. Tell the existing App slot to redeploy from that workspace path
databricks apps deploy livezerobus --source-code-path /Workspace/Users/<me>/livezerobus
```

Apps deploy requires a workspace path; you can't `--source-code-path
./backend` from your laptop directly. Hence the `databricks sync` step.

---

## 9. Authentication & authorization (end-to-end)

Three identity boundaries, one service principal.

### 9.1 The app's identity

The App slot `livezerobus` runs under the workspace's auto-assigned service
principal. Inside the app container, `WorkspaceClient()` automatically picks
up the injected credentials — no client-id/secret in `app.yaml`.

For local dev, set `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` +
`DATABRICKS_CLIENT_SECRET` and the same `WorkspaceClient()` calls work.

### 9.2 App → Lakebase (OAuth-as-password)

```
1.  WorkspaceClient().postgres.generate_database_credential(
        endpoint="projects/myzerobus/branches/production/endpoints/primary"
    )
    → returns DatabaseCredential(token="...", expiration_time=...)

2.  psycopg.connect(host=..., user=<sp-uuid>, password=<token>, sslmode=require)
    Lakebase recognizes the token via the `databricks_auth` Postgres extension.

3.  Connection pool reuses the same token until ~60 s before expiry,
    then transparently mints a new one.
```

### 9.3 The Postgres role for the app SP

This is the part that's easy to get wrong. The role for the service
principal **must be created by the `databricks_create_role` function**, not
by plain `CREATE ROLE`. The latter creates a `NO_LOGIN` role that OAuth
tokens can't authenticate against.

**Correct setup (as a Lakebase superuser):**

```sql
-- One-time per Lakebase project
CREATE EXTENSION IF NOT EXISTS databricks_auth;

-- Then for each SP / user that needs to connect:
SELECT databricks_create_role(
  role_name      => 'c4352007-a55b-4da5-b5c9-f4c8df89e58a',  -- SP UUID
  identity_type  => 'SERVICE_PRINCIPAL'
);
GRANT USAGE  ON SCHEMA liveoltp TO "c4352007-a55b-4da5-b5c9-f4c8df89e58a";
GRANT SELECT ON ALL TABLES IN SCHEMA liveoltp TO "c4352007-a55b-4da5-b5c9-f4c8df89e58a";
GRANT INSERT, UPDATE, DELETE ON
    email_outbox, po_drafts, budget_ledger,
    supplier_applications, invoice_reconciliations, agent_runs
  TO "c4352007-a55b-4da5-b5c9-f4c8df89e58a";
```

Verify the role is correctly typed:

```bash
databricks postgres list-roles \
  projects/myzerobus/branches/production
```

Look for: `auth_method: LAKEBASE_OAUTH_V1`, `identity_type: SERVICE_PRINCIPAL`.
If it shows `auth_method: NO_LOGIN`, drop and recreate via
`databricks_create_role`.

### 9.4 App → Foundation Model API

Same SP, same `WorkspaceClient().config.authenticate()` token. Posts
OpenAI-compatible chat completions to
`/serving-endpoints/databricks-meta-llama-3-3-70b-instruct/invocations`.
No separate API key.

---

## 10. Agent layer (Foundation Model API)

Five agents under `backend/app/agents/`. Every run is logged to
`liveoltp.agent_runs` (prompt/output tokens, status, input/output refs).

| Agent | Trigger | Inputs | Output rows |
|---|---|---|---|
| `negotiator` | recommendation with no RFQ yet, OR unprocessed inbound email | `procurement_recommendations`, `supplier_leaderboard`, `email_inbox` | RFQ in `email_outbox` or extracted JSON in `email_inbox` |
| `po_drafter` | thread has a QUOTE / ACCEPT reply | `email_inbox`, leaderboard | new `DRAFT` row in `po_drafts` |
| `budget_gate` | new `DRAFT` PO | `po_drafts`, `budget_ledger` | PO → APPROVED / REJECTED, budget debit |
| `supplier_onboarding` | new application via UI form | `supplier_applications` row | verdict APPROVED / SCREENING / REJECTED |
| `invoice_reconciler` | received invoice row | invoice + matched PO | OK / REVIEW / DISPUTE in `invoice_reconciliations` |

The shared `FoundationModelClient` wraps token-aware HTTP calls and JSON
extraction. The "Run agent cycle" button in the UI calls
`POST /api/agents/cycle` which chains
`negotiator → po_drafter → budget_gate → reconciler` in one pass — the
demo's narrative climax.

---

## 11. Configuration reference

### 11.1 Env vars (set in `backend/app.yaml`)

| Variable | Example | Purpose |
|---|---|---|
| `PGHOST` | `ep-frosty-flower-e2o5hjfp.database.cloud.databricks.com` | Lakebase endpoint host |
| `PGPORT` | `5432` | |
| `PGDATABASE` | `databricks_postgres` | Lakebase logical database |
| `PGUSER` | `<service-principal-uuid>` | App SP UUID — used as Postgres role name |
| `PG_SCHEMA` | `liveoltp` | Schema set on `search_path` per connection |
| `LAKEBASE_PROJECT` | `myzerobus` | Projects API resource — project |
| `LAKEBASE_BRANCH` | `production` | Projects API resource — branch |
| `LAKEBASE_ENDPOINT` | `primary` | Projects API resource — endpoint |
| `FRONTEND_DIST` | `static` | Path the FastAPI app serves the SPA from |
| `FM_MODEL` | `databricks-meta-llama-3-3-70b-instruct` | Foundation Model serving endpoint |
| `BUDGET_MONTHLY_USD` | `25000` | Seeded into `budget_ledger` on first hit |

### 11.2 Pipeline parameters

| Param | Default | Set by |
|---|---|---|
| `pipelines.catalog` | `livezerobus` | Lakeflow pipeline UI |
| `pipelines.schema` | `procurement` | Lakeflow pipeline UI |
| `livezerobus.model_name` | `livezerobus.procurement.supplier_scoring_model` | Lakeflow pipeline UI |

### 11.3 Repo layout

```
LiveZerobus/
├── backend/                ← FastAPI + agents + (built) static SPA  (deployed)
├── frontend/               ← React+TS source              (built into backend/static)
├── pipelines/              ← Lakeflow SDP source files    (deployed to /Workspace)
├── simulators/             ← Zerobus producers            (run on a job or laptop)
├── ml/                     ← MLflow training script
├── lakebase_sync/          ← (legacy) synced-table apply script + YAML spec
├── schemas/                ← Bronze + Lakebase DDL
├── scripts/                ← deploy_app.sh, build_frontend.sh, probes
└── docs/                   ← this file + DEMO_SCRIPT.md
```

---

## 12. End-to-end runbook — cold start to working demo

This is the full sequence to bring LiveZerobus up from scratch in a fresh
workspace, with a verification step at every stage. Follow it top-to-bottom
once and you should land in a fully animated demo (BUY_NOW recommendations,
RFQ threads, signed POs, debited budget).

### 12.0 Prerequisites

- Databricks workspace with Unity Catalog and Lakebase Autoscaling enabled
- A service principal with workspace access (we'll grant the rest below) —
  note its **application ID** (a UUID like
  `c4352007-a55b-4da5-b5c9-f4c8df89e58a`); we call it `<sp-uuid>` below
- An empty Apps slot named `livezerobus`:
  ```bash
  databricks apps create livezerobus
  ```
- Local: Python 3.11+, Node 20+, npm, `databricks` CLI v0.218+ authenticated
  (`databricks auth login --host https://<workspace>.azuredatabricks.net`)

### 12.1 Step 1 — Unity Catalog (Bronze + dimensions)

Create the UC catalog/schema and the 4 Bronze Delta tables that Zerobus
writes into:

```bash
python scripts/setup_unity_catalog.py
```

This creates `livezerobus.procurement` with `bz_inventory_events`,
`bz_supplier_quotes`, `bz_demand_events`, `bz_commodity_prices` — all with
`delta.appendOnly=true` and `delta.columnMapping.mode=name` (Zerobus
requires both).

Then seed the `dim_sku` (20 rows) and `dim_supplier` (10 rows) tables. In a
Databricks SQL notebook:

```sql
SET catalog = 'livezerobus';
SET schema  = 'procurement';
-- run schemas/seed_dimensions.sql here
```

**Verify:**

```sql
SELECT COUNT(*) FROM livezerobus.procurement.dim_sku;       -- 20
SELECT COUNT(*) FROM livezerobus.procurement.dim_supplier;  -- 10
SHOW TABLES IN livezerobus.procurement;                     -- 4 bz_* + 2 dim_*
```

### 12.2 Step 2 — Train + register the ML model

From your laptop or a Databricks notebook:

```bash
python ml/train_supplier_model.py
```

Logs an MLflow run, registers `livezerobus.procurement.supplier_scoring_model`
v1 in UC, and sets the `@prod` alias to it.

**Verify:** Catalog Explorer → Models → `supplier_scoring_model` exists with
alias `prod` pointing at v1. MLflow run shows `mae` ≈ `0.02–0.03`.

### 12.3 Step 3 — Lakebase project + DDL

In the Databricks UI: **Compute → Lakebase → Create project**:

- Project: `myzerobus`
- Branch: `production`
- Endpoint: `primary`
- Database: `databricks_postgres`

Open the **Lakebase SQL editor** connected to that database and run the
contents of `schemas/lakebase_schema.sql` end-to-end. This creates the
`liveoltp` schema with **5 placeholder tables** (which the synced tables
will replace) and **7 agent-state tables** (`email_outbox`, `email_inbox`,
`po_drafts`, `budget_ledger`, `supplier_applications`,
`invoice_reconciliations`, `agent_runs`).

**Verify:**

```sql
SELECT table_name FROM information_schema.tables WHERE table_schema='liveoltp';
-- expect 12 rows
```

### 12.4 Step 4 — Lakebase OAuth role for the app SP

In the same Lakebase SQL editor, as a Lakebase superuser:

```sql
-- One-time per Lakebase project
CREATE EXTENSION IF NOT EXISTS databricks_auth;

-- Create the role for the app's service principal
SELECT databricks_create_role(
  role_name     => '<sp-uuid>',
  identity_type => 'SERVICE_PRINCIPAL'
);

-- Grant read on synced tables + read/write on agent-state tables
GRANT USAGE  ON SCHEMA liveoltp TO "<sp-uuid>";
GRANT SELECT ON ALL TABLES IN SCHEMA liveoltp TO "<sp-uuid>";
GRANT INSERT, UPDATE ON
    liveoltp.email_outbox, liveoltp.email_inbox, liveoltp.po_drafts,
    liveoltp.budget_ledger, liveoltp.supplier_applications,
    liveoltp.invoice_reconciliations, liveoltp.agent_runs
  TO "<sp-uuid>";
```

> **Critical**: do **not** use plain `CREATE ROLE` — it produces a
> `NO_LOGIN` role that OAuth tokens cannot authenticate against.
> `databricks_create_role` is the right call.

**Verify:**

```bash
databricks postgres list-roles projects/myzerobus/branches/production
```

Look for an entry with `name: <sp-uuid>`, `auth_method: LAKEBASE_OAUTH_V1`,
`identity_type: SERVICE_PRINCIPAL`. If you see `NO_LOGIN`, drop and recreate.

### 12.5 Step 5 — Create the 5 Lakebase Synced Tables

In **Catalog Explorer**, drill into the catalog where your Lakebase synced
tables are visible (or use **Compute → Lakebase → myzerobus → production →
Synced Tables**). For each row in `lakebase_sync/synced_tables.yml`,
**Create Synced Table**:

| Source (UC) | Target (Lakebase) | Primary key | Schedule |
|---|---|---|---|
| `livezerobus.procurement.gd_inventory_snapshot` | `liveoltp.inventory_snapshot` | `(sku, room_id)` | SNAPSHOT 30 s |
| `livezerobus.procurement.gd_supplier_leaderboard` | `liveoltp.supplier_leaderboard` | `(sku, supplier_id)` | SNAPSHOT 30 s |
| `livezerobus.procurement.gd_commodity_latest` | `liveoltp.commodity_prices_latest` | `(input_key)` | SNAPSHOT 30 s |
| `livezerobus.procurement.gd_demand_1h` | `liveoltp.demand_1h` | `(sku, hour_ts)` | SNAPSHOT 60 s |
| `livezerobus.procurement.gd_procurement_recommendations` | `liveoltp.procurement_recommendations` | `(recommendation_id)` | SNAPSHOT 30 s |

> Until `lakebase_sync/apply.py` is rewritten for the Projects API, this
> step is manual via UI.

**Verify:** all five tables show `Status: Active` and a recent successful
sync (will be empty on first sync — that's fine).

### 12.6 Step 6 — Lakeflow pipeline (Bronze → Silver → Gold + ML)

Sync pipeline source files into the workspace:

```bash
databricks sync ./pipelines /Workspace/Users/<me>/livezerobus/pipelines
```

Then **Workflows → Pipelines → Create pipeline**:

- **Pipeline name**: `livezerobus_seed_procurement`
- **Channel**: Preview *(required for the new `pyspark.pipelines` API)*
- **Source code paths**: add all three:
  - `/Workspace/Users/<me>/livezerobus/pipelines/bronze_to_silver.py`
  - `/Workspace/Users/<me>/livezerobus/pipelines/silver_to_gold.py`
  - `/Workspace/Users/<me>/livezerobus/pipelines/auto_procurement_scoring.py`
- **Catalog**: `livezerobus`, **Schema**: `procurement`
- **Mode**: Continuous
- **Configuration**:
  - `pipelines.catalog = livezerobus`
  - `pipelines.schema  = procurement`
  - `livezerobus.model_name = livezerobus.procurement.supplier_scoring_model`
- Click **Start**

The DAG should show 4 streaming tables (`sv_*`) and 6 materialized views
(`gd_*`). At this point all are at zero rows — that's expected, no data is
flowing yet.

### 12.7 Step 7 — Grant FM endpoint access + deploy the app

In the Databricks UI: **Serving → `databricks-meta-llama-3-3-70b-instruct`
→ Permissions → Grant your `<sp-uuid>` `CAN_QUERY`**. The agents need this
to call the Foundation Model API.

Then deploy the app:

```bash
./scripts/deploy_app.sh
```

Three things happen: React → built into `backend/static/`, `backend/`
synced to `/Workspace/Users/<me>/livezerobus`, Apps slot redeployed.

**Verify:**

```bash
databricks apps logs livezerobus | tail -30
```

Look for `Uvicorn running on http://0.0.0.0:8000` and no Postgres auth
errors. Open the app URL — the dashboard loads, all KPI cards show 0 (no
data yet).

### 12.8 Step 8 — Start the simulators

On your laptop (or a small Databricks Job — see §14 / future work):

```bash
cd simulators/
pip install -r requirements.txt

export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_CLIENT_ID=<sp-uuid>
export DATABRICKS_CLIENT_SECRET=<sp-secret>
export ZEROBUS_ENDPOINT=<region-endpoint>     # see .env.example
export UC_CATALOG=livezerobus
export UC_SCHEMA=procurement

python run_all.py
```

This opens four long-lived gRPC streams against Zerobus and starts pumping
events into the Bronze tables.

**Verify** Bronze counts climbing:

```sql
SELECT 'bz_inventory_events'  t, COUNT(*) FROM livezerobus.procurement.bz_inventory_events  UNION ALL
SELECT 'bz_supplier_quotes',     COUNT(*) FROM livezerobus.procurement.bz_supplier_quotes   UNION ALL
SELECT 'bz_commodity_prices',    COUNT(*) FROM livezerobus.procurement.bz_commodity_prices  UNION ALL
SELECT 'bz_demand_events',       COUNT(*) FROM livezerobus.procurement.bz_demand_events;
```

You should see 4 non-zero counts within ~30 seconds.

### 12.9 Step 9 — Verify the medallion is flowing

Run after ~2 minutes:

```sql
SELECT 'sv_inventory_events' t, COUNT(*) FROM livezerobus.procurement.sv_inventory_events UNION ALL
SELECT 'sv_supplier_quotes',     COUNT(*) FROM livezerobus.procurement.sv_supplier_quotes  UNION ALL
SELECT 'sv_commodity_prices',    COUNT(*) FROM livezerobus.procurement.sv_commodity_prices UNION ALL
SELECT 'sv_demand_events',       COUNT(*) FROM livezerobus.procurement.sv_demand_events;

SELECT 'gd_inventory_snapshot'         t, COUNT(*) FROM livezerobus.procurement.gd_inventory_snapshot UNION ALL
SELECT 'gd_supplier_leaderboard',         COUNT(*) FROM livezerobus.procurement.gd_supplier_leaderboard UNION ALL
SELECT 'gd_commodity_latest',             COUNT(*) FROM livezerobus.procurement.gd_commodity_latest UNION ALL
SELECT 'gd_demand_1h',                    COUNT(*) FROM livezerobus.procurement.gd_demand_1h UNION ALL
SELECT 'gd_supplier_quotes_current',      COUNT(*) FROM livezerobus.procurement.gd_supplier_quotes_current UNION ALL
SELECT 'gd_procurement_recommendations',  COUNT(*) FROM livezerobus.procurement.gd_procurement_recommendations;
```

All Silver should be non-zero. All Gold except possibly
`gd_procurement_recommendations` should be non-zero (see §12.10 for that one).

In **Lakebase SQL editor**:

```sql
SELECT 'inventory_snapshot'          t, COUNT(*) FROM liveoltp.inventory_snapshot          UNION ALL
SELECT 'supplier_leaderboard',          COUNT(*) FROM liveoltp.supplier_leaderboard          UNION ALL
SELECT 'commodity_prices_latest',       COUNT(*) FROM liveoltp.commodity_prices_latest       UNION ALL
SELECT 'demand_1h',                     COUNT(*) FROM liveoltp.demand_1h                     UNION ALL
SELECT 'procurement_recommendations',   COUNT(*) FROM liveoltp.procurement_recommendations;
```

Within ~60 s of Gold being populated, all 5 should mirror.

The app's **Dashboard** tab should now show inventory, demand, commodity
prices, and the supplier leaderboard.

### 12.10 Step 10 — Tune reorder thresholds so recommendations populate

By default the simulators' inventory levels are far above `dim_sku.reorder_point_g`,
so `gd_procurement_recommendations` filters everything out. Bump the
threshold once for the demo:

```sql
UPDATE livezerobus.procurement.dim_sku
SET reorder_point_g = (
  SELECT CAST(MAX(on_hand_g) * 3 AS BIGINT)
  FROM livezerobus.procurement.gd_inventory_snapshot
);
```

In the pipeline UI, right-click **gd_procurement_recommendations → Full
refresh selected**. ~3 s later it has rows; ~30 s after that, the synced
table mirrors them.

**Verify:**

```sql
SELECT decision, COUNT(*) FROM liveoltp.procurement_recommendations GROUP BY decision;
```

Expect a healthy mix dominated by `BUY_NOW`. The app's **Dashboard**
recommendations panel populates.

### 12.11 Step 11 — Bring up the agent loop (Emails → POs → Budget)

This is the part that doesn't run automatically. Each click of the
"Run agent cycle" button in the app fires
`negotiator → po_drafter → budget_gate → invoice_reconciler` once.

**a. Draft 5 RFQs.** In the app, click **Run agent cycle** 5 times. Each
click drafts one RFQ for one BUY_NOW rec.

```sql
SELECT COUNT(*) FROM liveoltp.email_outbox;     -- expect 5
SELECT started_ts, status FROM liveoltp.agent_runs ORDER BY started_ts DESC LIMIT 5;
```

All 5 agent runs should be `OK` with non-zero token counts. The **Emails**
tab now lists 5 supplier threads.

**b. Simulate inbound replies.** Click each thread → **Simulate supplier
reply**. The FM API role-plays the named seed house and writes to
`email_inbox`. Each reply has 60% QUOTE / 25% COUNTER / 10% REJECT / 5% OOF.

```sql
SELECT COUNT(*) FROM liveoltp.email_inbox;      -- expect 5
SELECT intent_detected, COUNT(*) FROM liveoltp.email_inbox GROUP BY intent_detected;
-- intent_detected is NULL until the negotiator processes them in step (c)
```

**c. Process the inbox + draft POs + run the budget gate.** Click **Run
agent cycle** *one more time*. This single click does three things:

1. `negotiator` extracts structured terms from each inbox row
   (`processed=TRUE`, `intent_detected`, `extracted_json`)
2. `po_drafter` finds threads with intent QUOTE/ACCEPT/COUNTER and
   creates a `DRAFT` row in `po_drafts`
3. `budget_gate` lazy-seeds the monthly $25 000 budget on first call,
   then debits each DRAFT PO and flips it to `APPROVED` (or `REJECTED`
   if over budget)

**Verify the full chain:**

```sql
SELECT
  (SELECT COUNT(*) FROM liveoltp.email_inbox WHERE processed=TRUE) AS processed_inbox,
  (SELECT COUNT(*) FROM liveoltp.po_drafts)                        AS po_drafts,
  (SELECT COUNT(*) FROM liveoltp.po_drafts WHERE status='APPROVED') AS approved,
  (SELECT COUNT(*) FROM liveoltp.budget_ledger)                    AS ledger_entries,
  (SELECT MAX(balance_usd) FROM liveoltp.budget_ledger)            AS budget_balance;
```

The **POs & Budget** tab now shows DRAFT/APPROVED rows and the rolling
balance. The **Agent runs** tab shows ~10–15 OK rows with token counts.

### 12.12 Step 12 — Optional: hands-off demo loop

For a continuous live demo, schedule a tiny Databricks Workflow that ticks
the app every 60 s and simulates a reply every 90 s. Pseudocode for the
job's notebook task:

```python
import os, time, random, requests
from databricks.sdk import WorkspaceClient

APP = os.environ["APP_URL"]                         # https://livezerobus-…azuredatabricks.net
TOKEN = WorkspaceClient().config.authenticate()["Authorization"].split(" ", 1)[1]
H = {"Authorization": f"Bearer {TOKEN}"}

# 1. tick the cycle
requests.post(f"{APP}/api/agents/cycle", headers=H, timeout=30).raise_for_status()

# 2. simulate a reply on a random recent thread without one
threads = requests.get(f"{APP}/api/agents/email/threads", headers=H).json()
candidates = [t for t in threads if t.get("side") == "OUT"]   # outbox-only threads
if candidates:
    t = random.choice(candidates)
    requests.post(f"{APP}/api/agents/negotiator/simulate-reply",
                  json={"thread_id": t["thread_id"]}, headers=H, timeout=30)
```

Schedule the workflow on a 60 s cron; that's enough churn that during a
demo, every refresh of the app shows new threads, new POs, and budget
movement without a single manual click.

### 12.13 Quick-reference: the 12 commands

For a skim-only refresher the next time you set this up:

```bash
# 1. UC + Bronze + dimensions
python scripts/setup_unity_catalog.py
# (then run schemas/seed_dimensions.sql in Databricks SQL)

# 2. ML model
python ml/train_supplier_model.py

# 3-4. Lakebase project + DDL + role  (UI + Lakebase SQL editor)

# 5. Synced Tables  (Catalog Explorer UI)

# 6. Pipeline source + create pipeline
databricks sync ./pipelines /Workspace/Users/<me>/livezerobus/pipelines
# (then create pipeline in UI, click Start)

# 7. App
./scripts/deploy_app.sh

# 8. Simulators
cd simulators && python run_all.py

# 9. Verify medallion (SQL above)

# 10. Tune reorder threshold
#     UPDATE dim_sku SET reorder_point_g = (SELECT CAST(MAX(on_hand_g)*3 AS BIGINT) FROM gd_inventory_snapshot)
#     (then full-refresh gd_procurement_recommendations in pipeline UI)

# 11. Click "Run agent cycle" 5x → click "Simulate supplier reply" on each
#     thread → click "Run agent cycle" once more

# 12. (optional) schedule a 60s Workflow to keep the demo alive
```

---

## 13. Operational gotchas (learned the hard way)

These are the failure modes encountered during build-out. Recognizing them
early saves hours.

### 13.1 Pipeline checkpoint mismatch after Bronze re-create

Symptom: `[DIFFERENT_DELTA_TABLE_READ_BY_STREAMING_SOURCE]` in pipeline event
log, every Silver flow fails, every Gold flow `SKIPPED`.

Cause: dropped + recreated a Bronze table → new Delta UUID → streaming
checkpoint still references the old UUID → Delta refuses to silently switch.

Fix: in pipeline UI, **Start ▾ → Full refresh all** (or full-refresh the
affected `sv_*` nodes). Wipes checkpoints and replays from Bronze head.

Prevention: don't `DROP TABLE bz_*`. Use `DELETE FROM bz_* WHERE …` to wipe
test data — same UUID, checkpoint stays valid.

### 13.2 Lakebase Postgres role with `auth_method: NO_LOGIN`

Symptom: `password authentication failed for user '<sp-uuid>'`, even though
the SDK successfully mints a token.

Cause: role was created with plain `CREATE ROLE`, which produces `NO_LOGIN`
on Lakebase. OAuth tokens can't authenticate against that.

Fix: drop the role (use `databricks postgres delete-role` if Postgres
refuses due to ownership), then recreate with
`SELECT databricks_create_role(role_name=>…, identity_type=>'SERVICE_PRINCIPAL')`.

Verify via `databricks postgres list-roles …` — must show
`auth_method: LAKEBASE_OAUTH_V1`.

### 13.3 Wrong SDK namespace (`w.database.*` vs `w.postgres.*`)

Symptom: `Database instance '<endpoint-host>' not found`.

Cause: calling classic Lakebase Provisioned API
(`w.database.generate_database_credential(instance_names=[...])`) against an
Autoscaling / Projects instance.

Fix: use `w.postgres.generate_database_credential(endpoint="projects/.../endpoints/primary")`.
The SDK signature is `generate_database_credential(endpoint: str, *, claims=None)`.

`lakebase_sync/apply.py` still uses the classic API and needs a rewrite for
Projects (TODO).

### 13.4 Synced tables with no schedule

Symptom: synced tables exist in `liveoltp.*` but never refresh; row counts
stuck at zero (or initial snapshot).

Cause: synced table was created without setting `scheduling_policy: SNAPSHOT`
+ `snapshot_interval_seconds`. Default is no automatic refresh.

Fix: in Catalog Explorer, Edit each synced table → Scheduling: SNAPSHOT,
interval 30 s (60 s for `demand_1h`). Or trigger manually with **Sync now**.

### 13.5 Empty `gd_procurement_recommendations` despite full Gold

Symptom: every other Gold MV has rows, but `gd_procurement_recommendations`
emits 0.

Cause: filter `on_hand_g <= reorder_point_g` matches nothing — fresh
simulator state has every SKU at 100× the reorder point.

Fix (demo): `UPDATE dim_sku SET reorder_point_g = (SELECT CAST(AVG(on_hand_g) AS BIGINT) FROM gd_inventory_snapshot)`.
Triggers ~half the SKUs as "low stock" with mixed BUY_NOW / WAIT / REVIEW.

### 13.6 `databricks apps deploy` from local path fails

Symptom: `Source code path must be a valid workspace path`.

Cause: Apps deploy reads from `/Workspace/...`, not local FS.

Fix: `databricks sync ./backend /Workspace/Users/<me>/livezerobus` first,
then `databricks apps deploy livezerobus --source-code-path /Workspace/Users/<me>/livezerobus`.

---

## 14. Future work

- Rewrite `lakebase_sync/apply.py` against the Projects API (`w.postgres.*`)
  so synced tables can be reconciled in CI instead of clicked into existence
- Move simulators to a Databricks Job (currently laptop-friendly only)
- Replace synthetic `dim_supplier` / `dim_sku` with a small Lakebase-backed
  CRUD UI so the demo can mutate them live
- Add Lakebase CDC source for at least one Gold table (e.g. promote
  `gd_inventory_snapshot` to a streaming table) so we can show CONTINUOUS
  sync alongside SNAPSHOT
- Wire `agent_runs` token usage into the budget gate (token cost ↔ USD)
- Replace `BUY_NOW / WAIT / REVIEW` rule-based decision in
  `gd_procurement_recommendations` with a second MLflow-registered model
  trained on outcomes from `invoice_reconciliations`
