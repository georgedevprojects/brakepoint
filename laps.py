"""Shared lap helpers.

A sample is: [lap_ms, track_pos (0..1), speed_kmh, gas (0..1), brake (0..1), gear, steer, x, z]
(x, z = world position in metres; missing in sessions recorded before the track map)
"""


def clean_samples(samples):
    """Strip the start/finish wrap-around and duplicate frames from a raw lap."""
    n = len(samples)
    i = 0
    # leading frames still reporting ~0.99 track position from before the line
    while i < n // 4 and samples[i][1] > 0.5:
        i += 1
    out, last_t = [], -1
    for s in samples[i:]:
        if s[0] <= last_t:  # duplicate frame, or lap timer already reset
            continue
        out.append(s)
        last_t = s[0]
    j = len(out)
    # trailing frames already reporting ~0.0 after crossing the line
    while j > 3 * len(out) // 4 and out[j - 1][1] < 0.5:
        j -= 1
    return out[:j]


def make_lap(number, raw_samples, touched_pit=False):
    s = clean_samples(raw_samples)
    valid = (
        len(s) >= 200
        and s[0][1] < 0.05
        and s[-1][1] > 0.95
        and not touched_pit
    )
    return {
        "lap": number,
        "time_ms": s[-1][0] if s else 0,
        "valid": bool(valid),
        "samples": s,
    }


def fmt_time(ms):
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"
