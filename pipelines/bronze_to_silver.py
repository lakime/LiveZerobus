"""Lakeflow Spark Declarative Pipeline — Bronze → Silver.

Streaming, deduped, schema-enforced views of each of the four Zerobus feeds.
Uses the open-source Spark Declarative Pipelines API (`pyspark.pipelines`).

Run as a Lakeflow Pipeline (see resources/pipelines.yml) with catalog/schema
configured via pipeline parameters.
"""
from __future__ import annotations

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# `spark` is injected by the Lakeflow pipeline runtime.
CATALOG = spark.conf.get("pipelines.catalog", "main")       # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")  # noqa: F821


def _bronze(table: str):
    """Streaming read over a Zerobus-ingested Delta table."""
    return spark.readStream.table(f"{CATALOG}.{SCHEMA}.{table}")   # noqa: F821


# ---------------- Inventory ----------------


@dp.table(
    name="sv_inventory_events",
    comment="Deduped, validated inventory events.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("has_event_ts", "event_ts IS NOT NULL")
@dp.expect_or_drop("has_sku", "sku IS NOT NULL")
def sv_inventory_events():
    return (
        _bronze("bz_inventory_events")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Supplier quotes ----------------


@dp.table(
    name="sv_supplier_quotes",
    comment="Supplier quotes with price and lead time validated.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_price", "unit_price_usd > 0")
@dp.expect_or_drop("positive_lead", "lead_time_days >= 0")
def sv_supplier_quotes():
    return (
        _bronze("bz_supplier_quotes")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Demand ----------------


@dp.table(
    name="sv_demand_events",
    comment="Demand events with qty > 0 and derived revenue.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_qty", "qty > 0")
def sv_demand_events():
    return (
        _bronze("bz_demand_events")
        .dropDuplicates(["event_id"])
        .withColumn("revenue_usd", F.col("qty") * F.col("unit_price"))
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Commodity prices ----------------


@dp.table(
    name="sv_commodity_prices",
    comment="Commodity prices streaming view.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_price", "price_usd > 0")
def sv_commodity_prices():
    return (
        _bronze("bz_commodity_prices")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )
