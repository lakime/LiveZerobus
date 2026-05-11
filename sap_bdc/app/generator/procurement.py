"""Generate SAP procurement docs: EKKO, EKPO, EKBE, EKET, EBAN."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
from faker import Faker

from .master_data import (
    COMPANY_CODES, CURRENCIES, MATERIAL_GROUPS, PLANTS,
    PURCH_GROUPS, PURCH_ORGS, VENDOR_IDS, MATERIAL_IDS,
    _rand_date,
)

fake = Faker()
random.seed(42)
Faker.seed(42)

# SAP document type codes
PO_TYPES = ["NB", "ZNB", "UB", "FO"]  # standard PO, custom PO, stock transfer, framework
PO_CATEGORY = "F"  # external procurement

_EKKO_ROWS: list[dict] = []
_EKPO_ROWS: list[dict] = []


def gen_ekko(n: int = 150) -> pd.DataFrame:
    """Purchase Order Header (EKKO)."""
    global _EKKO_ROWS
    _EKKO_ROWS = []
    base_num = 4500100001
    for i in range(n):
        ebeln = str(base_num + i)
        doc_date = _rand_date(date(2023, 1, 1), date(2024, 12, 31))
        valid_start = doc_date
        valid_end = doc_date + timedelta(days=random.randint(30, 180))
        lifnr = random.choice(VENDOR_IDS) if VENDOR_IDS else f"{100000:010d}"
        bukrs = random.choice(COMPANY_CODES)
        werks = random.choice(PLANTS)
        _EKKO_ROWS.append({
            "MANDT": "100",
            "EBELN": ebeln,
            "BUKRS": bukrs,
            "BSTYP": PO_CATEGORY,
            "BSART": random.choice(PO_TYPES),
            "LIFNR": lifnr,
            "EKORG": random.choice(PURCH_ORGS),
            "EKGRP": random.choice(PURCH_GROUPS),
            "WAERS": random.choice(CURRENCIES),
            "WKURS": round(random.uniform(0.85, 1.15), 5),
            "BEDAT": doc_date.isoformat(),
            "KDATB": valid_start.isoformat(),
            "KDATE": valid_end.isoformat(),
            "WERKS": werks,
            "ZTERM": random.choice(["NT30", "NT60", "NT90", "2%10"]),
            "INCO1": random.choice(["EXW", "FCA", "DAP", "DDP"]),
            "INCO2": fake.city()[:28],
            "ERNAM": fake.user_name()[:12],
            "AEDAT": _rand_date(doc_date, date(2025, 1, 1)).isoformat(),
            "FRGRL": random.choice(["A", "B", " "]),
        })
    return pd.DataFrame(_EKKO_ROWS)


def gen_ekpo() -> pd.DataFrame:
    """Purchase Order Item (EKPO) — 2 items per PO on average."""
    global _EKPO_ROWS
    _EKPO_ROWS = []
    if not _EKKO_ROWS:
        return pd.DataFrame()
    for ekko in _EKKO_ROWS:
        n_items = random.randint(1, 4)
        for j in range(n_items):
            ebelp = f"{(j + 1) * 10:05d}"
            matnr = random.choice(MATERIAL_IDS) if MATERIAL_IDS else "MAT000000"
            menge = round(random.uniform(10, 5000), 3)
            netpr = round(random.uniform(0.5, 150.0), 2)
            peinh = 1
            netwr = round(menge * netpr / peinh, 2)
            eindt = date.fromisoformat(ekko["BEDAT"]) + timedelta(days=random.randint(7, 60))
            _EKPO_ROWS.append({
                "MANDT": "100",
                "EBELN": ekko["EBELN"],
                "EBELP": ebelp,
                "LOEKZ": " ",
                "STATU": "7",
                "AEDAT": ekko["AEDAT"],
                "TXZ01": fake.catch_phrase()[:40],
                "MATNR": matnr,
                "WERKS": ekko["WERKS"],
                "LGORT": random.choice(["0001", "0002", "RM01"]),
                "MATKL": random.choice(MATERIAL_GROUPS),
                "INFNR": f"5300{random.randint(100000, 999999)}",
                "MENGE": menge,
                "MEINS": "KG",
                "BPRME": "KG",
                "NETPR": netpr,
                "PEINH": peinh,
                "NETWR": netwr,
                "BRTWR": round(netwr * 1.21, 2),
                "WAERS": ekko["WAERS"],
                "EINDT": eindt.isoformat(),
                "BEDAT": ekko["BEDAT"],
                "MWSKZ": random.choice(["A0", "V1", "V2"]),
                "WEPOS": "X",
                "REPOS": "X",
                "WEBRE": "X",
                "KONNR": "",
                "ABSKZ": " ",
            })
    return pd.DataFrame(_EKPO_ROWS)


def gen_ekbe() -> pd.DataFrame:
    """PO History — goods receipts and invoice receipts (EKBE)."""
    if not _EKPO_ROWS:
        return pd.DataFrame()
    rows = []
    base_gr = 5000100001
    base_ir = 5100100001
    gr_counter = 0
    ir_counter = 0
    for ekpo in _EKPO_ROWS:
        po_date = date.fromisoformat(ekpo["BEDAT"])
        eindt = date.fromisoformat(ekpo["EINDT"])
        # Goods receipt (movement type 101)
        if random.random() > 0.15:
            gr_date = eindt + timedelta(days=random.randint(-2, 5))
            qty_frac = random.choice([0.5, 1.0, 1.0, 1.0])
            rows.append({
                "MANDT": "100",
                "EBELN": ekpo["EBELN"],
                "EBELP": ekpo["EBELP"],
                "VGABE": "1",  # goods receipt
                "GJAHR": str(gr_date.year),
                "BELNR": str(base_gr + gr_counter),
                "BUZEI": "0001",
                "BEWTP": "E",
                "BUDAT": gr_date.isoformat(),
                "MENGE": round(ekpo["MENGE"] * qty_frac, 3),
                "BPMNG": round(ekpo["MENGE"] * qty_frac, 3),
                "WRBTR": round(ekpo["NETPR"] * ekpo["MENGE"] * qty_frac / ekpo["PEINH"], 2),
                "DMBTR": round(ekpo["NETPR"] * ekpo["MENGE"] * qty_frac / ekpo["PEINH"], 2),
                "WAERS": ekpo["WAERS"],
                "MATNR": ekpo["MATNR"],
                "WERKS": ekpo["WERKS"],
            })
            gr_counter += 1
        # Invoice receipt (LIV)
        if random.random() > 0.2:
            inv_date = po_date + timedelta(days=random.randint(15, 45))
            variance = round(random.uniform(-0.02, 0.03), 4)
            rows.append({
                "MANDT": "100",
                "EBELN": ekpo["EBELN"],
                "EBELP": ekpo["EBELP"],
                "VGABE": "2",  # invoice
                "GJAHR": str(inv_date.year),
                "BELNR": str(base_ir + ir_counter),
                "BUZEI": "0001",
                "BEWTP": "Q",
                "BUDAT": inv_date.isoformat(),
                "MENGE": ekpo["MENGE"],
                "BPMNG": ekpo["MENGE"],
                "WRBTR": round(ekpo["NETWR"] * (1 + variance), 2),
                "DMBTR": round(ekpo["NETWR"] * (1 + variance), 2),
                "WAERS": ekpo["WAERS"],
                "MATNR": ekpo["MATNR"],
                "WERKS": ekpo["WERKS"],
            })
            ir_counter += 1
    return pd.DataFrame(rows)


def gen_eket() -> pd.DataFrame:
    """Schedule Lines (EKET) — delivery schedule per PO item."""
    if not _EKPO_ROWS:
        return pd.DataFrame()
    rows = []
    for ekpo in _EKPO_ROWS:
        eindt = date.fromisoformat(ekpo["EINDT"])
        n_lines = random.randint(1, 3)
        qty_split = _split_qty(ekpo["MENGE"], n_lines)
        for k, qty in enumerate(qty_split):
            sch_date = eindt + timedelta(days=k * 7)
            received = round(qty * random.uniform(0, 1), 3) if random.random() > 0.3 else 0.0
            rows.append({
                "MANDT": "100",
                "EBELN": ekpo["EBELN"],
                "EBELP": ekpo["EBELP"],
                "ETENR": f"{(k + 1):04d}",
                "EINDT": sch_date.isoformat(),
                "SLFDT": sch_date.isoformat(),
                "MENGE": round(qty, 3),
                "WEMNG": received,
                "WAMNG": round(qty - received, 3),
                "AMENG": 0.0,
            })
    return pd.DataFrame(rows)


def gen_eban(n: int = 120) -> pd.DataFrame:
    """Purchase Requisitions (EBAN)."""
    rows = []
    base_num = 1000100001
    for i in range(n):
        banfn = str(base_num + i)
        req_date = _rand_date(date(2023, 1, 1), date(2024, 12, 31))
        del_date = req_date + timedelta(days=random.randint(14, 90))
        matnr = random.choice(MATERIAL_IDS) if MATERIAL_IDS else "MAT000000"
        menge = round(random.uniform(5, 2000), 3)
        price = round(random.uniform(1.0, 200.0), 2)
        rows.append({
            "MANDT": "100",
            "BANFN": banfn,
            "BNFPO": "00010",
            "BSART": random.choice(PO_TYPES),
            "BSTYP": "B",
            "STATU": random.choice(["N", "A", "X"]),
            "ERDAT": req_date.isoformat(),
            "ERNAM": fake.user_name()[:12],
            "MATNR": matnr,
            "MATKL": random.choice(MATERIAL_GROUPS),
            "WERKS": random.choice(PLANTS),
            "LGORT": random.choice(["0001", "RM01"]),
            "MENGE": menge,
            "MEINS": "KG",
            "PREIS": price,
            "PEINH": 1,
            "WAERS": random.choice(CURRENCIES),
            "BEDAT": req_date.isoformat(),
            "LFDAT": del_date.isoformat(),
            "AFNAM": fake.user_name()[:12],
            "FRGKZ": random.choice([" ", "A", "F"]),
            "EKORG": random.choice(PURCH_ORGS),
            "EKGRP": random.choice(PURCH_GROUPS),
            "LIFNR": random.choice(VENDOR_IDS) if random.random() > 0.4 and VENDOR_IDS else "",
        })
    return pd.DataFrame(rows)


# ── Helper ────────────────────────────────────────────────────────────────────

def _split_qty(total: float, n: int) -> list[float]:
    if n == 1:
        return [total]
    points = sorted(random.uniform(0.1, 0.9) for _ in range(n - 1))
    splits = []
    prev = 0.0
    for p in points:
        splits.append(round((p - prev) * total, 3))
        prev = p
    splits.append(round((1.0 - prev) * total, 3))
    return splits
