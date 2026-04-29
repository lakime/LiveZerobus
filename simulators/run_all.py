"""Run all simulators in parallel threads. Intended for demo use.

Usage:
    python run_all.py                                      # uses config.toml defaults
    python run_all.py --catalog livezerobus --schema procurement --rate 20

`--rate` is a global multiplier applied on top of per-simulator rates in config.toml.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from typing import List

import click

import config as cfg


def _run(cmd: List[str], name: str) -> None:
    print(f"→ starting {name}: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    proc.wait()
    print(f"← {name} exited with code {proc.returncode}")


@click.command()
@click.option("--catalog", default=None, help="UC catalog (default: config.toml)")
@click.option("--schema",  default=None, help="UC schema (default: config.toml)")
@click.option("--rate",    default=None, type=int, help="Global rate multiplier (overrides per-sim rates).")
@click.option("--duration", default=0)
def main(catalog: str | None, schema: str | None, rate: int | None, duration: int) -> None:
    resolved_catalog = catalog or cfg.catalog()
    resolved_schema  = schema  or cfg.schema()

    if rate is not None:
        scale = max(rate // 5, 1)
        specs = [
            ("inventory",  ["python", "inventory_simulator.py",        f"--rate={2 * scale}"]),
            ("suppliers",  ["python", "supplier_quotes_simulator.py",  f"--rate={1 * scale}"]),
            ("demand",     ["python", "demand_simulator.py",           f"--rate={3 * scale}"]),
            ("commodity",  ["python", "commodity_simulator.py",        f"--rate={1}"]),
            ("sap",        ["python", "sap_simulator.py",              f"--rate={1}"]),
            ("iot",        ["python", "iot_simulator.py",              f"--rate={1}"]),
        ]
    else:
        specs = [
            ("inventory",  ["python", "inventory_simulator.py",       f"--rate={cfg.sim_rate('inventory')}"]),
            ("suppliers",  ["python", "supplier_quotes_simulator.py", f"--rate={cfg.sim_rate('suppliers')}"]),
            ("demand",     ["python", "demand_simulator.py",          f"--rate={cfg.sim_rate('demand')}"]),
            ("commodity",  ["python", "commodity_simulator.py",       f"--rate={cfg.sim_rate('commodity')}"]),
            ("sap",        ["python", "sap_simulator.py",             f"--rate={cfg.sim_rate('sap')}"]),
            ("iot",        ["python", "iot_simulator.py",             f"--rate={cfg.sim_rate('iot')}"]),
        ]

    common_args = [f"--catalog={resolved_catalog}", f"--schema={resolved_schema}"]
    if duration:
        common_args.append(f"--duration={duration}")

    threads = []
    for name, cmd in specs:
        t = threading.Thread(target=_run, args=(cmd + common_args, name), daemon=True)
        t.start()
        threads.append(t)

    def _stop(_sig, _frame):
        print("\nStopping simulators…")
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while any(t.is_alive() for t in threads):
        time.sleep(0.5)


if __name__ == "__main__":
    main()
