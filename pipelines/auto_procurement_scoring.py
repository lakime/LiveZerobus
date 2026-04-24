"""Lakeflow Spark Declarative Pipeline — Seed-Procurement scoring (ML).

For every SKU under `reorder_point_g` we:
  1. join the currently valid supplier seed-pack quotes,
  2. score each (sku, supplier) with the Unity-Catalog-registered MLflow
     `supplier_scoring_model` (alias @prod),
  3. pick the top-ranked one, and
  4. emit a recommendation row with decision = BUY_NOW / WAIT / REVIEW
     based on ML score + grow-input 24h trend (e.g. coco coir, nutrients).

Tables declared via `pyspark.pipelines` (Spark Declarative Pipelines).

Model features (in order):
    usd_per_gram, pack_size_g, lead_time_days, min_qty,
    on_time_pct, quality_score,
    demand_1h_trays, input_pct_24h, organic_cert_int
"""
from __future__ import annotations

import mlflow
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = spark.conf.get("pipelines.catalog", "livezerobus")                  # noqa: F821
SCHEMA = spark.conf.get("pipelines.schema", "procurement")                    # noqa: F821
MODEL_NAME = spark.conf.get("livezerobus.model_name",                         # noqa: F821
                            f"{CATALOG}.{SCHEMA}.supplier_scoring_model")

# Vectorized, per-executor model loader.
_score_udf = mlflow.pyfunc.spark_udf(
    spark,                                                                    # noqa: F821
    model_uri=f"models:/{MODEL_NAME}@prod",
    result_type="double",
)

# Which grow-input drives the cost volatility of each crop_type.
# Microgreens are nutrient/substrate-intensive; leafy greens are rockwool/coco.
SKU_INPUT_MAP = {
    "lettuce":      "rockwool",
    "basil":        "rockwool",
    "kale":         "rockwool",
    "arugula":      "rockwool",
    "spinach":      "rockwool",
    "herb":         "rockwool",
    "asian-green":  "rockwool",
    "microgreens":  "coco_coir",
}


# --------------------- Seed-supplier leaderboard ---------------------


@dp.table(name="gd_supplier_leaderboard",
          comment="Seed houses ranked per SKU using supplier_scoring_model.")
def gd_supplier_leaderboard():
    q = dp.read("gd_supplier_quotes_current")
    s = spark.table(f"{CATALOG}.{SCHEMA}.dim_supplier")                       # noqa: F821
    c = dp.read("gd_commodity_latest")
    d = dp.read("gd_demand_1h")

    demand_1h = d.groupBy("sku").agg(F.sum("trays").alias("demand_1h_trays"))

    sku_dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")                      # noqa: F821

    # Map each crop_type to its most-relevant grow-input.
    mapping_rows = [(k, v) for k, v in SKU_INPUT_MAP.items()]
    crop_to_input = spark.createDataFrame(                                    # noqa: F821
        mapping_rows, schema="crop_type STRING, input_key STRING"
    )
    sku_input = (
        sku_dim.select("sku", "crop_type", "organic_preferred")
               .join(crop_to_input, on="crop_type", how="left")
    )
    input_feat = (
        c.select("input_key", F.col("pct_24h").alias("input_pct_24h"))
         .join(sku_input.select("sku", "input_key"), on="input_key", how="inner")
         .select("sku", "input_pct_24h")
    )

    enriched = (
        q.join(s, on="supplier_id", how="left")
         .join(demand_1h, on="sku", how="left")
         .join(input_feat, on="sku", how="left")
         .withColumn(
             "organic_cert_int",
             F.when(F.col("organic_cert"), F.lit(1.0)).otherwise(F.lit(0.0)),
         )
         .fillna({
             "demand_1h_trays": 0,
             "input_pct_24h": 0.0,
             "on_time_pct": 0.85,
             "quality_score": 0.85,
             "organic_cert_int": 0.0,
         })
    )

    scored = enriched.withColumn(
        "score",
        _score_udf(
            F.col("usd_per_gram"),
            F.col("pack_size_g"),
            F.col("lead_time_days"),
            F.col("min_qty"),
            F.col("on_time_pct"),
            F.col("quality_score"),
            F.col("demand_1h_trays"),
            F.col("input_pct_24h"),
            F.col("organic_cert_int"),
        ),
    )

    w = Window.partitionBy("sku").orderBy(F.col("score").desc())
    return (
        scored
        .withColumn("rank", F.row_number().over(w))
        .select(
            "sku", "supplier_id", "supplier_name",
            "pack_size_g", "unit_price_usd", "usd_per_gram",
            "lead_time_days", "min_qty",
            "organic", "score", "rank",
            F.col("event_ts").alias("quote_ts"),
        )
    )


# --------------------- Seed procurement recommendations ---------------------


@dp.table(name="gd_procurement_recommendations",
          comment="Reorder actions ranked, ML-scored, per SKU / grow-room.")
def gd_procurement_recommendations():
    inv = dp.read("gd_inventory_snapshot")
    lb = dp.read("gd_supplier_leaderboard").where(F.col("rank") == 1)
    sku_dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_sku")                      # noqa: F821
    c = dp.read("gd_commodity_latest")

    mapping_rows = [(k, v) for k, v in SKU_INPUT_MAP.items()]
    crop_to_input = spark.createDataFrame(                                    # noqa: F821
        mapping_rows, schema="crop_type STRING, input_key STRING"
    )
    sku_input = (
        sku_dim.select("sku", "crop_type")
               .join(crop_to_input, on="crop_type", how="left")
    )
    input_feat = (
        c.select("input_key", F.col("pct_24h").alias("input_pct_24h"))
         .join(sku_input.select("sku", "input_key"), on="input_key", how="inner")
         .select("sku", "input_pct_24h")
    )

    # Reorder when below reorder_point_g (either rebuilding to target
    # or at least to safety stock — target wins when target > on_hand).
    low = inv.where(F.col("on_hand_g") <= F.col("reorder_point_g"))

    joined = (
        low.join(input_feat, on="sku", how="left")
           .join(lb, on="sku", how="left")
           .withColumn(
               "reorder_grams",
               F.greatest(F.col("target_stock_g") - F.col("on_hand_g"), F.lit(0.0)),
           )
           # pack count rounded up — never short-order seed
           .withColumn(
               "packs",
               F.ceil(F.col("reorder_grams") / F.col("pack_size_g")).cast("int"),
           )
           .withColumn(
               "total_cost_usd",
               F.col("packs") * F.col("unit_price_usd"),
           )
    )

    decision = (
        F.when(
            (F.col("input_pct_24h") > 0.01) |
            (F.col("on_hand_g") < F.col("reorder_point_g") * 0.5) |
            (F.col("score") > 0.85),
            F.lit("BUY_NOW"),
        )
        .when(
            (F.col("input_pct_24h") < -0.01) &
            (F.col("on_hand_g") > F.col("reorder_point_g") * 0.8),
            F.lit("WAIT"),
        )
        .otherwise(F.lit("REVIEW"))
    )

    return (
        joined
        .withColumn("recommendation_id",
                    F.concat_ws("-", F.col("sku"), F.col("room_id"),
                                F.date_format(F.current_timestamp(), "yyyyMMddHHmmss")))
        .withColumn("created_ts", F.current_timestamp())
        .withColumn("decision", decision)
        .withColumn("rationale",
                    F.concat_ws(" · ",
                                F.concat(F.lit("on_hand_g="),
                                         F.format_number(F.col("on_hand_g"), 0)),
                                F.concat(F.lit("reorder_g="),
                                         F.format_number(F.col("reorder_point_g"), 0)),
                                F.concat(F.lit("input24h="),
                                         F.format_number(F.col("input_pct_24h") * 100, 2),
                                         F.lit("%")),
                                F.concat(F.lit("ml_score="),
                                         F.format_number(F.col("score"), 3))))
        .select(
            "recommendation_id", "created_ts",
            "sku", "room_id",
            "reorder_grams", "packs",
            F.col("supplier_id").alias("recommended_supplier_id"),
            F.col("supplier_name").alias("recommended_supplier_name"),
            "pack_size_g", "unit_price_usd", "total_cost_usd",
            F.col("lead_time_days").alias("expected_lead_days"),
            F.col("score").alias("ml_score"),
            "input_pct_24h",
            "decision", "rationale",
        )
    )
