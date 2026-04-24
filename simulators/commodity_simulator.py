"""Grow-input price simulator.

One event per input per tick. Prices follow a bounded random walk so the
chart stays readable. These feed the ML supplier-scoring model as the
"market context" feature — rising substrate or energy costs make the
"grow it ourselves" option more expensive, nudging the model toward
buying finished trays or smaller, more frequent seed orders.
"""
from __future__ import annotations

import random
import time

import click

from common import (
    INPUTS,
    CommodityPrice,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

BASE = {
    "coco_coir":     0.55,   # USD/L
    "peat":          0.70,   # USD/kg
    "rockwool":      1.20,   # USD/kg
    "nutrient_pack": 18.00,  # USD/kg (concentrated mix)
    "kwh":           0.18,   # USD/kWh
}
SIGMA = {
    "coco_coir":     0.004,
    "peat":          0.004,
    "rockwool":      0.003,
    "nutrient_pack": 0.006,
    "kwh":           0.010,
}
SOURCE = {
    "coco_coir":     "MKT:COCO",
    "peat":          "MKT:PEAT",
    "rockwool":      "MKT:ROCK",
    "nutrient_pack": "MKT:NUTR",
    "kwh":           "GRID:SPOT",
}


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema", default="procurement")
@click.option("--rate", default=1, help="Events per second (per input).")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_commodity_prices"
    interval = 1.0 / max(rate, 1)
    prices = dict(BASE)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming grow-input prices → {table} @ ~{rate}/s per input")
        while True:
            for key, unit in INPUTS:
                shock = random.gauss(0, SIGMA[key])
                prices[key] = max(
                    BASE[key] * 0.65,
                    min(BASE[key] * 1.35, prices[key] * (1 + shock)),
                )
                evt = CommodityPrice(
                    event_id=new_event_id(),
                    event_ts=now_utc(),
                    input_key=key,
                    price_usd=round(prices[key], 4),
                    unit=unit,
                    currency="USD",
                    source=SOURCE[key],
                )
                stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
