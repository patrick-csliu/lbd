"""The heartbeat of a measurement: `name.lbd.live` beside `name.lbd.writing` (spec §7, plan 9).

A Writer keeps this small JSON file up to date while it measures: which computer and program
measure, how far the measurement is (points written, of how many; the outer axes' positions and
how long each of their steps takes), rewritten at least every `BEAT_EVERY` seconds even when no
point was written. The guard lock (writer.py) tells "measuring" only on the measuring computer;
this file travels with a sync tool, so another computer can tell "measuring on LAB-PC" from "no
sign from LAB-PC since …" by when *it* saw the file change (never by comparing clocks).

Counting points: each value's sweep dimensions that `write` addresses one position at a time
(the "stepped" ones, e.g. power) get a small array of how much of each position was written;
the dimensions given whole in a write (a trace along frequency) are counted as `per_write`. So
points are counted once each, without a mask as large as the value.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

import numpy as np

from .io import WRITING_SUFFIX, LBDError, _warn

LIVE_SUFFIX = ".live"        # name.lbd.live
BEAT_EVERY = 30.0            # seconds: the file is rewritten at least this often
LIVE_EVERY = 5.0             # seconds: and at most this often when the progress changes
RATE_WINDOW = 300.0          # seconds of recent progress the rate is taken from
MASK_LIMIT = 10_000_000      # stepped positions counted one by one up to this many (float32 each)

_clock = time.monotonic      # intervals (tests replace it)
_now = time.time             # the times written into the file

PathLike = Union[str, os.PathLike]


def live_path(path: PathLike) -> Path:
    """`name.lbd.live` for `name.lbd` or `name.lbd.writing`."""
    p = Path(path)
    name = p.name[: -len(WRITING_SUFFIX)] if p.name.lower().endswith(WRITING_SUFFIX) else p.name
    return p.with_name(name + LIVE_SUFFIX)


def writing_progress(path: PathLike) -> Optional[Dict[str, Any]]:
    """How far a measurement is, from its heartbeat file `name.lbd.live`.

    Parameters
    ----------
    path : str or path-like
        The file being written (`name.lbd.writing`), or `name.lbd`.

    Returns
    -------
    dict or None
        The heartbeat (spec §7): `computer`, `program`, `started`, `updated`, and per value
        `points`, `total` (None when the size isn't known in advance), `axes` (each outer
        axis' `index`, `length` and `step_seconds`) and `rate` (points per second lately).
        None when there is no heartbeat file (the measurement finished, or its writer doesn't
        write one).

    Raises
    ------
    LBDError
        The heartbeat file can't be read (e.g. a sync tool is copying it right now).

    Examples
    --------
    >>> p = lbd.writing_progress("sweep.lbd.writing")
    >>> p["values"]["S21"]["points"], p["values"]["S21"]["total"]
    (47069, 180090)
    """
    p = live_path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise LBDError(f"{p.name} can't be read: {e}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise LBDError(f"{p.name} is incomplete or damaged (a sync tool may be copying it); try again") from None
    if not isinstance(data, dict) or data.get("lbd_live") != 1:
        raise LBDError(f"{p.name} is not an LBD heartbeat file")
    return data


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


class ValueProgress:
    """How much of one value was written."""

    def __init__(self, d: Any, v: Any):
        self.dims = list(v.dims)
        self.names = [dim[-1] for dim in self.dims]
        # a growing axis or a group's level: no size known in advance
        self.lengths: List[Optional[int]] = []
        for dim in self.dims:
            ax = d.axes[dim[-1]]
            self.lengths.append(None if ax.grows or ax.group is not None else len(ax.data))
        self.known = all(n is not None for n in self.lengths)
        self.total = int(np.prod(self.lengths)) if self.known else None
        self.points = 0
        self.stepped: Optional[Tuple[int, ...]] = None     # the dims written one position at a time
        self.per_write = 1
        self.mask: Optional[np.ndarray] = None
        self.axes: Dict[int, Dict[str, Any]] = {}          # per stepped dim: index, steps, times
        self.samples: Deque[Tuple[float, int]] = collections.deque()

    def _cells(self, k: Any, n: Optional[int]) -> int:
        if isinstance(k, (int, np.integer)):
            return 1
        if isinstance(k, slice):
            if k.start is None and k.stop is None:
                return n if n is not None else 0
            return max(0, (k.stop or 0) - (k.start or 0))
        return int(np.size(k))

    def add(self, index: Tuple[Any, ...], t: float) -> None:
        sweep = index[: len(self.dims)]
        if self.stepped is None:
            self.stepped = tuple(i for i, k in enumerate(sweep) if isinstance(k, (int, np.integer)))
            if self.known:
                self.per_write = int(np.prod([self.lengths[i] for i in range(len(self.dims)) if i not in self.stepped]))
                shape = tuple(self.lengths[i] for i in self.stepped)
                if int(np.prod(shape)) <= MASK_LIMIT:
                    self.mask = np.zeros(shape, dtype=np.float32)
        cells = [self._cells(k, n) for k, n in zip(sweep, self.lengths)]
        written = int(np.prod(cells)) if cells else 1
        if self.mask is not None:
            # each stepped position: the share of its cells written, at most all of them
            sel = tuple(sweep[i] for i in self.stepped)
            others = int(np.prod([c for i, c in enumerate(cells) if i not in self.stepped]))
            before = float(np.sum(self.mask[sel]))
            self.mask[sel] = np.minimum(self.mask[sel] + others / max(self.per_write, 1), 1.0)
            self.points = min(int(round(self.points + (float(np.sum(self.mask[sel])) - before) * self.per_write)),
                              self.total)
        elif self.total is not None:
            self.points = min(self.points + written, self.total)
        else:
            self.points += written
        for i in self.stepped:
            k = sweep[i]
            if not isinstance(k, (int, np.integer)) or self.lengths[i] is None:
                continue
            a = self.axes.setdefault(i, {"index": None, "steps": 0, "first": None, "last": None})
            if a["index"] != int(k):
                if a["index"] is not None:
                    a["steps"] += 1
                    a["last"] = t
                else:
                    a["first"] = t
                a["index"] = int(k)
        self.samples.append((t, self.points))
        while len(self.samples) > 2 and t - self.samples[1][0] > RATE_WINDOW:
            self.samples.popleft()

    def info(self) -> Dict[str, Any]:
        rate = None
        if len(self.samples) >= 2:
            (t0, p0), (t1, p1) = self.samples[0], self.samples[-1]
            if t1 > t0:
                rate = round((p1 - p0) / (t1 - t0), 6)
        axes = []
        for i in sorted(self.axes):
            a = self.axes[i]
            step = (a["last"] - a["first"]) / a["steps"] if a["steps"] else None
            axes.append({"name": self.names[i], "index": a["index"], "length": self.lengths[i],
                         "step_seconds": None if step is None else round(step, 3)})
        return {"points": int(self.points), "total": self.total, "per_write": self.per_write,
                "rate": rate, "axes": axes}


class Heartbeat:
    """The `.live` file of one Writer: what it says, and when it is due."""

    def __init__(self, writing_path: Path, d: Any, program: str):
        self.path = live_path(writing_path)
        self.d = d
        self.program = program
        self.computer = socket.gethostname() or "this computer"
        self.started = _now()
        self.values: Dict[str, ValueProgress] = {}
        self.changed = True
        self.last_written: Optional[float] = None
        self.last_write_call: Optional[float] = None
        self.longest_gap = 0.0
        self.failed = False

    def record(self, puts: List[Tuple[str, Tuple[Any, ...], Any]]) -> None:
        """A `write` with these (value, index, data): counted (call under the Writer's lock)."""
        t = _clock()
        if self.last_write_call is not None:
            self.longest_gap = max(self.longest_gap, t - self.last_write_call)
        self.last_write_call = t
        for name, index, _ in puts:
            vp = self.values.get(name)
            if vp is None:
                vp = self.values[name] = ValueProgress(self.d, self.d.values[name])
            vp.add(index, t)
        self.changed = True

    def due(self) -> bool:
        t = _clock()
        if self.last_written is None:
            return True
        return t - self.last_written >= BEAT_EVERY or (self.changed and t - self.last_written >= LIVE_EVERY)

    def content(self) -> Dict[str, Any]:
        return {"lbd_live": 1, "computer": self.computer, "process": os.getpid(), "program": self.program,
                "started": _iso(self.started), "updated": _iso(_now()), "beat_every": BEAT_EVERY,
                "longest_gap": round(self.longest_gap, 3),
                "values": {n: vp.info() for n, vp in self.values.items()}}

    def write(self, content: Dict[str, Any]) -> None:
        """Replace the file with `content` (a whole new file, so a reader never sees half of
        one). A failure is said once and never stops the measurement."""
        self.last_written = _clock()
        self.changed = False
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(content, indent=1), encoding="utf-8")
            for attempt in range(20):                  # a reader may have it open (Windows)
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.05)
        except OSError as e:
            if not self.failed:
                self.failed = True
                _warn(f"{self.path.name} (how far the measurement is, for other computers) can't be written: {e}; "
                      "the measurement goes on")
            try:
                tmp.unlink()
            except OSError:
                pass

    def remove(self) -> None:
        for p in (self.path, self.path.with_name(self.path.name + ".tmp")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                _warn(f"{p.name} couldn't be removed ({e}); it can be deleted")
