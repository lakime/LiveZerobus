"""Supplier seed-quotes simulator.

Each seed supplier periodically re-quotes a subset of SKUs. Prices drift
with the underlying grow-input they correlate with (nutrient cost for
greens, substrate cost for microgreens) plus per-supplier bias (price
multiplier, lead-time bias, noise, organic offering).

Each quote is priced per pack and includes pack_size_g, so downstream
tables can compute normalized USD/gram.
"""
from __future__ import annotations

import math
import random
import time
from datetime import timedelta

import click

from common import (
    SKU_TO_INPUT,
    SKUS,
    SUPPLIERS,
    SupplierQuote,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

# Per-supplier bias: (price_mult, lead_time_bias_days, noise, organic_pct)
# price_mult < 1 means cheaper on average; noise higher means flakier pricing.
SUPPLIER_PROFILE: dict[str, tuple[float, int, float, float]] = {
    "SUP-JOHNNY":    (1.00,  4, 0.03, 0.60),
    "SUP-HIGHMOW":   (1.08,  5, 0.02, 1.00),   # pricier, 100% organic
    "SUP-TRUELEAF":  (0.92,  7, 0.05, 0.30),   # bulk discount, mixed organic
    "SUP-KITAZAWA":  (1.04,  9, 0.03, 0.40),
    "SUP-RIJK":      (1.12,  6, 0.02, 0.20),   # premium
    "SUP-ENZA":      (1.05,  6, 0.02, 0.70),
    "SUP-VITALIS":   (1.10,  8, 0.03, 1.00),
    "SUP-WESTCOAST": (0.98,  9, 0.04, 0.80),
    "SUP-KOPPERT":   (1.15, 12, 0.08, 0.50),   # new partner, flakier
    "SUP-VILMORIN":  (1.02, 11, 0.03, 0.35),
}

# Anchor USD/gram per SKU. Microgreens are cheap/gram; specialty greens
# more expensive. Matches dim_sku.unit_cost_hint order-of-magnitude.
SKU_USD_PER_GRAM: dict[str, float] = {
    "SEED-LETT-BUT-01": 0.35, "SEED-LETT-RED-01": 0.42, "SEED-LETT-ROM-01": 0.30,
    "SEED-BAS-GEN-01":  0.85, "SEED-BAS-THA-01":  1.10,
    "SEED-KALE-LAC-01": 0.48, "SEED-KALE-RED-01": 0.55,
    "SEED-ARU-AST-01":  0.38, "SEED-SPIN-SPA-01": 0.52,
    "SEED-MG-RAD-01":   0.18, "SEED-MG-PEA-01":   0.12, "SEED-MG-SUN-01": 0.15,
    "SEED-MG-BROC-01":  0.22, "SEED-MG-AMA-01":   0.34,
    "SEED-HERB-CIL-01": 0.58, "SEED-HERB-PAR-01": 0.44, "SEED-HERB-DIL-01": 0.36,
    "SEED-BOK-SHA-01":  0.40, "SEED-MUST-WAS-01": 0.68, "SEED-TAT-RED-01":  0.62,
}

# Reasonable pack sizes by crop class — microgreens move in much larger
# packs than specialty lettuce seed.
MICROGREEN_PACKS = [100.0, 250.0, 500.0, 1000.0, 2000.0]
REGULAR_PACKS    = [1.0, 5.0, 25.0, 100.0]


def _pack_sizes_for(sku: str) -> list[float]:
    return MICROGREEN_PACKS if sku.startswith("SEED-MG-") else REGULAR_PACKS


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema", default="procurement")
@click.option("--rate", default=2, help="Quotes per second.")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table = f"{catalog}.{schema}.bz_supplier_quotes"
    interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    t0 = time.time()

    with zerobus_stream(table) as stream:
        print(f"Streaming supplier seed-quotes → {table} @ ~{rate}/s")
        while True:
            sku = random.choice(SKUS)
            supplier = random.choice(SUPPLIERS)
            mult, lead_bias, noise, organic_pct = SUPPLIER_PROFILE[supplier]

            # Input-driven oscillation (±12%) — ties pricing to commodity stream.
            input_key = SKU_TO_INPUT.get(sku, "nutrient_pack")
            phase = {"nutrient_pack": 0.0, "coco_coir": 1.2, "rockwool": 2.4,
                     "peat": 3.5, "kwh": 4.7}.get(input_key, 0.0)
            drift = 1 + 0.12 * math.sin((time.time() - t0) / 120 + phase)

            pack = random.choice(_pack_sizes_for(sku))
            per_g = SKU_USD_PER_GRAM[sku] * mult * drift * random.gauss(1.0, noise)
            pack_price = max(per_g * pack, 0.25)
            lead = max(1, int(random.gauss(lead_bias, 1.5)))

            quote = SupplierQuote(
                event_id=new_event_id(),
                event_ts=now_utc(),
                supplier_id=supplier,
                sku=sku,
                pack_size_g=pack,
                unit_price_usd=round(pack_price, 4),
                min_qty=random.choice([1, 2, 5, 10]),
                lead_time_days=lead,
                valid_until_ts=now_utc() + timedelta(hours=random.choice([6, 12, 24, 48])),
                organic=random.random() < organic_pct,
                currency="USD",
            )
            stream.send(as_row(quote))

            time.sleep(interval)
            if t_end and time.time() > t_end:
                stream.flush()
                break


if __name__ == "__main__":
    main()
