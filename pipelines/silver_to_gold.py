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


# ---------------- SAP open PO lines ----------------


@dp.table(
    name="gd_sap_open_po_lines",
    comment="Latest SAP PO event per line with GR receipt status and outstanding quantity.",
)
def gd_sap_open_po_lines():
    sv_po = dp.read("sv_sap_purchase_orders")
    w_po  = Window.partitionBy("po_number", "po_item").orderBy(F.col("event_ts").desc())
    po_latest = (
        sv_po.withColumn("rn", F.row_number().over(w_po))
             .where(F.col("rn") == 1)
             .drop("rn")
    )

    sv_gr  = dp.read("sv_sap_goods_receipts")
    gr_agg = sv_gr.groupBy("po_number", "po_item").agg(
        F.sum("qty_received_g").alias("qty_received_g")
    )

    dim = spark.table(f"{CATALOG}.{SCHEMA}.dim_supplier")  # noqa: F821
    supplier_info = dim.select(
        "supplier_id",
        F.col("supplier_name").alias("supplier_name"),
        F.col("tier").alias("supplier_tier"),
    )

    return (
        po_latest
        .join(gr_agg, ["po_number", "po_item"], "left")
        .join(supplier_info, "supplier_id", "left")
        .withColumn("qty_received_g",   F.coalesce(F.col("qty_received_g"), F.lit(0.0)))
        .withColumn("qty_outstanding_g", F.col("quantity_g") - F.col("qty_received_g"))
        .withColumn(
            "po_status",
            F.when(F.col("event_type") == "CANCELLED", "CANCELLED")
             .when(F.col("qty_received_g") >= F.col("quantity_g") * 0.99, "FULLY_RECEIVED")
             .when(F.col("qty_received_g") > 0, "PARTIALLY_RECEIVED")
             .otherwise("OPEN"),
        )
    )


# ---------------- IoT grow-room sensor snapshot ----------------


# Threshold table: alert / warn ranges + display bounds per sensor type.
# These define NOMINAL (inside warn range), CAUTION (outside warn / inside alert),
# and ALERT (outside alert range) — computed in Gold so the UI doesn't hardcode them.
_IOT_THRESHOLDS = [
    # sensor_type,    alert_min, alert_max, warn_min, warn_max, disp_min, disp_max
    ("temperature",    12.0,  30.0,  15.0, 27.0,   5.0,  40.0),
    ("humidity",       40.0,  95.0,  50.0, 90.0,  20.0, 100.0),
    ("soil_moisture",  35.0,  97.0,  50.0, 88.0,  20.0, 100.0),
    ("light",          80.0, 650.0, 150.0,500.0,   0.0, 800.0),
    ("co2",           350.0,2200.0, 600.0,1600.0,250.0,2500.0),
    ("ph",              4.0,   8.5,   5.0,  7.0,   3.5,   9.0),
    ("ec",              0.3,   4.5,   0.8,  3.2,   0.0,   6.0),
]


@dp.table(
    name="gd_iot_sensor_latest",
    comment="Latest IoT sensor reading per (room_id, sensor_type) with thresholds and NOMINAL/CAUTION/ALERT status.",
)
def gd_iot_sensor_latest():
    from pyspark.sql.window import Window as _W
    sv = dp.read("sv_iot_sensor_events")

    # Latest reading per (room_id, sensor_type)
    w = _W.partitionBy("room_id", "sensor_type").orderBy(F.col("event_ts").desc())
    latest = (
        sv.withColumn("_rn", F.row_number().over(w))
          .where(F.col("_rn") == 1)
          .drop("_rn")
          .select("room_id", "sensor_type", "value", "unit",
                  F.col("event_ts").alias("event_ts"))
    )

    # Threshold reference table (in-memory, broadcast join)
    thresh = spark.createDataFrame(  # noqa: F821
        _IOT_THRESHOLDS,
        ["sensor_type", "alert_min", "alert_max", "warn_min", "warn_max", "disp_min", "disp_max"],
    )

    return (
        latest.join(thresh, "sensor_type", "left")
        .withColumn(
            "status",
            F.when(
                (F.col("value") < F.col("alert_min")) | (F.col("value") > F.col("alert_max")),
                "ALERT",
            ).when(
                (F.col("value") < F.col("warn_min")) | (F.col("value") > F.col("warn_max")),
                "CAUTION",
            ).otherwise("NOMINAL"),
        )
    )


# ---------------- SAP 3-way invoice match ----------------


@dp.table(
    name="gd_sap_invoice_matching",
    comment="3-way match: SAP invoice vs PO vs GR with variance and MATCHED/VARIANCE/PENDING_GR status.",
)
def gd_sap_invoice_matching():
    sv_inv = dp.read("sv_sap_invoice_documents")
    sv_po  = dp.read("sv_sap_purchase_orders")
    sv_gr  = dp.read("sv_sap_goods_receipts")

    w_po = Window.partitionBy("po_number", "po_item").orderBy(F.col("event_ts").desc())
    po_for_join = (
        sv_po.withColumn("rn", F.row_number().over(w_po))
             .where(F.col("rn") == 1)
             .drop("rn")
             .select(
                 "po_number", "po_item",
                 F.col("net_value_usd").alias("po_net_value_usd"),
                 F.col("quantity_g").alias("po_quantity_g"),
                 F.col("event_type").alias("po_event_type"),
                 F.col("sku"),
             )
    )

    gr_agg = sv_gr.groupBy("po_number", "po_item").agg(
        F.sum("qty_received_g").alias("gr_qty_g")
    )

    w_inv = Window.partitionBy("invoice_doc_number").orderBy(F.col("event_ts").desc())
    inv_latest = (
        sv_inv.withColumn("rn", F.row_number().over(w_inv))
              .where(F.col("rn") == 1)
              .drop("rn")
    )

    return (
        inv_latest
        .join(po_for_join, ["po_number", "po_item"], "left")
        .join(gr_agg,      ["po_number", "po_item"], "left")
        .withColumn("gr_qty_g", F.coalesce(F.col("gr_qty_g"), F.lit(0.0)))
        .withColumn(
            "match_status",
            F.when(F.col("po_net_value_usd").isNull(), "NO_PO")
             .when(F.col("gr_qty_g") == 0,             "PENDING_GR")
             .when(F.abs(F.col("variance_usd")) <= F.col("po_net_value_usd") * 0.02, "MATCHED")
             .otherwise("VARIANCE"),
        )
    )
