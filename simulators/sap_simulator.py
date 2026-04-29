"""SAP ERP procurement event simulator — procure-to-pay (P2P) cycle.

Simulates the three SAP event streams that would flow from an ERP integration:
  1. Purchase Orders (MM)   → bz_sap_purchase_orders
  2. Goods Receipts (MIGO)  → bz_sap_goods_receipts
  3. Invoice Documents (LIV/MIRO) → bz_sap_invoice_documents

Events are correlated: each PO triggers a GR after ~GR_DELAY_S seconds, and
each GR triggers an invoice after ~INV_DELAY_S seconds. These short delays
compress multi-day real-world lead times into a live demo window.
"""
from __future__ import annotations

import dataclasses
import itertools
import random
import time
from contextlib import ExitStack
from datetime import timedelta
from typing import NamedTuple

import click

from common import (
    ROOMS,
    SKUS,
    SUPPLIERS,
    SapGoodsReceipt,
    SapInvoiceDocument,
    SapPurchaseOrder,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

# Demo-scale delays: compress "days" into seconds so the pipeline shows activity
GR_DELAY_S  = 20
INV_DELAY_S = 15

PLANT_CODE   = "PL01"
COMPANY_CODE = "1000"
PURCH_ORG    = "1000"

# SAP document number sequences — large start values look authentic
_PO_SEQ  = itertools.count(4500100001)
_GR_SEQ  = itertools.count(5000100001)
_INV_SEQ = itertools.count(5100100001)

# Order quantities per SKU (grams per PO line; multiplied by a random pack count)
_ORDER_QTY_G: dict[str, float] = {
    "SEED-LETT-BUT-01": 25.0,   "SEED-LETT-RED-01": 25.0,   "SEED-LETT-ROM-01": 25.0,
    "SEED-BAS-GEN-01":   5.0,   "SEED-BAS-THA-01":   5.0,
    "SEED-KALE-LAC-01": 25.0,   "SEED-KALE-RED-01": 25.0,
    "SEED-ARU-AST-01":  25.0,   "SEED-SPIN-SPA-01": 25.0,
    "SEED-MG-RAD-01":  500.0,   "SEED-MG-PEA-01":  1000.0,  "SEED-MG-SUN-01":  500.0,
    "SEED-MG-BROC-01": 250.0,   "SEED-MG-AMA-01":   100.0,
    "SEED-HERB-CIL-01":100.0,   "SEED-HERB-PAR-01": 100.0,  "SEED-HERB-DIL-01":100.0,
    "SEED-BOK-SHA-01":  25.0,   "SEED-MUST-WAS-01":  25.0,  "SEED-TAT-RED-01":  25.0,
}

# Per-gram unit prices mirroring supplier_quotes_simulator.py SKU_USD_PER_GRAM
_UNIT_PRICE_G: dict[str, float] = {
    "SEED-LETT-BUT-01": 0.35, "SEED-LETT-RED-01": 0.42, "SEED-LETT-ROM-01": 0.30,
    "SEED-BAS-GEN-01":  0.85, "SEED-BAS-THA-01":  1.10,
    "SEED-KALE-LAC-01": 0.48, "SEED-KALE-RED-01": 0.55,
    "SEED-ARU-AST-01":  0.38, "SEED-SPIN-SPA-01": 0.52,
    "SEED-MG-RAD-01":   0.18, "SEED-MG-PEA-01":   0.12, "SEED-MG-SUN-01":  0.15,
    "SEED-MG-BROC-01":  0.22, "SEED-MG-AMA-01":   0.34,
    "SEED-HERB-CIL-01": 0.58, "SEED-HERB-PAR-01": 0.44, "SEED-HERB-DIL-01":0.36,
    "SEED-BOK-SHA-01":  0.40, "SEED-MUST-WAS-01": 0.68, "SEED-TAT-RED-01": 0.62,
}


class _PendingGR(NamedTuple):
    po: SapPurchaseOrder
    emit_after: float


class _PendingInvoice(NamedTuple):
    gr: SapGoodsReceipt
    po: SapPurchaseOrder
    emit_after: float


def _make_po(sku: str, supplier: str) -> SapPurchaseOrder:
    qty = _ORDER_QTY_G[sku] * random.choice([1, 2, 3, 5])
    unit_price = _UNIT_PRICE_G[sku] * random.gauss(1.0, 0.03)
    unit_price = max(unit_price, 0.001)
    return SapPurchaseOrder(
        event_id=new_event_id(),
        event_ts=now_utc(),
        po_number=str(next(_PO_SEQ)),
        po_item=10,
        event_type="CREATED",
        supplier_id=supplier,
        sku=sku,
        quantity_g=round(qty, 3),
        unit_price_usd=round(unit_price, 4),
        net_value_usd=round(qty * unit_price, 2),
        currency="USD",
        delivery_date_ts=now_utc() + timedelta(days=random.randint(3, 14)),
        plant=PLANT_CODE,
        company_code=COMPANY_CODE,
        purchase_org=PURCH_ORG,
    )


def _make_gr(po: SapPurchaseOrder, room: str) -> SapGoodsReceipt:
    r = random.random()
    if r < 0.07:
        # Partial delivery
        qty = round(po.quantity_g * random.uniform(0.50, 0.95), 3)
    elif r < 0.10:
        # Over-delivery (small)
        qty = round(po.quantity_g * random.uniform(1.01, 1.10), 3)
    else:
        qty = po.quantity_g
    return SapGoodsReceipt(
        event_id=new_event_id(),
        event_ts=now_utc(),
        gr_doc_number=str(next(_GR_SEQ)),
        gr_item=1,
        po_number=po.po_number,
        po_item=po.po_item,
        sku=po.sku,
        qty_received_g=qty,
        room_id=room,
        movement_type="101",
        batch_id=f"BAT-{new_event_id()[:8].upper()}",
        posting_date_ts=now_utc(),
        delivery_note=f"DN-{random.randint(100000, 999999)}",
    )


def _make_reversal(gr: SapGoodsReceipt) -> SapGoodsReceipt:
    return dataclasses.replace(
        gr,
        event_id=new_event_id(),
        event_ts=now_utc(),
        gr_doc_number=str(next(_GR_SEQ)),
        movement_type="122",
        qty_received_g=-gr.qty_received_g,  # negative to net out in Gold aggregates
    )


def _make_invoice(gr: SapGoodsReceipt, po: SapPurchaseOrder) -> SapInvoiceDocument:
    unit_price = po.unit_price_usd
    if random.random() < 0.05:
        unit_price *= random.uniform(0.97, 1.03)
    net = round(gr.qty_received_g * unit_price, 2)
    variance = round(net - po.net_value_usd, 2)
    # Block invoices where variance exceeds 2% of PO value
    status = "BLOCKED" if po.net_value_usd and abs(variance) > po.net_value_usd * 0.02 else "POSTED"
    return SapInvoiceDocument(
        event_id=new_event_id(),
        event_ts=now_utc(),
        invoice_doc_number=str(next(_INV_SEQ)),
        po_number=po.po_number,
        po_item=po.po_item,
        supplier_id=po.supplier_id,
        invoice_date_ts=now_utc(),
        posting_date_ts=now_utc(),
        quantity_invoiced_g=gr.qty_received_g,
        unit_price_usd=round(unit_price, 4),
        net_amount_usd=net,
        tax_amount_usd=0.0,
        currency="USD",
        payment_terms=random.choice(["NET30", "NET60", "2/10NET30"]),
        status=status,
        variance_usd=variance,
    )


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema",  default="procurement")
@click.option("--rate",    default=1, help="New POs per second.")
@click.option("--duration", default=0, help="Seconds to run; 0 = forever.")
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    po_table  = f"{catalog}.{schema}.bz_sap_purchase_orders"
    gr_table  = f"{catalog}.{schema}.bz_sap_goods_receipts"
    inv_table = f"{catalog}.{schema}.bz_sap_invoice_documents"

    interval = 1.0 / max(rate, 1)
    t_end = time.time() + duration if duration else None

    pending_grs:      list[_PendingGR]      = []
    pending_invoices: list[_PendingInvoice] = []

    with ExitStack() as stack:
        po_stream  = stack.enter_context(zerobus_stream(po_table))
        gr_stream  = stack.enter_context(zerobus_stream(gr_table))
        inv_stream = stack.enter_context(zerobus_stream(inv_table))

        print(
            f"Streaming SAP P2P → {po_table}, {gr_table}, {inv_table} @ ~{rate} PO/s\n"
            f"  GR delay={GR_DELAY_S}s  Invoice delay={INV_DELAY_S}s"
        )

        while True:
            now = time.time()

            # --- Emit a new PO ---
            sku      = random.choice(SKUS)
            supplier = random.choice(SUPPLIERS)
            po       = _make_po(sku, supplier)
            po_stream.send(as_row(po))

            # 40% chance: also emit an APPROVED event immediately
            if random.random() < 0.40:
                approved = dataclasses.replace(
                    po,
                    event_id=new_event_id(),
                    event_ts=now_utc(),
                    event_type="APPROVED",
                )
                po_stream.send(as_row(approved))

            # 3% chance: emit a CHANGED event (e.g. quantity adjustment)
            if random.random() < 0.03:
                changed_qty = round(po.quantity_g * random.uniform(0.8, 1.2), 3)
                changed = dataclasses.replace(
                    po,
                    event_id=new_event_id(),
                    event_ts=now_utc(),
                    event_type="CHANGED",
                    quantity_g=changed_qty,
                    net_value_usd=round(changed_qty * po.unit_price_usd, 2),
                )
                po_stream.send(as_row(changed))

            gr_jitter = GR_DELAY_S * random.uniform(0.8, 1.4)
            pending_grs.append(_PendingGR(po, now + gr_jitter))

            # --- Flush ready GRs ---
            still: list[_PendingGR] = []
            for pgr in pending_grs:
                if time.time() >= pgr.emit_after:
                    room = random.choice(ROOMS)
                    gr   = _make_gr(pgr.po, room)
                    gr_stream.send(as_row(gr))
                    # 4% chance: reversal shortly after GR
                    if random.random() < 0.04:
                        gr_stream.send(as_row(_make_reversal(gr)))
                    inv_jitter = INV_DELAY_S * random.uniform(0.8, 1.4)
                    pending_invoices.append(_PendingInvoice(gr, pgr.po, time.time() + inv_jitter))
                else:
                    still.append(pgr)
            pending_grs = still

            # --- Flush ready invoices ---
            still_inv: list[_PendingInvoice] = []
            for pinv in pending_invoices:
                if time.time() >= pinv.emit_after:
                    inv_stream.send(as_row(_make_invoice(pinv.gr, pinv.po)))
                else:
                    still_inv.append(pinv)
            pending_invoices = still_inv

            time.sleep(interval)
            if t_end and time.time() > t_end:
                po_stream.flush()
                gr_stream.flush()
                inv_stream.flush()
                break


if __name__ == "__main__":
    main()
