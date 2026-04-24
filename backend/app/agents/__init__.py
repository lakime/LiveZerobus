"""Agent layer.

Each agent is a stateless function that reads rows from Lakebase, calls the
Databricks Foundation Model API for reasoning, and writes result rows back
to Lakebase. A thin FastAPI layer (routes/agents.py) triggers them on
demand; a future scheduler could run them on a cron.
"""
from .llm import FoundationModelClient, LLMError
from .negotiator import run_negotiator_once
from .po_drafter import run_po_drafter
from .budget_gate import run_budget_gate
from .supplier_onboarding import run_onboarding
from .invoice_reconciler import run_reconciler

__all__ = [
    "FoundationModelClient",
    "LLMError",
    "run_negotiator_once",
    "run_po_drafter",
    "run_budget_gate",
    "run_onboarding",
    "run_reconciler",
]
