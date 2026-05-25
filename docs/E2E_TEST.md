# End-to-end test scenario

Numbered checkpoints. When you hit a broken step, paste me the step number + what you actually saw.

Each step has an **EXPECT** (what should happen) and **FAIL** (what to capture if it doesn't).

---

## 0. Prerequisites

Open these in tabs so we can debug fast:

- Databricks workspace: <https://adb-5347428297913551.11.azuredatabricks.net>
- livezerobus app: <https://livezerobus-5347428297913551.11.azure.databricksapps.com>
- Lakeflow pipeline: <https://adb-5347428297913551.11.azuredatabricks.net/pipelines/4cef05ca-ea6f-4217-af60-6b75a6b1a3f4>
- SAP BDC mock GUI (external, on VPS): <https://photop.uzar.pl>
- GitHub Actions runs: <https://github.com/lakime/LiveZerobus/actions>

Confirm:

- [ ] Latest CI run for `deploy` workflow on `main` is **✅ success**
- [ ] livezerobus app shows **app=RUNNING, compute=ACTIVE** (Workspace → Compute → Apps → livezerobus)

**FAIL**: paste the CI failure log or the app status line.

---

## 1. Backend health

```bash
TOKEN=$(databricks auth token --profile softdev 2>/dev/null \
  | python3 -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))")
curl -H "Authorization: Bearer $TOKEN" \
  https://livezerobus-5347428297913551.11.azure.databricksapps.com/healthz
```

**EXPECT**: `{"ok":true}`
**FAIL**: `App Not Active` → app crashed; check logs in Databricks UI → Apps → livezerobus → Logs tab.

---

## 2. Start simulators

```bash
cd /Users/puzar/livebus/LiveZerobus/simulators
python sim_ui.py
```

Browser opens <http://localhost:7777>. Click **▶ Start all**.

**EXPECT**: 6 simulator rows each show **RUNNING** with growing line counts in the log view.

**FAIL**: any sim stays at `STOPPED` or its log shows `ConnectionError` → paste the bad sim's log.

---

## 3. Bronze gets fresh events

Wait 30s after starting sims, then run from your laptop:

```bash
python3 - <<'EOF'
import json, re, urllib.request
TOKEN = "PASTE_YOUR_PAT_HERE"
HOST = "https://adb-5347428297913551.11.azuredatabricks.net"
WH = "6a1fb3b32b00f1cd"

def sql(q):
    req = urllib.request.Request(f"{HOST}/api/2.0/sql/statements",
        data=json.dumps({"warehouse_id":WH,"statement":q,"wait_timeout":"30s"}).encode(),
        method="POST", headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    r = json.loads(re.sub(r"[\x00-\x1f\x7f]"," ",urllib.request.urlopen(req,timeout=60).read().decode()))
    return r.get("result",{}).get("data_array",[])

for t in ["bz_commodity_prices","bz_demand_events","bz_inventory_events","bz_supplier_quotes","bz_sap_purchase_orders","bz_iot_sensor_events"]:
    rows = sql(f"SELECT MAX(event_ts) AS latest, COUNT(*) AS n FROM livezerobus.procurement.{t}")
    print(f"  {t:30s} latest={rows[0][0]}  n={rows[0][1]}")
EOF
```

**EXPECT**: every `latest` is within the last 1–2 min.

**FAIL**: any table's `latest` is hours/days old → that sim isn't emitting. Reply with the table name + the timestamp shown.

---

## 4. Pipeline runs Bronze → Gold

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/2.0/pipelines/4cef05ca-ea6f-4217-af60-6b75a6b1a3f4" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); u=(d.get('latest_updates') or [{}])[0]; print(f\"  state={d.get('state')}  latest_update={u.get('state')} {u.get('creation_time')}\")"
```

**EXPECT**: `state=RUNNING` AND `latest_update=COMPLETED` (or in `RUNNING/INITIALIZING` if just kicked).

**FAIL**: `latest_update=FAILED` → grab the update ID and look at the pipeline UI for the failed step.

Also check Gold freshness:

```python
for t in ["gd_commodity_latest","gd_demand_1h","gd_inventory_snapshot","gd_supplier_leaderboard"]:
    rows = sql(f"SELECT MAX(event_ts) FROM livezerobus.procurement.{t}" if t!='gd_demand_1h' else f"SELECT MAX(hour_ts) FROM livezerobus.procurement.{t}")
    print(f"  {t}  latest={rows[0][0]}")
```

**EXPECT**: each `latest` within last ~10 min.

**FAIL**: > 15 min → pipeline isn't propagating to Gold. Paste output + pipeline UI screenshot.

---

## 5. Backend `/api/*` returns Gold rows

In the livezerobus tab in your browser (already authenticated via Databricks OAuth), open DevTools → Network tab. Hard refresh (Cmd+Shift+R).

Find each request below and check **Status: 200** + **Response: non-empty JSON array**:

- [ ] `GET /api/commodity/latest` — expect 5 rows (coco_coir, kwh, nutrient_pack, peat, rockwool)
- [ ] `GET /api/inventory` — expect ≥ 80 rows
- [ ] `GET /api/suppliers/leaderboard?top=3` — expect ≥ 10 rows
- [ ] `GET /api/demand/hourly?hours=24` — expect ≥ 5 rows
- [ ] `GET /api/recommendations?limit=25` — expect any rows (may be empty if pipeline ML step skipped)
- [ ] `GET /api/iot/sensors` — expect 42 rows (6 rooms × 7 sensors)
- [ ] `GET /api/summary` — expect object with `skus_below_reorder`, `buy_now_last_5m`, etc.

**FAIL**: any endpoint returns `[]` or 5xx → paste step number + endpoint + the actual response JSON.

---

## 6. Dashboard panels render

In livezerobus tab → **Dashboard**. Watch each panel for 30s with sims running:

| # | Panel | EXPECT | FAIL diagnostic |
|---|---|---|---|
| 6a | **Inventory** | Table with SKUs, room IDs, on-hand grams. Numbers change as inventory events arrive. | Empty table → check step 5 `/api/inventory`. Numbers don't change → pipeline not running. |
| 6b | **Suppliers** | Top 3 suppliers per SKU listed with prices. | Empty → step 5 `/api/suppliers/leaderboard`. |
| 6c | **Grow-Input prices (KPI cards)** | 5 cards: coco_coir, peat, rockwool, nutrient_pack, kwh — each shows `$X.XX` + `±X.XX%`. | All cards say "—" → step 5 `/api/commodity/latest`. |
| 6d | **Grow-Input prices (chart)** | Line chart with up to 60 samples. After 1 min should have ~20 points. Lines move ±a few % as prices update. | Single flat line at 0% → backend returning same price every poll; pipeline isn't refreshing Gold. Empty chart → no samples accumulated (give it 30s). |
| 6e | **Planting / Demand** | Bar/area chart over the last 24h. | Empty → step 5 `/api/demand/hourly`. |
| 6f | **Recommendations table** | Rows of SKU/decision/score. May be empty if ML didn't score yet. | If pipeline run completed but still empty → ML step may have skipped. Not a blocker for the demo. |
| 6g | **Summary bar (top)** | `Updated <timestamp>` and counters showing real numbers. | All counters say 0 → check step 5 `/api/summary`. |

---

## 7. SAP P2P tab

EXPECT 2 tables: Open PO Lines, Invoice Matching. PO supplier column shows real vendor names (joined from BDC LFA1 — falls back to LIFNR if BDC offline).

**FAIL**: empty tables → `gd_sap_open_po_lines` / `gd_sap_invoice_matching` in Gold; check the SAP simulator output in step 3.

---

## 8. SAP BDC tab

EXPECT green **CONNECTED · 15 tables in sapsofts.procurement** banner + Overview / Vendors / Purchase Orders sub-tabs all populated.

**FAIL** modes:
- **DISCONNECTED** → SAP_BDC_WAREHOUSE_ID env var missing on backend (check `backend/app.yaml`).
- **Connected but Vendors empty** → grant SP read access in UC: `GRANT USE CATALOG, BROWSE ON CATALOG sapsofts TO 'c4352007-…'; GRANT USE SCHEMA, SELECT ON SCHEMA sapsofts.procurement TO 'c4352007-…';`
- **Random red error banner** → click **Sync now** in Overview sub-tab.

---

## 9. Genie tab

EXPECT iframe of Databricks Genie space.

**FAIL** modes:
- **NOT CONFIGURED** → click ⚙ Configure → paste your space ID → Save.
- `refused to connect` → space ID wrong, or `/genie/rooms/{id}` instead of `/embed/genie/rooms/{id}`. Toggle the "Use full-app URL" button to compare.

---

## 10. Auto-recovery is healthy

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://livezerobus-5347428297913551.11.azure.databricksapps.com/api/admin/recovery/status \
  | python3 -m json.tool
```

**EXPECT**:
- `last_cycle_started` and `last_cycle_finished` are within the last 5 minutes
- `last_error` is `null`
- `actions` shows recent log entries

**FAIL**: `last_error` populated → paste it.

---

## Reporting back

Tell me **"step N fails: <what you saw>"** — I'll fix that specific layer instead of chasing the symptom.

If everything passes, the demo path is solid. The dashboard charts moving visibly depends on pipeline cadence (~every 5–10 min), so leave sims + sim_ui running for a few minutes to see commodity prices drift on the chart.
