"""Read Assetto Corsa Competizione shared memory (Windows only).

ACC publishes three memory pages while it runs:
  Local\\acpmf_physics  - pedals, speed, gear ... (updates ~300 Hz)
  Local\\acpmf_graphics - lap timing, car position on track (~60 Hz)
  Local\\acpmf_static   - car / track names (set once per session)

Only the leading fields we need are mapped; the struct layouts match the
official ACC shared-memory documentation up to the last field listed here.
"""
import ctypes
import mmap
import sys

c_int = ctypes.c_int32
c_float = ctypes.c_float


def _w(n):
    # wchar_t on Windows is 2 bytes (UTF-16)
    return ctypes.c_uint16 * n


def wstr(arr):
    if isinstance(arr, str):  # demo reader passes plain strings
        return arr
    return bytes(arr).decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int),          # 0 = R, 1 = N, 2 = 1st ...
        ("rpms", c_int),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
    ]


class Graphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("status", c_int),        # 0 off, 1 replay, 2 live, 3 pause
        ("session", c_int),
        ("currentTime", _w(15)),
        ("lastTime", _w(15)),
        ("bestTime", _w(15)),
        ("split", _w(15)),
        ("completedLaps", c_int),
        ("position", c_int),
        ("iCurrentTime", c_int),  # ms into the current lap
        ("iLastTime", c_int),
        ("iBestTime", c_int),
        ("sessionTimeLeft", c_float),
        ("distanceTraveled", c_float),
        ("isInPit", c_int),
        ("currentSectorIndex", c_int),
        ("lastSectorTime", c_int),
        ("numberOfLaps", c_int),
        ("tyreCompound", _w(33)),
        ("replayTimeMultiplier", c_float),
        ("normalizedCarPosition", c_float),  # 0..1 around the lap
        ("activeCars", c_int),
        ("carCoordinates", (c_float * 3) * 60),  # world x, y, z per car
        ("carID", c_int * 60),
        ("playerCarID", c_int),
    ]


def player_xz(g):
    """World x/z of the player's car (y is height)."""
    for i in range(min(max(g.activeCars, 1), 60)):
        if g.carID[i] == g.playerCarID:
            c = g.carCoordinates[i]
            return c[0], c[2]
    c = g.carCoordinates[0]
    return c[0], c[2]


class Static(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", _w(15)),
        ("acVersion", _w(15)),
        ("numberOfSessions", c_int),
        ("numCars", c_int),
        ("carModel", _w(33)),
        ("track", _w(33)),
    ]


STATUS_OFF, STATUS_REPLAY, STATUS_LIVE, STATUS_PAUSE = 0, 1, 2, 3


class ACCReader:
    PAGES = {
        "physics": ("Local\\acpmf_physics", Physics),
        "graphics": ("Local\\acpmf_graphics", Graphics),
        "static": ("Local\\acpmf_static", Static),
    }

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError(
                "ACC shared memory only exists on Windows - run the recorder on your sim PC.")
        self._maps = {
            name: (mmap.mmap(-1, ctypes.sizeof(cls), tagname=tag), cls)
            for name, (tag, cls) in self.PAGES.items()
        }

    def _get(self, name):
        m, cls = self._maps[name]
        m.seek(0)
        return cls.from_buffer_copy(m.read(ctypes.sizeof(cls)))

    def physics(self) -> Physics:
        return self._get("physics")

    def graphics(self) -> Graphics:
        return self._get("graphics")

    def static(self) -> Static:
        return self._get("static")

    def close(self):
        for m, _ in self._maps.values():
            m.close()
