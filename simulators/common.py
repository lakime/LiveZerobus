"""Shared helpers for Zerobus producers.

The Zerobus Python SDK wraps a gRPC stream. Each producer is bound to a
UC-qualified table and sends protobuf rows whose schema matches the table's
columns. For demo readability we define the row shapes here as dataclasses
and serialize to dicts; the SDK compiles a protobuf descriptor on the fly.

This module is the shared vocabulary for the vertical-farm seed-procurement
demo. See schemas/setup.sql for the matching Delta tables.

If you prefer pre-compiled .proto files, run:
    databricks zerobus compile-schema \\
        --catalog livezerobus --schema procurement --table bz_inventory_events \\
        --out zerobus/generated
"""
from __future__ import annotations

import dataclasses
import os
import random
import string
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

try:
    # Databricks Zerobus Python SDK (pip install databricks-zerobus-sdk)
    from databricks.zerobus import ZerobusClient  # type: ignore
except ImportError as e:  # pragma: no cover - informational only
    raise SystemExit(
        "databricks-zerobus-sdk is required. `pip install -r requirements.txt`"
    ) from e


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"Missing required env var {name}")
    return v


def new_event_id() -> str:
    return uuid.uuid4().hex


def now_utc_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def rand_sku(pool: list[str]) -> str:
    return random.choice(pool)


def rand_suffix(n: int = 4) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


# -------------------------- Zerobus producer wrapper --------------------------


@contextmanager
def zerobus_stream(table_fqn: str) -> Iterator["ZerobusStream"]:
    """Context manager that opens a Zerobus gRPC stream for `catalog.schema.table`.

    Uses DATABRICKS_HOST + DATABRICKS_CLIENT_ID/SECRET for OAuth.
    Endpoint is taken from ZEROBUS_ENDPOINT (e.g. `region.zerobus...:443`).
    """
    endpoint = env("ZEROBUS_ENDPOINT")
    client = ZerobusClient(
        endpoint=endpoint,
        host=env("DATABRICKS_HOST"),
        client_id=env("DATABRICKS_CLIENT_ID"),
        client_secret=env("DATABRICKS_CLIENT_SECRET"),
    )
    stream = client.open_stream(table_fqn)
    try:
        yield ZerobusStream(stream, table_fqn)
    finally:
        try:
            stream.close()
        except Exception:  # pragma: no cover - best-effort close
            pass


class ZerobusStream:
    def __init__(self, stream: Any, table_fqn: str) -> None:
        self._stream = stream
        self._table = table_fqn
        self._sent = 0
        self._t0 = time.time()

    def send(self, row: dict[str, Any]) -> None:
        self._stream.ingest(row)
        self._sent += 1
        if self._sent % 500 == 0:
            rate = self._sent / max(time.time() - self._t0, 1e-6)
            print(f"[{self._table}] sent={self._sent} rate={rate:.0f}/s")

    def flush(self) -> None:
        self._stream.flush()


# ------------------------------ Dataclasses -----------------------------------


@dataclasses.dataclass
class InventoryEvent:
    event_id: str
    event_ts: datetime
    sku: str
    room_id: str
    lot_id: str
    delta_grams: float
    on_hand_g: float
    reason: str


@dataclasses.dataclass
class SupplierQuote:
    event_id: str
    event_ts: datetime
    supplier_id: str
    sku: str
    pack_size_g: float
    unit_price_usd: float
    min_qty: int
    lead_time_days: int
    valid_until_ts: datetime
    organic: bool
    currency: str


@dataclasses.dataclass
class DemandEvent:
    event_id: str
    event_ts: datetime
    sku: str
    zone_id: str
    trays: int
    grams_req: float
    crop_plan_id: str


@dataclasses.dataclass
class CommodityPrice:
    event_id: str
    event_ts: datetime
    input_key: str
    price_usd: float
    unit: str
    currency: str
    source: str


def as_row(obj: Any) -> dict[str, Any]:
    d = dataclasses.asdict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v
    return d


# --------------------- Shared reference data for simulators -------------------
# These MUST match dim_sku / dim_supplier in schemas/setup.sql. The simulators
# use them to generate correlated, plausible event streams.

SKUS: list[str] = [
    "SEED-LETT-BUT-01", "SEED-LETT-RED-01", "SEED-LETT-ROM-01",
    "SEED-BAS-GEN-01",  "SEED-BAS-THA-01",
    "SEED-KALE-LAC-01", "SEED-KALE-RED-01",
    "SEED-ARU-AST-01",  "SEED-SPIN-SPA-01",
    "SEED-MG-RAD-01",   "SEED-MG-PEA-01",  "SEED-MG-SUN-01",
    "SEED-MG-BROC-01",  "SEED-MG-AMA-01",
    "SEED-HERB-CIL-01", "SEED-HERB-PAR-01", "SEED-HERB-DIL-01",
    "SEED-BOK-SHA-01",  "SEED-MUST-WAS-01", "SEED-TAT-RED-01",
]

# Links each SKU to the grow-input whose price most affects its total grow cost.
# Microgreens use more substrate per gram of finished product; lettuces use
# more nutrients. This lets commodity ticks meaningfully move the ML score.
SKU_TO_INPUT: dict[str, str] = {
    "SEED-LETT-BUT-01": "nutrient_pack",
    "SEED-LETT-RED-01": "nutrient_pack",
    "SEED-LETT-ROM-01": "nutrient_pack",
    "SEED-BAS-GEN-01":  "nutrient_pack",
    "SEED-BAS-THA-01":  "nutrient_pack",
    "SEED-KALE-LAC-01": "nutrient_pack",
    "SEED-KALE-RED-01": "nutrient_pack",
    "SEED-ARU-AST-01":  "coco_coir",
    "SEED-SPIN-SPA-01": "coco_coir",
    "SEED-MG-RAD-01":   "coco_coir",
    "SEED-MG-PEA-01":   "coco_coir",
    "SEED-MG-SUN-01":   "coco_coir",
    "SEED-MG-BROC-01":  "coco_coir",
    "SEED-MG-AMA-01":   "coco_coir",
    "SEED-HERB-CIL-01": "rockwool",
    "SEED-HERB-PAR-01": "rockwool",
    "SEED-HERB-DIL-01": "rockwool",
    "SEED-BOK-SHA-01":  "nutrient_pack",
    "SEED-MUST-WAS-01": "nutrient_pack",
    "SEED-TAT-RED-01":  "nutrient_pack",
}

# Average grams of seed needed per tray per SKU. Used by the demand simulator
# to turn "seed N trays" into "need G grams". Mirrors dim_sku.seed_per_tray_g.
SKU_SEED_PER_TRAY_G: dict[str, float] = {
    "SEED-LETT-BUT-01": 0.35, "SEED-LETT-RED-01": 0.32, "SEED-LETT-ROM-01": 0.30,
    "SEED-BAS-GEN-01":  0.55, "SEED-BAS-THA-01":  0.58,
    "SEED-KALE-LAC-01": 0.40, "SEED-KALE-RED-01": 0.38,
    "SEED-ARU-AST-01":  0.45, "SEED-SPIN-SPA-01": 0.80,
    "SEED-MG-RAD-01":   7.50, "SEED-MG-PEA-01":  18.00, "SEED-MG-SUN-01": 14.00,
    "SEED-MG-BROC-01":  6.00, "SEED-MG-AMA-01":   2.80,
    "SEED-HERB-CIL-01": 3.60, "SEED-HERB-PAR-01": 2.50, "SEED-HERB-DIL-01": 2.20,
    "SEED-BOK-SHA-01":  0.40, "SEED-MUST-WAS-01": 0.70, "SEED-TAT-RED-01":  0.65,
}

SUPPLIERS: list[str] = [
    "SUP-JOHNNY", "SUP-HIGHMOW", "SUP-TRUELEAF", "SUP-KITAZAWA", "SUP-RIJK",
    "SUP-ENZA",   "SUP-VITALIS", "SUP-WESTCOAST", "SUP-KOPPERT",  "SUP-VILMORIN",
]

# Grow rooms (cold storage + main rooms) and planting zones in the farm.
ROOMS: list[str] = ["ROOM-COLD", "ROOM-A", "ROOM-B", "ROOM-C"]
ZONES: list[str] = [f"ZONE-{c}{i:02d}" for c in "AB" for i in range(1, 7)]

# The four grow inputs whose prices the commodity simulator walks.
INPUTS: list[tuple[str, str]] = [
    ("coco_coir",      "per_L"),
    ("peat",           "per_kg"),
    ("rockwool",       "per_kg"),
    ("nutrient_pack",  "per_kg"),
    ("kwh",            "per_kwh"),
]
