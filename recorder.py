#!/usr/bin/env python3
"""BrakePoint recorder - run this on your sim PC while you drive in ACC.

    python recorder.py

Every completed lap is saved to sessions/<date>_<track>_<car>.json.
Press Ctrl+C to stop. (BrakePoint.exe runs the same recorder from its window.)
"""
import argparse
import datetime as dt
import json
import pathlib
import threading
import time

from acc_shm import ACCReader, STATUS_LIVE, player_xz, wstr
from laps import fmt_time, make_lap


class Recorder:
    """Polls ACC and saves each completed lap. Runs until `stop` is set."""

    def __init__(self, out_dir="sessions", hz=60, reader_factory=ACCReader):
        self.out_dir = pathlib.Path(out_dir)
        self.period = 1.0 / hz if hz else 0.0  # hz=0: as fast as possible (demo)
        self.reader_factory = reader_factory
        self.path = None

    def run(self, stop: threading.Event, log=print, on_lap=None):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        reader = self.reader_factory()
        session = None
        raw, touched_pit, last_completed = [], False, None
        log("Waiting for ACC - get on track")
        try:
            while not stop.is_set():
                g = reader.graphics()
                if g.status != STATUS_LIVE:
                    time.sleep(0.2)
                    continue

                if session is None:
                    st = reader.static()
                    track = wstr(st.track) or "unknown_track"
                    car = wstr(st.carModel) or "unknown_car"
                    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
                    self.path = self.out_dir / f"{stamp}_{track}_{car}.json"
                    session = {"track": track, "car": car, "recorded": stamp, "laps": []}
                    last_completed = g.completedLaps
                    log(f"Recording {car} at {track}")

                if g.completedLaps != last_completed:
                    lap = make_lap(last_completed + 1, raw, touched_pit)
                    if lap["samples"]:
                        session["laps"].append(lap)
                        self.path.write_text(json.dumps(session))
                        tag = "" if lap["valid"] else "  (out-lap / pit / incomplete - skipped)"
                        log(f"Lap {lap['lap']}: {fmt_time(lap['time_ms'])}{tag}")
                        if on_lap:
                            on_lap(self.path, lap)
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
                if self.period:
                    time.sleep(self.period)
        finally:
            reader.close()
            if session:
                log(f"Saved {len(session['laps'])} laps")
        return self.path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hz", type=int, default=60, help="samples per second (default 60)")
    ap.add_argument("--out", default="sessions", help="folder for session files")
    args = ap.parse_args()

    stop = threading.Event()
    rec = Recorder(args.out, args.hz)
    print("BrakePoint recorder (Ctrl+C to stop)")
    try:
        rec.run(stop)
    except KeyboardInterrupt:
        stop.set()
    if rec.path:
        print(f"Session file: {rec.path}")
        print("Next: python analyze.py")


if __name__ == "__main__":
    main()
