"""Run all 4 simulators in parallel threads. Intended for demo use.

Usage:
    python run_all.py --catalog main --schema procurement --rate 20

`--rate` is a global knob: individual simulators scale from it.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from typing import List

import click


def _run(cmd: List[str], name: str) -> None:
    print(f"→ starting {name}: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    proc.wait()
    print(f"← {name} exited with code {proc.returncode}")


@click.command()
@click.option("--catalog", default="main")
@click.option("--schema", default="procurement")
@click.option("--rate", default=20, help="Global rate scaler.")
@click.option("--duration", default=0)
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    scale = max(rate // 5, 1)

    specs = [
        ("inventory",  ["python", "inventory_simulator.py",        f"--rate={2 * scale}"]),
        ("suppliers",  ["python", "supplier_quotes_simulator.py",  f"--rate={1 * scale}"]),
        ("demand",     ["python", "demand_simulator.py",           f"--rate={3 * scale}"]),
        ("commodity",  ["python", "commodity_simulator.py",        f"--rate={1}"]),
    ]

    common_args = [f"--catalog={catalog}", f"--schema={schema}"]
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
