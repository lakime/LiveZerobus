"""Shared helpers for Zerobus producers.

The Zerobus Python SDK wraps a gRPC stream. Each producer is bound to a
UC-qualified table and sends protobuf rows whose schema matches the table's
columns. For demo readability we define the row shapes here as dataclasses
and serialize to dicts; the SDK compiles a protobuf descriptor on the fly.

If you prefer pre-compiled .proto files, run:
    databricks zerobus compile-schema \\
        --catalog main --schema procurement --table bz_inventory_events \\
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
    dc_id: str
    delta_units: int
    on_hand: int
    reason: str


@dataclasses.dataclass
class SupplierQuote:
    event_id: str
    event_ts: datetime
    supplier_id: str
    sku: str
    unit_price_usd: float
    min_qty: int
    lead_time_days: int
    valid_until_ts: datetime
    currency: str


@dataclasses.dataclass
class DemandEvent:
    event_id: str
    event_ts: datetime
    sku: str
    store_id: str
    qty: int
    unit_price: float
    channel: str


@dataclasses.dataclass
class CommodityPrice:
    event_id: str
    event_ts: datetime
    commodity: str
    price_usd: float
    currency: str
    source: str


def as_row(obj: Any) -> dict[str, Any]:
    d = dataclasses.asdict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v
    return d


# --------------------- Shared reference data for simulators -------------------

SKUS = [f"SKU-{i:03d}" for i in range(1, 9)]
SKU_TO_COMMODITY = {
    "SKU-001": "steel",   "SKU-002": "copper", "SKU-003": "oil",    "SKU-004": "wheat",
    "SKU-005": "copper",  "SKU-006": "oil",    "SKU-007": "steel",  "SKU-008": "copper",
}
SUPPLIERS = [f"SUP-{i:02d}" for i in range(1, 9)]
DCS = ["DC-NYC", "DC-LAX", "DC-CHI", "DC-ATL"]
STORES = [f"STORE-{i:03d}" for i in range(1, 21)]
COMMODITIES = ["steel", "copper", "oil", "wheat"]
