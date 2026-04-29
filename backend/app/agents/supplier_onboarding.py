"""Supplier onboarding agent.

Processes new supplier applications in `procurement.supplier_applications`:
  * Asks the LLM to score the applicant 0..1 against a rubric.
  * Marks APPROVED (score >= 0.75), SCREENING (0.5-0.75), or REJECTED (<0.5).
  * Writes a friendly notes summary.

In the demo, applications are submitted via the React UI; in a real
deployment this would ingest a Typeform/Email connector.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..config import Settings
from . import db
from .llm import FoundationModelClient, LLMError


SYSTEM = """You are a supplier-onboarding analyst at a vertical-farm company.
Score an incoming supplier application on a 0..1 scale using this rubric:
  * Relevance of offered SKUs to our catalog (lettuce, basil, kale, microgreens,
    herbs, arugula, asian greens) — 0.40 weight
  * Organic certification          — 0.25 weight
  * Years in business (>=5 great)  — 0.20 weight
  * Country / shipping reach       — 0.15 weight

Output strictly JSON:
  score (number 0..1)
  verdict (one of "APPROVED","SCREENING","REJECTED")
  notes (string, <=180 chars, friendly, specific)
"""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def run_onboarding(settings: Settings) -> dict:
    llm = FoundationModelClient()
    apps = db.fetchall(
        settings,
        """SELECT * FROM procurement.supplier_applications
            WHERE status IN ('NEW','SCREENING')
            ORDER BY submitted_ts ASC
            LIMIT 25""",
    )
    processed: list[dict] = []
    for a in apps:
        started = _now()
        user = (
            f"Supplier name: {a['supplier_name']}\n"
            f"Country: {a['country']}\n"
            f"Contact: {a['contact_email']}\n"
            f"Offered SKUs: {a['offered_skus']}\n"
            f"Organic certified: {a['organic_cert']}\n"
            f"Years in business: {a['years_in_biz']}\n"
        )
        try:
            data, resp = llm.chat_json(SYSTEM, user, max_tokens=250)
        except LLMError as e:
            db.execute(
                settings,
                "UPDATE procurement.supplier_applications SET agent_notes=%s WHERE application_id=%s",
                [f"LLM error: {e}", a["application_id"]],
            )
            continue

        verdict = str(data.get("verdict", "SCREENING")).upper()
        score = float(data.get("score") or 0.5)
        notes = str(data.get("notes", ""))[:180]
        db.execute(
            settings,
            """UPDATE procurement.supplier_applications
                  SET status=%s, score=%s, agent_notes=%s
                WHERE application_id=%s""",
            [verdict, score, notes, a["application_id"]],
        )
        db.execute(
            settings,
            """INSERT INTO procurement.agent_runs
                 (run_id, started_ts, finished_ts, agent_name, input_ref,
                  output_ref, prompt_tokens, output_tokens, status, error_msg)
               VALUES (%s,%s,%s,'supplier_onboarding',%s,%s,%s,%s,'OK',NULL)""",
            [_new_id("RUN"), started, _now(),
             a["application_id"], verdict,
             resp.prompt_tokens, resp.output_tokens],
        )
        processed.append({"application_id": a["application_id"],
                          "verdict": verdict, "score": score})

    return {"processed": processed}
