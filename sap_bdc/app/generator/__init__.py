"""Generate all SAP tables and write them to Delta Lake."""
from __future__ import annotations

import logging

from ..config import Settings
from ..delta_store import write_table, list_table_names
from . import master_data as md
from . import procurement as proc
from . import inventory as inv
from . import finance as fin

log = logging.getLogger(__name__)

TABLE_ORDER = [
    "T001", "T001W", "T023", "T024",
    "LFA1", "MARA",
    "EKKO", "EKPO", "EKBE", "EKET", "EBAN",
    "MKPF", "MSEG",
    "RBKP", "BKPF",
]


def generate_all(settings: Settings, force: bool = False) -> None:
    """Generate all 15 SAP tables and persist as Delta files."""
    existing = set(list_table_names(settings))
    if not force and existing.issuperset(set(TABLE_ORDER)):
        log.info("All SAP tables already exist — skipping generation (use force=True to regenerate)")
        return

    log.info("Generating SAP master data…")
    lfa1 = md.gen_lfa1()
    mara = md.gen_mara()
    t001 = md.gen_t001()
    t001w = md.gen_t001w()
    t024 = md.gen_t024()
    t023 = md.gen_t023()

    log.info("Generating SAP procurement documents…")
    ekko = proc.gen_ekko()
    ekpo = proc.gen_ekpo()
    ekbe = proc.gen_ekbe()
    eket = proc.gen_eket()
    eban = proc.gen_eban()

    log.info("Generating SAP inventory documents…")
    mkpf = inv.gen_mkpf()
    mseg = inv.gen_mseg(mkpf)

    log.info("Generating SAP finance documents…")
    rbkp = fin.gen_rbkp()
    bkpf = fin.gen_bkpf()

    tables = {
        "T001": t001, "T001W": t001w, "T023": t023, "T024": t024,
        "LFA1": lfa1, "MARA": mara,
        "EKKO": ekko, "EKPO": ekpo, "EKBE": ekbe, "EKET": eket, "EBAN": eban,
        "MKPF": mkpf, "MSEG": mseg,
        "RBKP": rbkp, "BKPF": bkpf,
    }

    for name, df in tables.items():
        log.info("Writing %s (%d rows)…", name, len(df))
        write_table(settings, name, df)

    log.info("Generation complete: %d tables written", len(tables))
