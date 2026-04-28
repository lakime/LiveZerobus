"""Local web GUI for running and monitoring Zerobus simulators.

Usage:
    pip install fastapi uvicorn
    cd simulators
    python sim_ui.py

Then open http://localhost:7777 in your browser.

Required environment variables (same as simulators):
    DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET,
    ZEROBUS_ENDPOINT
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Simulator registry
# ---------------------------------------------------------------------------

SIMULATORS: dict[str, dict[str, Any]] = {
    "inventory": {
        "script": "inventory_simulator.py",
        "label": "Inventory",
        "description": "Seed stock movements — GR / plant / adjust / expiry events per SKU and room",
        "color": "#4ea1ff",
        "default_rate": 2,
    },
    "suppliers": {
        "script": "supplier_quotes_simulator.py",
        "label": "Supplier Quotes",
        "description": "Rolling seed-pack price quotes from 10 seed houses with organic flag and lead time",
        "color": "#21c07a",
        "default_rate": 1,
    },
    "demand": {
        "script": "demand_simulator.py",
        "label": "Demand",
        "description": "Planting schedule — trays seeded per zone driving grams-required downstream",
        "color": "#f2b840",
        "default_rate": 3,
    },
    "commodity": {
        "script": "commodity_simulator.py",
        "label": "Commodity Prices",
        "description": "Grow-input price feed: coco coir, peat, rockwool, nutrient packs, kWh",
        "color": "#b06bff",
        "default_rate": 1,
    },
    "sap": {
        "script": "sap_simulator.py",
        "label": "SAP P2P",
        "description": "Procure-to-Pay cycle: PO → goods receipt → 3-way invoice match",
        "color": "#ff8c42",
        "default_rate": 1,
    },
    "iot": {
        "script": "iot_simulator.py",
        "label": "IoT Sensors",
        "description": "6 grow-room sensors: temperature, humidity, soil moisture, light, CO₂, pH, EC",
        "color": "#00d4aa",
        "default_rate": 1,
    },
}

# ---------------------------------------------------------------------------
# Process state
# ---------------------------------------------------------------------------

_processes: dict[str, subprocess.Popen | None] = {k: None for k in SIMULATORS}
_event_counts: dict[str, int] = {k: 0 for k in SIMULATORS}
_event_rates: dict[str, float] = {k: 0.0 for k in SIMULATORS}
_start_times: dict[str, float] = {k: 0.0 for k in SIMULATORS}

# SSE subscribers: each is an asyncio.Queue
_subscribers: list[asyncio.Queue] = []
_main_loop: asyncio.AbstractEventLoop | None = None

# Ring buffer for replay when a client first connects
_log_buffer: list[dict] = []
_LOG_BUFFER_MAX = 300

_SENT_RE = re.compile(r"sent=(\d+)")

# ---------------------------------------------------------------------------
# Lakebase sync state
# ---------------------------------------------------------------------------

_sync_running = False
_sync_last_ts: float = 0.0
_sync_last_result: str = "never"   # "success" | "error" | "never"
_sync_next_at: float = 0.0
_SYNC_INTERVAL = 60                # seconds between automatic syncs


def _broadcast(msg: dict) -> None:
    _log_buffer.append(msg)
    if len(_log_buffer) > _LOG_BUFFER_MAX:
        _log_buffer.pop(0)
    if _main_loop:
        for q in list(_subscribers):
            try:
                asyncio.run_coroutine_threadsafe(q.put(msg), _main_loop)
            except Exception:
                pass


def _reader_thread(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        # Parse event count from "[table] sent=NNN rate=R/s" lines
        m = _SENT_RE.search(line)
        if m:
            _event_counts[name] = int(m.group(1))
        # Parse rate if present
        rate_m = re.search(r"rate=([\d.]+)/s", line)
        if rate_m:
            _event_rates[name] = float(rate_m.group(1))
        # Parse IoT cycle line
        iot_m = re.search(r"cycle=(\d+)", line)
        if iot_m:
            cycles = int(iot_m.group(1))
            sensors_per_cycle_m = re.search(r"sensors/cycle=(\d+)", line)
            if sensors_per_cycle_m:
                _event_counts[name] = cycles * int(sensors_per_cycle_m.group(1))

        _broadcast({"sim": name, "msg": line, "ts": time.time()})

    rc = proc.wait()
    _processes[name] = None
    _broadcast({"sim": name, "msg": f"[{name}] exited — return code {rc}", "ts": time.time(), "exit": True})


def _start(name: str, catalog: str, schema: str, rate: int) -> dict:
    if _processes.get(name):
        return {"ok": False, "error": f"{name} is already running"}
    spec = SIMULATORS[name]
    cmd = [
        sys.executable, spec["script"],
        f"--catalog={catalog}", f"--schema={schema}", f"--rate={rate}",
    ]
    env = {**os.environ}  # inherit all env vars (DATABRICKS_HOST etc.)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    _processes[name] = proc
    _event_counts[name] = 0
    _event_rates[name] = 0.0
    _start_times[name] = time.time()
    t = threading.Thread(target=_reader_thread, args=(name, proc), daemon=True)
    t.start()
    _broadcast({"sim": name, "msg": f"▶ Started {name} — pid={proc.pid}", "ts": time.time()})
    return {"ok": True, "pid": proc.pid}


def _stop(name: str) -> dict:
    proc = _processes.get(name)
    if not proc:
        return {"ok": False, "error": f"{name} is not running"}
    proc.terminate()
    _processes[name] = None
    _broadcast({"sim": name, "msg": f"■ Stopped {name}", "ts": time.time()})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Lakebase sync helpers
# ---------------------------------------------------------------------------

async def _run_sync_once() -> None:
    global _sync_running, _sync_last_ts, _sync_last_result
    if _sync_running:
        return
    _sync_running = True
    _broadcast({"sim": "sync", "msg": "▶ Lakebase sync starting…", "ts": time.time()})
    try:
        apply_py = str(
            pathlib.Path(__file__).resolve().parent.parent / "lakebase_sync" / "apply.py"
        )
        proc = await asyncio.create_subprocess_exec(
            sys.executable, apply_py,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = (stdout or b"").decode(errors="replace")
        for line in output.splitlines():
            if line.strip():
                _broadcast({"sim": "sync", "msg": line, "ts": time.time()})
        _sync_last_ts = time.time()
        if proc.returncode == 0:
            _sync_last_result = "success"
            _broadcast({"sim": "sync", "msg": "✔ Lakebase sync complete", "ts": time.time()})
        else:
            _sync_last_result = "error"
            _broadcast({"sim": "sync", "msg": f"✗ Sync failed (rc={proc.returncode})", "ts": time.time()})
    except Exception as exc:
        _sync_last_result = "error"
        _broadcast({"sim": "sync", "msg": f"✗ Sync error: {exc}", "ts": time.time()})
    finally:
        _sync_running = False


async def _sync_loop() -> None:
    global _sync_next_at
    await asyncio.sleep(10)          # brief startup delay
    while True:
        _sync_next_at = time.time() + _SYNC_INTERVAL
        await _run_sync_once()
        await asyncio.sleep(_SYNC_INTERVAL)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    task = asyncio.create_task(_sync_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="SimUI", docs_url=None, redoc_url=None, lifespan=_lifespan)


# ── REST endpoints ───────────────────────────────────────────────────────────


@app.get("/api/simulators")
def get_simulators():
    result = {}
    for name, spec in SIMULATORS.items():
        proc = _processes.get(name)
        running = proc is not None and proc.poll() is None
        result[name] = {
            **spec,
            "running": running,
            "pid": proc.pid if running else None,
            "event_count": _event_counts[name],
            "event_rate": _event_rates[name],
            "uptime_s": int(time.time() - _start_times[name]) if running else 0,
        }
    return result


@app.post("/api/simulators/{name}/start")
def start_sim(name: str, catalog: str = "livezerobus", schema: str = "procurement", rate: int = 0):
    if name not in SIMULATORS:
        return {"ok": False, "error": "Unknown simulator"}
    effective_rate = rate or SIMULATORS[name]["default_rate"]
    return _start(name, catalog, schema, effective_rate)


@app.post("/api/simulators/{name}/stop")
def stop_sim(name: str):
    if name not in SIMULATORS:
        return {"ok": False, "error": "Unknown simulator"}
    return _stop(name)


@app.post("/api/simulators/start-all")
def start_all(catalog: str = "livezerobus", schema: str = "procurement"):
    results = {}
    for name, spec in SIMULATORS.items():
        results[name] = _start(name, catalog, schema, spec["default_rate"])
    return results


@app.post("/api/simulators/stop-all")
def stop_all():
    return {name: _stop(name) for name in SIMULATORS}


@app.delete("/api/logs")
def clear_logs():
    _log_buffer.clear()
    return {"ok": True}


# ── SSE log stream ───────────────────────────────────────────────────────────


@app.get("/api/logs")
async def sse_logs():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)

    async def gen():
        try:
            # Replay buffer first
            for entry in list(_log_buffer):
                yield f"data: {json.dumps(entry)}\n\n"
            # Then stream live
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"ping\":true}\n\n"  # keep-alive
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Environment check ────────────────────────────────────────────────────────


@app.get("/api/env")
def check_env():
    keys = ["DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET", "ZEROBUS_ENDPOINT"]
    return {k: ("✓ set" if os.environ.get(k) else "✗ missing") for k in keys}


@app.get("/api/sync-status")
def get_sync_status():
    return {
        "running": _sync_running,
        "last_ts": _sync_last_ts,
        "last_result": _sync_last_result,
        "next_in_s": max(0, int(_sync_next_at - time.time())) if _sync_next_at else None,
    }


@app.post("/api/sync-now")
async def trigger_sync_now():
    asyncio.create_task(_run_sync_once())
    return {"ok": True}


# ── Serve the HTML UI ────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LiveZerobus · Simulator Control</title>
<style>
:root {
  color-scheme: dark;
  --bg:     #0b1020; --panel:  #141a2f; --panel2: #1a2140;
  --border: #263056; --text:   #eaf0ff; --muted:  #8a97b8;
  --accent: #4ea1ff; --good:   #21c07a; --warn:   #f2b840; --bad: #ef4a4a;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); min-height: 100vh; }

.app { max-width: 1400px; margin: 0 auto; padding: 20px 24px 40px; }

header {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 14px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
}
header h1 { font-size: 20px; letter-spacing: 0.3px; }
.live { font-size: 12px; color: var(--good); }

.config-bar {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 14px; margin-bottom: 16px;
}
.config-bar label { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.config-bar input {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 9px; font-size: 13px; width: 160px;
}
.config-bar input:focus { outline: none; border-color: var(--accent); }
.sep { width: 1px; height: 24px; background: var(--border); }

.env-bar {
  display: flex; gap: 10px; flex-wrap: wrap;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 8px 14px; margin-bottom: 20px;
  font-size: 11px;
}
.env-item { display: flex; gap: 5px; align-items: center; }
.env-item .key { color: var(--muted); }
.env-ok  { color: var(--good); }
.env-bad { color: var(--bad); }

.sim-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.sim-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-top: 3px solid var(--card-color, var(--accent));
  border-radius: 12px;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color 0.2s;
}
.sim-card.running { box-shadow: 0 0 16px rgba(0,0,0,0.3); }

.sim-header { display: flex; justify-content: space-between; align-items: flex-start; }
.sim-name { font-weight: 700; font-size: 15px; }
.sim-desc { font-size: 11px; color: var(--muted); line-height: 1.4; }

.status-dot {
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; margin-top: 3px;
  transition: background 0.3s, box-shadow 0.3s;
}
.status-dot.running {
  background: var(--good);
  box-shadow: 0 0 8px var(--good);
  animation: pulse 1.8s ease infinite;
}
.status-dot.stopped { background: var(--muted); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.45} }

.sim-meta {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 6px; font-size: 12px;
}
.meta-item .label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing:.8px; }
.meta-item .value { font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }

.sim-controls { display: flex; gap: 8px; align-items: center; }
.rate-input {
  width: 56px; background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 8px; font-size: 12px; text-align: center;
}
.rate-input:focus { outline: none; border-color: var(--accent); }

.btn {
  background: var(--panel2); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 14px; font-size: 13px; cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.btn:hover { background: #222a52; border-color: var(--accent); }
.btn:disabled { opacity: .5; cursor: default; }
.btn.start { border-color: var(--good); color: var(--good); }
.btn.start:hover { background: rgba(33,192,122,0.12); }
.btn.stop  { border-color: var(--bad);  color: var(--bad);  }
.btn.stop:hover  { background: rgba(239,74,74,0.12); }
.btn.all { padding: 8px 18px; }

.log-panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden;
}
.log-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  font-size: 12px; color: var(--muted);
}
.log-filter {
  display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
}
.chip {
  padding: 2px 10px; border-radius: 99px; font-size: 11px; cursor: pointer;
  border: 1px solid var(--border); color: var(--muted); background: transparent;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  user-select: none;
}
.chip.on { color: #0b0f1a; font-weight: 600; }
.chip:hover:not(.on) { border-color: var(--accent); color: var(--text); }

#log-output {
  font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, Consolas, monospace;
  font-size: 12px; line-height: 1.6;
  height: 320px; overflow-y: auto; padding: 10px 14px;
  color: #a8b6d8;
}
.log-line { display: flex; gap: 8px; }
.log-ts { color: #4d5a7a; flex-shrink: 0; width: 74px; }
.log-sim { flex-shrink: 0; width: 80px; font-weight: 600; }
.log-msg { word-break: break-all; }
.log-line.exit .log-msg { color: var(--bad); }

/* Pipeline panel */
.pipeline-panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; margin-bottom: 20px;
}
.pipeline-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 9px 14px; border-bottom: 1px solid var(--border);
  font-size: 11px; color: var(--muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px;
}
.sync-dot { font-size: 10px; transition: color 0.3s; }
.sync-dot.idle    { color: var(--muted); }
.sync-dot.ok      { color: var(--good); }
.sync-dot.error   { color: var(--bad); }
.sync-dot.running { color: var(--accent); animation: pulse 1s ease infinite; }
@keyframes lb-pulse {
  0%,100% { stroke-opacity:1; } 50% { stroke-opacity:0.25; }
}
</style>
</head>
<body>
<div class="app">

<header>
  <h1>LiveZerobus · Simulator Control</h1>
  <div style="display:flex;gap:12px;align-items:center">
    <button class="btn all start" onclick="startAll()">▶ Start all</button>
    <button class="btn all stop"  onclick="stopAll()">■ Stop all</button>
    <span class="live" id="clock">●</span>
  </div>
</header>

<div class="config-bar">
  <label>Catalog <input id="cfg-catalog" value="livezerobus"></label>
  <label>Schema  <input id="cfg-schema"  value="procurement"></label>
  <div class="sep"></div>
  <span id="env-summary" style="font-size:12px;color:var(--muted)">Checking env…</span>
</div>

<div id="env-bar" class="env-bar" style="display:none"></div>

<div class="sim-grid" id="sim-grid"></div>

<!-- ═══ Pipeline visualization ═══════════════════════════════════════════ -->
<div class="pipeline-panel">
  <div class="pipeline-header">
    <span>Data Pipeline · Lakeflow SDP</span>
    <div style="display:flex;gap:10px;align-items:center">
      <span class="sync-dot idle" id="sync-badge">●</span>
      <span style="font-size:11px;color:var(--muted)" id="sync-last-info">Last sync: never</span>
      <span style="font-size:11px;color:var(--muted)" id="sync-next-info"></span>
      <button class="btn" style="padding:3px 10px;font-size:11px" onclick="triggerSync()">⟳ Sync now</button>
    </div>
  </div>
  <div style="padding:10px 14px 16px;overflow-x:auto;text-align:center">
    <svg id="pipeline-svg" viewBox="0 0 660 310" width="660" height="310"
         style="display:inline-block;max-width:100%;font-family:'JetBrains Mono',Menlo,Consolas,monospace">

      <!-- ── Background vertical pipe ──────────────────────────── -->
      <line x1="330" y1="70" x2="330" y2="290" stroke="#1d2544" stroke-width="3"/>

      <!-- ── Sim → Zerobus convergence paths (dashed) ──────────── -->
      <path d="M 55,43 C 55,58 330,58 330,70"  fill="none" stroke="#4ea1ff" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>
      <path d="M 165,43 C 165,58 330,58 330,70" fill="none" stroke="#21c07a" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>
      <path d="M 275,43 C 275,58 330,58 330,70" fill="none" stroke="#f2b840" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>
      <path d="M 385,43 C 385,58 330,58 330,70" fill="none" stroke="#b06bff" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>
      <path d="M 495,43 C 495,58 330,58 330,70" fill="none" stroke="#ff8c42" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>
      <path d="M 605,43 C 605,58 330,58 330,70" fill="none" stroke="#00d4aa" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="3,3"/>

      <!-- ── Stage boxes ─────────────────────────────────────────── -->
      <!-- Zerobus -->
      <rect x="240" y="70"  width="180" height="24" rx="4" fill="#0d111e" stroke="#ff6640" stroke-width="1.2"/>
      <rect x="240" y="70"  width="4"   height="24" rx="1" fill="#ff6640"/>
      <text x="252" y="86" font-size="10" fill="#ff8c68">Zerobus · Delta ingest</text>
      <!-- Bronze -->
      <rect x="240" y="110" width="180" height="24" rx="4" fill="#0d111e" stroke="#cd8832" stroke-width="1.2"/>
      <rect x="240" y="110" width="4"   height="24" rx="1" fill="#cd8832"/>
      <text x="252" y="126" font-size="10" fill="#d9a050">Bronze Δ  ·  raw events</text>
      <!-- Silver -->
      <rect x="240" y="150" width="180" height="24" rx="4" fill="#0d111e" stroke="#9baecf" stroke-width="1.2"/>
      <rect x="240" y="150" width="4"   height="24" rx="1" fill="#9baecf"/>
      <text x="252" y="166" font-size="10" fill="#b0c2de">Silver Δ  ·  validated</text>
      <!-- Gold -->
      <rect x="240" y="190" width="180" height="24" rx="4" fill="#0d111e" stroke="#f5c542" stroke-width="1.2"/>
      <rect x="240" y="190" width="4"   height="24" rx="1" fill="#f5c542"/>
      <text x="252" y="206" font-size="10" fill="#f5cc5a">Gold Δ  ·  ML-scored</text>
      <!-- Lakebase -->
      <rect x="240" y="230" width="180" height="24" rx="4" fill="#0d111e" stroke="#21c07a" stroke-width="1.2" id="lb-box"/>
      <rect x="240" y="230" width="4"   height="24" rx="1" fill="#21c07a"/>
      <text x="252" y="246" font-size="10" fill="#3dd68c">Lakebase Postgres</text>
      <!-- FastAPI / React -->
      <rect x="240" y="270" width="180" height="24" rx="4" fill="#0d111e" stroke="#4ea1ff" stroke-width="1.2"/>
      <rect x="240" y="270" width="4"   height="24" rx="1" fill="#4ea1ff"/>
      <text x="252" y="286" font-size="10" fill="#6ab8ff">FastAPI · React UI</text>

      <!-- ── Sync branch (left of Lakebase) ─────────────────────── -->
      <line x1="100" y1="242" x2="237" y2="242" stroke="#21c07a" stroke-width="1.5" stroke-opacity="0.45" stroke-dasharray="4,3"/>
      <polygon points="233,239 241,242 233,245" fill="#21c07a" opacity="0.6"/>
      <text x="168" y="235" text-anchor="middle" font-size="8" fill="#21c07a" font-weight="600" letter-spacing="0.8">LAKEBASE SYNC</text>
      <text x="168" y="255" text-anchor="middle" font-size="8"  fill="#8a97b8" id="sync-ts-svg">never</text>

      <!-- ── Sim nodes ───────────────────────────────────────────── -->
      <circle id="node-inv" cx="55"  cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="55"  y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">Inv</text>
      <text x="55"  y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">Inventory</text>

      <circle id="node-sup" cx="165" cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="165" y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">Sup</text>
      <text x="165" y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">Supplier</text>

      <circle id="node-dem" cx="275" cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="275" y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">Dem</text>
      <text x="275" y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">Demand</text>

      <circle id="node-cmd" cx="385" cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="385" y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">Cmd</text>
      <text x="385" y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">Commodity</text>

      <circle id="node-sap" cx="495" cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="495" y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">SAP</text>
      <text x="495" y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">SAP P2P</text>

      <circle id="node-iot" cx="605" cy="30" r="13" fill="#0d111e" stroke="#263056" stroke-width="1.5"/>
      <text x="605" y="34" text-anchor="middle" font-size="8.5" fill="#8a97b8" pointer-events="none">IoT</text>
      <text x="605" y="53" text-anchor="middle" font-size="7"   fill="#4d5a7a" pointer-events="none">IoT Sensors</text>

      <!-- ── Sim spark particles (hidden until sim is running) ──── -->
      <g id="sparks-inv" style="opacity:0">
        <circle r="2.5" fill="#4ea1ff"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0s"    path="M 55,43 C 55,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#4ea1ff"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.6s"  path="M 55,43 C 55,58 330,58 330,70"/></circle>
      </g>
      <g id="sparks-sup" style="opacity:0">
        <circle r="2.5" fill="#21c07a"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.1s"  path="M 165,43 C 165,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#21c07a"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.7s"  path="M 165,43 C 165,58 330,58 330,70"/></circle>
      </g>
      <g id="sparks-dem" style="opacity:0">
        <circle r="2.5" fill="#f2b840"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.2s"  path="M 275,43 C 275,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#f2b840"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.8s"  path="M 275,43 C 275,58 330,58 330,70"/></circle>
      </g>
      <g id="sparks-cmd" style="opacity:0">
        <circle r="2.5" fill="#b06bff"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.3s"  path="M 385,43 C 385,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#b06bff"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.9s"  path="M 385,43 C 385,58 330,58 330,70"/></circle>
      </g>
      <g id="sparks-sap" style="opacity:0">
        <circle r="2.5" fill="#ff8c42"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.4s"  path="M 495,43 C 495,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#ff8c42"><animateMotion dur="1.2s" repeatCount="indefinite" begin="1.0s"  path="M 495,43 C 495,58 330,58 330,70"/></circle>
      </g>
      <g id="sparks-iot" style="opacity:0">
        <circle r="2.5" fill="#00d4aa"><animateMotion dur="1.2s" repeatCount="indefinite" begin="0.5s"  path="M 605,43 C 605,58 330,58 330,70"/></circle>
        <circle r="2.5" fill="#00d4aa"><animateMotion dur="1.2s" repeatCount="indefinite" begin="1.1s"  path="M 605,43 C 605,58 330,58 330,70"/></circle>
      </g>

      <!-- ── Main pipe flow particles ──────────────────────────── -->
      <g id="main-particles" style="opacity:0">
        <circle r="3" fill="#4ea1ff" opacity="0.8"><animateMotion dur="2.0s" repeatCount="indefinite" begin="0s"   path="M 330,70 L 330,290"/></circle>
        <circle r="3" fill="#f5c542" opacity="0.8"><animateMotion dur="2.0s" repeatCount="indefinite" begin="0.5s" path="M 330,70 L 330,290"/></circle>
        <circle r="3" fill="#21c07a" opacity="0.8"><animateMotion dur="2.0s" repeatCount="indefinite" begin="1.0s" path="M 330,70 L 330,290"/></circle>
        <circle r="3" fill="#cd8832" opacity="0.8"><animateMotion dur="2.0s" repeatCount="indefinite" begin="1.5s" path="M 330,70 L 330,290"/></circle>
      </g>

      <!-- ── Sync branch particle ──────────────────────────────── -->
      <g id="sync-particles" style="opacity:0">
        <circle r="2.5" fill="#21c07a" opacity="0.9"><animateMotion dur="0.8s" repeatCount="indefinite" begin="0s" path="M 100,242 L 238,242"/></circle>
      </g>
    </svg>
  </div>
</div>

<div class="log-panel">
  <div class="log-header">
    <div class="log-filter" id="log-filter">
      <span style="color:var(--muted);margin-right:4px">Filter:</span>
      <button class="chip on" data-sim="all" onclick="setFilter('all',this)" style="background:var(--accent);border-color:var(--accent)">ALL</button>
      <button class="chip" data-sim="sync" onclick="setFilter('sync',this)" style="border-color:#21c07a">sync</button>
    </div>
    <button class="btn" style="padding:4px 10px;font-size:11px" onclick="clearLog()">Clear</button>
  </div>
  <div id="log-output"></div>
</div>

</div><!-- .app -->
<script>
const SIM_COLORS = {
  inventory: '#4ea1ff', suppliers: '#21c07a', demand: '#f2b840',
  commodity: '#b06bff', sap: '#ff8c42', iot: '#00d4aa', sync: '#21c07a'
};
// abbreviation → simulator name mapping for pipeline node updates
const SIM_ABBR = {
  inv: 'inventory', sup: 'suppliers', dem: 'demand',
  cmd: 'commodity', sap: 'sap',       iot: 'iot',
};
const ABBR_COLOR = {
  inv:'#4ea1ff', sup:'#21c07a', dem:'#f2b840',
  cmd:'#b06bff', sap:'#ff8c42', iot:'#00d4aa',
};

let state = {};
let logFilter = 'all';
let autoScroll = true;
const logEl = document.getElementById('log-output');

logEl.addEventListener('scroll', () => {
  autoScroll = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
});

// ── Clock ──────────────────────────────────────────────────────────────────
setInterval(() => {
  document.getElementById('clock').textContent = '● ' + new Date().toLocaleTimeString();
}, 1000);

// ── Env check ──────────────────────────────────────────────────────────────
async function checkEnv() {
  const env = await fetch('/api/env').then(r => r.json());
  const ok = Object.values(env).every(v => v.startsWith('✓'));
  document.getElementById('env-summary').textContent =
    ok ? '✓ All env vars set' : '⚠ Some env vars missing — expand';
  document.getElementById('env-summary').style.color = ok ? 'var(--good)' : 'var(--warn)';
  document.getElementById('env-summary').style.cursor = 'pointer';
  document.getElementById('env-summary').onclick = () => {
    const bar = document.getElementById('env-bar');
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
  };
  const bar = document.getElementById('env-bar');
  bar.innerHTML = Object.entries(env).map(([k, v]) =>
    `<div class="env-item"><span class="key">${k}</span>
     <span class="${v.startsWith('✓') ? 'env-ok' : 'env-bad'}">${v}</span></div>`
  ).join('');
}
checkEnv();

// ── Simulator grid ─────────────────────────────────────────────────────────
function renderGrid(sims) {
  state = sims;
  const grid = document.getElementById('sim-grid');
  grid.innerHTML = '';
  for (const [name, s] of Object.entries(sims)) {
    const running = s.running;
    const card = document.createElement('div');
    card.className = 'sim-card' + (running ? ' running' : '');
    card.id = `card-${name}`;
    card.style.setProperty('--card-color', SIM_COLORS[name] || '#4ea1ff');
    card.innerHTML = `
      <div class="sim-header">
        <div>
          <div class="sim-name">${s.label}</div>
          <div class="sim-desc">${s.description}</div>
        </div>
        <div class="status-dot ${running ? 'running' : 'stopped'}" id="dot-${name}"></div>
      </div>
      <div class="sim-meta">
        <div class="meta-item">
          <div class="label">Events</div>
          <div class="value" id="cnt-${name}" style="color:${SIM_COLORS[name]}">${s.event_count.toLocaleString()}</div>
        </div>
        <div class="meta-item">
          <div class="label">Uptime</div>
          <div class="value" id="up-${name}">${running ? formatUptime(s.uptime_s) : '—'}</div>
        </div>
      </div>
      <div class="sim-controls">
        <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">
          rate/s <input class="rate-input" id="rate-${name}" type="number" min="1" max="50"
                        value="${s.default_rate}">
        </label>
        <button class="btn ${running ? 'stop' : 'start'}" id="btn-${name}"
                onclick="toggle('${name}')">${running ? '■ Stop' : '▶ Start'}</button>
      </div>
    `;
    grid.appendChild(card);
  }
  // Update filter chips
  updateFilterChips(Object.keys(sims));
}

function updateFilterChips(names) {
  const bar = document.getElementById('log-filter');
  const existing = [...bar.querySelectorAll('[data-sim]')].map(el => el.dataset.sim);
  for (const name of names) {
    if (!existing.includes(name)) {
      const btn = document.createElement('button');
      btn.className = 'chip';
      btn.dataset.sim = name;
      btn.textContent = name;
      btn.style.borderColor = SIM_COLORS[name] || '';
      btn.onclick = () => setFilter(name, btn);
      bar.appendChild(btn);
    }
  }
}

function setFilter(sim, el) {
  logFilter = sim;
  document.querySelectorAll('#log-filter .chip').forEach(c => {
    c.classList.remove('on');
    c.style.background = '';
    c.style.color = '';
  });
  el.classList.add('on');
  const col = sim === 'all' ? 'var(--accent)' : (SIM_COLORS[sim] || 'var(--accent)');
  el.style.background = col;
  el.style.color = '#0b0f1a';
}

function formatUptime(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}

// ── Patch in live updates without full re-render ───────────────────────────
function patchCard(name, s) {
  const dot = document.getElementById(`dot-${name}`);
  const btn = document.getElementById(`btn-${name}`);
  const card = document.getElementById(`card-${name}`);
  const cnt = document.getElementById(`cnt-${name}`);
  const up = document.getElementById(`up-${name}`);
  if (!dot) return;
  dot.className = 'status-dot ' + (s.running ? 'running' : 'stopped');
  if (btn) { btn.className = 'btn ' + (s.running ? 'stop' : 'start'); btn.textContent = s.running ? '■ Stop' : '▶ Start'; }
  if (card) { card.className = 'sim-card' + (s.running ? ' running' : ''); }
  if (cnt) cnt.textContent = s.event_count.toLocaleString();
  if (up) up.textContent = s.running ? formatUptime(s.uptime_s) : '—';
}

// ── Polling status ─────────────────────────────────────────────────────────
let firstLoad = true;
async function pollStatus() {
  try {
    const sims = await fetch('/api/simulators').then(r => r.json());
    if (firstLoad) { renderGrid(sims); firstLoad = false; }
    else { for (const [name, s] of Object.entries(sims)) patchCard(name, s); }
    updatePipeline(sims);
  } catch {}
}
pollStatus();
setInterval(pollStatus, 1500);

// ── Controls ───────────────────────────────────────────────────────────────
function getCfg() {
  return {
    catalog: document.getElementById('cfg-catalog').value.trim() || 'livezerobus',
    schema:  document.getElementById('cfg-schema').value.trim()  || 'procurement',
  };
}

async function toggle(name) {
  const btn = document.getElementById(`btn-${name}`);
  const running = btn?.textContent.includes('Stop');
  const cfg = getCfg();
  const rate = parseInt(document.getElementById(`rate-${name}`)?.value || '1');
  if (running) {
    await fetch(`/api/simulators/${name}/stop`, { method: 'POST' });
  } else {
    await fetch(`/api/simulators/${name}/start?catalog=${cfg.catalog}&schema=${cfg.schema}&rate=${rate}`, { method: 'POST' });
  }
  await pollStatus();
}

async function startAll() {
  const cfg = getCfg();
  await fetch(`/api/simulators/start-all?catalog=${cfg.catalog}&schema=${cfg.schema}`, { method: 'POST' });
  await pollStatus();
}

async function stopAll() {
  await fetch('/api/simulators/stop-all', { method: 'POST' });
  await pollStatus();
}

async function clearLog() {
  logEl.innerHTML = '';
  await fetch('/api/logs', { method: 'DELETE' });
}

// ── Pipeline diagram updates ───────────────────────────────────────────────
function updatePipeline(sims) {
  for (const [abbr, simName] of Object.entries(SIM_ABBR)) {
    const s = sims[simName];
    const running = s?.running ?? false;
    const col = ABBR_COLOR[abbr];
    const node = document.getElementById(`node-${abbr}`);
    const sparks = document.getElementById(`sparks-${abbr}`);
    if (node) {
      node.style.stroke = running ? col : '#263056';
      node.style.strokeWidth = running ? '2' : '1.5';
      node.style.fill = running ? col + '22' : '#0d111e';
    }
    if (sparks) sparks.style.opacity = running ? '1' : '0';
  }
  const anyRunning = Object.values(sims).some(s => s.running);
  const mp = document.getElementById('main-particles');
  if (mp) mp.style.opacity = anyRunning ? '1' : '0';
}

// ── Lakebase sync status ───────────────────────────────────────────────────
let _syncPollTs = null;
let _syncNextIn = null;

function formatAgo(s) {
  if (s <= 0) return 'now';
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}

async function pollSyncStatus() {
  try {
    const s = await fetch('/api/sync-status').then(r => r.json());
    _syncPollTs = Date.now() / 1000;
    _syncNextIn = s.next_in_s;
    const badge = document.getElementById('sync-badge');
    const lastInfo = document.getElementById('sync-last-info');
    const syncPart = document.getElementById('sync-particles');
    const lbBox = document.getElementById('lb-box');
    const syncSvgTs = document.getElementById('sync-ts-svg');

    if (s.running) {
      if (badge) { badge.className = 'sync-dot running'; }
      if (syncPart) syncPart.style.opacity = '1';
      if (lbBox) lbBox.style.animation = 'lb-pulse 1.2s ease infinite';
      if (lastInfo) { lastInfo.textContent = 'Syncing…'; lastInfo.style.color = 'var(--accent)'; }
    } else {
      if (syncPart) syncPart.style.opacity = '0';
      if (lbBox) lbBox.style.animation = '';
      if (s.last_result === 'success') {
        if (badge) badge.className = 'sync-dot ok';
        if (s.last_ts && lastInfo) {
          const ago = Math.round(Date.now()/1000 - s.last_ts);
          lastInfo.textContent = '✔ ' + formatAgo(ago) + ' ago';
          lastInfo.style.color = 'var(--good)';
          if (syncSvgTs) syncSvgTs.textContent = formatAgo(ago) + ' ago';
        }
      } else if (s.last_result === 'error') {
        if (badge) badge.className = 'sync-dot error';
        if (lastInfo) { lastInfo.textContent = '✗ sync failed'; lastInfo.style.color = 'var(--bad)'; }
      } else {
        if (badge) badge.className = 'sync-dot idle';
        if (lastInfo) { lastInfo.textContent = 'Last sync: never'; lastInfo.style.color = 'var(--muted)'; }
      }
    }
  } catch {}
}

function updateSyncCountdown() {
  const el = document.getElementById('sync-next-info');
  if (!el || _syncNextIn === null || _syncPollTs === null) return;
  const elapsed = Math.round(Date.now()/1000 - _syncPollTs);
  const remaining = Math.max(0, _syncNextIn - elapsed);
  el.textContent = 'Next: ' + formatAgo(remaining);
}

async function triggerSync() {
  await fetch('/api/sync-now', { method: 'POST' });
  setTimeout(pollSyncStatus, 400);
}

pollSyncStatus();
setInterval(pollSyncStatus, 5000);
setInterval(updateSyncCountdown, 1000);

// ── SSE log stream ─────────────────────────────────────────────────────────
const SIM_LABEL_COLORS = SIM_COLORS;

function appendLog(entry) {
  if (entry.ping) return;
  const { sim, msg, ts, exit: isExit } = entry;
  if (logFilter !== 'all' && sim !== logFilter) return;
  const line = document.createElement('div');
  line.className = 'log-line' + (isExit ? ' exit' : '');
  const t = ts ? new Date(ts * 1000).toLocaleTimeString() : '';
  const col = SIM_LABEL_COLORS[sim] || 'var(--muted)';
  line.innerHTML =
    `<span class="log-ts">${t}</span>` +
    `<span class="log-sim" style="color:${col}">[${sim}]</span>` +
    `<span class="log-msg">${escapeHtml(msg || '')}</span>`;
  logEl.appendChild(line);
  // Keep at most 1000 lines
  while (logEl.children.length > 1000) logEl.removeChild(logEl.firstChild);
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function connectSSE() {
  const es = new EventSource('/api/logs');
  es.onmessage = (e) => {
    try { appendLog(JSON.parse(e.data)); } catch {}
  };
  es.onerror = () => {
    setTimeout(connectSSE, 2000);
    es.close();
  };
}
connectSSE();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_HTML)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("SIM_UI_PORT", 7777))
    print(f"LiveZerobus Simulator UI → http://localhost:{port}")
    uvicorn.run("sim_ui:app", host="0.0.0.0", port=port, reload=False, log_level="warning")
