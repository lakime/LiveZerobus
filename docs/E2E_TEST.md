# End-to-end test scenario — LiveZerobus

Comprehensive walk-through of every feature. Each step has **EXPECT** and **FAIL** so you can run through systematically and report "step N.M fails: <what I saw>".

URLs:

- **livezerobus app**: <https://livezerobus-5347428297913551.11.azure.databricksapps.com>
- **SAP BDC mock (external VPS)**: <https://photop.uzar.pl>
- **Databricks workspace**: <https://adb-5347428297913551.11.azuredatabricks.net>
- **Lakeflow pipeline**: <https://adb-5347428297913551.11.azuredatabricks.net/pipelines/4cef05ca-ea6f-4217-af60-6b75a6b1a3f4>
- **Genie spaces**: <https://adb-5347428297913551.11.azuredatabricks.net/genie>
- **GitHub Actions**: <https://github.com/lakime/LiveZerobus/actions>

Before starting, open **DevTools** (F12) → **Network** tab in the livezerobus tab, filter by `/api/`. We use it throughout.

---

## §1. Deployment + boot

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 1.1 | Latest CI run on `main` at <https://github.com/lakime/LiveZerobus/actions/workflows/deploy.yml> | ✅ green; finished within the last 24h | Red run → paste the failing step from the log |
| 1.2 | Visit `<app>/healthz` | `{"ok":true}` | "App Not Available" or 5xx → app crashed; UI → Compute → Apps → livezerobus → Logs |
| 1.3 | Visit `<app>/api/admin/recovery/status` | JSON with `enabled:true`, recent `last_cycle_started`, `last_error:null` | `last_error` populated → paste it |
| 1.4 | Visit `<app>/api/admin/recovery/freshness` | `{"gold":{"latest":"<recent ts>"}}` — within ~10 min | error or old timestamp → see §3 |

---

## §2. Simulators

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 2.1 | Start sim UI: `cd simulators && python sim_ui.py`. Browser opens <http://localhost:7777> | All 6 sims listed | UI doesn't load → paste console error |
| 2.2 | Click **▶ Start all** | All 6 rows turn **RUNNING** within ~5s | Any stuck at STOPPED → paste that sim's log |
| 2.3 | Watch the log pane for `commodity_simulator` for 10s | 1 new line every 1-2s, no `ConnectionError` | Silent or red → that sim isn't emitting; paste log |
| 2.4 | The "Events" counter shows `0` | **This is a known UI bug — ignore it.** The real data check is §3 | n/a |

---

## §3. Data pipeline (Bronze → Gold)

Open the **Pipeline tab** in the livezerobus app.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 3.1 | Pipeline panel shows state | `RUNNING` (it may go through INITIALIZING → SETTING_UP_TABLES → RUNNING on cold start, up to 10 min) | `FAILED` → click into Databricks Pipeline UI, screenshot the failed stage |
| 3.2 | Last update timestamp shown | within the last 15 min | older → §3.3 |
| 3.3 | Click **▶ Run now** in Pipeline panel | Status changes to "WAITING_FOR_RESOURCES" → eventually "RUNNING" | Permission denied → SP doesn't have CAN_RUN; reply with that |
| 3.4 | Wait 5-10 min after pipeline COMPLETED | `<app>/api/admin/recovery/freshness` → `gold.latest` is within last few min | older → pipeline ran but didn't update Gold; tell me |

---

## §4. Backend API endpoints

In livezerobus tab, with DevTools Network open. Hard refresh (Cmd+Shift+R) so all `/api/*` calls fire.

For each endpoint, click it in Network → **Response** tab. EXPECT a non-empty JSON array (or object for `/summary`).

| # | Endpoint | EXPECT (sample) | FAIL → tell me |
|---|---|---|---|
| 4.1 | `/api/commodity/latest` | 5 rows: `coco_coir`, `kwh`, `nutrient_pack`, `peat`, `rockwool` | `[]` → tell me; check `/api/admin/recovery/freshness` |
| 4.2 | `/api/commodity/history?minutes=30` | 30-150 rows of historical price ticks | `[]` → Bronze table has no events; sim isn't writing |
| 4.3 | `/api/inventory` | ≥80 rows with `sku`, `room_id`, `on_hand_g` | `[]` → Gold MV stale |
| 4.4 | `/api/suppliers/leaderboard?top=3` | ≥10 rows with `supplier_name`, `score`, `rank` ≤3 | `[]` → tell me |
| 4.5 | `/api/demand/hourly?hours=24` | ≥5 rows with `sku`, `hour_ts`, `trays` | `[]` → tell me |
| 4.6 | `/api/recommendations?limit=25` | rows with `sku`, `decision`, `ml_score`. Empty OK if pipeline ML step didn't run | n/a if empty |
| 4.7 | `/api/iot/sensors` | 42 rows (6 rooms × 7 sensors) | `[]` → IoT sim isn't emitting |
| 4.8 | `/api/sap/po-lines` | rows with `po_number`, `po_status`, etc. Empty OK if SAP sim hasn't completed a cycle yet | n/a if empty |
| 4.9 | `/api/sap/invoice-matching` | rows; empty OK early | n/a if empty |
| 4.10 | `/api/summary` | non-zero `skus_below_reorder`, `buy_now_last_5m`, `last_market_tick` populated | all zero / null → tell me which fields |
| 4.11 | `/api/sap-bdc/info` | `{"connected":true,"table_count":15,...}` | `connected:false` → see §6 |
| 4.12 | `/api/genie/info` | `{"configured":true,"url":"https://.../embed/genie/rooms/<id>"}` OR `{"configured":false,...}` if no env var | n/a — see §7 |

---

## §5. Dashboard tab

Click **Dashboard** in the top tab bar. Watch each panel for ~30 seconds.

| # | Panel | EXPECT | FAIL → tell me |
|---|---|---|---|
| 5.1 | **Summary bar** at top | Non-zero counters; "Updated <time>" ticks every 3s | All zeros → §4.10 failed |
| 5.2 | **Inventory** | Table with SKU rows, on-hand grams numeric. Numbers change every 30s | Empty → §4.3 |
| 5.3 | **Supplier Leaderboard** | Top 3 suppliers per SKU with scores | "No seed quotes yet" → §4.4 |
| 5.4 | **Grow-Input Prices KPI cards** (5) | Each shows `$X.XX` price + `±X.XX%` 24h change | "—" → §4.1 |
| 5.5 | **Grow-Input Prices chart** | On first load → 30 min of history visible (preloaded). Lines drift up/down ±a few % | Blank → §4.2 |
| 5.6 | **Planting / Demand chart** | Bar/area chart over last 24h with multiple SKUs | "Waiting for planting data…" → §4.5 |
| 5.7 | **Recommendations** | Table with SKU/decision/score | Empty OK if ML step skipped |
| 5.8 | Hit `↻ Refresh` button at top | All panels re-fetch (Network tab shows new requests) | No re-fetch → reload bug; tell me |

---

## §6. SAP BDC tab

Click **SAP BDC** in the tab bar.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 6.1 | Top of panel | Green **CONNECTED** badge + "15 tables in sapsofts.procurement" | Red **DISCONNECTED** → §6.6 |
| 6.2 | Click **Overview** sub-tab | 15 SAP table codes as badges (EKKO, LFA1, MARA, ...) | Empty list → catalog not synced; click **Sync now** |
| 6.3 | Click **Sync now** button | Progress bar advances 0→100% as it warms each table | Hangs at one table → reply with which |
| 6.4 | Click **Vendors (LFA1)** sub-tab | Searchable table with 20 vendor rows: LIFNR, NAME1, LAND1, ORT01... | Empty / red error → §6.6 |
| 6.5 | Search "Germany" or "DE" in the Vendors search box | Filters down to matching rows | No filtering → tell me |
| 6.6 | If §6.1 says DISCONNECTED | Backend can't reach `sapsofts.procurement.*` via SQL warehouse | Either `SAP_BDC_WAREHOUSE_ID` env missing (check `backend/app.yaml`), or SP lacks UC grants on `sapsofts` |
| 6.7 | Click **Purchase Orders (EKKO+EKPO)** sub-tab | Joined PO header + line items + vendor name | Empty / red error → click Sync now in Overview |
| 6.8 | Open the BDC mock UI directly: <https://photop.uzar.pl> | SAP-styled interface loads (blue title bar, t-codes, status bar at bottom) | Won't load → SSH to VPS, `docker compose ps` |
| 6.9 | On photop.uzar.pl → **Tables** tab | Grid of 15 SAP table cards with row counts | Empty grid → sim/data missing; `docker compose logs sap-bdc` |
| 6.10 | On photop.uzar.pl → **Share** tab | 15 tables listed with toggle checkboxes — all ON | Some OFF → toggle ON or click "Enable all" |
| 6.11 | On photop.uzar.pl → **Connect** tab → **Download profile.json** | File downloads with `bearerToken` field set | Empty token / 401 → check `SAP_BDC_TOKEN` env on VPS |

---

## §7. Genie tab

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 7.1 | Click **Genie · Talk to data** in the tab bar | Either: iframe loads with a Genie chat UI **OR**: setup form ("NOT CONFIGURED" + config form) | Blank white area → see §7.5 |
| 7.2 | If you see the iframe | Type "show me top 5 vendors by PO value" in the chat → wait 10-20s for response | "Refused to connect" → §7.5 |
| 7.3 | If config form | Paste your Genie space URL (`https://adb-…/genie/rooms/01f…`) | n/a |
| 7.4 | Click **Save** → iframe loads | Genie chat appears with shared catalogs accessible | iframe still blank → click **⚙ Configure** → toggle "Use full-app URL" |
| 7.5 | "Refused to connect" | The URL should be `/embed/genie/rooms/<id>`, not `/genie/rooms/<id>`. Re-save with the correct URL. The /embed/ surface allows iframes, the standard URL doesn't | If still broken → reply with the full URL the iframe is hitting (browser DevTools → Network → click the iframe request → Request URL) |

---

## §8. SAP P2P tab

Click **SAP P2P** in the tab bar.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 8.1 | Two tables visible: **Open PO Lines** + **3-way Invoice Match** | Each with rows from the SAP simulator | Empty → SAP sim hasn't run a complete P2P cycle yet (PO→GR→Invoice takes ~45s per cycle) |
| 8.2 | Open PO Lines: supplier name column | Shows real vendor name (joined from BDC LFA1) OR raw LIFNR as fallback | Empty supplier → backend `/api/sap-bdc/vendor-lookup` not responding |
| 8.3 | Filter by status: select `OPEN` | Rows filter | Filter does nothing → §4.8 |
| 8.4 | 3-way Invoice Match: VARIANCE rows | Highlighted in red with non-zero variance | Empty → SAP sim hasn't reached invoice stage |

---

## §9. Agent tabs (Emails / POs & Budget / Onboarding / Invoices / Agent runs)

These all read/write Lakebase Postgres native agent state.

| # | Tab | EXPECT | FAIL → tell me |
|---|---|---|---|
| 9.1 | **Emails** | List of threads, each clickable to see messages | Empty → no agent runs yet OR Lakebase agent-state tables missing |
| 9.2 | **POs & Budget** | PO drafts + budget panel with remaining $ | "po_drafts does not exist" → run `python scripts/apply_lakebase_schema.py` |
| 9.3 | **Supplier Onboarding** | Form to apply + list of applications | Empty form OK; submit one → row should appear |
| 9.4 | **Invoices** | Reconciliation rows | Empty OK if no SAP cycles completed |
| 9.5 | **Agent runs** | History of agent tick runs | Empty → no agents have run yet; trigger via the buttons in agent-specific tabs |

---

## §10. IoT tab

Click **IoT Fields** in the tab bar.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 10.1 | Farm overview header | Aggregate values (e.g. avg temp, alert count) | Empty → §4.7 |
| 10.2 | 6 room cards | Each room shows 7 sensor gauges (temp, humidity, soil moisture, light, CO₂, pH, EC) | Some sensors blank → IoT sim fault injection; should self-recover in ~5 min |
| 10.3 | Sparklines on each gauge | Last 10-20 readings as a small line trend | Flat / missing → sim writing too slowly OR Gold MV stale |
| 10.4 | Status badges | NOMINAL (green) / CAUTION (yellow) / ALERT (red) based on thresholds | All NOMINAL is normal if sim has been running long enough for faults to inject + recover |

---

## §11. Pipeline tab

Click **Pipeline** in the tab bar.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 11.1 | Pipeline state badge | `RUNNING` or `IDLE` | `FAILED` → §3.1 |
| 11.2 | Last update info | Timestamp + state + duration | Stale → §3 |
| 11.3 | Click **▶ Run now** | New update kicks off (status changes) | Permission denied → SP CAN_RUN missing |
| 11.4 | Watch the status update | Cycles through INITIALIZING → SETTING_UP_TABLES → RUNNING → COMPLETED | Stuck on any stage > 15 min → reply with which |

---

## §12. Auto-recovery

The backend self-heal thread should be doing its job invisibly.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 12.1 | `<app>/api/admin/recovery/status` | `last_cycle_started` within last 5 min | older → recovery thread not running |
| 12.2 | `actions[]` array | Contains messages like "Gold MV is fresh" or "kicked Lakeflow pipeline update" every 5 min | Sparse / empty → restart app |
| 12.3 | `last_error` | `null` (the harmless ResourceConflict was suppressed) | non-null → paste it |
| 12.4 | Force a cycle: POST `<app>/api/admin/recovery/run` | `{"started":true}` | 5xx → reply |

---

## §13. SAP BDC service health (the external VPS)

Open <https://photop.uzar.pl> directly (NOT via livezerobus).

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 13.1 | Page loads SAP-styled GUI | Blue title bar, "BDC/100" system info, 4 tabs at top, status bar at bottom | Won't load → SSH to VPS, `docker compose ps` |
| 13.2 | `<photop>/healthz` | `{"ok":true}` | Anything else → §6.8 |
| 13.3 | `<photop>/api/info` | `{"tables_ready":15,"tables_total":15,"tables_shared":15}` | `tables_shared` < 15 → toggle "Enable all" in Share tab |
| 13.4 | `<photop>/api/profile.json` | Profile JSON with token + endpoint | Empty → broken SAP_BDC_TOKEN env |
| 13.5 | Click **Share** tab → all 15 checkboxes ON | All ON, "15 / 15 tables shared" badge | Some OFF → toggle ON |
| 13.6 | From Databricks SQL editor: `SELECT count(*) FROM sapsofts.procurement.ekko` | Returns 150 | `RESOURCE_DOES_NOT_EXIST` → run `python scripts/refresh_sapsofts_catalog.py` |

---

## §14. Genie space configuration (one-time)

Only needed once.

| # | Action | EXPECT | FAIL → tell me |
|---|---|---|---|
| 14.1 | Open <https://adb-…databricks.net/genie/spaces> | Existing Genie spaces listed | Empty → create one: click **+ New** |
| 14.2 | Create space "LiveZerobus — Talk to data", warehouse `6a1fb3b32b00f1cd` | Wizard succeeds | Permission denied → CAN_USE on warehouse missing |
| 14.3 | Add tables: `livezerobus.procurement.gd_*` + `sapsofts.procurement.*` | Tables listed in space config | Catalog not visible → §6.6 |
| 14.4 | Copy the space_id from the URL | URL has format `/genie/rooms/01f…` — copy that hex string | n/a |
| 14.5 | In livezerobus Genie tab → ⚙ Configure → paste URL → Save | Iframe loads the space | "Refused to connect" → §7.5 |

---

## Reporting back

For any failure: **"§X.Y fails: <what I saw>"** — that pinpoints the exact layer.

If everything passes:

1. Leave sims + sim_ui running for ~15 min so the pipeline runs a couple times
2. Dashboard charts will show movement (commodity price drift, demand bars filling in)
3. Try a Genie question like "which supplier is cheapest for SEED-LETT-RED-01"
4. Demo path is solid.

## Quick recovery commands (if needed)

```bash
# All-purpose: refresh the sapsofts catalog with retries
DATABRICKS_TOKEN=<pat> python scripts/refresh_sapsofts_catalog.py

# Apply Lakebase agent-state schema (one-time after a fresh Lakebase deploy)
python scripts/apply_lakebase_schema.py

# Force livezerobus to redeploy
gh workflow run deploy.yml --ref main
```
