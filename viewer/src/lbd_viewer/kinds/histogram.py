"""A histogram in an Explore session. The counts are the expensive part, and depend only on which
numbers are shown: they are kept by `key_of`, so another vertical axis or drawing style needs no
recount.

Few numbers are counted at once. More are counted in the background, with `crange.py`'s workers: a
first pass finds the bins, a second counts into them, so only the bins and one block are held. The
picture shows the counts so far (`meta["crange"]` says how far), and the page asks again until they
are complete. A slider moved meanwhile stops the old count.

With operations or equations on, the numbers come from a private session drawing curves (`_op_blocks`):
operations work on curves, so the longest All axis is the curves' x, the next one a curve per step,
and each other All axis and Colour by step is taken in turn.
"""

import itertools
import json
import sys
import threading
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import numpy as np

import lbd
from lbd.plot import histogram as hist
from lbd.plot import render as rnd
from lbd.plot import tables

from .. import crange, memory
from .. import operations as ops_mod
from . import Interaction

QUICK = 2_000_000         # up to this many numbers are counted at once
OPS_QUICK = 100_000       # after operations: up to this many, in at most OPS_QUICK_DRAWS drawings
OPS_QUICK_DRAWS = 16
MOST_DRAWS = 20_000       # drawings a private session is asked for: more would take very long
KEEP = 32                 # results kept (least recently used dropped)
SPEC_NUMBERS = ("values", "complex", "color", "all", "index")


class Job(crange.Job):
    """A count in the background. `partial`: the counts so far, once the bins are known."""

    def __init__(self, total: int):
        super().__init__(total)
        self.partial: Optional[hist.Counted] = None
        self.sessions: Set[str] = set()
        self.shown: Optional[Tuple[str, str]] = None         # after operations: what the numbers are
        self.ops: Optional[Dict[str, Any]] = None            # the private session's `ops_info`

    def info(self) -> Dict[str, Any]:
        return {**super().info(), "from": "histogram"}


_lock = threading.Lock()
_results: "OrderedDict[str, hist.Counted]" = OrderedDict()
_jobs: Dict[str, Job] = {}
_session_job: Dict[str, str] = {}          # session id: the key of the count it waits for
_names: "OrderedDict[str, Any]" = OrderedDict()   # what equations can use, per file and value


def key_of(s: Any, settings: Dict[str, Any]) -> str:
    """What the counts depend on: path, version, which numbers, the bins, what is done to them."""
    spec = {k: s.spec.get(k) for k in SPEC_NUMBERS}
    return json.dumps([str(Path(s.path).resolve()), s.version, spec, s.spec["options"]["bins"], changes(settings)],
                      sort_keys=True, default=str)


def changes(settings: Dict[str, Any]) -> Dict[str, Any]:
    """The operations and equations on, as settings for a private session ({}: the stored numbers)."""
    if settings.get("ops_on") is False:
        return {}
    out: Dict[str, Any] = {}
    ops = ops_mod.check(settings.get("ops"))
    if any(op["on"] for op in ops):
        out["ops"] = ops                                 # those off too: each has its note
    equations = {k: v for k, v in (settings.get("equations") or {}).items() if v.strip()}
    if equations:
        out["equations"] = equations
    return out


def refusal(settings: Dict[str, Any]) -> Optional[str]:
    """Why the numbers can't be counted after these operations."""
    if any(op["op"] == "iq_histogram" and op["on"] for op in changes(settings).get("ops", [])):
        return ("The I/Q histogram makes a map of its own, so a histogram can't count it: turn that operation off, "
                "or show this plot as a map")
    return None


def numbers_in(d: Any, spec: Dict[str, Any]) -> int:
    """How many numbers a histogram counts."""
    total = 0
    for name in spec["values"]:
        v = d.values[name]
        fixed = hist._fixed(v, spec)
        fixed.pop(spec.get("color"), None)
        total += int(np.prod([n for a, n in zip(v.axes, v.shape) if a not in fixed], dtype=np.int64))
    return total


def draws_in(d: Any, spec: Dict[str, Any]) -> int:
    """How many drawings a private session makes for one pass."""
    return sum(int(np.prod([n for _, n in _taken_in_turn(d.values[name], spec)], dtype=np.int64))
               for name in spec["values"])


def _whole(v: Any, spec: Dict[str, Any]) -> List[str]:
    """The All axes of a value, longest first."""
    return sorted((a for a in v.axes if a in spec["all"]), key=lambda a: -v.shape[v.axes.index(a)])


def _taken_in_turn(v: Any, spec: Dict[str, Any]) -> List[Tuple[str, int]]:
    """The axes a private session steps through: (name, steps). The two longest All axes are drawn."""
    axes = _whole(v, spec)[2:] + ([spec["color"]] if spec["color"] in v.axes else [])
    return [(a, v.shape[v.axes.index(a)]) for a in axes]


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
        wanted = changes(settings)
        if job is None and wanted:
            _check_operated(s.data, s.spec)
        if job is None and (total > OPS_QUICK or draws_in(s.data, s.spec) > OPS_QUICK_DRAWS if wanted else total > QUICK):
            job = _jobs[key] = Job(2 * total)                  # two passes
            threading.Thread(target=_work, args=(key, job, s.path, s.version, s.spec, s.style, wanted), daemon=True,
                             name="lbd-histogram").start()
        if job is not None:
            job.sessions.add(s.id)
            _session_job[s.id] = key
            return None, job
    now = Job(2 * total)
    source = ((lambda: _op_blocks(now, s.path, s.version, s.spec, s.style, wanted)) if wanted else
              (lambda: hist.blocks(s.data, s.spec, block_size())))
    counted = _two_passes(now, source, s.data, s.spec, wanted)
    with _lock:
        _keep(key, counted)
    return counted, None


def _check_operated(d: Any, spec: Dict[str, Any]) -> None:
    from ..explore import ExploreError

    for name in spec["values"]:
        if not _whole(d.values[name], spec):
            raise ExploreError("operations work along an axis: make one of the axes All, or turn the operations off")
    n = draws_in(d, spec)
    if n > MOST_DRAWS:
        raise ExploreError(f"operations here would need {n:,} drawings, which would take very long: make some axes "
                           "sliders, or turn the operations off")


def _op_blocks(job: Job, path: Any, version: str, spec: Dict[str, Any], style: Any,
               wanted: Dict[str, Any]) -> Iterator[Tuple[int, np.ndarray]]:
    """(series number, numbers), the operations and equations `wanted` done, from a private session."""
    from ..explore import ExploreError, ExploreSession

    header = rnd.flat(lbd.info(path))

    def curves(name: str, steps: Dict[str, int]) -> Dict[str, Any]:
        axes = _whole(header.values[name], spec)
        return {"kind": "curve", "values": [name], "x": axes[0], "series": axes[1] if len(axes) > 1 else "none",
                "complex": spec["complex"], "index": {**spec["index"], **steps}}

    ws = None
    first = 0
    try:
        for name in spec["values"]:
            v = header.values[name]
            turns = _taken_in_turn(v, spec)
            for positions in itertools.product(*[range(n) for _, n in turns]):
                if job.cancelled:
                    return
                steps = {a: i for (a, _), i in zip(turns, positions)}
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", rnd.RenderWarning)
                    if ws is None:
                        ws = ExploreSession(Path(path), version, curves(name, steps), style, 200, 150, 1.0,
                                            saved_view=False, bare=True)
                    else:
                        ws.set_spec(curves(name, steps))
                    ws.apply(wanted)
                if ws.kind != "curve":
                    raise ExploreError("these operations don't give curves, so there is nothing to count")
                if ws.summarised:
                    raise ExploreError("these curves are larger than the memory free now, and operations need "
                                       "them whole: make some axes sliders")
                info = ws.ops_info()
                job.ops = info
                if info["applied"]:
                    job.shown = (info.get("shows") or name, info.get("unit") or "")
                m = ws.model
                numbers = np.concatenate([np.ravel(np.asarray(y, dtype=float)) / m.yf for y, _ in m.lines])
                yield first + steps.get(spec["color"], 0), numbers
            first += v.shape[v.axes.index(spec["color"])] if spec["color"] in v.axes else 1
    finally:
        if ws is not None:
            ws.close()


def _work(key: str, job: Job, path: Any, version: str, spec: Dict[str, Any], style: Any, wanted: Dict[str, Any]) -> None:
    try:
        with crange._running:
            if job.cancelled:
                return
            d = rnd.flat(lbd.open(path, hold=False))
            try:
                source = ((lambda: _op_blocks(job, path, version, spec, style, wanted)) if wanted else
                          (lambda: hist.blocks(d, spec, block_size())))
                counted = _two_passes(job, source, d, spec, wanted)
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
                spec: Dict[str, Any], wanted: Optional[Dict[str, Any]] = None) -> Optional[hist.Counted]:
    """The bins from a first pass over `blocks()`, then the counts from a second. None: cancelled."""
    span = hist.Span()
    for _, numbers in blocks():
        if job.cancelled:
            return None
        span.add(numbers)
        job.done += numbers.size
    edges = span.edges(spec["options"]["bins"], not wanted and hist.is_integer(d, spec))
    counts = [np.zeros(edges.size - 1, dtype=np.int64) for _ in hist.series_of(d, spec)]
    job.partial = hist.Counted(edges, counts, span.left_out, job.shown, job.ops)
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
        _names.clear()


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
    return hist.Counted(part.edges, [c.copy() for c in part.counts], part.left_out, part.shown)


def names_for_equations(s: Any) -> Optional[Any]:
    """What equations can use here, from a private session on one curve of the first value."""
    key = json.dumps([str(s.path), s.version, s.spec["values"][0], s.spec["complex"]])
    with _lock:
        if key in _names:
            return _names[key]
    names = None
    spec = next(iter(s.spec["values"]))
    axes = _whole(s.data.values[spec], s.spec) or list(s.data.values[spec].axes)
    if axes:
        from ..explore import ExploreError, ExploreSession

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", rnd.RenderWarning)
                ws = ExploreSession(Path(s.path), s.version, {"kind": "curve", "values": [spec], "x": axes[0], "series": "none",
                                                              "complex": s.spec["complex"], "index": s.spec["index"]},
                                    s.style, 200, 150, 1.0, saved_view=False, bare=True)
            try:
                names = ws.ops_info().get("names")
            finally:
                ws.close()
        except (ExploreError, ValueError):               # no legend then; the equations still work
            names = None
    with _lock:
        _names[key] = names
        while len(_names) > KEEP:
            _names.popitem(last=False)
    return names


def _column(label: str) -> str:
    return "count_" + "".join(c if c.isalnum() else "_" for c in label).strip("_") if label else "count"


def _which_numbers(s: Any, m: hist.HistModel) -> str:
    """For a saved table: which numbers were counted, and how."""
    parts = []
    for a in s.spec["all"]:
        parts.append(f"all of {s.data.axes[a].label or a}")
    for sl in s.spec["slices"]:
        parts.append(f"{sl['label'] or sl['axis']} at step {sl['index']}")
    if s.spec["color"] != "none":
        parts.append(f"a column per step of {s.data.axes[s.spec['color']].label or s.spec['color']}")
    bins = s.spec["options"]["bins"]
    parts.append(f"{m.edges.size - 1} bins" + (" (auto)" if bins == "auto" else ""))
    if m.left_out:
        parts.append(f"{m.left_out} numbers not finite: not counted")
    return "counted: " + ", ".join(parts)


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
        settings = getattr(s, "settings", None) or {}
        counted, job = get(s, {} if refusal(settings) else settings)
        s.crange_info = job.info() if job else None
        s.hist_counted = counted
        return hist.prepare(s.data, s.spec, s.style, big=_shown(s, counted, job))

    def setup(self) -> None:
        s = self.s
        self.drawn = hist.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style, quiet=True)
        self.showing = (id(s.model), s.ax.get_yscale() == "log")

    def apply(self, settings: Dict[str, Any], chosen: Optional[set], clim: Any) -> None:
        from ..explore import ExploreError

        s = self.s
        why = refusal(settings)
        if why:
            raise ExploreError(why)
        counted, job = get(s, settings)
        s.crange_info = job.info() if job else None
        s.hist_ops = getattr(counted, "ops", None) or (job.ops if job else None)
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

    def _bin(self, x: float) -> int:
        """The bin at x: the nearest one outside the edges; the top edge is in the last bin."""
        edges = self.s.model.edges
        return int(np.clip(np.searchsorted(edges, x, side="right") - 1, 0, edges.size - 2))

    def _rows(self, first: int, last: int) -> List[Dict[str, Any]]:
        """Each series' count and fraction in bins `first` to `last`, both included."""
        rows = []
        for s in self.s.model.series:
            total, n = int(s.counts.sum()), int(s.counts[first:last + 1].sum())
            rows.append({"label": s.label, "count": n, "fraction": n / total if total else None})
        return rows

    def read(self, cursor: Dict[str, Any], kind: str, geo: Any) -> Optional[Dict[str, Any]]:
        from ..reading import _check_point

        m = self.s.model
        x, _ = _check_point(cursor)
        i = int(np.clip(self._bin(x) + int((cursor.get("step") or (0, 0))[0]), 0, m.edges.size - 2))
        lo, hi = float(m.edges[i]), float(m.edges[i + 1])
        top = max(float(hist.heights(m, s)[i]) for s in m.series)
        return {"x": (lo + hi) / 2, "y": top, "free": False, "index": {"bin": i},
                "items": [{"role": "x", "name": "bin", "label": m.label, "unit": m.unit, "value": (lo + hi) / 2 / m.xf}],
                "bin": {"lo": lo / m.xf, "hi": hi / m.xf, "unit": m.unit, "rows": self._rows(i, i)}}

    def read_all(self, cursors: List[Any], kind: str, geo: Any) -> Dict[str, Any]:
        if len(cursors) < 2 or None in cursors:
            return {}
        a, b = sorted(c["index"]["bin"] for c in cursors)
        return {"between": {"rows": self._rows(a, b)}}

    def room(self, cursor: Dict[str, Any]) -> List[Tuple[int, int]]:
        i, last = self._bin(float(cursor["x"])), self.s.model.edges.size - 2
        return [(-i, last - i), (0, 0)]

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
        # panels share x when they count the same thing in the same unit; the counts are their own
        return {"crange": self.s.crange_info, "sync": {"x": self.s.ax.get_xlabel(), "y": f"counts of {self.s.id}"}}

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> tables.Table:
        """What is shown: each bin's low and high edge (stored units), a count column per series."""
        from ..explore import ExploreError

        s = self.s
        m = s.model
        info = s.crange_info
        if info:
            raise ExploreError("the histogram is still being counted: save it when the count is done" if info["state"] == "working"
                               else info["error"])
        low, high = m.edges[:-1] / m.xf, m.edges[1:] / m.xf
        names = [_column(c.label) for c in m.series]
        columns: List[Tuple[tables.Column, tables.Rows]] = [
            (tables.Column("bin_high", f"{m.label}, bin high", m.unit), tables.Rows(high))]
        columns += [(tables.Column(n, f"Count: {c.label}" if len(m.series) > 1 else "Count"), tables.Rows(c.counts.astype(float)))
                    for n, c in zip(names, m.series)]
        t = tables.Table(x=low, x_col=tables.Column("bin_low", f"{m.label}, bin low", m.unit), values=columns)
        if view is not None:
            lo, hi = view["xlim"]
            t.points = np.flatnonzero((m.edges[1:] > lo) & (m.edges[:-1] < hi))
        t.comments = tables._comments(s.data, s.spec, "shown", False) + [_which_numbers(s, m)]
        return t

    def ops_info(self) -> Dict[str, Any]:
        """As the session's: from the private session that ran them, or the plain plot's names."""
        s = self.s
        ops = s.ops_list
        done = getattr(s, "hist_ops", None)
        if done is not None and len(done["notes"]) == len(ops):
            return done
        return {"notes": [None if op["on"] else "off" for op in ops], "applied": 0, "equations": {},
                "names": names_for_equations(s)}


INTERACTION = Histogram
