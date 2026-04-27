"""Negotiation agent.

Given a BUY_NOW procurement recommendation, drafts an email to the recommended
supplier asking for a firm quote (or a better price than the leaderboard
shows). When a supplier reply lands in `liveoltp.email_inbox`, the agent
extracts structured terms from the body, decides whether to accept,
counter, or escalate, and writes a follow-up email.

The FastAPI route `/api/agents/negotiator/tick` runs this agent once. It's
idempotent: each thread advances at most one step per tick.

This file also contains a tiny supplier-persona LLM helper used by the
simulated-inbox endpoint to generate plausible replies. In a real
deployment you'd replace that with an IMAP/Graph fetch.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import db
from .llm import FoundationModelClient, LLMError


NEGOTIATOR_SYSTEM = """You are a procurement negotiator for a vertical farm.
You email seed suppliers to obtain firm quotes for urgent seed SKUs.
Be concise, friendly, and specific about quantity, timing, and substitutions.
Never commit to payment terms. Reference certifications (organic) when relevant.

Output strictly JSON with these keys:
  subject    (string)
  body_md    (string, markdown body of the email, 80-220 words)
  target_price_usd_per_gram (number, your aim — used as our walk-away)
  ask_confirm_by (ISO date, 1-3 business days out)
"""

SUPPLIER_PERSONA_SYSTEM = """You role-play a seed-supplier sales rep replying
to a vertical-farm buyer's RFQ. Stay in character as the named supplier and
quote based on their typical pricing tier. Output strictly JSON:
  subject (string)
  body_md (string, 80-200 words, professional but human)
  quoted_unit_price_usd (number, per pack)
  pack_size_g (number)
  lead_time_days (integer)
  organic (boolean)
  intent  (one of "QUOTE","COUNTER","REJECT")
"""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _record_run(
    settings: Settings,
    agent: str,
    input_ref: str,
    output_ref: str,
    status: str,
    started: datetime,
    llm_usage: tuple[int, int] | None = None,
    error: str | None = None,
) -> None:
    p, o = llm_usage or (0, 0)
    db.execute(
        settings,
        """INSERT INTO liveoltp.agent_runs
             (run_id, started_ts, finished_ts, agent_name, input_ref,
              output_ref, prompt_tokens, output_tokens, status, error_msg)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [_new_id("RUN"), started, _now(), agent, input_ref, output_ref,
         p, o, status, error],
    )


# ---------------------------------------------------------------------------
# Step 1 — draft RFQs for new BUY_NOW recs that don't have a thread yet.
# ---------------------------------------------------------------------------

def _open_rec_needing_rfq(settings: Settings) -> dict | None:
    return db.fetchone(
        settings,
        """SELECT r.recommendation_id, r.sku, r.reorder_grams, r.packs,
                  r.pack_size_g, r.unit_price_usd, r.total_cost_usd,
                  r.expected_lead_days, r.recommended_supplier_id,
                  r.recommended_supplier_name
             FROM liveoltp.procurement_recommendations r
            WHERE r.decision = 'BUY_NOW'
              AND NOT EXISTS (
                SELECT 1 FROM liveoltp.email_outbox o
                 WHERE o.sku = r.sku
                   AND o.supplier_id = r.recommended_supplier_id
                   AND o.intent = 'RFQ'
                   AND o.created_ts > NOW() - INTERVAL '1 day'
              )
            ORDER BY r.created_ts DESC
            LIMIT 1""",
    )


def _supplier_email(settings: Settings, supplier_id: str) -> str:
    # dim_supplier lives in Unity Catalog (not synced to Lakebase by default).
    # We keep a small lookup synced into liveoltp.supplier_leaderboard rows via
    # supplier_name; for the demo the LLM writes to a fake mailbox, so we
    # derive an email from the supplier_id if nothing is synced.
    row = db.fetchone(
        settings,
        "SELECT supplier_name FROM liveoltp.supplier_leaderboard WHERE supplier_id = %s LIMIT 1",
        [supplier_id],
    )
    name = (row or {}).get("supplier_name") or supplier_id
    slug = name.lower().split()[0].replace("'", "")
    return f"orders@{slug}.demo"


def _draft_rfq(
    settings: Settings, rec: dict, llm: FoundationModelClient
) -> str | None:
    started = _now()
    user = (
        f"SKU: {rec['sku']}\n"
        f"Quantity required: {rec['reorder_grams']:.0f} g "
        f"({rec['packs']} packs × {rec['pack_size_g']:.0f} g)\n"
        f"Current leaderboard unit price: ${rec['unit_price_usd']:.2f}\n"
        f"Current lead time: {rec['expected_lead_days']} days\n"
        f"Supplier: {rec.get('recommended_supplier_name') or rec['recommended_supplier_id']}\n"
        "Draft an RFQ email asking for a firm quote, aiming to beat the "
        "leaderboard price by 3-8% and confirm lead time."
    )
    try:
        data, resp = llm.chat_json(NEGOTIATOR_SYSTEM, user, max_tokens=700)
    except LLMError as e:
        _record_run(settings, "negotiator", rec["recommendation_id"], "",
                    "ERROR", started, error=str(e))
        return None

    thread_id = _new_id("THR")
    email_id = _new_id("EM")
    db.execute(
        settings,
        """INSERT INTO liveoltp.email_outbox
             (email_id, thread_id, created_ts, supplier_id, supplier_email,
              subject, body_md, sku, intent, sent_by, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RFQ','negotiator','SENT')""",
        [email_id, thread_id, _now(), rec["recommended_supplier_id"],
         _supplier_email(settings, rec["recommended_supplier_id"]),
         str(data.get("subject", "RFQ — seed order")),
         str(data.get("body_md", "")), rec["sku"]],
    )
    _record_run(
        settings, "negotiator", rec["recommendation_id"], thread_id,
        "OK", started, (resp.prompt_tokens, resp.output_tokens),
    )
    return thread_id


# ---------------------------------------------------------------------------
# Step 2 — process supplier replies from the inbox.
# ---------------------------------------------------------------------------

def _unprocessed_inbound(settings: Settings) -> list[dict]:
    return db.fetchall(
        settings,
        """SELECT * FROM liveoltp.email_inbox
            WHERE processed IS NOT TRUE
            ORDER BY received_ts ASC
            LIMIT 20""",
    )


EXTRACTION_SYSTEM = """You parse a seed-supplier email into JSON. Extract:
  intent_detected (one of "QUOTE","COUNTER","ACCEPT","REJECT","OOF")
  unit_price_usd (number or null)  // per pack
  pack_size_g (number or null)
  lead_time_days (integer or null)
  organic (boolean or null)
  notes  (string, <=120 chars)
Output strictly JSON only.
"""


def _process_inbound(
    settings: Settings, email: dict, llm: FoundationModelClient
) -> None:
    started = _now()
    user = f"Subject: {email['subject']}\n\n{email['body_md']}"
    try:
        data, resp = llm.chat_json(EXTRACTION_SYSTEM, user, max_tokens=400)
    except LLMError as e:
        _record_run(settings, "negotiator", email["email_id"], "",
                    "ERROR", started, error=str(e))
        db.execute(
            settings,
            "UPDATE liveoltp.email_inbox SET processed=TRUE WHERE email_id=%s",
            [email["email_id"]],
        )
        return

    intent = str(data.get("intent_detected") or "QUOTE").upper()
    db.execute(
        settings,
        """UPDATE liveoltp.email_inbox
             SET intent_detected=%s, extracted_json=%s, processed=TRUE
           WHERE email_id=%s""",
        [intent, json.dumps(data), email["email_id"]],
    )
    _record_run(
        settings, "negotiator", email["email_id"], email["thread_id"],
        "OK", started, (resp.prompt_tokens, resp.output_tokens),
    )


# ---------------------------------------------------------------------------
# Public entry — one tick of the loop.
# ---------------------------------------------------------------------------

def run_negotiator_once(settings: Settings) -> dict:
    """Run one iteration: pick a rec → draft RFQ, and process any new replies."""
    llm = FoundationModelClient()
    drafted: list[str] = []
    processed: list[str] = []

    rec = _open_rec_needing_rfq(settings)
    if rec:
        thread = _draft_rfq(settings, rec, llm)
        if thread:
            drafted.append(thread)

    for email in _unprocessed_inbound(settings):
        _process_inbound(settings, email, llm)
        processed.append(email["email_id"])

    return {"drafted_threads": drafted, "processed_inbound": processed}


# ---------------------------------------------------------------------------
# Simulated-supplier helper — called by /api/agents/simulate-reply to
# generate an inbound email on a live thread.
# ---------------------------------------------------------------------------

def simulate_supplier_reply(
    settings: Settings, thread_id: str
) -> dict:
    started = _now()
    thread = db.fetchone(
        settings,
        """SELECT * FROM liveoltp.email_outbox
            WHERE thread_id=%s ORDER BY created_ts DESC LIMIT 1""",
        [thread_id],
    )
    if not thread:
        return {"error": f"thread {thread_id} not found"}
    llm = FoundationModelClient()
    supplier_row = db.fetchone(
        settings,
        "SELECT supplier_name FROM liveoltp.supplier_leaderboard "
        "WHERE supplier_id=%s LIMIT 1",
        [thread["supplier_id"]],
    )
    supplier_name = (supplier_row or {}).get("supplier_name") or thread["supplier_id"]
    user = (
        f"You are {supplier_name}. The buyer asked about SKU {thread['sku']}.\n\n"
        f"Original email subject: {thread['subject']}\n"
        f"Original body:\n{thread['body_md']}\n\n"
        "Write your reply as JSON. 60% chance QUOTE, 25% COUNTER, 10% REJECT, 5% OOF."
    )
    try:
        data, resp = llm.chat_json(SUPPLIER_PERSONA_SYSTEM, user, max_tokens=600)
    except LLMError as e:
        return {"error": str(e)}

    email_id = _new_id("IN")
    db.execute(
        settings,
        """INSERT INTO liveoltp.email_inbox
             (email_id, thread_id, received_ts, supplier_id, supplier_email,
              subject, body_md, sku, intent_detected, extracted_json, processed)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,FALSE)""",
        [email_id, thread_id, _now(), thread["supplier_id"],
         thread["supplier_email"],
         str(data.get("subject", "Re: " + thread["subject"])),
         str(data.get("body_md", "")), thread["sku"]],
    )
    _record_run(
        settings, "supplier_persona", thread_id, email_id,
        "OK", started, (resp.prompt_tokens, resp.output_tokens),
    )
    return {"email_id": email_id, "intent": data.get("intent")}
