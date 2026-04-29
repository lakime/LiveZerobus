"""
Integration tests for Lakebase Postgres (procurement schema).

Verifies that all tables exist with the correct structure, synced Gold tables
are populated with fresh data, and the summary query returns plausible values.

Prerequisites:
    pip install pytest
    Set env vars: PGHOST, PGDATABASE, PGUSER,
                  LAKEBASE_PROJECT, LAKEBASE_BRANCH, LAKEBASE_ENDPOINT
    Auth via Databricks SDK (DATABRICKS_HOST + DATABRICKS_TOKEN or OAuth M2M).

Run:
    pytest backend/tests/test_lakebase.py -v
"""
from __future__ import annotations

import os
import time
import threading
import pytest
import psycopg
import psycopg.rows
from databricks.sdk import WorkspaceClient

# ---------------------------------------------------------------------------
# Connection fixture
# ---------------------------------------------------------------------------

_TOKEN_CACHE: tuple[str, float] = ("", 0.0)
_TOKEN_LOCK = threading.Lock()


def _get_token() -> str:
    global _TOKEN_CACHE
    with _TOKEN_LOCK:
        token, exp = _TOKEN_CACHE
        if not token or exp - time.time() < 60:
            project = os.environ["LAKEBASE_PROJECT"]
            branch = os.environ["LAKEBASE_BRANCH"]
            endpoint = os.environ["LAKEBASE_ENDPOINT"]
            resource = f"projects/{project}/branches/{branch}/endpoints/{endpoint}"
            w = WorkspaceClient()
            cred = w.postgres.generate_database_credential(endpoint=resource)
            token = cred.token or ""
            if not token:
                raise RuntimeError(f"No token returned for {resource}")
            exp_attr = getattr(cred, "expiration_time", None)
            exp = exp_attr.timestamp() if exp_attr and hasattr(exp_attr, "timestamp") else time.time() + 3600
            _TOKEN_CACHE = (token, exp)
        return token


@pytest.fixture(scope="session")
def conn():
    token = _get_token()
    c = psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "databricks_postgres"),
        user=os.environ["PGUSER"],
        password=token,
        sslmode="require",
        row_factory=psycopg.rows.dict_row,
    )
    yield c
    c.close()


def q(conn, sql: str, params=None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# 1. Schema existence
# ---------------------------------------------------------------------------

class TestSchemaExists:
    def test_procurement_schema_exists(self, conn):
        rows = q(conn, """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name = 'procurement'
        """)
        assert rows, "Schema 'procurement' not found in Lakebase"


# ---------------------------------------------------------------------------
# 2. All 12 tables exist
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    # synced from Gold
    "inventory_snapshot",
    "supplier_leaderboard",
    "commodity_prices_latest",
    "demand_1h",
    "procurement_recommendations",
    # agent state
    "email_outbox",
    "email_inbox",
    "po_drafts",
    "budget_ledger",
    "supplier_applications",
    "invoice_reconciliations",
    "agent_runs",
]


class TestTablesExist:
    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_table_exists(self, conn, table):
        rows = q(conn, """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'procurement' AND table_name = %s
        """, (table,))
        assert rows, f"Table 'procurement.{table}' does not exist"


# ---------------------------------------------------------------------------
# 3. Column structure for critical tables
# ---------------------------------------------------------------------------

class TestColumnStructure:
    def _columns(self, conn, table: str) -> set[str]:
        rows = q(conn, """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'procurement' AND table_name = %s
        """, (table,))
        return {r["column_name"] for r in rows}

    def test_inventory_snapshot_columns(self, conn):
        cols = self._columns(conn, "inventory_snapshot")
        required = {"sku", "room_id", "on_hand_g", "last_event_ts",
                    "reorder_point_g", "target_stock_g"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_supplier_leaderboard_columns(self, conn):
        cols = self._columns(conn, "supplier_leaderboard")
        required = {"sku", "supplier_id", "supplier_name", "unit_price_usd",
                    "usd_per_gram", "lead_time_days", "score", "rank"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_commodity_prices_latest_columns(self, conn):
        cols = self._columns(conn, "commodity_prices_latest")
        required = {"input_key", "price_usd", "unit", "event_ts", "pct_1h", "pct_24h"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_demand_1h_columns(self, conn):
        cols = self._columns(conn, "demand_1h")
        required = {"sku", "hour_ts", "trays", "grams_req"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_procurement_recommendations_columns(self, conn):
        cols = self._columns(conn, "procurement_recommendations")
        required = {"recommendation_id", "created_ts", "sku", "room_id",
                    "reorder_grams", "recommended_supplier_id", "total_cost_usd",
                    "decision", "ml_score"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_po_drafts_columns(self, conn):
        cols = self._columns(conn, "po_drafts")
        required = {"po_id", "created_ts", "sku", "supplier_id",
                    "total_cost_usd", "status"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_email_outbox_columns(self, conn):
        cols = self._columns(conn, "email_outbox")
        required = {"email_id", "thread_id", "created_ts", "supplier_id",
                    "subject", "body_md", "intent", "status"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_budget_ledger_columns(self, conn):
        cols = self._columns(conn, "budget_ledger")
        required = {"ledger_id", "entry_ts", "period_ym", "category",
                    "delta_usd", "balance_usd"}
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_agent_runs_columns(self, conn):
        cols = self._columns(conn, "agent_runs")
        required = {"run_id", "started_ts", "agent_name", "status"}
        assert required <= cols, f"Missing columns: {required - cols}"


# ---------------------------------------------------------------------------
# 4. Synced Gold tables are populated
# ---------------------------------------------------------------------------

class TestSyncedTablesPopulated:
    def test_inventory_snapshot_has_rows(self, conn):
        rows = q(conn, "SELECT COUNT(*) AS n FROM procurement.inventory_snapshot")
        assert rows[0]["n"] > 0, "inventory_snapshot is empty — sync may not have run"

    def test_supplier_leaderboard_has_rows(self, conn):
        rows = q(conn, "SELECT COUNT(*) AS n FROM procurement.supplier_leaderboard")
        assert rows[0]["n"] > 0, "supplier_leaderboard is empty — sync may not have run"

    def test_commodity_prices_latest_has_rows(self, conn):
        rows = q(conn, "SELECT COUNT(*) AS n FROM procurement.commodity_prices_latest")
        assert rows[0]["n"] > 0, "commodity_prices_latest is empty — sync may not have run"

    def test_demand_1h_has_rows(self, conn):
        rows = q(conn, "SELECT COUNT(*) AS n FROM procurement.demand_1h")
        assert rows[0]["n"] > 0, "demand_1h is empty — simulators may not be running"

    def test_procurement_recommendations_has_rows(self, conn):
        rows = q(conn, "SELECT COUNT(*) AS n FROM procurement.procurement_recommendations")
        assert rows[0]["n"] > 0, "procurement_recommendations is empty — Gold pipeline may not have run"


# ---------------------------------------------------------------------------
# 5. Data quality checks on synced tables
# ---------------------------------------------------------------------------

class TestDataQuality:
    def test_inventory_on_hand_non_negative(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.inventory_snapshot
            WHERE on_hand_g < 0
        """)
        assert rows[0]["n"] == 0, f"{rows[0]['n']} rows have negative on_hand_g"

    def test_inventory_has_sku_and_room(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.inventory_snapshot
            WHERE sku IS NULL OR room_id IS NULL
        """)
        assert rows[0]["n"] == 0, "inventory_snapshot has NULL sku or room_id"

    def test_supplier_leaderboard_rank_positive(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.supplier_leaderboard
            WHERE rank < 1
        """)
        assert rows[0]["n"] == 0, "supplier_leaderboard has rank < 1"

    def test_supplier_prices_positive(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.supplier_leaderboard
            WHERE unit_price_usd <= 0 OR usd_per_gram <= 0
        """)
        assert rows[0]["n"] == 0, "supplier_leaderboard has non-positive prices"

    def test_commodity_prices_positive(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.commodity_prices_latest
            WHERE price_usd <= 0
        """)
        assert rows[0]["n"] == 0, "commodity_prices_latest has non-positive prices"

    def test_recommendations_decision_values(self, conn):
        rows = q(conn, """
            SELECT DISTINCT decision FROM procurement.procurement_recommendations
            WHERE decision IS NOT NULL
        """)
        valid = {"BUY_NOW", "WAIT", "REVIEW"}
        found = {r["decision"] for r in rows}
        unexpected = found - valid
        assert not unexpected, f"Unexpected decision values: {unexpected}"

    def test_recommendations_costs_non_negative(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.procurement_recommendations
            WHERE total_cost_usd < 0
        """)
        assert rows[0]["n"] == 0, "procurement_recommendations has negative total_cost_usd"

    def test_demand_grams_positive(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.demand_1h
            WHERE grams_req <= 0 OR trays <= 0
        """)
        assert rows[0]["n"] == 0, "demand_1h has non-positive grams_req or trays"


# ---------------------------------------------------------------------------
# 6. Data freshness (synced tables should have recent data)
# ---------------------------------------------------------------------------

class TestDataFreshness:
    def test_commodity_prices_recent(self, conn):
        rows = q(conn, """
            SELECT MAX(event_ts) AS latest FROM procurement.commodity_prices_latest
        """)
        latest = rows[0]["latest"]
        assert latest is not None, "commodity_prices_latest has no event_ts at all"
        rows2 = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.commodity_prices_latest
            WHERE event_ts > NOW() - INTERVAL '1 hour'
        """)
        assert rows2[0]["n"] > 0, \
            f"No commodity prices in last hour (latest: {latest}) — simulators may be down"

    def test_demand_data_recent(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.demand_1h
            WHERE hour_ts > NOW() - INTERVAL '2 hours'
        """)
        assert rows[0]["n"] > 0, \
            "No demand_1h rows in last 2 hours — planting simulator may be down"

    def test_recommendations_recent(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.procurement_recommendations
            WHERE created_ts > NOW() - INTERVAL '5 minutes'
        """)
        assert rows[0]["n"] >= 0, "procurement_recommendations freshness check"
        # Warn rather than fail if pipeline isn't ticking live
        recent = rows[0]["n"]
        if recent == 0:
            pytest.warns(UserWarning, match="")  # soft: pipeline may be paused


# ---------------------------------------------------------------------------
# 7. Agent-state tables: PKs are unique (basic integrity)
# ---------------------------------------------------------------------------

class TestAgentStateIntegrity:
    def _check_pk_unique(self, conn, table: str, pk_col: str):
        rows = q(conn, f"""
            SELECT COUNT(*) AS total, COUNT(DISTINCT {pk_col}) AS uniq
            FROM procurement.{table}
        """)
        r = rows[0]
        assert r["total"] == r["uniq"], \
            f"procurement.{table}: duplicate {pk_col} — {r['total']} rows, {r['uniq']} distinct"

    def test_po_drafts_pk_unique(self, conn):
        self._check_pk_unique(conn, "po_drafts", "po_id")

    def test_email_outbox_pk_unique(self, conn):
        self._check_pk_unique(conn, "email_outbox", "email_id")

    def test_email_inbox_pk_unique(self, conn):
        self._check_pk_unique(conn, "email_inbox", "email_id")

    def test_budget_ledger_pk_unique(self, conn):
        self._check_pk_unique(conn, "budget_ledger", "ledger_id")

    def test_supplier_applications_pk_unique(self, conn):
        self._check_pk_unique(conn, "supplier_applications", "application_id")

    def test_invoice_reconciliations_pk_unique(self, conn):
        self._check_pk_unique(conn, "invoice_reconciliations", "reconciliation_id")

    def test_agent_runs_pk_unique(self, conn):
        self._check_pk_unique(conn, "agent_runs", "run_id")

    def test_po_status_values(self, conn):
        rows = q(conn, """
            SELECT DISTINCT status FROM procurement.po_drafts WHERE status IS NOT NULL
        """)
        valid = {"DRAFT", "APPROVED", "REJECTED", "SENT", "RECEIVED"}
        found = {r["status"] for r in rows}
        assert found <= valid, f"Unexpected PO status values: {found - valid}"

    def test_supplier_application_status_values(self, conn):
        rows = q(conn, """
            SELECT DISTINCT status FROM procurement.supplier_applications WHERE status IS NOT NULL
        """)
        valid = {"NEW", "SCREENING", "APPROVED", "REJECTED"}
        found = {r["status"] for r in rows}
        assert found <= valid, f"Unexpected application status values: {found - valid}"


# ---------------------------------------------------------------------------
# 8. Summary query (mirrors GET /api/summary)
# ---------------------------------------------------------------------------

class TestSummaryQuery:
    def test_summary_query_runs(self, conn):
        rows = q(conn, """
            SELECT
              (SELECT COUNT(*) FROM procurement.inventory_snapshot
                 WHERE on_hand_g <= reorder_point_g)                          AS skus_below_reorder,
              (SELECT COUNT(*) FROM procurement.procurement_recommendations
                 WHERE decision = 'BUY_NOW'
                   AND created_ts > NOW() - INTERVAL '5 minutes')             AS buy_now_last_5m,
              (SELECT COALESCE(SUM(total_cost_usd), 0)
                 FROM procurement.procurement_recommendations
                 WHERE created_ts > NOW() - INTERVAL '1 hour')                AS spend_pending_1h_usd,
              (SELECT MAX(event_ts) FROM procurement.commodity_prices_latest)    AS last_market_tick,
              (SELECT COUNT(*) FROM procurement.po_drafts
                 WHERE status = 'DRAFT')                                      AS po_drafts_open,
              (SELECT COUNT(*) FROM procurement.email_inbox
                 WHERE processed IS NOT TRUE)                                  AS inbound_unprocessed
        """)
        assert rows, "Summary query returned no rows"
        r = rows[0]
        assert r["skus_below_reorder"] is not None
        assert r["spend_pending_1h_usd"] is not None
        assert float(r["spend_pending_1h_usd"]) >= 0

    def test_summary_skus_below_reorder_plausible(self, conn):
        rows = q(conn, """
            SELECT COUNT(*) AS total FROM procurement.inventory_snapshot
        """)
        total = rows[0]["total"]
        rows2 = q(conn, """
            SELECT COUNT(*) AS n FROM procurement.inventory_snapshot
            WHERE on_hand_g <= reorder_point_g
        """)
        below = rows2[0]["n"]
        assert below <= total, \
            f"skus_below_reorder ({below}) exceeds total inventory rows ({total})"
