"""Lakeflow Spark Declarative Pipeline — Silver → Gold.

Live materialized views driving the app:
  - gd_inventory_snapshot      : latest on_hand per (sku, dc)
  - gd_commodity_latest        : latest price per commodity (+ 1h / 24h pct)
  - gd_demand_1h               : 1-hour demand aggregates per sku
  - gd_supplier_quotes_current : currently valid quotes per (sku, supplier)

All tables declared via `pyspark.pipelines` (Spark Declarative Pipelines).
"""
from __future__ import annotations

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = spark.conf.get("pipelines.catalog", "main")       # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")  # noqa: F821


# ---------------- Inventory snapshot ----------------


@dp.table(name="gd_inventory_snapshot",
          comment="Latest on_hand per (sku, dc) with reorder metadata.")
def gd_inventory_snapshot():
    sv = dp.read("sv_inventory_events")
    w = Window.partitionBy("sku", "dc_id").orderBy(F.col("event_ts").desc())
    latest = (
        sv.withColumn("rn", F.row_number().over(w))
          .where(F.col("rn") == 1)
          .drop("rn")
          .select("sku", "dc_id", "on_hand", F.col("event_ts").alias("last_event_ts"))
    )
    dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")  # noqa: F821
    return latest.join(
        dim.select("sku", "reorder_point", "target_stock"),
        on="sku", how="left",
    )


# ---------------- Commodity latest ----------------


@dp.table(name="gd_commodity_latest",
          comment="Latest price plus 1h / 24h pct change per commodity.")
def gd_commodity_latest():
    sv = dp.read("sv_commodity_prices")
    w = Window.partitionBy("commodity").orderBy(F.col("event_ts").desc())
    latest = (
        sv.withColumn("rn", F.row_number().over(w))
          .where(F.col("rn") == 1)
          .select("commodity", "price_usd", F.col("event_ts").alias("event_ts"))
    )

    def _pct_at(hours_ago: int, alias: str):
        ref_ts = F.expr(f"current_timestamp() - INTERVAL {hours_ago} HOURS")
        ref = (
            sv.where(F.col("event_ts") <= ref_ts)
              .groupBy("commodity")
              .agg(F.max("event_ts").alias("ref_ts"))
        )
        return (
            sv.alias("a")
              .join(ref.alias("b"),
                    (F.col("a.commodity") == F.col("b.commodity")) &
                    (F.col("a.event_ts") == F.col("b.ref_ts")),
                    "inner")
              .select(F.col("a.commodity"), F.col("a.price_usd").alias(alias + "_price"))
        )

    ref1 = _pct_at(1, "h1")
    ref24 = _pct_at(24, "h24")

    return (
        latest
        .join(ref1, on="commodity", how="left")
        .join(ref24, on="commodity", how="left")
        .withColumn("pct_1h",
                    F.when(F.col("h1_price").isNotNull(),
                           (F.col("price_usd") - F.col("h1_price")) / F.col("h1_price")))
        .withColumn("pct_24h",
                    F.when(F.col("h24_price").isNotNull(),
                           (F.col("price_usd") - F.col("h24_price")) / F.col("h24_price")))
        .drop("h1_price", "h24_price")
    )


# ---------------- 1-hour demand ----------------


@dp.table(name="gd_demand_1h",
          comment="1-hour tumbling-window demand aggregates per SKU.")
def gd_demand_1h():
    sv = dp.read("sv_demand_events")
    return (
        sv.groupBy(
            "sku",
            F.window("event_ts", "1 hour").alias("w"),
        ).agg(
            F.sum("qty").alias("qty"),
            F.sum("revenue_usd").alias("revenue_usd"),
        )
        .select("sku", F.col("w.start").alias("hour_ts"), "qty", "revenue_usd")
    )


# ---------------- Current supplier quotes ----------------


@dp.table(
    name="gd_supplier_quotes_current",
    comment="Most-recent still-valid quote per (sku, supplier).",
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
