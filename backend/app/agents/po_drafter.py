"""PO-drafter agent.

When a negotiation thread has an accepted supplier quote (intent QUOTE or
ACCEPT with plausible pack_size_g + unit_price), promote it to a PO draft
in `liveoltp.po_drafts` with status DRAFT. The budget_gate agent then
approves or rejects it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from ..config import Settings
from . import db


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _candidate_threads(settings: Settings) -> list[dict]:
    # Threads whose latest inbound email looks like a valid QUOTE/ACCEPT and
    # which don't already have a PO draft.
    return db.fetchall(
        settings,
        """WITH latest AS (
             SELECT DISTINCT ON (thread_id) *
               FROM liveoltp.email_inbox
              WHERE intent_detected IN ('QUOTE','ACCEPT','COUNTER')
              ORDER BY thread_id, received_ts DESC
           )
           SELECT l.*, o.sku AS out_sku, o.supplier_id AS out_supplier
             FROM latest l
             JOIN liveoltp.email_outbox o
               ON o.thread_id = l.thread_id
              AND o.intent = 'RFQ'
            WHERE NOT EXISTS (
                    SELECT 1 FROM liveoltp.po_drafts p
                     WHERE p.thread_id = l.thread_id
                  )
            ORDER BY l.received_ts DESC
            LIMIT 10""",
    )


def run_po_drafter(settings: Settings) -> dict:
    drafted: list[str] = []
    for row in _candidate_threads(settings):
        data = {}
        try:
            data = json.loads(row.get("extracted_json") or "{}")
        except Exception:
            data = {}
        price = data.get("unit_price_usd")
        pack  = data.get("pack_size_g")
        lead  = data.get("lead_time_days") or 7
        if not price or not pack:
            continue

        # Look up the reorder grams from the original recommendation if any,
        # otherwise fall back to 10 packs so the demo flow always advances.
        rec = db.fetchone(
            settings,
            """SELECT reorder_grams, packs FROM liveoltp.procurement_recommendations
                WHERE sku=%s ORDER BY created_ts DESC LIMIT 1""",
            [row["sku"] or row["out_sku"]],
        ) or {}
        packs = max(int((rec.get("reorder_grams") or 0) / pack) or
                    (rec.get("packs") or 10), 1)
        total_g = packs * pack
        total_cost = packs * float(price)

        po_id = _new_id("PO")
        db.execute(
            settings,
            """INSERT INTO liveoltp.po_drafts
                 (po_id, created_ts, thread_id, sku, supplier_id,
                  packs, pack_size_g, total_grams, unit_price_usd,
                  total_cost_usd, needed_by, status, rationale)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s)""",
            [
                po_id, _now(), row["thread_id"],
                row["sku"] or row["out_sku"],
                row.get("out_supplier") or row["supplier_id"],
                packs, float(pack), float(total_g),
                float(price), float(total_cost),
                (_now() + timedelta(days=int(lead))).date(),
                f"Extracted from supplier email {row['email_id']}; intent={row.get('intent_detected')}",
            ],
        )
        drafted.append(po_id)

    return {"drafted": drafted}
