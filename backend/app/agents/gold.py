"""Read-only lookups against Gold Delta MVs via the SQL warehouse.

Agents previously read these via Lakebase synced tables in Postgres, but
those tables routinely get stuck on stale snapshots. The dashboard already
queries Gold directly; agents do the same here so the negotiator and
po-drafter never wait on a synced-table refresh.

This module is intentionally narrow — only the 3 lookups the agents need.
Returns plain dicts with numeric coercion (Statement Execution returns all
values as strings).
"""
from __future__ import annotations

from typing import Any

from ..config import Settings
from ..warehouse import execute as wh_execute

CATALOG = "livezerobus"
SCHEMA = "procurement"


def _coerce(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "" or s.lower() in ("null", "none"):
        return None
    if s[0] in "-+0123456789" and any(c.isdigit() for c in s):
        try:
            return float(s) if ("." in s or "e" in s or "E" in s) else int(s)
        except ValueError:
            return v
    return v


def _rows(settings: Settings, sql: str, params: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    rows = wh_execute(settings, sql, parameters=params)
    return [{k: _coerce(v) for k, v in r.items()} for r in rows]


def latest_recommendation_for_sku(settings: Settings, sku: str) -> dict | None:
    """Most-recent recommendation row for a given SKU."""
    rows = _rows(
        settings,
        f"""SELECT reorder_grams, packs
              FROM {CATALOG}.{SCHEMA}.gd_procurement_recommendations
             WHERE sku = :sku
             ORDER BY created_ts DESC
             LIMIT 1""",
        [{"name": "sku", "value": sku}],
    )
    return rows[0] if rows else None


def open_buy_now_recommendations(settings: Settings, limit: int = 20) -> list[dict]:
    """BUY_NOW recommendations with a recommended supplier and non-zero qty,
    newest first. Caller filters out the ones that already have an RFQ in
    `procurement.email_outbox` (which lives in Postgres)."""
    return _rows(
        settings,
        f"""SELECT recommendation_id, sku, reorder_grams, packs,
                   pack_size_g, unit_price_usd, total_cost_usd,
                   expected_lead_days, recommended_supplier_id,
                   recommended_supplier_name, created_ts
              FROM {CATALOG}.{SCHEMA}.gd_procurement_recommendations
             WHERE decision = 'BUY_NOW'
               AND reorder_grams > 0
               AND packs > 0
               AND recommended_supplier_id IS NOT NULL
             ORDER BY created_ts DESC
             LIMIT {int(limit)}""",
    )


def supplier_name(settings: Settings, supplier_id: str) -> str | None:
    """Look up a supplier's display name from the leaderboard."""
    rows = _rows(
        settings,
        f"""SELECT supplier_name
              FROM {CATALOG}.{SCHEMA}.gd_supplier_leaderboard
             WHERE supplier_id = :supplier_id
             LIMIT 1""",
        [{"name": "supplier_id", "value": supplier_id}],
    )
    return (rows[0].get("supplier_name") if rows else None)
