"""The colour range of a map over every slider position (plan 11; view setting `crange`).

A map with a slider (e.g. flux × frequency at each power) shows one slice at a time. With
`crange: "all"` its colours span the lowest to the highest value of **every** slice, so a colour
means the same number at every slider position; with `"slice"` (as before) each slice has its own.

The range is of the numbers as shown: complex mode, operations and equations applied (the user's
choice: "if the user selects all, then all"). So it is worked out by drawing each slice once in a
private session, in the background (a large file takes a while); until it is ready the map uses
its own slice's range and the picture's `meta["crange"]` says how far it is. Results are kept
for the server's run (one per file version, plot settings and operations), so moving the slider,
reopening the file or another tab showing the same thing is instant.

Numbers are kept as stored (divided by the model's unit factor `zf`), so a slice drawn with
another unit prefix still gets the same colours.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lbd.plot import render as rnd

SAMPLE = 200_000          # values kept for the contrast histogram (of all slices together)
KEEP = 32                 # results kept (least recently used dropped)
WORKERS = 2               # ranges worked out at the same time


class Range:
    """The lowest and highest finite number of every slice (stored units), the lowest above 0
    (for a log colour scale), and a sample of the numbers (all of them when few) for the
    histogram."""

    def __init__(self, lo: float, hi: float, lo_pos: float, sample: np.ndarray, slices: int):
        self.lo, self.hi, self.lo_pos, self.sample, self.slices = lo, hi, lo_pos, sample, slices


class Job:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.error: Optional[str] = None
        self.cancelled = False
        self.started = time.monotonic()

    def info(self) -> Dict[str, Any]:
        state = "failed" if self.error else "working"
        return {"state": state, "fraction": round(self.done / max(self.total, 1), 3), "slices": self.total,
                "error": self.error}


_lock = threading.Lock()
_results: "OrderedDict[str, Range]" = OrderedDict()
_jobs: Dict[str, Job] = {}
_running = threading.Semaphore(WORKERS)


def sliders(s) -> List[Tuple[str, int]]:
    """The map's slider axes: the value's axes other than the drawn ones, with more than one
    position (name, number of positions)."""
    if s.base_kind != "heatmap":
        return []
    v = s.header.values[s.spec["values"][0]]
    drawn = {s.spec["x"], s.spec["y"]}
    return [(a, len(s.data.axes[a].data)) for a in v.axes if a not in drawn and a in s.data.axes
            and len(s.data.axes[a].data) > 1]


def key_of(s, settings: Dict[str, Any]) -> str:
    spec = {k: v for k, v in s.spec.items() if k not in ("index", "slices")}
    shown = {k: settings.get(k) for k in ("ops", "ops_on", "equations", "select")}
    return json.dumps([str(Path(s.path).resolve()), s.version, spec, shown], sort_keys=True, default=str)


def _per_slice_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """What changes the numbers (not the colours, scales or limits)."""
    return {k: settings[k] for k in ("ops", "ops_on", "equations", "select") if k in settings}


def get(s, settings: Dict[str, Any]) -> Tuple[Optional[Range], Optional[Dict[str, Any]]]:
    """The range of every slice of what session `s` shows, or (None, how far it is): started in
    the background the first time it is asked for."""
    axes = sliders(s)
    if not axes:
        return None, None
    key = key_of(s, settings)
    with _lock:
        r = _results.get(key)
        if r is not None:
            _results.move_to_end(key)
            return r, None
        job = _jobs.get(key)
        if job is None:
            total = int(np.prod([n for _, n in axes]))
            job = _jobs[key] = Job(total)
            spec = {k: v for k, v in s.spec.items() if k in rnd.SPEC_KEYS}   # the plot settings, not what they resolved to
            threading.Thread(target=_work, args=(key, job, s.path, s.version, spec, s.style, axes,
                                                 _per_slice_settings(settings)),
                             daemon=True, name="lbd-colour-range").start()
    return None, job.info()


def peek(s, settings: Dict[str, Any]) -> Optional[Range]:
    """The range if it is worked out already (nothing started)."""
    if not sliders(s):
        return None
    with _lock:
        return _results.get(key_of(s, settings))


def cancel_all() -> None:
    """Stop every range being worked out (tests; the server's end)."""
    with _lock:
        for job in _jobs.values():
            job.cancelled = True


def forget() -> None:
    """Drop every kept range (tests)."""
    cancel_all()
    with _lock:
        _results.clear()
        _jobs.clear()


def _work(key: str, job: Job, path, version: str, spec: Dict[str, Any], style, axes, settings) -> None:
    from .explore import ExploreSession            # the session drawing each slice (imports this module)

    lo, hi, lo_pos = np.inf, -np.inf, np.inf
    parts: List[np.ndarray] = []
    per = max(SAMPLE // max(job.total, 1), 64)
    rng = np.random.default_rng(0)
    ws = None
    try:
        with _running:
            ws = ExploreSession(Path(path), version, spec, style, 200, 150, 1.0, saved_view=False, bare=True)
            fixed = dict(spec.get("index") or {})
            for positions in itertools.product(*[range(n) for _, n in axes]):
                if job.cancelled:
                    return
                index = {**fixed, **{a: int(i) for (a, _), i in zip(axes, positions)}}
                ws.set_spec({**spec, "index": index})
                ws.apply(settings)
                zf = float(getattr(ws.model, "zf", 1.0) or 1.0)
                z = np.asarray(ws._finite_z(), dtype=float) / zf
                z = z[np.isfinite(z)]
                if z.size:
                    lo, hi = min(lo, float(z.min())), max(hi, float(z.max()))
                    pos = z[z > 0]
                    if pos.size:
                        lo_pos = min(lo_pos, float(pos.min()))
                    parts.append(z if z.size <= per else rng.choice(z, per, replace=False))
                job.done += 1
        sample = np.concatenate(parts) if parts else np.zeros(0)
        result = Range(lo, hi, lo_pos, sample, job.total)
        with _lock:
            _results[key] = result
            _results.move_to_end(key)
            while len(_results) > KEEP:
                _results.popitem(last=False)
            _jobs.pop(key, None)
    except Exception as e:                            # said in the panel; the slice's own range is used
        job.error = f"the colour range of every slice couldn't be worked out ({e}); each slice uses its own"
    finally:
        if ws is not None:
            ws.close()


def norm_limits(r: Range, zf: float, log: bool) -> Tuple[Optional[float], Optional[float]]:
    """The range in the plot's units (None where there is no number)."""
    lo = r.lo_pos if log else r.lo
    if not np.isfinite(lo) or not np.isfinite(r.hi):
        return None, None
    return lo * zf, r.hi * zf

