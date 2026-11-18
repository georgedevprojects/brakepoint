#!/usr/bin/env python3
"""Generate a fake ACC session so you can try BrakePoint without the game.

    python mock_session.py          -> sessions/demo_mock_ring_demo_gt3.json
"""
import json
import pathlib
import random

import numpy as np

from laps import make_lap

L = 3900.0                     # track length, m
STEP = 1.0                     # profile resolution, m
VMAX = 268 / 3.6
DEC = 27.0                     # best-case braking, m/s^2
CORNERS = [  # apex distance (m), min speed (km/h)
    (420, 88), (1050, 142), (1480, 72), (2080, 178), (2650, 96), (3250, 121), (3720, 158),
]


def accel(v):
    return 9.5 * (1 - 0.75 * v / VMAX)


def lap_profile(rng, skill):
    d = np.arange(0, L, STEP)
    n = len(d)
    cap = np.full(n, VMAX)
    dec = np.full(n, DEC)
    acc_scale = np.ones(n)
    prev = 0
    for apex, vmin in CORNERS:
        i = int(apex / STEP)
        cap[i] = (vmin + rng.normal(-3.0 * (1 - skill), 1.2)) / 3.6
        # lower decel = driver brakes earlier and softer
        dec[prev:i] = DEC * min(1.0, rng.uniform(0.86, 1.0) + 0.1 * skill - 0.05)
        # slow pick-up of the throttle after the apex
        delay = int(rng.uniform(10, 25) + 40 * (1 - skill))
        acc_scale[i:i + delay] = 0.25
        prev = i
    dec[prev:] = DEC

    fwd = np.empty(n)
    fwd[0] = 200 / 3.6
    for k in range(1, n):
        fwd[k] = min(cap[k], np.sqrt(fwd[k - 1] ** 2 + 2 * accel(fwd[k - 1]) * acc_scale[k] * STEP))
    v = fwd.copy()
    for k in range(n - 2, -1, -1):
        v[k] = min(v[k], np.sqrt(v[k + 1] ** 2 + 2 * dec[k] * STEP))

    braking = v < fwd - 0.05
    brake = np.where(braking, np.clip(dec / DEC, 0, 1), 0.0)
    for k in range(1, n):  # trail off the brake into the apex
        if braking[k - 1] and not braking[k]:
            back = min(25, k)
            brake[k - back:k] *= np.linspace(1, 0.15, back)
    gas = np.where(braking, 0.0, np.where(acc_scale < 1, 0.35, 1.0))
    return d, v, gas, brake


def track_shape():
    """Closed fake circuit: heading turns at each corner, sharper for slower corners."""
    d = np.arange(0, L, STEP)
    sev = np.array([1 / v for _, v in CORNERS])
    sev = sev / sev.sum() * 2 * np.pi            # total turning = one full loop
    curv = np.zeros(len(d))
    for (apex, vmin), ang in zip(CORNERS, sev):
        w = 25 + vmin * 0.35                     # faster corners are longer arcs
        g = np.exp(-0.5 * ((d - apex) / w) ** 2)
        curv += ang * g / g.sum()
    heading = np.cumsum(curv)
    x = np.cumsum(np.cos(heading)) * STEP
    z = np.cumsum(np.sin(heading)) * STEP
    # close the loop by spreading the end-point error along the lap
    x -= np.linspace(0, x[-1] - x[0], len(d))
    z -= np.linspace(0, z[-1] - z[0], len(d))
    return d, x, z


TRACK = None


def gear_for(kmh):
    return int(np.searchsorted([0, 75, 110, 145, 180, 215], kmh))


def make_raw_lap(rng, skill, hz=60):
    d, v, gas, brake = lap_profile(rng, skill)
    t = np.concatenate([[0], np.cumsum(STEP / np.maximum(v[:-1], 1))])
    total = t[-1] + STEP / v[-1]
    ts = np.arange(0, total, 1 / hz)
    ds = np.interp(ts, t, d)
    global TRACK
    if TRACK is None:
        TRACK = track_shape()
    td, tx, tz = TRACK
    samples = []
    for k, tk in enumerate(ts):
        spd = float(np.interp(ds[k], d, v)) * 3.6 + rng.normal(0, 0.4)
        samples.append([
            int(tk * 1000),
            round(ds[k] / L, 6),
            round(spd, 2),
            round(float(np.interp(ds[k], d, gas)), 3),
            round(float(np.clip(np.interp(ds[k], d, brake) + rng.normal(0, 0.01), 0, 1)), 3),
            gear_for(spd),
            0.0,
            round(float(np.interp(ds[k], td, tx)) + rng.normal(0, 0.15), 2),
            round(float(np.interp(ds[k], td, tz)) + rng.normal(0, 0.15), 2),
        ])
    samples[-1][0] = int(total * 1000)
    return samples


def main():
    rng = np.random.default_rng(7)
    random.seed(7)
    laps = []
    skills = [0.55, 0.7, 0.8, 0.95, 0.75, 0.85, 1.0, 0.8]
    for n, skill in enumerate(skills, start=1):
        laps.append(make_lap(n, make_raw_lap(rng, skill)))
    session = {"track": "mock_ring", "car": "demo_gt3", "recorded": "demo", "laps": laps}
    out = pathlib.Path("sessions")
    out.mkdir(exist_ok=True)
    path = out / "demo_mock_ring_demo_gt3.json"
    path.write_text(json.dumps(session))
    from laps import fmt_time
    for lap in laps:
        print(f"Lap {lap['lap']}: {fmt_time(lap['time_ms'])}  valid={lap['valid']}")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
