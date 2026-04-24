"""Seed-inventory simulator.

Streams seed-stock movements (plantings, receipts, adjustments, expiries)
per SKU and grow-room, measured in grams. Keeps a local `on_hand_g` counter
per (sku, room) so snapshot rows are consistent.
"""
from __future__ import annotations

import random
import time
import uuid

import click

from common import (
    ROOMS,
    SKUS,
    InventoryEvent,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)


def _seed_on_hand() -> dict[tuple[str, str], float]:
    # Most SKUs live in a cold-storage room; grow rooms hold small working stock.
    d: dict[tuple[str, str], float] = {}
    for sku in SKUS:
        for room in ROOMS:
            if room == "ROOM-COLD":
                d[(sku, room)] = random.uniform(800.0, 3500.0)   # g
            else:
                d[(sku, room)] = random.uniform(50.0, 300.0)
    return d


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema", default="procurement")
@click.option("--rate", default=5, help="Events per second.")
@click.option("--duration", default=0, help="Seconds to run; 0 = forever.")
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_inventory_events"
    on_hand = _seed_on_hand()

    interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming seed-inventory events → {table} @ ~{rate}/s")
        while True:
            sku = random.choice(SKUS)
            room = random.choice(ROOMS)
            key = (sku, room)

            # Mostly PLANT outflow, occasional RECEIVE replenishment, rare
            # ADJUST / EXPIRY / WASTE events for realism.
            r = random.random()
            if r < 0.10:
                delta = random.uniform(500.0, 2500.0)
                reason = "RECEIVE"
            elif r < 0.12:
                delta = random.uniform(-5.0, 5.0)
                reason = "ADJUST"
            elif r < 0.13:
                delta = -random.uniform(5.0, 40.0)
                reason = "EXPIRY"
            elif r < 0.14:
                delta = -random.uniform(1.0, 15.0)
                reason = "WASTE"
            else:
                delta = -random.uniform(0.5, 8.0)
                reason = "PLANT"

            on_hand[key] = max(on_hand[key] + delta, 0.0)
            evt = InventoryEvent(
                event_id=new_event_id(),
                event_ts=now_utc(),
                sku=sku,
                room_id=room,
                lot_id=f"LOT-{uuid.uuid4().hex[:8].upper()}",
                delta_grams=round(delta, 3),
                on_hand_g=round(on_hand[key], 3),
                reason=reason,
            )
            stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
