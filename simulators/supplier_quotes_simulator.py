"""Supplier quotes simulator.

Each supplier periodically re-quotes a subset of SKUs. Prices drift with the
underlying commodity price (injected via env or random walk) plus per-supplier
noise (bias, premium/discount, lead-time variability).
"""
from __future__ import annotations

import math
import random
import time
from datetime import timedelta

import click

from common import (
    SKU_TO_COMMODITY,
    SKUS,
    SUPPLIERS,
    SupplierQuote,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

# Per-supplier bias: (price_mult, lead_time_bias_days, reliability_noise)
SUPPLIER_PROFILE: dict[str, tuple[float, int, float]] = {
    "SUP-01": (1.00,  5, 0.03),
    "SUP-02": (0.98,  7, 0.02),
    "SUP-03": (0.95, 10, 0.06),
    "SUP-04": (0.97, 12, 0.05),
    "SUP-05": (0.92, 21, 0.10),   # cheap but slow / unreliable
    "SUP-06": (1.02,  4, 0.02),
    "SUP-07": (1.01,  8, 0.04),
    "SUP-08": (0.99,  6, 0.03),
}

SKU_BASE_PRICE = {
    "SKU-001": 4.20,  "SKU-002": 7.50,  "SKU-003": 1.10,  "SKU-004": 9.80,
    "SKU-005": 11.00, "SKU-006": 3.20,  "SKU-007": 48.00, "SKU-008": 14.50,
}


@click.command()
@click.option("--catalog", default="main")
@click.option("--schema", default="procurement")
@click.option("--rate", default=2, help="Quotes per second.")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_supplier_quotes"
    interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    # commodity bias oscillates slowly to make charts look realistic
    t0 = time.time()

    with zerobus_stream(table) as stream:
        print(f"Streaming supplier quotes → {table} @ ~{rate}/s")
        while True:
            sku = random.choice(SKUS)
            supplier = random.choice(SUPPLIERS)
            base = SKU_BASE_PRICE[sku]
            mult, lead_bias, noise = SUPPLIER_PROFILE[supplier]

            # commodity-driven oscillation (±12%)
            comm = SKU_TO_COMMODITY[sku]
            phase = {"steel": 0, "copper": 1.2, "oil": 2.4, "wheat": 3.5}[comm]
            drift = 1 + 0.12 * math.sin((time.time() - t0) / 120 + phase)

            price = base * mult * drift * random.gauss(1.0, noise)
            lead = max(1, int(random.gauss(lead_bias, 1.5)))

            quote = SupplierQuote(
                event_id=new_event_id(),
                event_ts=now_utc(),
                supplier_id=supplier,
                sku=sku,
                unit_price_usd=round(price, 4),
                min_qty=random.choice([100, 250, 500, 1000]),
                lead_time_days=lead,
                valid_until_ts=now_utc() + timedelta(hours=random.choice([6, 12, 24])),
                currency="USD",
            )
            stream.send(as_row(quote))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
