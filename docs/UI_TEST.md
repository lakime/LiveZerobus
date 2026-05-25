# UI test — LiveZerobus app

Pure browser walk-through. No terminal, no DevTools, no SSH. Just click through every screen and check what you see.

For any failure, reply **"step N fails: <what I saw>"** — I'll fix it.

**App URL**: <https://livezerobus-5347428297913551.11.azure.databricksapps.com>

Before starting, make sure simulators are running (`python sim_ui.py` → <http://localhost:7777> → ▶ Start all). Then wait ~10 min for the pipeline to produce fresh data.

---

## 1. App loads

| # | Action | EXPECT |
|---|---|---|
| 1.1 | Open the app URL | Header `LiveZerobus — Vertical-Farm Seed Procurement`. Tab bar with 11 tabs |
| 1.2 | Tab bar visible | Dashboard, Emails, POs & Budget, Supplier Onboarding, Invoices, Agent runs, SAP P2P, SAP BDC, Genie · Talk to data, IoT Fields, Pipeline |
| 1.3 | Summary bar at top | Shows numbers (e.g. "3 SKUs below reorder", "$XX,XXX pending spend") + `Updated <time>` ticking every 3s |

---

## 2. Dashboard — every panel

Click **Dashboard**.

| # | Panel | EXPECT |
|---|---|---|
| 2.1 | **Inventory snapshot** | Table with SKU rows × room columns. On-hand grams shown. Numbers update every ~10 min as new events flow through |
| 2.2 | **Supplier leaderboard (ML-ranked)** | Table with top 3 suppliers per SKU. Columns: supplier name, score, price |
| 2.3 | **Grow-input prices — 5 KPI cards** | 5 cards: `coco_coir`, `peat`, `rockwool`, `nutrient_pack`, `kwh` — each shows `$X.XX` price + `±X.XX%` 24h change |
| 2.4 | **Grow-input prices — chart** | Line chart with last 30 min of price history visible immediately on page load. 5 colored lines (one per commodity). Y-axis is % change since first sample |
| 2.5 | **Planting / Demand chart** | Bar or area chart spanning last 24h with multiple SKU series |
| 2.6 | **Recommendations table** | Rows with SKU + BUY_NOW / HOLD decision + ML score (empty acceptable if pipeline ML step hasn't scored yet) |
| 2.7 | Click `↻ Refresh` (top-right) | All panels re-fetch; the "Updated" timestamp jumps |

---

## 3. Emails

Click **Emails**.

| # | Action | EXPECT |
|---|---|---|
| 3.1 | List view | Email threads listed with vendor name + subject + last-message time. Empty if no agent has run yet |
| 3.2 | Click a thread | Right pane shows the full message history (vendor request, agent reply, etc.) |
| 3.3 | Top of panel | Counter showing inbox / processed / pending counts |

---

## 4. POs & Budget

Click **POs & Budget**.

| # | Action | EXPECT |
|---|---|---|
| 4.1 | PO Drafts table | Rows of generated POs with supplier, SKU, qty, $ amount, status (DRAFT / APPROVED / etc.) |
| 4.2 | Budget panel (right side) | Monthly budget remaining bar + spend by category |
| 4.3 | Click a draft PO | Detail view showing reasoning text from the agent |

---

## 5. Supplier Onboarding

Click **Supplier Onboarding**.

| # | Action | EXPECT |
|---|---|---|
| 5.1 | Onboarding form | Fields: supplier name (dropdown with autocomplete), contact email, SKU specialties, certifications, etc. |
| 5.2 | Existing applications table | Below the form — list of submitted applications with status (NEW / SCREENING / APPROVED / REJECTED) |
| 5.3 | Submit a new test application | After submit, new row appears in the table within ~5s |

---

## 6. Invoices

Click **Invoices**.

| # | Action | EXPECT |
|---|---|---|
| 6.1 | Invoice reconciliation list | Rows with PO number, invoiced $, expected $, variance % |
| 6.2 | Status badges | MATCHED (green) / VARIANCE (yellow) / BLOCKED (red) |
| 6.3 | High-variance row | Highlighted with reason text (e.g. "Quantity mismatch") |

---

## 7. Agent runs

Click **Agent runs**.

| # | Action | EXPECT |
|---|---|---|
| 7.1 | Run history list | One row per agent tick: timestamp, agent name, status (OK / ERROR), duration |
| 7.2 | Click a row | Detail panel with the agent's input → reasoning → output |
| 7.3 | Five agent buttons | Each tab/section also has a "▶ Run <agent>" button — click one, a new row should appear within ~5s |

---

## 8. SAP P2P

Click **SAP P2P**.

| # | Action | EXPECT |
|---|---|---|
| 8.1 | **Open PO Lines** table | Rows with PO number, supplier name (real name, not just code), SKU, qty, value, delivery date, status |
| 8.2 | Filter dropdown | Select `OPEN` → table filters; select `FULLY_RECEIVED` → different rows |
| 8.3 | **3-way Invoice Match** table | Rows showing PO × GR × Invoice match status |
| 8.4 | VARIANCE rows | Red highlight, variance $ amount shown |

---

## 9. SAP BDC

Click **SAP BDC**.

| # | Action | EXPECT |
|---|---|---|
| 9.1 | Top banner | Green **CONNECTED** + "15 tables in sapsofts.procurement" |
| 9.2 | **Overview** sub-tab | 15 SAP table badges (EKKO, EKPO, LFA1, MARA, T001, …). Click `↻ Sync now` → progress bar advances |
| 9.3 | **Vendors (LFA1)** sub-tab | 20 vendor rows with LIFNR, NAME1, LAND1, ORT01, STRAS, TELF1 |
| 9.4 | Search the vendors | Type a name fragment → filters the table |
| 9.5 | **Purchase Orders (EKKO+EKPO)** sub-tab | Joined PO header + line items + vendor name. Multiple rows per PO (one per line item) |
| 9.6 | Click a column header | Sortable / visual feedback |

---

## 10. Genie · Talk to data

Click **Genie · Talk to data**.

| # | Action | EXPECT |
|---|---|---|
| 10.1 | If never configured | Setup form. Paste your Genie space URL (from Databricks → Genie → your space → copy URL) → Save |
| 10.2 | After config | Iframe loads with the Databricks Genie chat UI |
| 10.3 | In the Genie chat box | Type "show me top 5 vendors by total PO value" → wait 10-30s → answer with chart |
| 10.4 | Click **⚙ Configure** (top-right) | Config form reopens; you can switch to a different space ID or clear local override |

---

## 11. IoT Fields

Click **IoT Fields**.

| # | Action | EXPECT |
|---|---|---|
| 11.1 | Farm overview header | Aggregate values: 6 rooms, avg temp, alert count |
| 11.2 | 6 room cards | One card per grow room (ROOM-A through ROOM-COLD) |
| 11.3 | Per room | 7 sensor gauges: Temperature, Humidity, Soil moisture, Light, CO₂, pH, EC |
| 11.4 | Each gauge | Arc + numeric value + colored status (green NOMINAL / yellow CAUTION / red ALERT) |
| 11.5 | Sparkline under each gauge | Last ~10 readings as a tiny line trend |
| 11.6 | Wait 30s | At least one sensor's gauge needle moves slightly (sims drift values) |

---

## 12. Pipeline

Click **Pipeline**.

| # | Action | EXPECT |
|---|---|---|
| 12.1 | Pipeline state card | Shows `RUNNING` or `IDLE` |
| 12.2 | Last update info | Timestamp + state + duration of last pipeline run |
| 12.3 | Click `▶ Run now` | New update kicks off; status changes to WAITING_FOR_RESOURCES → INITIALIZING → RUNNING → COMPLETED (5-10 min total) |
| 12.4 | After completion | Dashboard panels show fresher data |

---

## Done

If every step above worked, the demo path is solid. Leave the simulators running for the duration of the demo so data keeps flowing.

If any step fails, reply with:

```
step N.M fails: <what I saw>
```

and I'll fix that specific layer.

For deeper diagnosis (curl, DevTools), see [`docs/E2E_TEST.md`](E2E_TEST.md).
