"""Agent trigger + state routes.

All state lives in Lakebase; these endpoints either read current state for
the dashboard or run an agent loop iteration on demand. In a real
deployment, /tick endpoints would be called by a scheduled job; during a
demo the UI calls them manually via a "Run cycle" button.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..agents import (
    run_budget_gate,
    run_negotiator_once,
    run_onboarding,
    run_po_drafter,
    run_reconciler,
)
from ..agents.db import execute, fetchall, fetchone
from ..agents.negotiator import simulate_supplier_reply
from ..config import Settings

router = APIRouter(prefix="/api/agents", tags=["agents"])


def get_settings() -> Settings:
    return Settings.from_env()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# --------------------------- Emails ----------------------------------------


@router.get("/email/threads")
def email_threads(
    limit: int = Query(25, ge=1, le=200),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    return fetchall(settings, """
        WITH last_out AS (
            SELECT DISTINCT ON (thread_id)
                   thread_id, created_ts AS last_ts, supplier_id,
                   supplier_email, sku, subject, intent, 'OUT' AS side
              FROM live.email_outbox
             ORDER BY thread_id, created_ts DESC
        ),
        last_in AS (
            SELECT DISTINCT ON (thread_id)
                   thread_id, received_ts AS last_ts, supplier_id,
                   supplier_email, sku, subject, intent_detected AS intent, 'IN' AS side
              FROM live.email_inbox
             ORDER BY thread_id, received_ts DESC
        ),
        unioned AS (
            SELECT * FROM last_out
            UNION ALL
            SELECT * FROM last_in
        ),
        rolled AS (
            SELECT DISTINCT ON (thread_id) *
              FROM unioned
             ORDER BY thread_id, last_ts DESC
        )
        SELECT * FROM rolled
        ORDER BY last_ts DESC
        LIMIT %s
    """, [limit])


@router.get("/email/thread/{thread_id}")
def email_thread(
    thread_id: str,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    return fetchall(settings, """
        SELECT email_id, thread_id, created_ts AS ts, supplier_id,
               supplier_email, subject, body_md, sku, intent, sent_by,
               status, 'OUT' AS side
          FROM live.email_outbox
         WHERE thread_id = %s
        UNION ALL
        SELECT email_id, thread_id, received_ts AS ts, supplier_id,
               supplier_email, subject, body_md, sku, intent_detected AS intent,
               NULL AS sent_by, NULL AS status, 'IN' AS side
          FROM live.email_inbox
         WHERE thread_id = %s
         ORDER BY ts ASC
    """, [thread_id, thread_id])


# --------------------------- PO drafts + budget ----------------------------


@router.get("/po_drafts")
def po_drafts(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if status:
        return fetchall(settings,
            "SELECT * FROM live.po_drafts WHERE status=%s "
            "ORDER BY created_ts DESC LIMIT %s",
            [status.upper(), limit])
    return fetchall(settings,
        "SELECT * FROM live.po_drafts ORDER BY created_ts DESC LIMIT %s",
        [limit])


@router.get("/budget")
def budget(settings: Settings = Depends(get_settings)) -> dict:
    n = _now()
    period = f"{n.year:04d}-{n.month:02d}"
    row = fetchone(settings,
        "SELECT balance_usd, entry_ts FROM live.budget_ledger "
        "WHERE period_ym=%s AND category='SEED' "
        "ORDER BY entry_ts DESC LIMIT 1",
        [period])
    entries = fetchall(settings,
        "SELECT * FROM live.budget_ledger WHERE period_ym=%s "
        "ORDER BY entry_ts DESC LIMIT 20", [period])
    return {
        "period_ym": period,
        "balance_usd": float(row["balance_usd"]) if row else None,
        "last_entry_ts": row["entry_ts"] if row else None,
        "entries": entries,
    }


# --------------------------- Applications + invoices -----------------------


@router.get("/applications")
def applications(
    status: str | None = None,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if status:
        return fetchall(settings,
            "SELECT * FROM live.supplier_applications WHERE status=%s "
            "ORDER BY submitted_ts DESC",
            [status.upper()])
    return fetchall(settings,
        "SELECT * FROM live.supplier_applications "
        "ORDER BY submitted_ts DESC LIMIT 50")


@router.post("/applications")
def submit_application(
    payload: dict,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Submit a supplier application (demo UI form POST)."""
    required = {"supplier_name", "contact_email", "country"}
    missing = required - set(payload.keys())
    if missing:
        raise HTTPException(400, f"missing fields: {missing}")
    app_id = _new_id("APP")
    execute(settings, """
        INSERT INTO live.supplier_applications
          (application_id, submitted_ts, supplier_name, contact_email,
           country, offered_skus, organic_cert, years_in_biz, status,
           score, agent_notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'NEW', NULL, NULL)
    """, [
        app_id, _now(),
        payload["supplier_name"], payload["contact_email"], payload["country"],
        payload.get("offered_skus", ""),
        bool(payload.get("organic_cert", False)),
        int(payload.get("years_in_biz", 0) or 0),
    ])
    return {"application_id": app_id, "status": "NEW"}


@router.get("/invoices")
def invoices(
    status: str | None = None,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if status:
        return fetchall(settings,
            "SELECT * FROM live.invoice_reconciliations WHERE status=%s "
            "ORDER BY received_ts DESC LIMIT 100",
            [status.upper()])
    return fetchall(settings,
        "SELECT * FROM live.invoice_reconciliations "
        "ORDER BY received_ts DESC LIMIT 100")


@router.get("/runs")
def agent_runs(
    limit: int = Query(50, ge=1, le=500),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    return fetchall(settings,
        "SELECT * FROM live.agent_runs ORDER BY started_ts DESC LIMIT %s",
        [limit])


# --------------------------- Agent tick endpoints ---------------------------


@router.post("/negotiator/tick")
def negotiator_tick(settings: Settings = Depends(get_settings)) -> dict:
    return run_negotiator_once(settings)


@router.post("/negotiator/simulate-reply")
def simulate_reply(
    thread_id: str = Query(..., min_length=4),
    settings: Settings = Depends(get_settings),
) -> dict:
    return simulate_supplier_reply(settings, thread_id)


@router.post("/po_drafter/tick")
def po_drafter_tick(settings: Settings = Depends(get_settings)) -> dict:
    return run_po_drafter(settings)


@router.post("/budget_gate/tick")
def budget_gate_tick(settings: Settings = Depends(get_settings)) -> dict:
    return run_budget_gate(settings)


@router.post("/onboarding/tick")
def onboarding_tick(settings: Settings = Depends(get_settings)) -> dict:
    return run_onboarding(settings)


@router.post("/reconciler/tick")
def reconciler_tick(settings: Settings = Depends(get_settings)) -> dict:
    return run_reconciler(settings)


@router.post("/cycle")
def full_cycle(settings: Settings = Depends(get_settings)) -> dict:
    """Run the full agent chain in order. Handy for the demo."""
    out: dict[str, Any] = {}
    out["negotiator"] = run_negotiator_once(settings)
    out["po_drafter"] = run_po_drafter(settings)
    out["budget_gate"] = run_budget_gate(settings)
    out["onboarding"] = run_onboarding(settings)
    out["reconciler"] = run_reconciler(settings)
    return out
