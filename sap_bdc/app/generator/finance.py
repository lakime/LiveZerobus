"""Generate SAP finance docs: RBKP (MM invoice header), BKPF (accounting header)."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
from faker import Faker

from .master_data import COMPANY_CODES, CURRENCIES, VENDOR_IDS, _rand_date
from .procurement import _EKKO_ROWS

fake = Faker()
random.seed(44)

DOC_TYPES = ["RE", "KR", "KG", "KZ"]  # vendor invoice, vendor credit, credit memo, payment
PAYMENT_TERMS = ["NT30", "NT60", "NT90", "2%10NET30"]
TAX_CODES = ["V1", "V2", "A0"]

_RBKP_ROWS: list[dict] = []


def gen_rbkp(n: int = 150) -> pd.DataFrame:
    """Invoice Receipt Header (RBKP) — MM Logistics Invoice Verification."""
    global _RBKP_ROWS
    _RBKP_ROWS = []
    base = 5100200001
    ekko_sample = _EKKO_ROWS[:] if _EKKO_ROWS else []
    for i in range(n):
        inv_date = _rand_date(date(2023, 3, 1), date(2025, 1, 1))
        post_date = inv_date + timedelta(days=random.randint(0, 5))
        lifnr = random.choice(VENDOR_IDS) if VENDOR_IDS else f"{100000:010d}"
        bukrs = random.choice(COMPANY_CODES)
        waers = random.choice(CURRENCIES)
        gross = round(random.uniform(500, 80000), 2)
        tax = round(gross * random.choice([0.0, 0.09, 0.19, 0.21]), 2)
        rbeln = str(base + i)
        gjahr = str(inv_date.year)
        ekko_ref = random.choice(ekko_sample) if ekko_sample and random.random() > 0.2 else None
        _RBKP_ROWS.append({
            "MANDT": "100",
            "RBELN": rbeln,
            "GJAHR": gjahr,
            "BLDAT": inv_date.isoformat(),
            "BUDAT": post_date.isoformat(),
            "CPUDT": post_date.isoformat(),
            "USNAM": fake.user_name()[:12],
            "LIFNR": ekko_ref["LIFNR"] if ekko_ref else lifnr,
            "BUKRS": ekko_ref["BUKRS"] if ekko_ref else bukrs,
            "WAERS": ekko_ref["WAERS"] if ekko_ref else waers,
            "WRBTR": gross,
            "RMWWR": round(gross - tax, 2),
            "WMWST": tax,
            "ZTERM": random.choice(PAYMENT_TERMS),
            "BKTXT": fake.sentence(nb_words=5)[:25],
            "XBLNR": fake.bothify(text="INV-####-##")[:16],
            "STBLG": "",
            "RBSTAT": random.choice(["A", "A", "A", "B", "P"]),  # mostly posted
        })
    return pd.DataFrame(_RBKP_ROWS)


def gen_bkpf(n: int = 150) -> pd.DataFrame:
    """Accounting Document Header (BKPF) — FI-AP."""
    rows = []
    base = 1900100001
    rbkp_sample = _RBKP_ROWS[:] if _RBKP_ROWS else []
    for i in range(n):
        post_date = _rand_date(date(2023, 3, 1), date(2025, 1, 1))
        bukrs = random.choice(COMPANY_CODES)
        gjahr = str(post_date.year)
        belnr = str(base + i)
        blart = random.choice(DOC_TYPES)
        rbkp_ref = random.choice(rbkp_sample) if rbkp_sample and random.random() > 0.25 else None
        rows.append({
            "MANDT": "100",
            "BUKRS": rbkp_ref["BUKRS"] if rbkp_ref else bukrs,
            "BELNR": belnr,
            "GJAHR": gjahr,
            "BLART": blart,
            "BLDAT": post_date.isoformat(),
            "BUDAT": post_date.isoformat(),
            "MONAT": f"{post_date.month:02d}",
            "CPUDT": post_date.isoformat(),
            "USNAM": fake.user_name()[:12],
            "WAERS": rbkp_ref["WAERS"] if rbkp_ref else random.choice(CURRENCIES),
            "KURSF": round(random.uniform(0.85, 1.15), 5),
            "BKTXT": fake.sentence(nb_words=4)[:25],
            "XBLNR": rbkp_ref["XBLNR"] if rbkp_ref else fake.bothify(text="REF-####")[:16],
            "AWTYP": "RMRP" if rbkp_ref else "BKPF",
            "AWKEY": (rbkp_ref["RBELN"] + rbkp_ref["GJAHR"]) if rbkp_ref else "",
            "BVTYP": "",
            "STBLG": "",
            "STODT": "",
        })
    return pd.DataFrame(rows)
