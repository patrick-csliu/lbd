"""A histogram in an Explore session. The counts are the expensive part, and depend only on which
numbers are shown: they are kept by `key_of`, so another vertical axis or drawing style needs no
recount.

Few numbers are counted at once. More are counted in the background, with `crange.py`'s workers: a
first pass finds the bins, a second counts into them, so only the bins and one block are held. The
picture shows the counts so far (`meta["crange"]` says how far), and the page asks again until they
are complete. A slider moved meanwhile stops the old count.
"""

import json
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import numpy as np

import lbd
from lbd.plot import histogram as hist
from lbd.plot import render as rnd

from .. import crange, memory
from . import Interaction

QUICK = 2_000_000         # up to this many numbers are counted at once
KEEP = 32                 # results kept (least recently used dropped)
NUMBER_SETTINGS = ("ops", "ops_on", "equations", "select")     # the view settings that change the numbers
SPEC_NUMBERS = ("values", "complex", "color", "all", "index")


class Job(crange.Job):
    """A count in the background. `partial`: the counts so far, once the bins are known."""

    def __init__(self, total: int):
        super().__init__(total)
        self.partial: Optional[hist.Counted] = None
        self.sessions: Set[str] = set()

    def info(self) -> Dict[str, Any]:
        return {**super().info(), "from": "histogram"}


_lock = threading.Lock()
_results: "OrderedDict[str, hist.Counted]" = OrderedDict()
_jobs: Dict[str, Job] = {}
_session_job: Dict[str, str] = {}          # session id: the key of the count it waits for


def key_of(s: Any, settings: Dict[str, Any]) -> str:
    """What the counts depend on: path, version, which numbers, the bins, what is done to them."""
    spec = {k: s.spec.get(k) for k in SPEC_NUMBERS}
    shown = {k: settings.get(k) for k in NUMBER_SETTINGS}
    return json.dumps([str(Path(s.path).resolve()), s.version, spec, s.spec["options"]["bins"], shown],
                      sort_keys=True, default=str)


def numbers_in(d: Any, spec: Dict[str, Any]) -> int:
    """How many numbers a histogram counts."""
    total = 0
    for name in spec["values"]:
        v = d.values[name]
        fixed = hist._fixed(v, spec)
        fixed.pop(spec.get("color"), None)
        total += int(np.prod([n for a, n in zip(v.axes, v.shape) if a not in fixed], dtype=np.int64))
    return total


def block_size() -> int:
    """Numbers read at a time: fewer when memory is short (a block is copied a few times)."""
    return int(min(hist.BLOCK, max(memory.shared().memory.room() // 64, 2 ** 16)))


def _keep(key: str, counted: hist.Counted) -> None:
    """Under `_lock`."""
    _results[key] = counted
    _results.move_to_end(key)
    while len(_results) > KEEP:
        _results.popitem(last=False)


def _leave(sid: str, unless: Optional[str] = None) -> None:
    """Session `sid` no longer waits for its count, which stops if nobody else does. Under `_lock`."""
    key = _session_job.get(sid)
    if key is None or key == unless:
        return
    del _session_job[sid]
    job = _jobs.get(key)
    if job is not None:
        job.sessions.discard(sid)
        if not job.sessions:
            job.cancelled = True
            del _jobs[key]


def get(s: Any, settings: Dict[str, Any]) -> Tuple[Optional[hist.Counted], Optional[Job]]:
    """The counts of what session `s` shows, or (None, the job counting them), started the first
    time it is asked for."""
    key = key_of(s, settings)
    with _lock:
        _leave(s.id, unless=key)
        counted = _results.get(key)
        if counted is not None:
            _results.move_to_end(key)
            _leave(s.id)
            return counted, None
        job = _jobs.get(key)
        total = numbers_in(s.data, s.spec)
        if job is None and total > QUICK:
            job = _jobs[key] = Job(2 * total)                  # two passes
            threading.Thread(target=_work, args=(key, job, s.path, s.spec), daemon=True,
                             name="lbd-histogram").start()
        if job is not None:
            job.sessions.add(s.id)
            _session_job[s.id] = key
            return None, job
    counted = _two_passes(Job(2 * total), lambda: hist.blocks(s.data, s.spec, block_size()), s.data, s.spec)
    with _lock:
        _keep(key, counted)
    return counted, None


def _work(key: str, job: Job, path: Any, spec: Dict[str, Any]) -> None:
    try:
        with crange._running:
            if job.cancelled:
                return
            d = rnd.flat(lbd.open(path, hold=False))
            try:
                counted = _two_passes(job, lambda: hist.blocks(d, spec, block_size()), d, spec)
            finally:
                d.close()
        if counted is None:
            return
        with _lock:
            _keep(key, counted)
            _jobs.pop(key, None)
            for sid in job.sessions:
                _session_job.pop(sid, None)
    except Exception as e:                            # said in the panel; nothing is drawn as if complete
        job.error = f"the numbers couldn't be counted ({e})"


def _two_passes(job: Job, blocks: Callable[[], Iterator[Tuple[int, np.ndarray]]], d: Any,
                spec: Dict[str, Any]) -> Optional[hist.Counted]:
    """The bins from a first pass over `blocks()`, then the counts from a second. None: cancelled."""
    span = hist.Span()
    for _, numbers in blocks():
        if job.cancelled:
            return None
        span.add(numbers)
        job.done += numbers.size
    edges = span.edges(spec["options"]["bins"], hist.is_integer(d, spec))
    counts = [np.zeros(edges.size - 1, dtype=np.int64) for _ in hist.series_of(d, spec)]
    job.partial = hist.Counted(edges, counts, span.left_out)
    for k, numbers in blocks():
        if job.cancelled:
            return None
        counts[k] += hist.count_bins(numbers, edges)[1]
        job.done += numbers.size
    return job.partial


def cancel_all() -> None:
    """Stop every count (tests; the server's end): `crange.cancel_all` comes here too."""
    with _lock:
        for job in _jobs.values():
            job.cancelled = True


def forget() -> None:
    """Drop every kept count (tests)."""
    cancel_all()
    with _lock:
        _results.clear()
        _jobs.clear()
        _session_job.clear()


crange.others.append(sys.modules[__name__])


def _nothing_yet(s: Any) -> hist.Counted:
    """Empty axes, until the bins are known."""
    edges = hist.count_bins([], 2, (0.0, 1.0))[0]
    return hist.Counted(edges, [np.zeros(2, dtype=np.int64) for _ in hist.series_of(s.data, s.spec)])


def _shown(s: Any, counted: Optional[hist.Counted], job: Optional[Job]) -> hist.Counted:
    """What to draw: the counts, or those so far (a copy: the job goes on adding to them). After
    a failure nothing: it mustn't look complete."""
    if counted is not None:
        return counted
    part = job.partial if job is not None and not job.error else None
    if part is None:
        return _nothing_yet(s)
    return hist.Counted(part.edges, [c.copy() for c in part.counts], part.left_out)


class Histogram(Interaction):
    name = kind = "histogram"
    model = hist.HistModel
    cursor_types = ("vertical",)
    operations = "before"         # on the numbers, before they are counted
    log_x = False

    def __init__(self, session: Any):
        super().__init__(session)
        self.drawn: List[Any] = []
        self.showing: Optional[Tuple[int, bool]] = None      # the model and scale the artists show

    @classmethod
    def prepare(cls, s: Any) -> hist.HistModel:
        counted, job = get(s, getattr(s, "settings", None) or {})
        s.crange_info = job.info() if job else None
        s.hist_counted = counted
        return hist.prepare(s.data, s.spec, s.style, big=_shown(s, counted, job))

    def setup(self) -> None:
        s = self.s
        self.drawn = hist.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style, quiet=True)
        self.showing = (id(s.model), s.ax.get_yscale() == "log")

    def apply(self, settings: Dict[str, Any], chosen: Optional[set], clim: Any) -> None:
        s = self.s
        counted, job = get(s, settings)
        s.crange_info = job.info() if job else None
        if counted is not None and counted is s.hist_counted:
            return
        s.hist_counted = counted
        m = hist.prepare(s.data, s.spec, s.style, big=_shown(s, counted, job))
        s.model = s.base_model = s.raw_model = m
        s.ax.set_xlabel(m.x_label)
        s.ax.set_ylabel(m.y_label)

    def _log(self) -> bool:
        return self.s.ax.get_yscale() == "log"

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        edges = self.s.model.edges
        return (float(edges[0]), float(edges[-1])), hist.y_limits(self.s.model, self._log())

    def picture(self, pxe: np.ndarray, pye: np.ndarray, stat: str, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        m = self.s.model
        now = (id(m), self._log())
        if now != self.showing:
            hist.update_series(self.drawn, m, now[1])
            self.showing = now
        info = self.s.crange_info
        if info and info["state"] == "working":
            return f"Counting… {round(info['fraction'] * 100)} %", False
        total = sum(int(s.counts.sum()) for s in m.series)
        return f"{total:,} numbers in {m.edges.size - 1:,} bins", False

    def has_positive(self, which: str) -> bool:
        return which == "horizontal" or any(s.counts.any() for s in self.s.model.series)

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        s = self.s
        info = s.crange_info
        if info:                                         # nothing is complete yet
            return [], info["error"]
        empty = None if any(c.counts.any() for c in s.model.series) else s._why_empty("number")
        return hist.notes_of(s.model), empty

    def meta(self) -> Dict[str, Any]:
        return {"crange": self.s.crange_info}


INTERACTION = Histogram
