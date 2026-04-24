"""Planting-schedule simulator (demand stream).

In a vertical farm, "demand" is the production plan: trays to be seeded per
SKU, per zone, per hour. A diurnal pattern peaks in the morning shift when
the seeding team loads most trays, with lighter activity overnight.

Each event corresponds to one scheduled tray-seeding batch: N trays of a
SKU in a zone. `grams_req` is derived from dim_sku.seed_per_tray_g.
"""
from __future__ import annotations

import math
import random
import time
import uuid

import click

from common import (
    SKU_SEED_PER_TRAY_G,
    SKUS,
    ZONES,
    DemandEvent,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)


def _seasonality(ts_epoch: float) -> float:
    """Diurnal wave peaking around 8am local; never drops below 0.3."""
    hour = (ts_epoch / 3600) % 24
    diurnal = 0.6 + 0.7 * math.sin(math.pi * (hour - 6) / 12)
    return max(diurnal, 0.3)


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema", default="procurement")
@click.option("--rate", default=8, help="Planting events per second.")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_demand_events"
    base_interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming planting-schedule events → {table} @ ~{rate}/s (seasonal)")
        while True:
            interval = base_interval / _seasonality(time.time())
            sku = random.choice(SKUS)
            # Most seedings are 1-4 trays; occasional large batch.
            trays = max(1, int(random.expovariate(0.7)) + 1)
            grams = trays * SKU_SEED_PER_TRAY_G.get(sku, 1.0) * random.gauss(1.0, 0.05)

            evt = DemandEvent(
                event_id=new_event_id(),
                event_ts=now_utc(),
                sku=sku,
                zone_id=random.choice(ZONES),
                trays=trays,
                grams_req=round(max(grams, 0.0), 3),
                crop_plan_id=f"PLAN-{uuid.uuid4().hex[:6].upper()}",
            )
            stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
