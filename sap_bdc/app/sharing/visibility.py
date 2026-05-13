"""Per-table sharing on/off switch.

State is persisted as JSON in `${DATA_DIR}/_sharing.json`. Default is
ALL DISABLED — operators must explicitly enable each table before it
becomes visible over the Delta Sharing protocol. The GUI's /api/tables
endpoints are unaffected (still show all tables, with a shared flag).

Comparisons are case-insensitive against the stored canonical table
names so Databricks UC's lowercased lookups (`ekko` → `EKKO`) still work.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from ..config import Settings

_LOCK = threading.RLock()
_FILENAME = "_sharing.json"


def _path(settings: Settings) -> Path:
    return settings.data_dir / _FILENAME


def _load(settings: Settings) -> set[str]:
    p = _path(settings)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
        return set(data.get("enabled", []))
    except Exception:
        return set()


def _save(settings: Settings, enabled: set[str]) -> None:
    p = _path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": sorted(enabled)}, indent=2))


def is_shared(settings: Settings, name: str) -> bool:
    with _LOCK:
        enabled = _load(settings)
    target = name.lower()
    return any(t.lower() == target for t in enabled)


def list_enabled(settings: Settings) -> list[str]:
    with _LOCK:
        return sorted(_load(settings))


def enable(settings: Settings, name: str) -> None:
    with _LOCK:
        enabled = _load(settings)
        # store canonical (case-preserved) name
        target = name.lower()
        if not any(t.lower() == target for t in enabled):
            enabled.add(name)
            _save(settings, enabled)


def disable(settings: Settings, name: str) -> None:
    with _LOCK:
        enabled = _load(settings)
        target = name.lower()
        new = {t for t in enabled if t.lower() != target}
        if new != enabled:
            _save(settings, new)


def set_enabled(settings: Settings, names: list[str]) -> None:
    with _LOCK:
        _save(settings, set(names))


def enable_all(settings: Settings, all_table_names: list[str]) -> None:
    with _LOCK:
        _save(settings, set(all_table_names))


def disable_all(settings: Settings) -> None:
    with _LOCK:
        _save(settings, set())


def bootstrap_if_missing(settings: Settings, all_table_names: list[str]) -> bool:
    """First-run bootstrap: if no state file exists yet, seed with all
    tables enabled. Returns True iff bootstrap actually ran.

    Once the file exists (even containing an empty enabled list from an
    explicit disable-all), this becomes a no-op — operator choices are
    preserved across restarts.
    """
    with _LOCK:
        if _path(settings).exists() or not all_table_names:
            return False
        _save(settings, set(all_table_names))
        return True
