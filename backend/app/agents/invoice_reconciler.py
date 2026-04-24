"""Invoice-reconciliation agent.

Given open reconciliation rows in `live.invoice_reconciliations` (status='NEW'),
compute variance vs. the approved PO and flip the status:
  variance_pct <= 1.0%  → OK
  1.0% < variance_pct <= 5.0%  → REVIEW
  > 5.0% or missing PO  → DISPUTE

For the demo the reconciliation rows are produced by a small simulator that
inserts an invoice shortly after the PO is APPROVED; in production this
would ingest from an AP connector.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..config import Settings
from . import db


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def run_reconciler(settings: Settings) -> dict:
    rows = db.fetchall(
        settings,
        """SELECT * FROM live.invoice_reconciliations
            WHERE status='NEW' ORDER BY received_ts ASC LIMIT 50""",
    )
    updated: list[dict] = []
    for r in rows:
        po = db.fetchone(
            settings,
            "SELECT total_cost_usd FROM live.po_drafts WHERE po_id=%s",
            [r["po_id"]],
        )
        expected = float(po["total_cost_usd"]) if po and po.get("total_cost_usd") is not None else None
        invoiced = float(r["invoiced_amount_usd"] or 0.0)
        if expected is None or expected == 0:
            variance = invoiced
            pct = 100.0
            status = "DISPUTE"
            note = "No matching PO total found"
        else:
            variance = invoiced - expected
            pct = abs(variance) / expected * 100.0
            if pct <= 1.0:
                status = "OK"
                note = "Within 1% tolerance"
            elif pct <= 5.0:
                status = "REVIEW"
                note = f"{pct:.2f}% variance — human review recommended"
            else:
                status = "DISPUTE"
                note = f"{pct:.2f}% variance — exceeds tolerance"

        db.execute(
            settings,
            """UPDATE live.invoice_reconciliations
                  SET expected_amount_usd=%s,
                      variance_usd=%s, variance_pct=%s,
                      status=%s, agent_notes=%s
                WHERE reconciliation_id=%s""",
            [expected, variance, pct, status, note, r["reconciliation_id"]],
        )
        db.execute(
            settings,
            """INSERT INTO live.agent_runs
                 (run_id, started_ts, finished_ts, agent_name, input_ref,
                  output_ref, prompt_tokens, output_tokens, status, error_msg)
               VALUES (%s,%s,%s,'invoice_reconciler',%s,%s,0,0,'OK',NULL)""",
            [_new_id("RUN"), _now(), _now(),
             r["reconciliation_id"], status],
        )
        updated.append({
            "reconciliation_id": r["reconciliation_id"],
            "status": status,
            "variance_pct": round(pct, 3),
        })

    return {"processed": updated}
