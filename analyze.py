#!/usr/bin/env python3
"""BrakePoint analyzer - compare a lap with your best and find where braking costs you time.

    python analyze.py                      # latest session, last lap vs best lap
    python analyze.py --lap 5              # lap 5 vs best
    python analyze.py --lap 5 --ref 3      # lap 5 vs lap 3
    python analyze.py sessions/x.json      # a specific session
"""
import argparse
import json
import pathlib
import webbrowser

import numpy as np

from laps import fmt_time

N = 2000                 # resample points around the lap
ON, OFF, FULL = 0.15, 0.05, 0.9


# ---------- resampling ----------

def resample(lap):
    a = np.asarray(lap["samples"], dtype=float)
    t, pos = a[:, 0] / 1000.0, np.maximum.accumulate(a[:, 1])
    keep = np.concatenate([[True], np.diff(pos) > 1e-7])
    a, t, pos = a[keep], t[keep], pos[keep]
    if pos[0] > 0:
        pos, t, a = np.r_[0.0, pos], np.r_[0.0, t], np.vstack([a[0], a])
    if pos[-1] < 1:
        pos, t, a = np.r_[pos, 1.0], np.r_[t, lap["time_ms"] / 1000.0], np.vstack([a, a[-1]])
    g = np.linspace(0, 1, N)
    return {
        "t": np.interp(g, pos, t),
        "speed": np.interp(g, pos, a[:, 2]),
        "gas": np.interp(g, pos, a[:, 3]),
        "brake": np.interp(g, pos, a[:, 4]),
        "gear": np.round(np.interp(g, pos, a[:, 5])),
        "x": np.interp(g, pos, a[:, 7]) if a.shape[1] >= 9 else None,
        "z": np.interp(g, pos, a[:, 8]) if a.shape[1] >= 9 else None,
    }


def lap_length(r):
    v = (r["speed"][1:] + r["speed"][:-1]) / 2 / 3.6
    return float(np.sum(np.diff(r["t"]) * v))


# ---------- braking zones ----------

def brake_segments(b):
    segs, s = [], None
    for i, v in enumerate(b):
        if s is None and v > ON:
            s = i
        elif s is not None and v < OFF:
            segs.append([s, i])
            s = None
    if s is not None:
        segs.append([s, len(b) - 1])
    return segs


def first(cond, lo, hi):
    idx = np.nonzero(cond[lo:hi])[0]
    return int(lo + idx[0]) if len(idx) else None


def analyse(ref, cmp, L):
    dist = np.linspace(0, L, N)
    delta = cmp["t"] - ref["t"]

    def at(m):
        return int(np.clip(round(m / L * (N - 1)), 0, N - 1))

    segs = brake_segments(ref["brake"])
    merged = []
    for s in segs:
        if merged and dist[s[0]] - dist[merged[-1][1]] < 40:
            merged[-1][1] = s[1]
        else:
            merged.append(s)

    cands = []
    for onset, release in merged:
        exit_i = first(ref["gas"] > FULL, release, N) or min(N - 1, release + at(150))
        apex = onset + int(np.argmin(ref["speed"][onset:exit_i + 1]))
        if ref["speed"][onset] - ref["speed"][apex] >= 15:
            cands.append((onset, release, exit_i, apex))

    zones, prev_end = [], 0
    for k, (onset, release, exit_i, apex) in enumerate(cands):
        next_start = at(dist[cands[k + 1][0]] - 60) if k + 1 < len(cands) else N - 1
        ws = max(prev_end, at(dist[onset] - 60))
        c_on = first(cmp["brake"] > ON, max(ws - at(140), prev_end), apex + 1)
        c_apex = ws + int(np.argmin(cmp["speed"][ws:min(next_start, exit_i + at(60)) + 1]))
        c_full = first(cmp["gas"] > FULL, c_apex, next_start)
        # window runs until both laps are flat out again (+100 m so exit speed shows up)
        we = min(max(exit_i, c_full or exit_i) + at(100), next_start)
        prev_end = we

        z = {
            "start_m": float(dist[ws]),
            "end_m": float(dist[we]),
            "brake_m": float(dist[onset]),
            "time_lost": float(delta[we] - delta[ws]),
            "entry_loss": float(delta[apex] - delta[ws]),
            "exit_loss": float(delta[we] - delta[apex]),
            "entry_ref": float(ref["speed"][onset]),
            "vmin_ref": float(ref["speed"][apex]),
            "vmin_cmp": float(cmp["speed"][c_apex]),
            "peak_ref": float(ref["brake"][onset:release + 1].max()),
            "peak_cmp": float(cmp["brake"][ws:we + 1].max()),
            "brake_diff_m": None if c_on is None else float(dist[c_on] - dist[onset]),
            "throttle_diff_m": None if c_full is None else float(dist[c_full] - dist[exit_i]),
        }
        z["tips"] = tips(z)
        zones.append(z)

    for i, z in enumerate(zones, 1):
        z["n"] = i
    return dist, delta, zones


def tips(z):
    out = []
    bd, td, lost = z["brake_diff_m"], z["throttle_diff_m"], z["time_lost"]
    dv = z["vmin_cmp"] - z["vmin_ref"]
    # A huge loss, or no braking where the best lap braked, means an incident
    # (off, lock-up, spin, traffic), not a technique difference - don't coach it.
    if lost > 0.8 or (bd is None and lost > 0.15):
        return [f"Lost {lost:.2f}s here. That looks like a mistake (off, lock-up, spin or traffic), "
                "not a technique gap. Compare a cleaner lap for coaching tips."]
    if bd is None:
        out.append("Braking didn't line up with your best lap here. Check the brake trace.")
    elif bd < -8:
        out.append(f"Braked {abs(bd):.0f} m earlier than your best. There's room to brake later.")
    elif bd > 8 and lost > 0.03:
        out.append(f"Braked {bd:.0f} m later than your best but still lost time. Probably overdriving the entry.")
    elif bd > 8:
        out.append(f"Braked {bd:.0f} m later than your best and it worked.")
    if bd is not None and z["peak_cmp"] < z["peak_ref"] - 0.1:
        out.append(f"Peak brake {z['peak_cmp']:.0%} vs {z['peak_ref']:.0%} on your best. Hit the pedal harder at the start.")
    if dv < -3:
        out.append(f"Minimum speed {abs(dv):.0f} km/h lower. Release the brake earlier and roll more speed to the apex.")
    elif dv > 3:
        out.append(f"Carried {dv:.0f} km/h more minimum speed than your best.")
    if td is not None and td > 12:
        out.append(f"Back to full throttle {td:.0f} m later than your best.")
    elif td is not None and td < -12:
        out.append(f"Full throttle {abs(td):.0f} m earlier than your best.")
    if lost > 0.03:
        part, amt = ("entry (brake to apex)", z["entry_loss"]) if z["entry_loss"] >= z["exit_loss"] \
            else ("exit (apex to full throttle)", z["exit_loss"])
        out.insert(0, f"Most of the loss is on {part}: {amt:+.3f}s.")
        if len(out) == 1:
            out.append("The differences are small and spread out. Focus on being consistent here." if amt < 0.08
                       else "Compare the speed traces closely here. The loss is real but there's no single cause.")
    if not out:
        out.append("Matching your best here." if lost <= 0.01 else "Close to your best here.")
    return out


# ---------- report ----------

def build_report(session, ref_lap, cmp_lap, out_path):
    ref, cmp = resample(ref_lap), resample(cmp_lap)
    L = lap_length(ref)
    dist, delta, zones = analyse(ref, cmp, L)
    step = 2
    r = lambda a, d=2: [round(float(x), d) for x in a[::step]]
    data = {
        "track": session.get("track"), "car": session.get("car"),
        "ref": {"lap": ref_lap["lap"], "time": fmt_time(ref_lap["time_ms"]),
                "speed": r(ref["speed"], 1), "brake": r(ref["brake"]), "gas": r(ref["gas"])},
        "cmp": {"lap": cmp_lap["lap"], "time": fmt_time(cmp_lap["time_ms"]),
                "speed": r(cmp["speed"], 1), "brake": r(cmp["brake"]), "gas": r(cmp["gas"])},
        "dist": r(dist, 1), "delta": r(delta, 3),
        "total_delta": round((cmp_lap["time_ms"] - ref_lap["time_ms"]) / 1000, 3),
        "zone_loss": round(sum(max(0, z["time_lost"]) for z in zones), 3),
        "length_m": round(L),
        "zones": zones,
        "map": None if ref["x"] is None else {"x": r(ref["x"], 1), "z": r(ref["z"], 1)},
        "laps": [{"lap": l["lap"], "time": fmt_time(l["time_ms"]), "valid": l["valid"]} for l in session["laps"]],
    }
    tpl = (pathlib.Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    html = tpl.replace("__DATA__", json.dumps(data)).replace(
        "__TITLE__", f"{data['track']} - lap {cmp_lap['lap']} vs {ref_lap['lap']}")
    out_path.write_text(html, encoding="utf-8")
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", help="session .json (default: newest in sessions/)")
    ap.add_argument("--lap", type=int, help="lap to analyse (default: last valid lap)")
    ap.add_argument("--ref", type=int, help="reference lap (default: fastest valid lap)")
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    args = ap.parse_args()

    if args.session:
        path = pathlib.Path(args.session)
    else:
        files = sorted(pathlib.Path("sessions").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            raise SystemExit("No sessions found. Run recorder.py (or mock_session.py) first.")
        path = files[-1]
    session = json.loads(path.read_text())
    laps = {l["lap"]: l for l in session["laps"]}
    valid = [l for l in session["laps"] if l["valid"]]
    if len(valid) < 2 and not (args.lap and args.ref):
        raise SystemExit("Need at least two complete laps to compare.")

    ref = laps[args.ref] if args.ref else min(valid, key=lambda l: l["time_ms"])
    if args.lap:
        cmp = laps[args.lap]
    else:
        others = [l for l in valid if l["lap"] != ref["lap"]]
        cmp = others[-1]

    print(f"{session['track']} / {session['car']}  ({path.name})")
    for l in session["laps"]:
        mark = " <- best" if l is ref else (" <- analysing" if l is cmp else "")
        print(f"  Lap {l['lap']:>2}: {fmt_time(l['time_ms'])}{'' if l['valid'] else '  (invalid)'}{mark}")

    out_dir = pathlib.Path("reports")
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{path.stem}_lap{cmp['lap']}_vs_{ref['lap']}.html"
    data = build_report(session, ref, cmp, out)

    print(f"\nLap {cmp['lap']} is {data['total_delta']:+.3f}s vs lap {ref['lap']}. "
          f"Biggest braking-zone losses:")
    for z in sorted(data["zones"], key=lambda z: -z["time_lost"])[:3]:
        print(f"  Zone {z['n']} ({z['brake_m']:.0f} m): {z['time_lost']:+.3f}s - {z['tips'][0]}")
    print(f"\nReport: {out}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
