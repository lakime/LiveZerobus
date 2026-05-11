from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import Settings
from ..delta_store import list_table_names, read_table, table_metadata, table_row_count
from ..generator import TABLE_ORDER

router = APIRouter(prefix="/api", tags=["gui"])

TABLE_DESCRIPTIONS = {
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

MODULE_MAP = {
    "T001": "Org", "T001W": "Org", "T023": "MM", "T024": "MM",
    "LFA1": "MM", "MARA": "MM",
    "EKKO": "MM-PUR", "EKPO": "MM-PUR", "EKBE": "MM-PUR",
    "EKET": "MM-PUR", "EBAN": "MM-PUR",
    "MKPF": "MM-IM", "MSEG": "MM-IM",
    "RBKP": "MM-IV", "BKPF": "FI-AP",
}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/tables")
def list_tables(request: Request) -> list[dict[str, Any]]:
    s = _settings(request)
    names = list_table_names(s)
    result = []
    for name in TABLE_ORDER:
        result.append({
            "name": name,
            "description": TABLE_DESCRIPTIONS.get(name, ""),
            "module": MODULE_MAP.get(name, ""),
            "row_count": table_row_count(s, name) if name in names else 0,
            "available": name in names,
        })
    return result


@router.get("/tables/{name}/rows")
def table_rows(
    name: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str = Query("", alias="q"),
) -> dict[str, Any]:
    s = _settings(request)
    names = list_table_names(s)
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Table {name} not found")
    df = read_table(s, name)
    if search:
        mask = df.apply(
            lambda col: col.astype(str).str.contains(search, case=False, na=False)
        ).any(axis=1)
        df = df[mask]
    total = len(df)
    page = df.iloc[offset: offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": list(page.columns),
        "rows": page.fillna("").astype(str).values.tolist(),
    }


@router.get("/tables/{name}/schema")
def table_schema(name: str, request: Request) -> dict[str, Any]:
    s = _settings(request)
    names = list_table_names(s)
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Table {name} not found")
    return table_metadata(s, name)
