from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .generator import generate_all
from .routes.admin import router as admin_router
from .routes.tables import router as tables_router
from .sharing.router import router as sharing_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"


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


# Serve React SPA — static assets first, then fallback to index.html
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        index = STATIC_DIR / "index.html"
        return FileResponse(str(index), headers={"Cache-Control": "no-store"})
