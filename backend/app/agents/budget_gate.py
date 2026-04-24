"""Budget / approval-gate agent.

Walks DRAFT POs, checks the budget ledger balance for the current month in
category SEED, and flips the PO to APPROVED or REJECTED. Each approval
writes a negative delta to the ledger so the balance reflects committed spend.

A monthly allocation row is lazily seeded the first time we see a new month,
so the demo "just works" without manual setup.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..config import Settings
from . import db


MONTHLY_SEED_BUDGET_USD = 25000.0


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _period() -> str:
    n = _now()
    return f"{n.year:04d}-{n.month:02d}"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _ensure_allocation(settings: Settings) -> float:
    period = _period()
    row = db.fetchone(
        settings,
        """SELECT balance_usd FROM live.budget_ledger
            WHERE period_ym=%s AND category='SEED'
            ORDER BY entry_ts DESC LIMIT 1""",
        [period],
    )
    if row:
        return float(row["balance_usd"])
    db.execute(
        settings,
        """INSERT INTO live.budget_ledger
             (ledger_id, entry_ts, period_ym, category,
              delta_usd, balance_usd, po_id, note)
           VALUES (%s,%s,%s,'SEED',%s,%s,NULL,%s)""",
        [_new_id("LED"), _now(), period, MONTHLY_SEED_BUDGET_USD,
         MONTHLY_SEED_BUDGET_USD, f"Monthly seed budget allocation {period}"],
    )
    return MONTHLY_SEED_BUDGET_USD


def _current_balance(settings: Settings) -> float:
    row = db.fetchone(
        settings,
        """SELECT balance_usd FROM live.budget_ledger
            WHERE period_ym=%s AND category='SEED'
            ORDER BY entry_ts DESC LIMIT 1""",
        [_period()],
    )
    return float(row["balance_usd"]) if row else _ensure_allocation(settings)


def run_budget_gate(settings: Settings) -> dict:
    _ensure_allocation(settings)
    approved: list[str] = []
    rejected: list[str] = []

    drafts = db.fetchall(
        settings,
        "SELECT * FROM live.po_drafts WHERE status='DRAFT' ORDER BY created_ts ASC",
    )
    for po in drafts:
        balance = _current_balance(settings)
        cost = float(po["total_cost_usd"] or 0.0)
        if cost <= balance:
            new_balance = balance - cost
            db.execute(
                settings,
                "UPDATE live.po_drafts SET status='APPROVED' WHERE po_id=%s",
                [po["po_id"]],
            )
            db.execute(
                settings,
                """INSERT INTO live.budget_ledger
                     (ledger_id, entry_ts, period_ym, category,
                      delta_usd, balance_usd, po_id, note)
                   VALUES (%s,%s,%s,'SEED',%s,%s,%s,%s)""",
                [_new_id("LED"), _now(), _period(), -cost, new_balance,
                 po["po_id"], f"Approved PO {po['po_id']} for SKU {po['sku']}"],
            )
            approved.append(po["po_id"])
        else:
            db.execute(
                settings,
                "UPDATE live.po_drafts SET status='REJECTED', "
                "rationale = COALESCE(rationale,'') || ' | BUDGET_EXCEEDED' "
                "WHERE po_id=%s",
                [po["po_id"]],
            )
            rejected.append(po["po_id"])

    return {"approved": approved, "rejected": rejected,
            "balance_usd": _current_balance(settings)}
