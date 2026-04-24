"""Lakeflow Spark Declarative Pipeline — Silver → Gold (Seed Procurement).

Live materialized views driving the vertical-farm procurement app:
  - gd_inventory_snapshot      : latest on_hand_g per (sku, room_id)
  - gd_commodity_latest        : latest grow-input price (+ 1h / 24h pct)
  - gd_demand_1h               : 1-hour tray + gram aggregates per sku
  - gd_supplier_quotes_current : currently valid seed quotes per (sku, supplier)

All tables declared via `pyspark.pipelines` (Spark Declarative Pipelines).
"""
from __future__ import annotations

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = spark.conf.get("pipelines.catalog", "livezerobus")  # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")  # noqa: F821


# ---------------- Seed inventory snapshot ----------------


@dp.table(name="gd_inventory_snapshot",
          comment="Latest on_hand_g per (sku, room_id) with reorder metadata.")
def gd_inventory_snapshot():
    sv = dp.read("sv_inventory_events")
    w = Window.partitionBy("sku", "room_id").orderBy(F.col("event_ts").desc())
    latest = (
        sv.withColumn("rn", F.row_number().over(w))
          .where(F.col("rn") == 1)
          .drop("rn")
          .select("sku", "room_id", "on_hand_g",
                  F.col("event_ts").alias("last_event_ts"))
    )
    dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")  # noqa: F821
    return latest.join(
        dim.select("sku", "sku_name", "crop_type",
                   "reorder_point_g", "safety_stock_g", "target_stock_g",
                   "organic_preferred"),
        on="sku", how="left",
    )


# ---------------- Grow-input price latest ----------------


@dp.table(name="gd_commodity_latest",
          comment="Latest price plus 1h / 24h pct change per grow input.")
def gd_commodity_latest():
    sv = dp.read("sv_commodity_prices")
    w = Window.partitionBy("input_key").orderBy(F.col("event_ts").desc())
    latest = (
        sv.withColumn("rn", F.row_number().over(w))
          .where(F.col("rn") == 1)
          .select("input_key", "price_usd", "unit",
                  F.col("event_ts").alias("event_ts"))
    )

    def _pct_at(hours_ago: int, alias: str):
        ref_ts = F.expr(f"current_timestamp() - INTERVAL {hours_ago} HOURS")
        ref = (
            sv.where(F.col("event_ts") <= ref_ts)
              .groupBy("input_key")
              .agg(F.max("event_ts").alias("ref_ts"))
        )
        return (
            sv.alias("a")
              .join(ref.alias("b"),
                    (F.col("a.input_key") == F.col("b.input_key")) &
                    (F.col("a.event_ts") == F.col("b.ref_ts")),
                    "inner")
              .select(F.col("a.input_key"),
                      F.col("a.price_usd").alias(alias + "_price"))
        )

    ref1 = _pct_at(1, "h1")
    ref24 = _pct_at(24, "h24")

    return (
        latest
        .join(ref1, on="input_key", how="left")
        .join(ref24, on="input_key", how="left")
        .withColumn("pct_1h",
                    F.when(F.col("h1_price").isNotNull(),
                           (F.col("price_usd") - F.col("h1_price")) / F.col("h1_price")))
        .withColumn("pct_24h",
                    F.when(F.col("h24_price").isNotNull(),
                           (F.col("price_usd") - F.col("h24_price")) / F.col("h24_price")))
        .drop("h1_price", "h24_price")
    )


# ---------------- 1-hour planting demand ----------------


@dp.table(name="gd_demand_1h",
          comment="1-hour tumbling-window planting demand per SKU (trays + grams).")
def gd_demand_1h():
    sv = dp.read("sv_demand_events")
    return (
        sv.groupBy(
            "sku",
            F.window("event_ts", "1 hour").alias("w"),
        ).agg(
            F.sum("trays").alias("trays"),
            F.sum("grams_req").alias("grams_req"),
        )
        .select("sku", F.col("w.start").alias("hour_ts"), "trays", "grams_req")
    )


# ---------------- Current supplier seed quotes ----------------


@dp.table(
    name="gd_supplier_quotes_current",
    comment="Most-recent still-valid seed quote per (sku, supplier) with $/gram.",
)
def gd_supplier_quotes_current():
    sv = dp.read("sv_supplier_quotes")
    current = sv.where(F.col("valid_until_ts") > F.current_timestamp())
    w = Window.partitionBy("sku", "supplier_id").orderBy(F.col("event_ts").desc())
    return (
        current.withColumn("rn", F.row_number().over(w))
               .where(F.col("rn") == 1)
               .drop("rn")
    )
