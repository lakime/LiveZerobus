from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .generator import generate_all
from .routes.admin import router as admin_router
from .routes.tables import router as tables_router
from .sharing.router import router as sharing_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger(__name__)


def _resolve_static_dir() -> Path:
    """Find frontend/dist regardless of how Databricks Apps lays out the code.

    Tries: alongside the app package, cwd, /app, /home/app, and walks up
    from __file__ until it finds a `frontend/dist/index.html`.
    """
    candidates = [
        Path(__file__).parent.parent / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
        Path("/app/frontend/dist"),
        Path("/home/app/frontend/dist"),
    ]
    p = Path(__file__).resolve()
    for _ in range(6):
        candidates.append(p / "frontend" / "dist")
        p = p.parent
    for c in candidates:
        try:
            if (c / "index.html").exists():
                log.info("Resolved STATIC_DIR=%s", c)
                return c
        except Exception:
            continue
    log.warning("Could not find frontend/dist; tried: %s", [str(c) for c in candidates])
    return candidates[0]


STATIC_DIR = _resolve_static_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.settings = settings
    log.info("SAP BDC service starting — host=%s data_dir=%s", settings.host, settings.data_dir)
    generate_all(settings)
    yield
    log.info("SAP BDC service stopped")


app = FastAPI(
    title="SAP Business Data Cloud — Mock",
    version="1.0.0",
    description="Delta Sharing provider with 15 SAP procurement tables",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if os.environ.get("DEV") else [],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sharing_router, prefix="/delta-sharing")
app.include_router(tables_router)
app.include_router(admin_router)


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/api/debug")
def debug():
    return {
        "static_dir": str(STATIC_DIR),
        "static_dir_exists": STATIC_DIR.exists(),
        "index_exists": (STATIC_DIR / "index.html").exists(),
        "file": __file__,
        "cwd": str(Path.cwd()),
    }


_INDEX = STATIC_DIR / "index.html"
_FALLBACK_HTML = """<!doctype html>
<meta charset=utf-8><title>SAP BDC</title>
<style>body{font-family:system-ui;margin:2rem;max-width:42rem}</style>
<h1>SAP Business Data Cloud — Mock</h1>
<p>Service is running. Frontend bundle was not found on disk.</p>
<ul>
<li><a href="/api/info">/api/info</a></li>
<li><a href="/api/tables">/api/tables</a></li>
<li><a href="/api/profile.json">/api/profile.json</a></li>
<li><a href="/api/debug">/api/debug</a></li>
</ul>"""

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if _INDEX.exists():
        return FileResponse(str(_INDEX), headers={"Cache-Control": "no-store"})
    return HTMLResponse(_FALLBACK_HTML, status_code=200)
