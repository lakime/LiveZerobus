"""Generate SAP inventory documents: MKPF, MSEG."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
from faker import Faker

from .master_data import MATERIAL_IDS, PLANTS, _rand_date
from .procurement import _EKPO_ROWS

fake = Faker()
random.seed(43)

MOVEMENT_TYPES = {
    "101": "GR for purchase order",
    "122": "Return to vendor",
    "261": "GI for production order",
    "301": "Transfer posting plant to plant",
    "551": "Scrapping",
}


def gen_mkpf(n: int = 200) -> pd.DataFrame:
    """Material Document Header (MKPF)."""
    rows = []
    base = 5000200001
    for i in range(n):
        doc_date = _rand_date(date(2023, 1, 1), date(2025, 1, 1))
        rows.append({
            "MANDT": "100",
            "MBLNR": str(base + i),
            "MJAHR": str(doc_date.year),
            "VGART": "WE",
            "BLDAT": doc_date.isoformat(),
            "BUDAT": doc_date.isoformat(),
            "CPUDT": doc_date.isoformat(),
            "USNAM": fake.user_name()[:12],
            "BKTXT": fake.sentence(nb_words=4)[:25],
            "FRBNR": fake.bothify(text="DN-########")[:16],
        })
    return pd.DataFrame(rows)


def gen_mseg(mkpf_df: pd.DataFrame) -> pd.DataFrame:
    """Material Document Segment (MSEG) — 2 lines per header on average."""
    if mkpf_df.empty:
        return pd.DataFrame()
    rows = []
    ekpo_sample = _EKPO_ROWS[:] if _EKPO_ROWS else []
    for _, mkpf in mkpf_df.iterrows():
        n_lines = random.randint(1, 3)
        for j in range(n_lines):
            bwart = random.choice(list(MOVEMENT_TYPES.keys()))
            matnr = random.choice(MATERIAL_IDS) if MATERIAL_IDS else "MAT000000"
            menge = round(random.uniform(5, 2000), 3)
            price = round(random.uniform(0.5, 100), 2)
            # Link some lines to existing POs for realism
            ebeln, ebelp = "", ""
            if bwart in ("101", "122") and ekpo_sample and random.random() > 0.3:
                ekpo = random.choice(ekpo_sample)
                ebeln = ekpo["EBELN"]
                ebelp = ekpo["EBELP"]
                matnr = ekpo["MATNR"]
            rows.append({
                "MANDT": "100",
                "MBLNR": mkpf["MBLNR"],
                "MJAHR": mkpf["MJAHR"],
                "ZEILE": f"{(j + 1):04d}",
                "BWART": bwart,
                "WERKS": random.choice(PLANTS),
                "LGORT": random.choice(["0001", "0002", "RM01"]),
                "MATNR": matnr,
                "MENGE": menge,
                "MEINS": "KG",
                "DMBTR": round(menge * price, 2),
                "WAERS": "EUR",
                "EBELN": ebeln,
                "EBELP": ebelp,
                "ERFME": "KG",
                "BUDAT": mkpf["BUDAT"],
                "SHKZG": "S" if bwart not in ("122", "301") else "H",
                "KOSTL": f"K{random.randint(1000, 9999)}",
            })
    return pd.DataFrame(rows)
