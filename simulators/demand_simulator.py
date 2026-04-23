"""Demand (POS / order) simulator.

Generates sales events with day-of-week and hour-of-day seasonality so the
1-hour demand aggregates look believable in the dashboard.
"""
from __future__ import annotations

import math
import random
import time

import click

from common import (
    SKUS,
    STORES,
    DemandEvent,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

UNIT_PRICE = {
    "SKU-001": 6.10,  "SKU-002": 10.40, "SKU-003": 1.90,  "SKU-004": 13.20,
    "SKU-005": 15.00, "SKU-006": 4.80,  "SKU-007": 62.00, "SKU-008": 19.50,
}

CHANNELS = ["web", "retail", "b2b"]


def _seasonality(ts_epoch: float) -> float:
    """Diurnal wave multiplied by weekday factor, centered around 1.0."""
    hour = (ts_epoch / 3600) % 24
    diurnal = 0.6 + 0.6 * math.sin(math.pi * (hour - 6) / 12)
    return max(diurnal, 0.2)


@click.command()
@click.option("--catalog", default="main")
@click.option("--schema", default="procurement")
@click.option("--rate", default=8)
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_demand_events"
    base_interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming demand events → {table} @ ~{rate}/s (seasonal)")
        while True:
            interval = base_interval / _seasonality(time.time())
            sku = random.choice(SKUS)
            qty = max(1, int(random.expovariate(1.0)) + 1)
            price = UNIT_PRICE[sku] * random.gauss(1.0, 0.02)

            evt = DemandEvent(
                event_id=new_event_id(),
                event_ts=now_utc(),
                sku=sku,
                store_id=random.choice(STORES),
                qty=qty,
                unit_price=round(price, 2),
                channel=random.choice(CHANNELS),
            )
            stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
