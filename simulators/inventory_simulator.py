"""Inventory simulator.

Streams warehouse stock movements (picks, shipments, adjustments) per SKU/DC.
Keeps a local `on_hand` counter per (sku, dc) so snapshot rows are consistent.
"""
from __future__ import annotations

import random
import time

import click

from common import (
    DCS,
    SKUS,
    InventoryEvent,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)


def _seed_on_hand() -> dict[tuple[str, str], int]:
    return {(sku, dc): random.randint(800, 2500) for sku in SKUS for dc in DCS}


@click.command()
@click.option("--catalog", default="main")
@click.option("--schema", default="procurement")
@click.option("--rate", default=5, help="Events per second.")
@click.option("--duration", default=0, help="Seconds to run; 0 = forever.")
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_inventory_events"
    on_hand = _seed_on_hand()

    interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming inventory events → {table} @ ~{rate}/s")
        while True:
            sku = random.choice(SKUS)
            dc = random.choice(DCS)
            key = (sku, dc)

            # bias toward outbound picks (demand), occasional big inbound shipment
            if random.random() < 0.08:
                delta = random.randint(200, 800)       # inbound shipment
                reason = "shipment"
            elif random.random() < 0.02:
                delta = random.randint(-20, 20)         # stock adjust
                reason = "adjust"
            else:
                delta = -random.randint(1, 12)          # pick
                reason = "pick"

            on_hand[key] = max(on_hand[key] + delta, 0)
            evt = InventoryEvent(
                event_id=new_event_id(),
                event_ts=now_utc(),
                sku=sku,
                dc_id=dc,
                delta_units=delta,
                on_hand=on_hand[key],
                reason=reason,
            )
            stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
