#!/usr/bin/env python3
"""BrakePoint recorder - run this on your sim PC while you drive in ACC.

    python recorder.py

Every completed lap is saved to sessions/<date>_<track>_<car>.json.
Press Ctrl+C to stop.
"""
import argparse
import datetime as dt
import json
import pathlib
import time

from acc_shm import ACCReader, STATUS_LIVE, player_xz, wstr
from laps import fmt_time, make_lap


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hz", type=int, default=60, help="samples per second (default 60)")
    ap.add_argument("--out", default="sessions", help="folder for session files")
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(exist_ok=True)
    reader = ACCReader()
    period = 1.0 / args.hz

    session, path = None, None
    raw, touched_pit, last_completed = [], False, None
    print("BrakePoint: waiting for ACC - get on track (Ctrl+C to stop)")

    try:
        while True:
            g = reader.graphics()
            if g.status != STATUS_LIVE:
                time.sleep(0.2)
                continue

            if session is None:
                st = reader.static()
                track = wstr(st.track) or "unknown_track"
                car = wstr(st.carModel) or "unknown_car"
                stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
                path = out_dir / f"{stamp}_{track}_{car}.json"
                session = {"track": track, "car": car, "recorded": stamp, "laps": []}
                last_completed = g.completedLaps
                print(f"Recording {car} at {track}  ->  {path}")

            if g.completedLaps != last_completed:
                lap = make_lap(last_completed + 1, raw, touched_pit)
                if lap["samples"]:
                    session["laps"].append(lap)
                    path.write_text(json.dumps(session))
                    tag = "" if lap["valid"] else "  (out-lap / pit / incomplete - ignored)"
                    print(f"  Lap {lap['lap']}: {fmt_time(lap['time_ms'])}{tag}")
                raw, touched_pit = [], False
                last_completed = g.completedLaps

            p = reader.physics()
            x, z = player_xz(g)
            if g.isInPit:
                touched_pit = True
            raw.append([
                g.iCurrentTime,
                round(g.normalizedCarPosition, 6),
                round(p.speedKmh, 2),
                round(p.gas, 3),
                round(p.brake, 3),
                p.gear - 1,
                round(p.steerAngle, 3),
                round(x, 2),
                round(z, 2),
            ])
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()
        if session:
            print(f"Saved {len(session['laps'])} laps to {path}")
            print("Next: python analyze.py")


if __name__ == "__main__":
    main()
