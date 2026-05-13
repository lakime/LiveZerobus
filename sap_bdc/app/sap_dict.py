"""SAP table and field descriptions used to enrich Delta Sharing metadata.

These show up as table descriptions and column comments in Databricks
Catalog Explorer's Overview pane. Keys are case-insensitive on lookup.
"""
from __future__ import annotations

# Table-level descriptions (already used by routes/tables.py too).
TABLE_DESCRIPTIONS: dict[str, str] = {
    "LFA1":  "Vendor Master General — company name, address, bank, payment terms",
    "MARA":  "Material Master General — material type, group, base unit of measure",
    "T001":  "Company Codes — company name, country, currency",
    "T001W": "Plants / Branches — production sites and distribution centres",
    "T024":  "Purchasing Groups — buyer group names and contact details",
    "T023":  "Material Groups — commodity category descriptions",
    "EKKO":  "Purchase Order Header — vendor, org, currency, validity dates",
    "EKPO":  "Purchase Order Item — material, quantity, net price, delivery date",
    "EKBE":  "PO History — goods receipts and invoice receipts per PO line",
    "EKET":  "Schedule Lines — delivery schedule quantities and dates per PO item",
    "EBAN":  "Purchase Requisitions — internal demand requests awaiting PO creation",
    "MKPF":  "Material Document Header — goods movement header (GR / GI / transfer)",
    "MSEG":  "Material Document Segment — movement details, quantity, value, storage loc.",
    "RBKP":  "Invoice Receipt Header — MM Logistics Invoice Verification header",
    "BKPF":  "Accounting Document Header — FI-AP document for vendor payments",
}

# Canonical SAP field name → one-line description. Used to populate
# column metadata.comment so they appear in Catalog Explorer.
FIELD_COMMENTS: dict[str, str] = {
    # Universal
    "MANDT":  "Client (SAP system tenant)",
    # Org structure
    "BUKRS":  "Company code",
    "BUTXT":  "Company name",
    "WAERS":  "Currency key",
    "LAND1":  "Country key",
    "SPRAS":  "Language key",
    "WERKS":  "Plant",
    "NAME1":  "Name 1",
    "ORT01":  "City",
    "STRAS":  "Street and house number",
    "TELF1":  "First telephone number",
    "KTOKK":  "Vendor account group",
    # Material master
    "MATNR":  "Material number",
    "MTART":  "Material type",
    "MBRSH":  "Industry sector",
    "MATKL":  "Material group",
    "MEINS":  "Base unit of measure",
    "BRGEW":  "Gross weight",
    "NTGEW":  "Net weight",
    "GEWEI":  "Weight unit",
    # Purchasing groups
    "EKGRP":  "Purchasing group",
    "EKNAM":  "Purchasing group description",
    "EKORG":  "Purchasing organization",
    # Purchase order
    "EBELN":  "Purchase order number",
    "EBELP":  "PO item number",
    "BSTYP":  "PO category (F=PO, A=RFQ, K=Contract, L=Scheduling agreement)",
    "BSART":  "PO type",
    "LIFNR":  "Vendor account number",
    "BEDAT":  "PO date",
    "KDATB":  "Validity period start",
    "KDATE":  "Validity period end",
    "WKURS":  "Exchange rate",
    "ZTERM":  "Payment terms key",
    "INCO1":  "Incoterm part 1",
    "INCO2":  "Incoterm part 2",
    "ERNAM":  "Name of person who created the object",
    "AEDAT":  "Date on which the record was created",
    "FRGRL":  "Release indicator",
    "MENGE":  "Quantity",
    "NETPR":  "Net price (per unit)",
    "NETWR":  "Net value (line)",
    "PEINH":  "Price unit",
    "EINDT":  "Item delivery date",
    "LGORT":  "Storage location",
    "BEWTP":  "PO history category (E=GR, Q=IR)",
    "DMBTR":  "Amount in local currency",
    "BWART":  "Movement type",
    # Material document
    "MBLNR":  "Material document number",
    "MJAHR":  "Material document year",
    "ZEILE":  "Item number in material document",
    # Finance
    "RBELN":  "Invoice document number",
    "GJAHR":  "Fiscal year",
    "BLDAT":  "Document date",
    "BUDAT":  "Posting date",
    "WRBTR":  "Amount in document currency",
    "RMWWR":  "Gross invoice amount",
    "BKTXT":  "Document header text",
    # Requisitions
    "BANFN":  "Purchase requisition number",
    "BNFPO":  "PR item number",
}


def table_description(name: str) -> str | None:
    """Case-insensitive table description lookup."""
    target = name.upper()
    return TABLE_DESCRIPTIONS.get(target)


def field_comment(name: str) -> str | None:
    """Case-insensitive field comment lookup."""
    return FIELD_COMMENTS.get(name.upper())
