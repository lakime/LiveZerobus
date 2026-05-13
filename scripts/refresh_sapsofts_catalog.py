#!/usr/bin/env python3
"""Reliably refresh the SAP BDC Delta Sharing catalog in Databricks UC.

UC's Delta Sharing connector has an intermittent internal RPC issue —
DESCRIBE TABLE / SELECT sometimes fails with RESOURCE_DOES_NOT_EXIST
even though our BDC server returns 200 for every probe. The fix is to
retry each statement until it succeeds. With 3-5 retries per table the
full refresh is reliably idempotent.

Usage:
    python scripts/refresh_sapsofts_catalog.py
Env:
    DATABRICKS_HOST=https://adb-...azuredatabricks.net
    DATABRICKS_TOKEN=dapi...
    SAP_BDC_WAREHOUSE_ID=6a1fb3b32b00f1cd   (default if unset)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

HOST = os.environ.get("DATABRICKS_HOST", "https://adb-5347428297913551.11.azuredatabricks.net").rstrip("/")
TOKEN = os.environ["DATABRICKS_TOKEN"]
WAREHOUSE = os.environ.get("SAP_BDC_WAREHOUSE_ID", "6a1fb3b32b00f1cd")

CATALOG = "sapsofts"
SCHEMA = "procurement"
SHARE_PROVIDER = "sapsofts"
SHARE_NAME = "sap-procurement"

TABLES = [
    "bkpf", "eban", "ekbe", "eket", "ekko", "ekpo",
    "lfa1", "mara", "mkpf", "mseg", "rbkp",
    "t001", "t001w", "t023", "t024",
]


def run(sql: str, retries: int = 5, sleep: float = 2.0) -> dict:
    """Execute a SQL statement, retrying on UC's intermittent RPC failures."""
    last_err = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            f"{HOST}/api/2.0/sql/statements",
            data=json.dumps({"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "30s"}).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        raw = urllib.request.urlopen(req, timeout=60).read().decode()
        clean = re.sub(r"[\x00-\x1f\x7f]", " ", raw)
        r = json.loads(clean)
        state = r.get("status", {}).get("state")
        if state == "SUCCEEDED":
            return r
        last_err = r.get("status", {}).get("error", {}).get("message", "")[:200]
        # Don't bother retrying real syntax/permission errors.
        if any(s in last_err for s in ["PERMISSION_DENIED", "SYNTAX_ERROR", "UNAUTHORIZED"]):
            break
        print(f"   ⚠  attempt {attempt}/{retries} failed: {last_err[:120]}", file=sys.stderr)
        time.sleep(sleep)
    raise RuntimeError(f"Statement failed after {retries} retries: {sql}\n  last error: {last_err}")


def main() -> int:
    print(f"Refreshing {CATALOG}.{SCHEMA} (provider={SHARE_PROVIDER}, share={SHARE_NAME})")

    # Step 1: nuke + recreate.
    run(f"DROP CATALOG IF EXISTS {CATALOG} CASCADE")
    print("  ✓ DROP CATALOG")
    run(f"CREATE CATALOG {CATALOG} USING SHARE `{SHARE_PROVIDER}`.`{SHARE_NAME}`")
    print("  ✓ CREATE CATALOG")

    # Step 2: poke UC into materialising the schema list.
    run(f"SHOW SCHEMAS IN {CATALOG}")
    run(f"SHOW TABLES IN {CATALOG}.{SCHEMA}")
    print("  ✓ schema materialised")

    # Step 3: warm column metadata for each table with retries.
    successes, failures = [], []
    for t in TABLES:
        try:
            run(f"DESCRIBE TABLE {CATALOG}.{SCHEMA}.{t}", retries=5, sleep=2.0)
            successes.append(t)
            print(f"  ✓ {t}")
        except Exception as e:
            failures.append((t, str(e)[:140]))
            print(f"  ✗ {t}: {e}", file=sys.stderr)

    # Step 4: smoke test by counting rows in EKKO.
    try:
        r = run(f"SELECT count(*) FROM {CATALOG}.{SCHEMA}.ekko")
        rows = r["result"]["data_array"][0][0]
        print(f"  ✓ smoke test: EKKO has {rows} rows")
    except Exception as e:
        failures.append(("smoke", str(e)[:140]))
        print(f"  ✗ smoke test: {e}", file=sys.stderr)

    print()
    print(f"Result: {len(successes)}/{len(TABLES)} tables warmed.")
    if failures:
        print("Failures:")
        for t, e in failures:
            print(f"  {t}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
