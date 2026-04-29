"""Simulator configuration loader.

Reads config.toml from the simulators/ directory.
CLI flags passed to individual simulators or run_all.py override these values.
"""
from __future__ import annotations

import os
import pathlib
import tomllib
from typing import Any

_CONFIG_PATH = pathlib.Path(__file__).parent / "config.toml"

_DEFAULTS: dict[str, Any] = {
    "databricks": {
        "catalog": "livezerobus",
        "schema": "procurement",
    },
    "simulators": {
        "inventory": {"rate": 5},
        "suppliers": {"rate": 2},
        "demand":    {"rate": 8},
        "commodity": {"rate": 1},
        "sap":       {"rate": 1},
        "iot":       {"rate": 1},
    },
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load() -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "rb") as f:
            cfg = _deep_merge(cfg, tomllib.load(f))
    return cfg


_ENV_PATH = pathlib.Path(__file__).parent / ".env"


def load_env_file() -> None:
    """Read .env and populate os.environ for vars not already set in the shell."""
    if not _ENV_PATH.exists():
        return
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val


def save_env_file(values: dict[str, str]) -> None:
    """Merge `values` into .env, writing key="value" lines."""
    existing: dict[str, str] = {}
    if _ENV_PATH.exists():
        with open(_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip().strip("\"'")
    existing.update({k: v for k, v in values.items() if v})
    with open(_ENV_PATH, "w") as f:
        for k, v in existing.items():
            f.write(f'{k}="{v}"\n')


# Module-level singleton — imported by other modules as `from config import CFG`
CFG: dict[str, Any] = load()
load_env_file()  # populate os.environ from .env on import


def catalog() -> str:
    return CFG["databricks"]["catalog"]


def schema() -> str:
    return CFG["databricks"]["schema"]


def sim_rate(name: str) -> int:
    return int(CFG.get("simulators", {}).get(name, {}).get("rate", 1))
