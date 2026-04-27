"""Shared helpers for Zerobus producers.

Uses the official Databricks Zerobus Ingest SDK for Python
(`databricks-zerobus-ingest-sdk`). Each producer opens a gRPC stream bound
to a UC-qualified Bronze Delta table and pushes rows via the SDK. For demo
readability we use JSON record mode — no protobuf descriptor compilation
required; the SDK serialises dicts to the wire.

This module is the shared vocabulary for the vertical-farm seed-procurement
demo. See schemas/setup.sql for the matching Delta tables.

If you later want higher throughput, switch to PROTO mode:
  1. Generate the descriptor via `python -m zerobus.tools.generate_proto ...`
  2. Pass `TableProperties(fqn, record_pb2.Event.DESCRIPTOR)` and leave
     `StreamConfigurationOptions()` on its default (RecordType.PROTO).
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
    # pip install databricks-zerobus-ingest-sdk
    from zerobus.sdk.sync import ZerobusSdk  # type: ignore
    from zerobus.sdk.shared import (  # type: ignore
        RecordType,
        StreamConfigurationOptions,
        TableProperties,
    )
except ImportError as e:  # pragma: no cover - informational only
    raise SystemExit(
        "databricks-zerobus-ingest-sdk is required. "
        "`pip install -r requirements.txt`"
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

    Env contract:
        DATABRICKS_HOST         — workspace URL (https://…azuredatabricks.net)
        DATABRICKS_CLIENT_ID    — service-principal Application ID
        DATABRICKS_CLIENT_SECRET— SP OAuth secret
        ZEROBUS_ENDPOINT        — full URL, e.g.
                                   https://<workspace-id>.zerobus.<region>.azuredatabricks.net
                                   (include the https:// scheme, per the
                                   Azure Databricks Zerobus Ingest docs)
    """
    server_endpoint = env("ZEROBUS_ENDPOINT")
    workspace_url = env("DATABRICKS_HOST")

    sdk = ZerobusSdk(server_endpoint, workspace_url)
    table_properties = TableProperties(table_fqn)
    options = StreamConfigurationOptions(record_type=RecordType.JSON)

    stream = sdk.create_stream(
        env("DATABRICKS_CLIENT_ID"),
        env("DATABRICKS_CLIENT_SECRET"),
        table_properties,
        options,
    )
    try:
        yield ZerobusStream(stream, table_fqn)
    finally:
        try:
            stream.flush()
        except Exception:  # pragma: no cover - best-effort
            pass
        try:
            stream.close()
        except Exception:  # pragma: no cover - best-effort
            pass


class ZerobusStream:
    """Thin wrapper over the SDK stream that adds rate logging."""

    def __init__(self, stream: Any, table_fqn: str) -> None:
        self._stream = stream
        self._table = table_fqn
        self._sent = 0
        self._t0 = time.time()

    def send(self, row: dict[str, Any]) -> None:
        # JSON mode: fire-and-forget is fine for the demo volume (~20/s).
        # Switch to `ingest_record_offset` if you want per-row durable acks.
        self._stream.ingest_record_nowait(row)
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
    """Dataclass → JSON-safe dict for Zerobus RecordType.JSON.

    Delta TIMESTAMP columns expect integer microseconds since Unix epoch
    when ingested via Zerobus JSON mode — ISO-8601 strings are rejected
    with "invalid digit found in string" (server tries to parse the
    string as i64).
    """
    d = dataclasses.asdict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            # Ensure tz-aware, then → microseconds since epoch (UTC).
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            d[k] = int(v.timestamp() * 1_000_000)
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
