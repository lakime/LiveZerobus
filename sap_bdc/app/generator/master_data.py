"""Generate SAP master data: LFA1, MARA, T001, T001W, T024, T023."""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# ── Reference constants ────────────────────────────────────────────────────────

COMPANY_CODES = ["1000", "2000", "3000"]
PLANTS = ["PL01", "PL02", "PL03", "GH04", "GH05"]
PURCH_ORGS = ["1000", "2000"]
PURCH_GROUPS = ["P01", "P02", "P03", "P04", "P05", "P06"]
MATERIAL_GROUPS = ["SEEDS", "FERTS", "SUBST", "EQUIP", "PPACK", "CHEM1", "NUTRI", "MISC"]
CURRENCIES = ["USD", "EUR", "GBP"]
COUNTRIES = ["US", "DE", "NL", "FR", "GB"]
LANGUAGES = ["EN", "DE", "FR"]
ACCOUNT_GROUPS = ["LIEF", "CPD"]
MATERIAL_TYPES = ["ROH", "HIBE", "VERP", "NLAG"]
UNITS = ["KG", "G", "ST", "L", "PAK"]
VENDOR_IDS: list[str] = []
MATERIAL_IDS: list[str] = []


def gen_lfa1(n: int = 20) -> pd.DataFrame:
    """Vendor Master General (LFA1)."""
    global VENDOR_IDS
    rows = []
    for i in range(n):
        lifnr = f"{100000 + i:010d}"
        VENDOR_IDS.append(lifnr)
        rows.append({
            "MANDT": "100",
            "LIFNR": lifnr,
            "LAND1": random.choice(COUNTRIES),
            "NAME1": fake.company()[:35],
            "NAME2": fake.company_suffix()[:35],
            "ORT01": fake.city()[:35],
            "PSTLZ": fake.postcode()[:10],
            "REGIO": fake.state_abbr()[:3],
            "STRAS": fake.street_address()[:35],
            "TELF1": fake.phone_number()[:16],
            "TELFX": fake.phone_number()[:16],
            "KTOKK": random.choice(ACCOUNT_GROUPS),
            "SPRAS": random.choice(LANGUAGES),
            "ERDAT": _rand_date(date(2018, 1, 1), date(2023, 12, 31)).isoformat(),
            "ERNAM": fake.user_name()[:12],
            "STCD1": fake.ssn().replace("-", "")[:16],
            "BANKS": random.choice(COUNTRIES),
        })
    return pd.DataFrame(rows)


def gen_mara(n: int = 80) -> pd.DataFrame:
    """Material Master General Data (MARA)."""
    global MATERIAL_IDS
    rows = []
    mat_group_map = {
        "SEEDS": ("ROH", "KG"),
        "FERTS": ("ROH", "KG"),
        "SUBST": ("ROH", "KG"),
        "NUTRI": ("ROH", "KG"),
        "EQUIP": ("HIBE", "ST"),
        "PPACK": ("VERP", "ST"),
        "CHEM1": ("ROH", "L"),
        "MISC":  ("NLAG", "ST"),
    }
    seed_names = [
        "LETTUCE-ROMAINE", "LETTUCE-BUTTER", "KALE-CURLY", "KALE-LACINATO",
        "SPINACH-BABY", "ARUGULA-WILD", "BASIL-GENOVESE", "CILANTRO-FRESH",
        "MICROGREEN-SUNFLOWER", "MICROGREEN-RADISH", "MICROGREEN-PEA",
        "CHARD-RAINBOW", "MIZUNA-PURPLE", "MUSTARD-RED", "TATSOI-SPOON",
        "WATERCRESS-UPLAND", "SORREL-FRENCH", "FENNEL-BRONZE", "DILL-BOUQUET",
        "PARSLEY-FLAT",
    ]
    for i in range(n):
        matkl = random.choice(MATERIAL_GROUPS)
        mtart, base_unit = mat_group_map[matkl]
        if matkl == "SEEDS" and i < len(seed_names):
            name = f"SEED-{seed_names[i % len(seed_names)]}"
        else:
            name = f"{matkl}-{fake.word().upper()[:8]}-{i:03d}"
        matnr = f"MAT{i:06d}"
        MATERIAL_IDS.append(matnr)
        weight = round(random.uniform(0.1, 50.0), 3)
        rows.append({
            "MANDT": "100",
            "MATNR": matnr,
            "ERSDA": _rand_date(date(2019, 1, 1), date(2023, 6, 1)).isoformat(),
            "ERNAM": fake.user_name()[:12],
            "LAEDA": _rand_date(date(2023, 1, 1), date(2024, 6, 1)).isoformat(),
            "AENAM": fake.user_name()[:12],
            "MTART": mtart,
            "MBRSH": "C",
            "MATKL": matkl,
            "MEINS": base_unit,
            "BRGEW": weight,
            "NTGEW": round(weight * 0.9, 3),
            "GEWEI": "KG",
            "MAKTX": name[:40],
            "NORMT": "",
            "BSTME": base_unit,
            "LABOR": "LAB1",
        })
    return pd.DataFrame(rows)


def gen_t001() -> pd.DataFrame:
    """Company Codes (T001)."""
    rows = [
        {"MANDT": "100", "BUKRS": "1000", "BUTXT": "GreenHarvest AG", "ORT01": "Amsterdam", "LAND1": "NL", "WAERS": "EUR", "SPRAS": "EN", "KTOPL": "INT"},
        {"MANDT": "100", "BUKRS": "2000", "BUTXT": "GreenHarvest US Inc", "ORT01": "New York", "LAND1": "US", "WAERS": "USD", "SPRAS": "EN", "KTOPL": "INT"},
        {"MANDT": "100", "BUKRS": "3000", "BUTXT": "GreenHarvest UK Ltd", "ORT01": "London", "LAND1": "GB", "WAERS": "GBP", "SPRAS": "EN", "KTOPL": "INT"},
    ]
    return pd.DataFrame(rows)


def gen_t001w() -> pd.DataFrame:
    """Plants / Branches (T001W)."""
    rows = [
        {"MANDT": "100", "WERKS": "PL01", "NAME1": "Amsterdam Greenhouse 1", "BWKEY": "PL01", "LAND1": "NL", "ORT01": "Amsterdam", "REGIO": "NH", "BUKRS": "1000"},
        {"MANDT": "100", "WERKS": "PL02", "NAME1": "Amsterdam Greenhouse 2", "BWKEY": "PL02", "LAND1": "NL", "ORT01": "Almere", "REGIO": "FL", "BUKRS": "1000"},
        {"MANDT": "100", "WERKS": "PL03", "NAME1": "Rotterdam Distribution", "BWKEY": "PL03", "LAND1": "NL", "ORT01": "Rotterdam", "REGIO": "ZH", "BUKRS": "1000"},
        {"MANDT": "100", "WERKS": "GH04", "NAME1": "New York Farm Hub", "BWKEY": "GH04", "LAND1": "US", "ORT01": "New York", "REGIO": "NY", "BUKRS": "2000"},
        {"MANDT": "100", "WERKS": "GH05", "NAME1": "London Vertical Farm", "BWKEY": "GH05", "LAND1": "GB", "ORT01": "London", "REGIO": "ENG", "BUKRS": "3000"},
    ]
    return pd.DataFrame(rows)


def gen_t024() -> pd.DataFrame:
    """Purchasing Groups (T024)."""
    rows = [
        {"MANDT": "100", "EKGRP": "P01", "EKNAM": "Seeds & Genetics", "TELEF": fake.phone_number()[:16]},
        {"MANDT": "100", "EKGRP": "P02", "EKNAM": "Fertilisers & Nutrients", "TELEF": fake.phone_number()[:16]},
        {"MANDT": "100", "EKGRP": "P03", "EKNAM": "Substrate & Growing Media", "TELEF": fake.phone_number()[:16]},
        {"MANDT": "100", "EKGRP": "P04", "EKNAM": "Equipment & Machinery", "TELEF": fake.phone_number()[:16]},
        {"MANDT": "100", "EKGRP": "P05", "EKNAM": "Packaging", "TELEF": fake.phone_number()[:16]},
        {"MANDT": "100", "EKGRP": "P06", "EKNAM": "Chemicals & Crop Protection", "TELEF": fake.phone_number()[:16]},
    ]
    return pd.DataFrame(rows)


def gen_t023() -> pd.DataFrame:
    """Material Groups (T023)."""
    rows = [
        {"MANDT": "100", "MATKL": "SEEDS", "WGBEZ": "Seed Stock", "WGBEZ60": "Seed Stock — all crop types"},
        {"MANDT": "100", "MATKL": "FERTS", "WGBEZ": "Fertilisers", "WGBEZ60": "Macro and micro nutrient fertilisers"},
        {"MANDT": "100", "MATKL": "SUBST", "WGBEZ": "Substrates", "WGBEZ60": "Growing media: rockwool, coco, perlite"},
        {"MANDT": "100", "MATKL": "EQUIP", "WGBEZ": "Equipment", "WGBEZ60": "Grow lights, HVAC, pumps, sensors"},
        {"MANDT": "100", "MATKL": "PPACK", "WGBEZ": "Packaging", "WGBEZ60": "Retail and wholesale packaging"},
        {"MANDT": "100", "MATKL": "CHEM1", "WGBEZ": "Chemicals", "WGBEZ60": "Crop protection and sterilisation"},
        {"MANDT": "100", "MATKL": "NUTRI", "WGBEZ": "Nutrients", "WGBEZ60": "Hydroponic nutrient solutions"},
        {"MANDT": "100", "MATKL": "MISC",  "WGBEZ": "Miscellaneous", "WGBEZ60": "Uncategorised procurement items"},
    ]
    return pd.DataFrame(rows)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rand_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))
