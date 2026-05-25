"""Tells the frontend the URL of the Genie space to iframe-embed."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings

router = APIRouter(prefix="/api/genie", tags=["genie"])


def get_settings() -> Settings:
    return Settings.from_env()


@router.get("/info")
def info(settings: Settings = Depends(get_settings)) -> dict:
    """Return Genie iframe URL or signal that nothing is configured."""
    if not (settings.genie_space_id and settings.databricks_host):
        return {
            "configured": False,
            "reason": "GENIE_SPACE_ID or DATABRICKS_HOST not set on backend",
        }
    # Standalone embed URL — Databricks Genie spaces have a `/_/embed` view
    # that hides the workspace chrome. The browser must already have a
    # Databricks session (which it does, since livezerobus is itself a
    # Databricks App and the user is OAuth-authenticated).
    base = settings.databricks_host
    space_id = settings.genie_space_id
    # /embed/genie/rooms/{id} ships with `Content-Security-Policy:
    # frame-ancestors *` so it's iframeable from anywhere.
    # /genie/rooms/{id} is the full-app URL — opens fine in a new tab
    # but is blocked from iframes by X-Frame-Options.
    return {
        "configured": True,
        "space_id": space_id,
        "url": f"{base}/embed/genie/rooms/{space_id}",
        "url_alt": f"{base}/genie/rooms/{space_id}",
    }
