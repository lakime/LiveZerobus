"""Lakeflow Spark Declarative Pipeline — Procurement recommendations (ML).

For every SKU under reorder_point we:
  1. join the currently valid supplier quotes,
  2. score each (sku, supplier) with the Unity-Catalog-registered MLflow
     `supplier_scoring_model` (alias @prod),
  3. pick the top-ranked one, and
  4. emit a recommendation row with decision = BUY_NOW / WAIT / REVIEW
     based on ML score + commodity 24h trend.

All tables declared via `pyspark.pipelines` (Spark Declarative Pipelines).
"""
from __future__ import annotations

import mlflow
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = spark.conf.get("pipelines.catalog", "main")                         # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")                    # noqa: F821
MODEL_NAME = spark.conf.get("pipelines.model_name",                           # noqa: F821
                            f"{CATALOG}.{SCHEMA}.supplier_scoring_model")

# Vectorized, per-executor model loader.
_score_udf = mlflow.pyfunc.spark_udf(
    spark,                                                                    # noqa: F821
    model_uri=f"models:/{MODEL_NAME}@prod",
    result_type="double",
)


# --------------------- Supplier leaderboard ---------------------


@dp.table(name="gd_supplier_leaderboard",
          comment="Suppliers ranked per SKU using supplier_scoring_model.")
def gd_supplier_leaderboard():
    q = dp.read("gd_supplier_quotes_current")
    s = spark.table(f"{CATALOG}.{SCHEMA}.dim_supplier")                       # noqa: F821
    c = dp.read("gd_commodity_latest")
    d = dp.read("gd_demand_1h")

    demand_1h = d.groupBy("sku").agg(F.sum("qty").alias("demand_1h_qty"))

    sku_dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")                      # noqa: F821
    sku_comm = sku_dim.select("sku", "commodity")
    commodity_feat = (
        c.select("commodity", F.col("pct_24h").alias("commodity_pct_24h"))
         .join(sku_comm, on="commodity", how="inner")
         .select("sku", "commodity_pct_24h")
    )

    enriched = (
        q.join(s, on="supplier_id", how="left")
         .join(demand_1h, on="sku", how="left")
         .join(commodity_feat, on="sku", how="left")
         .fillna({"demand_1h_qty": 0, "commodity_pct_24h": 0.0,
                  "on_time_pct": 0.85, "quality_score": 0.85})
    )

    scored = enriched.withColumn(
        "score",
        _score_udf(
            F.col("unit_price_usd"),
            F.col("lead_time_days"),
            F.col("min_qty"),
            F.col("on_time_pct"),
            F.col("quality_score"),
            F.col("demand_1h_qty"),
            F.col("commodity_pct_24h"),
        ),
    )

    w = Window.partitionBy("sku").orderBy(F.col("score").desc())
    return (
        scored
        .withColumn("rank", F.row_number().over(w))
        .select(
            "sku", "supplier_id", "supplier_name",
            "unit_price_usd", "lead_time_days", "min_qty",
            "score", "rank",
            F.col("event_ts").alias("quote_ts"),
        )
    )


# --------------------- Procurement recommendations ---------------------


@dp.table(name="gd_procurement_recommendations",
          comment="Reorder actions ranked, ML-scored, per SKU / DC.")
def gd_procurement_recommendations():
    inv = dp.read("gd_inventory_snapshot")
    lb = dp.read("gd_supplier_leaderboard").where(F.col("rank") == 1)
    comm = (
        dp.read("gd_commodity_latest")
          .select("commodity", F.col("pct_24h").alias("commodity_pct_24h"))
    )
    sku_dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")                      # noqa: F821

    low = inv.where(F.col("on_hand") <= F.col("reorder_point"))

    joined = (
        low.join(sku_dim.select("sku", "commodity"), on="sku", how="left")
           .join(comm, on="commodity", how="left")
           .join(lb, on="sku", how="left")
           .withColumn("reorder_qty",
                       F.greatest(F.col("target_stock") - F.col("on_hand"), F.lit(0)))
           .withColumn("total_cost_usd",
                       F.col("reorder_qty") * F.col("unit_price_usd"))
    )

    decision = (
        F.when(
            (F.col("commodity_pct_24h") > 0.01) |
            (F.col("on_hand") < F.col("reorder_point") * 0.5) |
            (F.col("score") > 0.85),
            F.lit("BUY_NOW"),
        )
        .when(
            (F.col("commodity_pct_24h") < -0.01) &
            (F.col("on_hand") > F.col("reorder_point") * 0.8),
            F.lit("WAIT"),
        )
        .otherwise(F.lit("REVIEW"))
    )

    return (
        joined
        .withColumn("recommendation_id",
                    F.concat_ws("-", F.col("sku"), F.col("dc_id"),
                                F.date_format(F.current_timestamp(), "yyyyMMddHHmmss")))
        .withColumn("created_ts", F.current_timestamp())
        .withColumn("decision", decision)
        .withColumn("rationale",
                    F.concat_ws(" · ",
                                F.concat(F.lit("on_hand="), F.col("on_hand")),
                                F.concat(F.lit("reorder="), F.col("reorder_point")),
                                F.concat(F.lit("trend24h="),
                                         F.format_number(F.col("commodity_pct_24h") * 100, 2),
                                         F.lit("%")),
                                F.concat(F.lit("ml_score="),
                                         F.format_number(F.col("score"), 3))))
        .select(
            "recommendation_id", "created_ts",
            "sku", "dc_id",
            "reorder_qty",
            F.col("supplier_id").alias("recommended_supplier_id"),
            F.col("supplier_name").alias("recommended_supplier_name"),
            "unit_price_usd", "total_cost_usd",
            F.col("lead_time_days").alias("expected_lead_days"),
            F.col("score").alias("ml_score"),
            "commodity_pct_24h",
            "decision", "rationale",
        )
    )
