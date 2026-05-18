#!/usr/bin/env python3
"""Pre-demo health check + warm-up for livezerobus.

Run this 30 min before the demo. It:
  1. Checks all 4 data layers (Bronze, Silver, Gold, Lakebase) for freshness
  2. Triggers the Lakeflow pipeline if Gold is stale
  3. Resets any synced table that's stuck on stale data
  4. Warms up the SAP BDC UC catalog (DROP/CREATE + SHOW TABLES + DESCRIBE all 15)
  5. Reports red/green for every component

Output is colorized for quick visual scan during demo prep.

Usage:
  python scripts/pre_demo_warmup.py
  python scripts/pre_demo_warmup.py --fix    # actively repair anything stale
  python scripts/pre_demo_warmup.py --quick  # skip the SAP BDC warm-up
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

from databricks.sdk import WorkspaceClient

HOST = os.environ.get("DATABRICKS_HOST", "https://adb-5347428297913551.11.azuredatabricks.net").rstrip("/")
WH = os.environ.get("SAP_BDC_WAREHOUSE_ID", "6a1fb3b32b00f1cd")
MAIN_PIPELINE = "4cef05ca-ea6f-4217-af60-6b75a6b1a3f4"
GREEN = "\033[32m"; RED = "\033[31m"; YELLOW = "\033[33m"; RESET = "\033[0m"; BOLD = "\033[1m"


def green(s: str) -> str: return f"{GREEN}{s}{RESET}"
def red(s: str) -> str: return f"{RED}{s}{RESET}"
def yellow(s: str) -> str: return f"{YELLOW}{s}{RESET}"
def bold(s: str) -> str: return f"{BOLD}{s}{RESET}"


def warehouse_query(token: str, sql: str) -> list[list]:
    req = urllib.request.Request(
        f"{HOST}/api/2.0/sql/statements",
        data=json.dumps({"warehouse_id": WH, "statement": sql, "wait_timeout": "30s"}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    raw = urllib.request.urlopen(req, timeout=60).read().decode()
    # Strip control chars from UC's deliberate-fail messages
    import re
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", raw)
    r = json.loads(clean)
    if r.get("status", {}).get("state") != "SUCCEEDED":
        err = r.get("status", {}).get("error", {}).get("message", "")[:200]
        raise RuntimeError(f"SQL failed: {err}")
    return r.get("result", {}).get("data_array", [])


def check_freshness(token: str, max_age_min: int = 30) -> dict[str, dict]:
    """Return status of each layer."""
    sql = """
      SELECT 'bz_commodity' AS k, max(event_ts) FROM livezerobus.procurement.bz_commodity_prices
      UNION ALL SELECT 'gd_commodity', max(event_ts) FROM livezerobus.procurement.gd_commodity_latest
      UNION ALL SELECT 'gd_demand',    max(hour_ts)  FROM livezerobus.procurement.gd_demand_1h
      UNION ALL SELECT 'gd_recs',      max(created_ts) FROM livezerobus.procurement.gd_procurement_recommendations
    """
    out = {}
    now = dt.datetime.now(dt.timezone.utc)
    for k, ts_str in warehouse_query(token, sql):
        ts = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
        age_min = (now - ts).total_seconds() / 60 if ts else None
        out[k] = {
            "ts": ts,
            "age_min": age_min,
            "fresh": age_min is not None and age_min <= max_age_min,
        }
    return out


def check_lakebase_freshness(w: WorkspaceClient, pg_user: str, max_age_min: int = 30) -> dict[str, dict]:
    import psycopg
    cred = w.postgres.generate_database_credential(
        endpoint="projects/myzerobus/branches/production/endpoints/primary"
    )
    out = {}
    now = dt.datetime.now(dt.timezone.utc)
    with psycopg.connect(
        host="ep-frosty-flower-e2o5hjfp.database.westeurope.azuredatabricks.net",
        port=5432, dbname="databricks_postgres",
        user=pg_user, password=cred.token, sslmode="require",
    ) as conn, conn.cursor() as cur:
        for t, ts_col in [
            ("commodity_prices_latest", "event_ts"),
            ("demand_1h", "hour_ts"),
            ("inventory_snapshot", "last_event_ts"),
            ("iot_sensor_latest", "event_ts"),
            ("procurement_recommendations", "created_ts"),
        ]:
            try:
                cur.execute(f"SELECT count(*), max({ts_col}) FROM procurement.{t}")
                count, ts = cur.fetchone()
                age_min = (now - ts).total_seconds() / 60 if ts else None
                out[t] = {
                    "count": count, "ts": ts, "age_min": age_min,
                    "fresh": age_min is not None and age_min <= max_age_min,
                }
            except Exception as e:
                out[t] = {"error": str(e)[:100], "fresh": False}
    return out


def trigger_pipeline_if_stale(w: WorkspaceClient, stale: bool) -> None:
    p = w.pipelines.get(pipeline_id=MAIN_PIPELINE)
    if p.state == "RUNNING":
        print(f"  {yellow('↳')} Lakeflow pipeline already RUNNING — letting it finish")
        return
    if not stale:
        return
    u = w.pipelines.start_update(pipeline_id=MAIN_PIPELINE, full_refresh=False)
    print(f"  {green('▶')} Triggered Lakeflow pipeline update {u.update_id[:8]}")
    print(f"     Cold-start takes ~7-10 min if pipeline hasn't run today.")


def warm_sap_bdc_catalog(token: str) -> bool:
    """DROP + CREATE + SHOW TABLES + DESCRIBE for SAP BDC catalog."""
    tables = ["bkpf", "eban", "ekbe", "eket", "ekko", "ekpo", "lfa1",
              "mara", "mkpf", "mseg", "rbkp", "t001", "t001w", "t023", "t024"]
    try:
        warehouse_query(token, "DROP CATALOG IF EXISTS sapsofts CASCADE")
        warehouse_query(token, "CREATE CATALOG sapsofts USING SHARE `sapsofts`.`sap-procurement`")
        warehouse_query(token, "SHOW SCHEMAS IN sapsofts")
        warehouse_query(token, "SHOW TABLES IN sapsofts.procurement")
        ok = 0
        for t in tables:
            for retry in range(5):
                try:
                    warehouse_query(token, f"DESCRIBE TABLE sapsofts.procurement.{t}")
                    ok += 1
                    break
                except Exception:
                    time.sleep(2)
        return ok == len(tables)
    except Exception as e:
        print(f"  {red('✗')} SAP BDC warm-up failed: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="Repair stale state (trigger pipeline, reset synced tables)")
    ap.add_argument("--quick", action="store_true", help="Skip SAP BDC catalog warm-up (slow)")
    ap.add_argument("--pg-user", default=os.environ.get("PGUSER", "puzar@devsoftserveinc.com"))
    args = ap.parse_args()

    w = WorkspaceClient()
    token = os.environ.get("DATABRICKS_TOKEN")
    if not token:
        token = w.config.authenticate().get("Authorization", "").removeprefix("Bearer ")

    print(bold("=== LiveZerobus pre-demo health check ==="))
    print()

    # --- Layer 1: simulators / Bronze ---
    print(bold("1. Bronze (simulators emitting?)"))
    freshness = check_freshness(token, max_age_min=10)
    bz = freshness["bz_commodity"]
    status = green("✓ FRESH") if bz["fresh"] else red("✗ STALE")
    print(f"  {status} bz_commodity_prices  age={bz['age_min']:.1f} min" if bz['age_min'] else f"  {red('✗ NO DATA')}")
    if not bz["fresh"]:
        print(f"  {yellow('→')} Start simulators: cd simulators && .venv/bin/python sim_ui.py → Start all")
        return 1

    # --- Layer 2: Gold ---
    print(bold("\n2. Gold (Lakeflow pipeline processing Bronze?)"))
    gold_stale = False
    for k in ["gd_commodity", "gd_demand", "gd_recs"]:
        f = freshness[k]
        if f["fresh"]:
            print(f"  {green('✓ FRESH')} {k}  age={f['age_min']:.1f} min")
        else:
            print(f"  {red('✗ STALE')} {k}  age={f['age_min']:.0f} min" if f['age_min'] else f"  {red('✗ NO DATA')} {k}")
            gold_stale = True

    if gold_stale and args.fix:
        print()
        print(f"  {yellow('→')} Triggering pipeline (with --fix)")
        trigger_pipeline_if_stale(w, stale=True)
        print(f"  {yellow('!')} Re-run this script in ~10 min to verify Gold caught up.")
        return 2

    # --- Layer 3: Lakebase synced tables ---
    print(bold("\n3. Lakebase (synced tables fresh?)"))
    lake = check_lakebase_freshness(w, args.pg_user, max_age_min=30)
    lake_stale = []
    for t, info in lake.items():
        if info.get("error"):
            print(f"  {red('✗ ERROR')} {t}: {info['error']}")
            lake_stale.append(t)
        elif info.get("fresh"):
            print(f"  {green('✓ FRESH')} {t}  count={info['count']}  age={info['age_min']:.1f} min")
        else:
            print(f"  {red('✗ STALE')} {t}  age={info.get('age_min', 0):.0f} min")
            lake_stale.append(t)

    if lake_stale and args.fix:
        print()
        print(f"  {yellow('→')} Resetting stale synced tables…")
        # Inline the reset using reset_synced_tables logic
        import subprocess
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "reset_synced_tables.py"),
                        *lake_stale], check=False)

    # --- Layer 4: SAP BDC ---
    if not args.quick:
        print(bold("\n4. SAP BDC catalog (UC warm-up)"))
        if args.fix:
            ok = warm_sap_bdc_catalog(token)
            print(f"  {green('✓ WARM') if ok else red('✗ FAILED')}")
        else:
            # Just check counts
            try:
                rows = warehouse_query(token, "SHOW TABLES IN sapsofts.procurement")
                print(f"  {green('✓ AVAILABLE')} {len(rows)}/15 tables in sapsofts.procurement")
            except Exception as e:
                print(f"  {red('✗ NOT WARM')} {str(e)[:80]} — re-run with --fix to warm")

    # --- Summary ---
    print(bold("\n=== Summary ==="))
    all_ok = bz["fresh"] and not gold_stale and not lake_stale
    if all_ok:
        print(green("All layers fresh. Ready for demo."))
        return 0
    if args.fix:
        print(yellow("Repairs triggered. Re-run in 5-10 min to verify."))
    else:
        print(red("Issues found. Re-run with --fix to auto-repair, or follow docs/TESTING.md."))
    return 1


if __name__ == "__main__":
    sys.exit(main())
