"""Files being measured (plan 9): their state as this computer can know it, and their progress as
steady text.

The state of `name.lbd.writing`:

- **measuring**: its writer holds the guard here (lbd.writing_status), so it measures on this
  computer.
- **elsewhere**: its heartbeat `name.lbd.live` names another computer and changed recently (as
  this computer saw it): "Measuring on LAB-PC". Without a heartbeat (an older writer), a data file
  that changed recently is also "elsewhere", computer unknown ("not being written on this
  computer").
- **silent**: the heartbeat names another computer but hasn't changed for a while: "No sign from
  LAB-PC since 10:06: it probably stopped, or the sync is paused". This computer can't know which.
- **stopped**: nothing measures it here and nothing changes (a crash here; or a stopped
  measurement from elsewhere, long ago).

Times: "changed recently" is judged by when *this* computer saw the heartbeat (or data file)
change, never by comparing another computer's clock with this one's.

The progress text never jumps (the user's rule): each part comes with the widest text it can take
(the page keeps a box that wide); the percentage and points are rounded so they change at most
about once a second; the time left comes from the writer's rate over the last minutes, rounded to
steps that suit its size, and changes only when the new estimate differs by more than 10 %.
"""

from __future__ import annotations

import glob
import math
import re
import socket
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import lbd

ALIVE_MIN = 600.0          # seconds: a heartbeat seen within this is "measuring elsewhere" at least
DATA_ALIVE_MIN = 120.0     # without a heartbeat: the data file changed within this (or 3 × its gaps)
SLOW_AXIS = 5.0            # seconds per step: an axis this slow or slower is shown on its own
TIME_CHANGE = 0.10         # the time left changes only when the estimate moves more than this


def this_computer() -> str:
    return socket.gethostname() or "this computer"


def _same_computer(a: Optional[str], b: str) -> bool:
    return bool(a) and a.strip().lower() == b.strip().lower()


def _group(n: int) -> str:
    """47069 → '47 069' (a narrow no-break space between thousands)."""
    return f"{n:,}".replace(",", " ")


def time_left_text(seconds: float) -> str:
    """Rounded to steps that suit the size: about 40 s, 3 min, 25 min, 2 h 10 min."""
    s = max(0.0, seconds)
    if s < 60:
        return f"about {max(10, int(round(s / 10.0)) * 10)} s"
    if s < 600:
        return f"about {int(round(s / 60.0))} min"
    if s < 3600:
        return f"about {int(round(s / 300.0)) * 5} min"
    m = int(round(s / 600.0)) * 10
    h, m = divmod(m, 60)
    return f"about {h} h" + (f" {m} min" if m else "")


class _Steady:
    """What was shown last for one file: the time-left estimate it showed."""

    def __init__(self) -> None:
        self.time_left: Optional[float] = None
        self.at: Optional[float] = None


def progress_parts(value: Dict[str, Any], steady: _Steady, now: float) -> List[Dict[str, str]]:
    """The parts of the status line for one value's progress (from the heartbeat):
    [{"kind": "axes" | "percent" | "points" | "time", "text", "width"}]."""
    points, total = int(value.get("points") or 0), value.get("total")
    rate = value.get("rate")
    parts: List[Dict[str, str]] = []
    for a in value.get("axes") or []:
        step = a.get("step_seconds")
        if step is None or step < SLOW_AXIS:
            continue                                   # too fast to read: only in % and points
        n = int(a["length"])
        parts.append({"kind": "axes", "text": f"{a['name']} {min(int(a['index']) + 1, n)} of {n}",
                      "width": f"{a['name']} {n} of {n}"})
    # points: rounded so the text changes at most about once a second
    step = 1
    if rate and rate > 1:
        step = 10 ** math.ceil(math.log10(rate))
    shown = points if step == 1 or (total is not None and points >= total) else (points // step) * step
    if total is None:
        parts.append({"kind": "points", "text": f"{_group(shown)} points",
                      "width": f"{_group(10 ** len(str(max(points, 1))) - 1)} points"})
        return parts
    total = int(total)
    pct = 100.0 * points / total if total else 100.0
    per_minute = 100.0 * rate * 60 / total if rate and total else 0.0
    if points >= total:
        pct_text, pct_width = "100 %", "100 %"
    elif per_minute < 1:
        pct_text, pct_width = f"{math.floor(pct * 10) / 10:.1f} %", "99.9 %"
    else:
        pct_text, pct_width = f"{min(math.floor(pct), 99)} %", "99 %"
    parts.append({"kind": "percent", "text": pct_text, "width": pct_width})
    parts.append({"kind": "points", "text": f"{_group(shown)} of {_group(total)} points",
                  "width": f"{_group(total)} of {_group(total)} points"})
    # time left: from the writer's recent rate; a new estimate only when it moved > 10 %
    left_width = "about 10 h 50 min"
    per_write = int(value.get("per_write") or 1)
    if points >= total:
        text = "done"
    elif not rate or rate <= 0 or points < 3 * per_write:
        text = "estimating…"
    else:
        estimate = (total - points) / rate
        if steady.time_left is not None and steady.at is not None:
            expected = max(0.0, steady.time_left - (now - steady.at))     # the last one, counted down
            if expected > 0 and abs(estimate - expected) <= TIME_CHANGE * expected:
                estimate = expected
            else:
                steady.time_left, steady.at = estimate, now
        else:
            steady.time_left, steady.at = estimate, now
        text = time_left_text(estimate) + " left"
    parts.append({"kind": "time", "text": text, "width": left_width + " left"})
    return parts


class LiveWatch:
    """What this computer knows about the files being measured that the pages show. One per
    viewer; `clock` (intervals) and `wall` (times shown) can be replaced in tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 computer: Optional[str] = None):
        self.clock, self.wall = clock, wall
        self.computer = computer or this_computer()
        self._lock = threading.Lock()
        # path → (heartbeat signature, when this computer saw it change (clock), (wall))
        self._beats: Dict[str, Tuple[str, float, float]] = {}
        # path → (data file signature, when seen changed (clock), (wall), longest gap seen)
        self._data: Dict[str, Tuple[str, float, float, float]] = {}
        self._steady: Dict[str, _Steady] = {}
        self._ids: Dict[str, str] = {}             # path → the measurement's id, seen while written
        self._followed: set = set()

    def _seen(self, table: Dict[str, Tuple], path: str, sig: str, mtime: float) -> Tuple[float, float, float]:
        """(seconds since this computer saw `sig` change, the wall time of that, longest gap)."""
        now, wall = self.clock(), self.wall()
        old = table.get(path)
        if old is None:
            # first look: the file's own time says how old it is, at most "now"
            age = min(max(0.0, wall - mtime), 24 * 3600.0)
            table[path] = (sig, now - age, wall - age, 0.0) if table is self._data else (sig, now - age, wall - age)
        elif old[0] != sig:
            gap = now - old[1]
            if table is self._data:
                table[path] = (sig, now, wall, max(old[3], gap))
            else:
                table[path] = (sig, now, wall)
        rec = table[path]
        return now - rec[1], rec[2], (rec[3] if table is self._data else 0.0)

    def status(self, path: str, value: Optional[str] = None) -> Dict[str, Any]:
        """The state of a file being measured, and its progress (for `value`, else the value
        with the most points)."""
        p = Path(path)
        with self._lock:
            try:
                local = lbd.writing_status(p)
            except FileNotFoundError:
                return {"state": "gone"}
            beat, unreadable = None, None
            try:
                beat = lbd.writing_progress(p)
            except lbd.LBDError as e:
                unreadable = str(e)
            out: Dict[str, Any] = {"state": "stopped", "computer": None, "since": None, "progress": None}
            if beat is not None:
                values = beat.get("values") or {}
                chosen = values.get(value) if value else None
                if chosen is None and values:
                    chosen = max(values.values(), key=lambda v: (v.get("total") is not None, v.get("points") or 0))
                if chosen is not None:
                    steady = self._steady.setdefault(str(p), _Steady())
                    out["progress"] = progress_parts(chosen, steady, self.clock())
            self.remember_id(str(p))
            if local == "measuring":
                out.update(state="measuring", computer=self.computer)
                return out
            beat_file = p.with_name(p.name[: -len(".writing")] + ".live")
            if beat is not None and not _same_computer(beat.get("computer"), self.computer):
                st = beat_file.stat()
                ago, at, _ = self._seen(self._beats, str(p), f"{st.st_mtime_ns}-{st.st_size}", st.st_mtime)
                alive = max(ALIVE_MIN, 3 * float(beat.get("longest_gap") or 0) + 2 * float(beat.get("beat_every") or 30))
                out.update(state="elsewhere" if ago < alive else "silent", computer=beat.get("computer"), since=at)
                return out
            if beat is None:
                st = p.stat()
                ago, at, gap = self._seen(self._data, str(p), f"{st.st_mtime_ns}-{st.st_size}", st.st_mtime)
                if ago < max(DATA_ALIVE_MIN, 3 * gap):
                    out.update(state="elsewhere", since=at)       # computer unknown
                    if unreadable:
                        out["note"] = unreadable
                    return out
                out["since"] = at
            return out

    def forget(self, path: str) -> None:
        with self._lock:
            for table in (self._beats, self._data, self._steady, self._ids):
                table.pop(path, None)

    def remember_id(self, path: str) -> None:
        """Note the measurement's id while its file is being written, to find it once finished."""
        if path in self._ids:
            return
        try:
            with warnings.catch_warnings():          # "still being written": known
                warnings.simplefilter("ignore", lbd.LBDWarning)
                self._ids[path] = lbd.info(path).id
        except Exception:                            # being written: read again next time
            pass

    def finished(self, path: str) -> Optional[Path]:
        """The finished file of a measurement whose `name.lbd.writing` is gone: `name.lbd` (or
        `name (2).lbd` …, as the Writer names it when the name was taken) with the same id; None
        when there is none (yet), or the id wasn't seen while it was written."""
        p = Path(path)
        ident = self._ids.get(str(p))
        if p.exists() or not ident:
            return None
        base = p.name[: -len(".writing")]
        stem = base[: -len(".lbd")]
        for c in sorted(p.parent.glob(glob.escape(stem) + "*.lbd")):
            if c.name != base and not re.fullmatch(re.escape(stem) + r" \(\d+\)\.lbd", c.name):
                continue
            try:
                if lbd.info(c).id == ident:
                    return c
            except Exception:                        # unreadable: not this one
                continue
        return None

    def mark_followed(self, path: str) -> bool:
        """True the first time only: LBD's records follow a finished file once."""
        with self._lock:
            if path in self._followed:
                return False
            self._followed.add(path)
            return True


_shared: Dict[str, LiveWatch] = {}


def shared() -> LiveWatch:
    """The viewer's one LiveWatch."""
    if "watch" not in _shared:
        _shared["watch"] = LiveWatch()
    return _shared["watch"]
