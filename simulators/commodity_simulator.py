"""Commodity prices simulator.

One event per commodity per tick (default ~1/s total). Prices follow a
Geometric Brownian Motion-ish random walk bounded within ±35% of the mean so
the chart stays readable.
"""
from __future__ import annotations

import random
import time

import click

from common import (
    COMMODITIES,
    CommodityPrice,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

BASE = {"steel": 780.0, "copper": 9200.0, "oil": 82.0, "wheat": 610.0}
SIGMA = {"steel": 0.004, "copper": 0.006, "oil": 0.010, "wheat": 0.005}
SOURCE = {"steel": "CMX:HRC", "copper": "LME:CU", "oil": "NYMEX:CL", "wheat": "CBOT:ZW"}


@click.command()
@click.option("--catalog", default="main")
@click.option("--schema", default="procurement")
@click.option("--rate", default=1, help="Events per second (per commodity).")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_commodity_prices"
    interval = 1.0 / max(rate, 1)
    prices = dict(BASE)
    t_end = time.time() + duration if duration else None

    with zerobus_stream(table) as stream:
        print(f"Streaming commodity prices → {table} @ ~{rate}/s per commodity")
        while True:
            for c in COMMODITIES:
                shock = random.gauss(0, SIGMA[c])
                prices[c] = max(BASE[c] * 0.65, min(BASE[c] * 1.35, prices[c] * (1 + shock)))
                evt = CommodityPrice(
                    event_id=new_event_id(),
                    event_ts=now_utc(),
                    commodity=c,
                    price_usd=round(prices[c], 4),
                    currency="USD",
                    source=SOURCE[c],
                )
                stream.send(as_row(evt))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
