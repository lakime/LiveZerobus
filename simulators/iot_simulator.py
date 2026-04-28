"""IoT sensor simulator — 6 grow rooms × 7 sensor types.

Emits one IotSensorEvent per (room, sensor) per cycle into bz_iot_sensor_events.
State machine: each sensor slowly mean-reverts to its nominal value with
Gaussian noise, and randomly initiates fault events that drift toward caution
or alert zones before recovering.
"""
from __future__ import annotations

import dataclasses
import random
import time

import click

from common import (
    IotSensorEvent,
    as_row,
    new_event_id,
    now_utc,
    zerobus_stream,
)

# Six grow rooms with assigned crop types
GROW_ROOMS: list[tuple[str, str]] = [
    ("GR-01", "Butterhead Lettuce"),
    ("GR-02", "Red Leaf Lettuce"),
    ("GR-03", "Genovese Basil"),
    ("GR-04", "Cilantro Herb"),
    ("GR-05", "Radish Microgreens"),
    ("GR-06", "Pea Shoot Microgreens"),
]

# Sensor specs: nominal value, per-tick noise std-dev, physical unit, clamp range
SENSOR_SPECS: dict[str, dict] = {
    "temperature":   {"nominal": 21.0,   "noise": 0.20,  "unit": "°C",    "lo": 4.0,   "hi": 42.0},
    "humidity":      {"nominal": 70.0,   "noise": 0.80,  "unit": "%",     "lo": 10.0,  "hi": 99.0},
    "soil_moisture": {"nominal": 72.0,   "noise": 1.20,  "unit": "%",     "lo": 10.0,  "hi": 99.0},
    "light":         {"nominal": 300.0,  "noise": 6.0,   "unit": "μmol",  "lo": 0.0,   "hi": 800.0},
    "co2":           {"nominal": 1000.0, "noise": 20.0,  "unit": "ppm",   "lo": 250.0, "hi": 2500.0},
    "ph":            {"nominal": 6.0,    "noise": 0.035, "unit": "pH",    "lo": 3.5,   "hi": 9.0},
    "ec":            {"nominal": 2.0,    "noise": 0.025, "unit": "mS/cm", "lo": 0.0,   "hi": 6.0},
}

# Fault targets: where the sensor drifts to when a fault fires.
# Two levels: "caution" (outside warn range) and "alert" (outside alert range).
_FAULT_TARGETS: dict[str, dict[str, list[float]]] = {
    "temperature":   {"caution": [14.0, 28.5], "alert": [9.0, 32.0]},
    "humidity":      {"caution": [46.0, 92.0], "alert": [35.0, 97.0]},
    "soil_moisture": {"caution": [44.0, 87.0], "alert": [30.0, 96.0]},
    "light":         {"caution": [130.0, 520.0],"alert": [55.0, 660.0]},
    "co2":           {"caution": [550.0, 1620.0],"alert": [300.0, 2150.0]},
    "ph":            {"caution": [4.7, 7.1],   "alert": [3.9, 8.3]},
    "ec":            {"caution": [0.7, 3.3],   "alert": [0.2, 4.3]},
}

# Mean-reversion strength (higher = snaps back faster)
_ALPHA = 0.06
# Probability per sensor per cycle of starting a fault event
_FAULT_PROB = 0.008


@dataclasses.dataclass
class _SensorState:
    value: float
    fault_target: float | None = None
    fault_steps: int = 0


def _make_states() -> dict[tuple[str, str], _SensorState]:
    states = {}
    for room_id, _ in GROW_ROOMS:
        for stype, spec in SENSOR_SPECS.items():
            # Small per-room offset so rooms don't read identically
            offset = random.gauss(0, spec["noise"] * 3)
            v = max(spec["lo"], min(spec["hi"], spec["nominal"] + offset))
            states[(room_id, stype)] = _SensorState(value=v)
    return states


def _tick(state: _SensorState, spec: dict) -> float:
    if state.fault_steps > 0:
        # Drift toward fault target
        state.value += (state.fault_target - state.value) * 0.18 + random.gauss(0, spec["noise"] * 0.4)
        state.fault_steps -= 1
        if state.fault_steps == 0:
            state.fault_target = None
    else:
        # Gaussian noise + mean-reversion to nominal
        state.value += _ALPHA * (spec["nominal"] - state.value) + random.gauss(0, spec["noise"])
        # Random fault onset
        if random.random() < _FAULT_PROB:
            level = random.choices(["caution", "alert"], weights=[0.72, 0.28])[0]
            # Pick the closer extreme (high or low) randomly
            targets = _FAULT_TARGETS[list(SENSOR_SPECS.keys())[
                list(SENSOR_SPECS.keys()).index(
                    next(k for k, v in SENSOR_SPECS.items() if v is spec)
                )
            ]][level]
            state.fault_target = random.choice(targets)
            state.fault_steps = random.randint(8, 25)

    state.value = max(spec["lo"], min(spec["hi"], state.value))
    return state.value


def _tick_sensor(state: _SensorState, stype: str) -> float:
    spec = SENSOR_SPECS[stype]
    if state.fault_steps > 0:
        state.value += (state.fault_target - state.value) * 0.18 + random.gauss(0, spec["noise"] * 0.4)
        state.fault_steps -= 1
        if state.fault_steps == 0:
            state.fault_target = None
    else:
        state.value += _ALPHA * (spec["nominal"] - state.value) + random.gauss(0, spec["noise"])
        if random.random() < _FAULT_PROB:
            level = random.choices(["caution", "alert"], weights=[0.72, 0.28])[0]
            targets = _FAULT_TARGETS[stype][level]
            state.fault_target = random.choice(targets)
            state.fault_steps = random.randint(8, 25)
    state.value = max(spec["lo"], min(spec["hi"], state.value))
    return state.value


@click.command()
@click.option("--catalog", default="livezerobus")
@click.option("--schema",  default="procurement")
@click.option("--rate",    default=1, help="Sensor cycles per second.")
@click.option("--duration",default=0, help="Stop after N seconds (0=forever).")
def main(catalog: str, schema: str, rate: int, duration: int) -> None:
    table_fqn = f"{catalog}.{schema}.bz_iot_sensor_events"
    cycle_s = 1.0 / max(rate, 1)
    t_end = (time.time() + duration) if duration else float("inf")
    states = _make_states()
    cycle = 0

    with zerobus_stream(table_fqn) as stream:
        while time.time() < t_end:
            t0 = time.time()
            for room_id, _ in GROW_ROOMS:
                for stype, spec in SENSOR_SPECS.items():
                    key = (room_id, stype)
                    value = _tick_sensor(states[key], stype)
                    event = IotSensorEvent(
                        event_id=new_event_id(),
                        event_ts=now_utc(),
                        room_id=room_id,
                        sensor_type=stype,
                        value=round(value, 4),
                        unit=spec["unit"],
                    )
                    stream.send(as_row(event))
            cycle += 1
            if cycle % 60 == 0:
                print(f"[iot] cycle={cycle}  rooms={len(GROW_ROOMS)}  sensors/cycle={len(GROW_ROOMS)*len(SENSOR_SPECS)}")
            elapsed = time.time() - t0
            wait = max(0.0, cycle_s - elapsed)
            if wait:
                time.sleep(wait)


if __name__ == "__main__":
    main()
