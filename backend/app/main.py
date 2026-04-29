"""FastAPI entrypoint for the LiveZerobus Databricks App.

Serves two things:
  * JSON API at /api/*  — read-only live queries against Lakebase.
  * The compiled React bundle at /         — static assets + SPA fallback.
"""
from __future__ import annotations

import os
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .routes.agents import router as agents_router
from .routes.data import router as data_router


settings = Settings.from_env()
app = FastAPI(title="LiveZerobus — Seed Procurement", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if os.environ.get("DEV") else [],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(data_router)
app.include_router(agents_router)


@app.get("/healthz")
def health() -> dict:
    return {"ok": True}


# --- Static frontend ----------------------------------------------------------

_FRONTEND = pathlib.Path(settings.frontend_dist).resolve()
if _FRONTEND.is_dir():
    # mount assets at /assets and keep / as SPA fallback
    app.mount("/assets", StaticFiles(directory=_FRONTEND / "assets"), name="assets")

    def _no_cache_html() -> FileResponse:
        return FileResponse(
            _FRONTEND / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/")
    def root() -> FileResponse:
        return _no_cache_html()

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        target = _FRONTEND / full_path
        if target.is_file():
            return FileResponse(target)
        return _no_cache_html()
else:
    @app.get("/")
    def root_fallback() -> dict:
        return {
            "msg": "Frontend bundle not found. Build with `cd frontend && npm run build`.",
            "api": "/api/summary, /api/inventory, /api/suppliers/leaderboard, "
                   "/api/commodity/latest, /api/demand/hourly, /api/recommendations",
        }
