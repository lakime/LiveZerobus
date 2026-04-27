"""Invoice-reconciliation agent.

Given open reconciliation rows in `liveoltp.invoice_reconciliations` (status='NEW'),
compute variance vs. the approved PO and flip the status:
  variance_pct <= 1.0%  → OK
  1.0% < variance_pct <= 5.0%  → REVIEW
  > 5.0% or missing PO  → DISPUTE

For the demo the reconciliation rows are produced by `simulate_invoice_for_po`
below, which is invoked once per /cycle call (and exposed on its own route
for manual triggering). In production this would ingest from an AP connector
(SAP Concur, Coupa, custom AR feed, etc.).
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from ..config import Settings
from . import db


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ---------------------------------------------------------------------------
# Invoice simulator — produces synthetic invoices for APPROVED POs that have
# no invoice yet. Distribution of variance is intentionally skewed so the
# reconciler tab shows a realistic mix of OK / REVIEW / DISPUTE rows:
#   70% within ±1%  → OK
#   20% within ±5%  → REVIEW
#   10% beyond ±5%  → DISPUTE
# ---------------------------------------------------------------------------

def _pick_approved_po_without_invoice(settings: Settings) -> dict | None:
    """Return one APPROVED PO that does not yet have a reconciliation row."""
    return db.fetchone(
        settings,
        """SELECT p.po_id, p.supplier_id, p.total_cost_usd
             FROM liveoltp.po_drafts p
            WHERE p.status = 'APPROVED'
              AND NOT EXISTS (
                    SELECT 1 FROM liveoltp.invoice_reconciliations r
                     WHERE r.po_id = p.po_id
                  )
            ORDER BY p.created_ts ASC
            LIMIT 1""",
    )


def _sample_variance_pct() -> float:
    """Pick a signed variance percentage with the OK/REVIEW/DISPUTE mix."""
    bucket = random.random()
    if bucket < 0.70:                 # 70% OK
        v = random.uniform(-1.0, 1.0)
    elif bucket < 0.90:               # 20% REVIEW
        v = random.uniform(1.0, 5.0) * random.choice([-1.0, 1.0])
    else:                             # 10% DISPUTE
        v = random.uniform(5.0, 12.0) * random.choice([-1.0, 1.0])
    return v


def simulate_invoice_for_po(
    settings: Settings, po_id: str | None = None
) -> dict:
    """Insert one invoice row for an APPROVED PO and return the new id.

    If `po_id` is None, picks the oldest APPROVED PO without an invoice.
    Returns {"reconciliation_id": ..., "po_id": ..., "invoiced_amount_usd": ...}
    or {"error": ...} when there's nothing to invoice.
    """
    if po_id:
        po = db.fetchone(
            settings,
            """SELECT po_id, supplier_id, total_cost_usd
                 FROM liveoltp.po_drafts
                WHERE po_id = %s AND status = 'APPROVED'""",
            [po_id],
        )
        if not po:
            return {"error": f"PO {po_id} not found or not APPROVED"}
        # Refuse to double-invoice
        existing = db.fetchone(
            settings,
            "SELECT 1 FROM liveoltp.invoice_reconciliations WHERE po_id=%s LIMIT 1",
            [po_id],
        )
        if existing:
            return {"error": f"PO {po_id} already has an invoice"}
    else:
        po = _pick_approved_po_without_invoice(settings)
        if not po:
            return {"error": "no APPROVED POs without invoices"}

    expected = float(po["total_cost_usd"] or 0.0)
    variance_pct = _sample_variance_pct()
    invoiced = round(expected * (1.0 + variance_pct / 100.0), 2)

    rec_id = _new_id("REC")
    db.execute(
        settings,
        """INSERT INTO liveoltp.invoice_reconciliations
             (reconciliation_id, received_ts, po_id, supplier_id,
              invoiced_amount_usd, expected_amount_usd,
              variance_usd, variance_pct, status, agent_notes)
           VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, 'NEW', NULL)""",
        [rec_id, _now(), po["po_id"], po.get("supplier_id"), invoiced],
    )
    return {
        "reconciliation_id": rec_id,
        "po_id": po["po_id"],
        "invoiced_amount_usd": invoiced,
        "expected_amount_usd": expected,
        "simulated_variance_pct": round(variance_pct, 3),
    }


def run_reconciler(settings: Settings) -> dict:
    rows = db.fetchall(
        settings,
        """SELECT * FROM liveoltp.invoice_reconciliations
            WHERE status='NEW' ORDER BY received_ts ASC LIMIT 50""",
    )
    updated: list[dict] = []
    for r in rows:
        po = db.fetchone(
            settings,
            "SELECT total_cost_usd FROM liveoltp.po_drafts WHERE po_id=%s",
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
            """UPDATE liveoltp.invoice_reconciliations
                  SET expected_amount_usd=%s,
                      variance_usd=%s, variance_pct=%s,
                      status=%s, agent_notes=%s
                WHERE reconciliation_id=%s""",
            [expected, variance, pct, status, note, r["reconciliation_id"]],
        )
        db.execute(
            settings,
            """INSERT INTO liveoltp.agent_runs
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
