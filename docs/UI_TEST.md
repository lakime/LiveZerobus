# UI walk-through — step by step

Open <https://livezerobus-5347428297913551.11.azure.databricksapps.com>.

Do each step in order. After every step there's a 👁 line showing what should be on screen.

If a step doesn't match, reply **"step N: <what I see instead>"**.

---

## A. Open the app

1. Go to the URL above.
   👁 You see a header `LiveZerobus — Vertical-Farm Seed Procurement` and a row of tabs.

2. Look at the very top, just under the header.
   👁 A bar with numbers, e.g. `3 SKUs below reorder · $12,000 pending spend · Updated 14:23:11`.

3. Wait 4 seconds.
   👁 The `Updated` time on the right ticks forward.

---

## B. Refresh the data (Pipeline)

4. Click the **Pipeline** tab (last tab on the right).
   👁 A card shows the pipeline name and a state, e.g. `RUNNING` or `IDLE`.

5. Look for a `▶ Run now` button on that card.
   👁 The button is visible.

6. Click `▶ Run now`.
   👁 State changes to `WAITING_FOR_RESOURCES` (or `RUNNING` if a cluster is already warm).

7. (Optional, takes 5–10 min) Wait until state changes to `COMPLETED`.
   👁 The "Last update" timestamp on the card jumps to "just now".

---

## C. Dashboard — read each panel

8. Click the **Dashboard** tab.
   👁 Several panels appear on one page.

9. Find the **Inventory snapshot** panel.
   👁 A table with rows like `SEED-BAS-GEN-01 · ROOM-A · 7600 g`.

10. Find the **Supplier leaderboard** panel.
    👁 A table with 3 supplier rows per SKU. Columns include supplier name, price, score.

11. Find the **Grow-input prices** section, look at the top of it.
    👁 5 small cards in a row: `coco_coir`, `peat`, `rockwool`, `nutrient_pack`, `kwh`. Each shows a $-price and a green/red % below it.

12. Look at the **chart below those 5 cards**.
    👁 A line chart with 5 colored lines. The lines span the width of the chart.
    👁 Y-axis shows percentage values like `+1.2%`, `-0.8%`.
    👁 X-axis shows times like `14:00`, `14:05`, `14:10`.

13. Find the **Planting / Demand chart** panel.
    👁 A bar or area chart with multiple SKU series along the bottom (last 24 hours).

14. Find the **Recommendations** table.
    👁 Rows with SKU + a decision word like `BUY_NOW` or `HOLD` + a score. (Empty is OK if pipeline is still warming up.)

15. Click the `↻ Refresh` button at the top-right.
    👁 Panels re-fetch. The `Updated` timestamp at the very top jumps.

---

## D. Emails — see what agents talked about

16. Click the **Emails** tab.
    👁 A list of email threads on the left, each with vendor name + subject.

17. Click the first thread.
    👁 On the right, the full message exchange appears (vendor request, agent reply, etc.).

18. Scroll the message list.
    👁 You can see multiple messages stacked vertically.

---

## E. POs & Budget — trigger an agent

19. Click the **POs & Budget** tab.
    👁 Left side: a table of PO drafts. Right side: a budget panel with $ remaining.

20. Look at the table — any row at all is fine.
    👁 At least one PO row visible with supplier, SKU, $ amount, status badge (`DRAFT` / `APPROVED` / `BLOCKED`).

21. Look for a `▶ Run negotiator` (or `▶ Run PO drafter`) button.
    👁 The button is visible somewhere on the panel.

22. Click it.
    👁 A status message appears (e.g. "Negotiator running…" or "PO drafted: PO-12345").
    👁 Within ~10 seconds, a new row appears in the PO table.

23. Click the new PO row.
    👁 Detail expands showing the agent's reasoning text.

---

## F. Supplier onboarding — submit a fake supplier

24. Click the **Supplier Onboarding** tab.
    👁 A form with fields like supplier name, contact email, certifications.

25. In the supplier name dropdown, start typing "Test"
    👁 Autocomplete options appear OR field accepts new text.

26. Fill in contact email, e.g. `test@example.com`.
    👁 Field accepts the value.

27. Click **Submit**.
    👁 The form clears OR a confirmation appears.
    👁 In the applications table below, a new row appears with status `NEW`.

28. (Optional) Look for a `▶ Run onboarding agent` button → click it.
    👁 Within ~10 s, the new row's status changes to `SCREENING` then `APPROVED`/`REJECTED`.

---

## G. Invoices

29. Click the **Invoices** tab.
    👁 A table of invoice rows with PO #, $ invoiced, $ expected, variance %.

30. Look for a row with a red background or `VARIANCE` badge.
    👁 At least one row stands out as variance (if SAP sim has run long enough).

31. (Optional) Click `▶ Run reconciler` button.
    👁 Within ~10 s, a row's status changes.

---

## H. Agent runs

32. Click the **Agent runs** tab.
    👁 Table of past runs: timestamp, agent name, status, duration.

33. Click any row.
    👁 Detail panel shows input → reasoning → output of that run.

---

## I. SAP P2P

34. Click the **SAP P2P** tab.
    👁 Two tables: Open PO Lines (top) + 3-way Invoice Match (bottom).

35. In Open PO Lines, find the status filter dropdown.
    👁 Dropdown with options like ALL, OPEN, PARTIALLY_RECEIVED, FULLY_RECEIVED, CANCELLED.

36. Select `OPEN`.
    👁 Table filters to only OPEN POs.

37. Look at the Supplier column.
    👁 Real names appear (e.g. "Acme Seeds Ltd"), not just numeric codes.
    (If you only see codes like `0000100013`, that's the BDC join failed — note it.)

38. Scroll to the 3-way Invoice Match table.
    👁 Rows with PO/GR/Invoice numbers + match status badges (MATCHED / VARIANCE / PENDING_GR / NO_PO).

---

## J. SAP BDC — external Delta Sharing data

39. Click the **SAP BDC** tab.
    👁 At the very top: a green `CONNECTED` badge + "15 tables in sapsofts.procurement".

40. Click the **Overview** sub-tab inside this panel.
    👁 A grid of 15 small badges: EKKO, EKPO, LFA1, MARA, T001, T001W, T023, T024, EKBE, EKET, EBAN, MKPF, MSEG, RBKP, BKPF.

41. Look for a `↻ Sync now` button.
    👁 The button is visible above the badges.

42. Click `↻ Sync now`.
    👁 A progress bar appears and advances 0% → 100% (takes ~30-60 s).
    👁 At 100%, all 15 badges are green.

43. Click the **Vendors (LFA1)** sub-tab.
    👁 A search box at the top + a table with 20 rows: LIFNR, name, country, city, address, phone.

44. In the search box, type `de` (German vendors).
    👁 Table filters to rows where country/city contains "de".

45. Clear the search.
    👁 All 20 rows return.

46. Click the **Purchase Orders (EKKO+EKPO)** sub-tab.
    👁 A table of joined PO header + line items + vendor name. Many rows.

---

## K. Genie — talk to your data

47. Click the **Genie · Talk to data** tab.
    👁 Either:
       (a) An iframe loads with a Databricks Genie chat interface, OR
       (b) A setup form saying "NOT CONFIGURED".

48. If (b) setup form:
    - In Databricks workspace, go to Genie in sidebar → open your space → copy the URL from the browser address bar (looks like `https://adb-…/genie/rooms/01f…`).
    - Paste into the input field in the form.
    - Click **Save**.
    👁 The iframe loads with Genie chat.

49. In the Genie chat box, type: `which 5 suppliers have the highest total PO value?`
    👁 Genie thinks for 5-20 seconds, then returns a chart + table answer.

50. Type: `show grow-input prices over the last hour`
    👁 Genie returns a line chart.

---

## L. IoT Fields

51. Click the **IoT Fields** tab.
    👁 A header strip with farm-wide aggregates (avg temp, alerts).

52. Below it, 6 room cards.
    👁 Each card titled `ROOM-A`, `ROOM-B`, `ROOM-C`, `ROOM-D`, `ROOM-E`, `ROOM-COLD`.

53. Pick any one card and look at it closely.
    👁 7 small arc-shaped gauges inside: Temp, Humidity, Soil moisture, Light, CO₂, pH, EC.

54. Each gauge shows a current value + a colored status.
    👁 Most should be green (NOMINAL). Possibly some yellow (CAUTION) or red (ALERT) if sim has injected a fault.

55. Look under each gauge.
    👁 A tiny sparkline showing the last 10-ish readings.

56. Wait 30 seconds without doing anything.
    👁 Some gauge needles or sparklines change (sims drift values).

---

## Done

If every step matched, the app is fully working. Demo away.

For any mismatch, reply:

```
step N: <what I see>
```

I'll fix that specific thing.
