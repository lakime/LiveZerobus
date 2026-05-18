# LiveZerobus end-to-end testing playbook

A reproducible script for spinning everything up and walking the full demo. ~30 min including the data warm-up wait.

Failure modes we've actually hit (with recovery commands inline) are folded into each step.

---

## 0. Prerequisites (one-time, skip if already configured)

| Need | How |
|------|-----|
| Lakebase agent-state tables exist + SP has grants | `python scripts/apply_lakebase_schema.py` (idempotent) |
| App SP has UC grants on the SAP BDC share | `GRANT USE CATALOG, BROWSE ON CATALOG sapsofts TO \`c4352007-…\`; GRANT USE SCHEMA, SELECT ON SCHEMA sapsofts.procurement TO \`c4352007-…\`;` |
| External sap-bdc service is up | `curl https://photop.uzar.pl/healthz` → `{"ok":true}` |
| Latest livezerobus code is deployed | `gh run list --workflow=deploy.yml --limit 1` → most recent commit on `main` |

---

## 1. Start the data plane (simulators)

```bash
cd simulators
.venv/bin/python sim_ui.py        # opens browser at :8765
```

In the sim UI:
1. Click **Start all** — six simulators should show "running" status.
2. Look at the **Pipeline** panel — it auto-triggers the Lakeflow pipeline (`livezerobus_procurement_sdp`) every 10 minutes while sims are running.
3. Click **▶ Run now** under Pipeline to kick off the first run immediately (don't wait 10 min on a fresh start).

> **Heads-up**: the per-simulator "events emitted" counter in sim_ui is buggy — it stays at 0 even though Bronze tables are getting rows. Don't trust it; use the SQL diagnostic in step 2.

---

## 2. Sanity check the four layers (Bronze / Silver / Gold / Lakebase)

After ~3 min of simulators running + one pipeline cycle, run this from your laptop. Replace `$TOKEN` with a workspace PAT:

```bash
TOKEN="<your-databricks-PAT>"
HOST="https://adb-5347428297913551.11.azuredatabricks.net"
WH="6a1fb3b32b00f1cd"

q() { curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$HOST/api/2.0/sql/statements" \
  -d "{\"warehouse_id\":\"$WH\",\"statement\":\"$1\",\"wait_timeout\":\"30s\"}" \
  | python3 -c "import json,sys;r=json.load(sys.stdin);d=r.get('result',{}).get('data_array',[]);print(d[0] if d else r.get('status',{}).get('state'))"; }

echo "=== Bronze (simulators are emitting) ==="
q "SELECT count(*), max(event_ts) FROM livezerobus.procurement.bz_commodity_prices"
q "SELECT count(*), max(event_ts) FROM livezerobus.procurement.bz_demand_events"
q "SELECT count(*), max(event_ts) FROM livezerobus.procurement.bz_inventory_events"

echo "=== Gold (Lakeflow pipeline ran) ==="
q "SELECT count(*), max(event_ts) FROM livezerobus.procurement.gd_commodity_latest"
q "SELECT count(*), max(hour_ts)  FROM livezerobus.procurement.gd_demand_1h"
q "SELECT count(*) FROM livezerobus.procurement.gd_procurement_recommendations WHERE decision='BUY_NOW'"
```

Expected: Bronze + Gold both have today's timestamps. If Bronze is fresh but Gold is stale → trigger the Lakeflow pipeline (sim_ui Pipeline tab → ▶ Run now), wait 2-3 min, recheck.

---

## 3. Sanity check Lakebase (the layer that the Dashboard actually reads)

The Lakebase synced tables snapshot from Gold MVs every 30-60s. They occasionally get stuck on a stale snapshot — when that happens, the Dashboard panels show empty.

```bash
cd /Users/puzar/livebus/LiveZerobus
DATABRICKS_CONFIG_PROFILE=softdev \
PGUSER="puzar@devsoftserveinc.com" \
.venv/bin/python3 <<'PY'
import psycopg
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
cred = w.postgres.generate_database_credential(
    endpoint="projects/myzerobus/branches/production/endpoints/primary")
with psycopg.connect(
    host="ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net",
    port=5432, dbname="databricks_postgres",
    user="puzar@devsoftserveinc.com", password=cred.token, sslmode="require",
) as conn, conn.cursor() as cur:
    for t, ts_col in [
        ("commodity_prices_latest", "event_ts"),
        ("demand_1h", "hour_ts"),
        ("inventory_snapshot", "last_event_ts"),
        ("iot_sensor_latest", "event_ts"),
    ]:
        cur.execute(f"SELECT count(*), max({ts_col}) FROM procurement.{t}")
        c, ts = cur.fetchone()
        print(f"  {t:32s} count={c:6d}  max({ts_col})={ts}")
PY
```

**Expected**: every `max()` is today within the last ~5 minutes. If any is more than a day stale → that synced table is corrupted. Recovery:

```bash
# Replace <name> with the stuck table (e.g. commodity_prices_latest)
TOKEN="<your-databricks-PAT>"
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "https://adb-5347428297913551.11.azuredatabricks.net/api/2.0/database/synced_tables/livezerobus.procurement.<name>"

# Then drop the Postgres-side table:
psql "host=ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net dbname=databricks_postgres user=puzar@devsoftserveinc.com sslmode=require" -c "DROP TABLE procurement.<name> CASCADE"
# (password = output of: databricks postgres generate-database-credential --endpoint 'projects/myzerobus/branches/production/endpoints/primary')

# Re-run the apply script which recreates all missing synced tables:
python lakebase_sync/apply.py --catalog livezerobus --schema procurement \
  --lakebase-instance myzerobus --lakebase-branch production
```

---

## 4. Walk through each tab

Open **https://livezerobus-5347428297913551.11.azure.databricksapps.com**.

### 4.1 Dashboard

- **Inventory panel**: rows per `(sku, room_id)` with `on_hand_g` values updating every refresh.
- **Supplier Leaderboard**: top 3 per SKU with `score` and `rank`.
- **Commodity Chart**: 5 lines (kwh, peat, rockwool, coco_coir, nutrient_pack) with `pct_1h` / `pct_24h` badges.
- **Demand Chart**: 24h rolling demand by SKU.
- **Recommendations**: rows with `decision ∈ {BUY_NOW, WAIT, REVIEW}` and `ml_score` (0–1).

✅ **Pass**: all panels have data, all timestamps within last ~10 min.

❌ Empty panel → step 3 (Lakebase staleness).

### 4.2 Emails (negotiator agent)

- See thread list on the left (outbound RFQs + inbound replies).
- Click any thread → message chain renders on the right.
- Click **Tick agent**. Wait ~10s.
- A new email should appear in the outbox — either a fresh RFQ to a new supplier or a follow-up on an existing thread.

✅ **Pass**: new email mentions a non-zero quantity (e.g. `300 g (12 packs × 25 g)`).
❌ **Email asks for "0 g"**: that's the bug we fixed in commit `28ae511`. Make sure latest backend is deployed (`gh run list --workflow=deploy.yml --limit 1`).

### 4.3 POs & Budget (po_drafter + budget_gate)

- Top: **PO Drafts** table — rows with `status ∈ {DRAFT, APPROVED, REJECTED, SENT, RECEIVED}`.
- Bottom: **Budget Ledger** with rolling balance + entries.
- Click **Tick po_drafter** → at least one new DRAFT row appears, sourced from a BUY_NOW recommendation.
- Click **Tick budget_gate** → at least one DRAFT flips to APPROVED or REJECTED. The Budget Ledger gets a new entry tagged with the PO.

✅ **Pass**: full draft → approve flow visible.

### 4.4 Supplier onboarding

- Fill the **Submit application** form (name, email, country, SKUs, organic ✓, years ≥ 1).
- Submit. Row appears with `status = PENDING`.
- Click **Tick supplier_onboarding**. Status flips to APPROVED or REJECTED. `agent_notes` explains why.

### 4.5 Invoices (invoice_reconciler)

- Click **Simulate invoice** → injects a synthetic invoice referencing one of the SAP PO rows.
- Refresh → new row with `status = RECEIVED`, expected/invoiced amounts populated.
- Click **Tick invoice_reconciler** → status moves to MATCHED / VARIANCE_OK / FLAGGED, with a `variance_pct`.

### 4.6 Agent Runs (telemetry)

- Table of the last 25 agent invocations. `status`, `prompt_tokens`, `output_tokens`, `error_msg` if any.

✅ **Pass**: at least one row per agent you ticked. All `OK` status.
❌ **All ERROR**: FM_MODEL endpoint unreachable. Check the app's env vars.

### 4.7 SAP P2P

- **Open PO Lines** table (top): `po_number / po_item`, **Supplier column** shows readable vendor names when LIFNR happens to match a row in LFA1 (from BDC); otherwise raw `0000100013` style IDs.
- **3-way invoice match** (bottom): invoice vs PO vs GR; status badge MATCHED / VARIANCE / PENDING_GR / NO_PO; variance$ column.
- Filter dropdowns to slice by status.

✅ **Pass**: both tables populated. Some vendor names visible (any → BDC vendor-lookup is working).

### 4.8 SAP BDC (the new external Delta-Sharing tab)

**4.8.1 Overview sub-tab**

- Green **CONNECTED** badge + "15 tables in `sapsofts.procurement`".
- Click **↻ Sync now** — progress bar advances 0% → 100%, "currently: <table>" updates live, takes ~1-2 min.
- Watch the badge grid (15 SAP tables) turn green one by one.
- Open **Sync log** at the bottom — last 50 lines.

✅ **Pass**: 15/15 green, no failures.

❌ **DISCONNECTED banner shows**: see Prerequisites step 1 (SP grants on catalog).

❌ **Red badges or "RESOURCE_DOES_NOT_EXIST"** in log: that's UC's connector flake. Click Sync now again — retry logic usually resolves it within 2 tries.

**4.8.2 Vendors (LFA1)**

- Table of 20 vendor master rows from the BDC mock.
- Search by name / country / city / LIFNR works.

✅ **Pass**: 20 rows. Search "DE" → only German vendors.

**4.8.3 Purchase Orders (EKKO+EKPO)**

- 367 PO line items joined with header + LFA1 vendor name.
- Search by PO# / vendor / material works.

✅ **Pass**: rows render with vendor names + prices.

❌ **White screen**: a stale frontend bundle from before commit `e5a1aeb` (numeric-string crash fix). Hard refresh.
❌ **Red ERROR banner**: UC flake on the 3-way join. Click Sync now in Overview, then retry.

### 4.9 IoT Fields

- 6 grow-room cards. Each has 7 SVG arc-gauge speedometers: temperature, humidity, soil moisture, light, CO₂, pH, EC.
- Sparklines beneath each gauge show recent trend.
- Colors: green = NOMINAL, yellow = CAUTION, red = ALERT.
- Wait 1-2 min — sensors slowly oscillate, occasional ALERT injection self-recovers after ~5 min.

✅ **Pass**: gauges animate, mix of statuses (mostly NOMINAL with occasional CAUTION).

### 4.10 Pipeline

- Status of the `livezerobus_procurement_sdp` Lakeflow pipeline (RUNNING / IDLE / FAILED).
- Last update timestamp.
- **▶ Run now** button manually triggers a refresh — useful after fixing data.

---

## 5. End-to-end agent chain (the killer demo, do this last)

After the Dashboard has BUY_NOW recommendations, run this in order:

```
Recommendations  →  PO Drafter  →  Budget Gate  →  Negotiator  →  Invoice Reconciler
   (Dashboard)        (POs tab)      (POs tab)       (Emails)         (Invoices)
```

1. **Dashboard** — confirm at least one `BUY_NOW` recommendation with nonzero `reorder_grams`.
2. **POs & Budget** — Tick `po_drafter`. New DRAFT references that recommendation.
3. Same tab — Tick `budget_gate`. DRAFT flips to APPROVED (or REJECTED if over budget).
4. **Emails** — Tick `negotiator`. New outbound RFQ references the PO with nonzero quantity.
5. **Invoices** — Simulate invoice (references the PO from step 3). Status RECEIVED.
6. Same tab — Tick `invoice_reconciler`. Status MATCHED / VARIANCE_OK / FLAGGED.
7. **Agent Runs** — all 4 ticks logged with token counts.

✅ **Full pass**: a single recommendation flowed through all 5 agents without manual intervention beyond clicking Tick.

---

## 6. Cleanup

```bash
# Stop simulators
# (in sim_ui at :8765) → Stop all

# Optionally stop the livezerobus app compute to save budget
# Databricks UI → Compute → Apps → livezerobus → Stop
```

---

## Quick diagnostic flowchart

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard panels all empty | Lakeflow pipeline never ran | Pipeline tab → ▶ Run now |
| One panel empty (commodity / demand / inventory) | Synced table stale | Step 3 recovery |
| Demand chart empty but synced has rows | All rows older than 24h (chart filter) | Trigger main pipeline, wait, recheck |
| Email asks for 0g | Old code or stale recs | Verify backend is on commit ≥ `28ae511`; trigger Lakeflow pipeline |
| SAP P2P shows raw LIFNR (no vendor names) | LIFNR↔LFA1 mismatch (different ID schemes) | Expected — only some IDs overlap |
| SAP BDC DISCONNECTED | Missing UC grants on `sapsofts` catalog | Prerequisites step 1 |
| SAP BDC white screen on Purchase Orders | Stale bundle pre-`e5a1aeb` | Hard refresh |
| Agent ticks all ERROR | FM_MODEL unreachable | Check app env vars in Databricks Apps UI |
| `/api/summary` 500 (`po_drafts does not exist`) | Lakebase schema not applied | `python scripts/apply_lakebase_schema.py` |
