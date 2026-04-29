"""Lakeflow Spark Declarative Pipeline — Bronze → Silver (Seed Procurement).

Streaming, deduped, schema-enforced views of each of the four Zerobus feeds
for the Vertical-Farm Seed Procurement demo.

Uses the open-source Spark Declarative Pipelines API (`pyspark.pipelines`).
Run as a Lakeflow Pipeline (see resources/pipelines.yml) with catalog/schema
configured via pipeline parameters.

Bronze sources (Zerobus append-only):
  * bz_inventory_events   — seed stock movements (grams per SKU per room)
  * bz_supplier_quotes    — rolling seed-house quotes (per pack_size_g)
  * bz_demand_events      — planting schedule (trays + grams_req)
  * bz_commodity_prices   — grow-input prices (input_key: coco_coir|peat|...)
"""
from __future__ import annotations

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# `spark` is injected by the Lakeflow pipeline runtime.
CATALOG = spark.conf.get("pipelines.catalog", "livezerobus")  # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")  # noqa: F821


def _bronze(table: str):
    """Streaming read over a Zerobus-ingested Delta table."""
    return spark.readStream.table(f"{CATALOG}.{SCHEMA}.{table}")   # noqa: F821


# ---------------- Seed inventory ----------------


@dp.table(
    name="sv_inventory_events",
    comment="Deduped, validated seed inventory movements (grams).",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("has_event_ts", "event_ts IS NOT NULL")
@dp.expect_or_drop("has_sku", "sku IS NOT NULL")
@dp.expect_or_drop("has_room", "room_id IS NOT NULL")
@dp.expect_or_drop("non_negative_stock", "on_hand_g >= 0")
def sv_inventory_events():
    return (
        _bronze("bz_inventory_events")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Seed-house supplier quotes ----------------


@dp.table(
    name="sv_supplier_quotes",
    comment="Supplier seed-pack quotes with price / pack size / lead validated.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_price", "unit_price_usd > 0")
@dp.expect_or_drop("positive_pack", "pack_size_g > 0")
@dp.expect_or_drop("positive_lead", "lead_time_days >= 0")
def sv_supplier_quotes():
    return (
        _bronze("bz_supplier_quotes")
        .dropDuplicates(["event_id"])
        .withColumn("usd_per_gram", F.col("unit_price_usd") / F.col("pack_size_g"))
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Planting schedule (demand) ----------------


@dp.table(
    name="sv_demand_events",
    comment="Planting schedule with trays > 0 and grams_req derived.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_trays", "trays > 0")
@dp.expect_or_drop("positive_grams", "grams_req > 0")
def sv_demand_events():
    return (
        _bronze("bz_demand_events")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- Grow-input prices ----------------


@dp.table(
    name="sv_commodity_prices",
    comment="Grow-input (substrate / nutrients / kWh) prices streaming view.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_price", "price_usd > 0")
@dp.expect_or_drop("has_input_key", "input_key IS NOT NULL")
def sv_commodity_prices():
    return (
        _bronze("bz_commodity_prices")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- SAP Purchase Orders ----------------


@dp.table(
    name="sv_sap_purchase_orders",
    comment="SAP MM purchase order events — deduped and quantity/price validated.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("positive_qty",   "quantity_g > 0")
@dp.expect_or_drop("positive_price", "unit_price_usd > 0")
@dp.expect_or_drop("has_supplier",   "supplier_id IS NOT NULL")
def sv_sap_purchase_orders():
    return (
        _bronze("bz_sap_purchase_orders")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- SAP Goods Receipts ----------------


@dp.table(
    name="sv_sap_goods_receipts",
    comment="SAP MIGO goods receipt events — deduped; qty may be negative for movement 122 reversals.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("has_po",  "po_number IS NOT NULL")
@dp.expect_or_drop("has_sku", "sku IS NOT NULL")
def sv_sap_goods_receipts():
    return (
        _bronze("bz_sap_goods_receipts")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- SAP Invoice Documents ----------------


@dp.table(
    name="sv_sap_invoice_documents",
    comment="SAP LIV/MIRO invoice documents — deduped, feeds 3-way match Gold view.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("has_po",       "po_number IS NOT NULL")
@dp.expect_or_drop("has_supplier", "supplier_id IS NOT NULL")
def sv_sap_invoice_documents():
    return (
        _bronze("bz_sap_invoice_documents")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )


# ---------------- IoT grow-room sensors ----------------


@dp.table(
    name="sv_iot_sensor_events",
    comment="Grow-room IoT sensor readings — deduped and value-range validated.",
    table_properties={"quality": "silver"},
)
@dp.expect_or_drop("has_room",   "room_id IS NOT NULL")
@dp.expect_or_drop("has_sensor", "sensor_type IS NOT NULL")
@dp.expect_or_drop("valid_value","value IS NOT NULL")
def sv_iot_sensor_events():
    return (
        _bronze("bz_iot_sensor_events")
        .dropDuplicates(["event_id"])
        .withColumn("ingest_ts", F.current_timestamp())
    )
