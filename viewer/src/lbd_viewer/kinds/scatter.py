"""A scatter plot in an Explore session: markers, or above `DENSITY_ABOVE` points the number of
points in each pixel, counted again for each view so that zooming stays sharp.

Points too many for memory aren't held at all: a first job finds their ends (the model has no points,
only labels and units), then each view is counted into its pixels from the file, part by part, in the
background, with `crange.py`'s workers. Results are kept per view; `meta["crange"]` says how far.
"""

import json
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import lbd
from lbd.plot import render as rnd
from lbd.plot import scatter as sc
from lbd.plot import tables
from lbd.plot.histogram import count_bins
from lbd.plot.render import position_text

from .. import crange, memory
from . import Interaction
from .histogram import block_size

BYTES_PER_POINT = 48      # x, y and a stored index per dimension, about
FILE_SIDE_BINS = 64       # the histograms beside a plot counted from the file: their bins come before the numbers
KEEP = 16                 # results kept: each is the picture's pixels

_lock = threading.Lock()
_results: "OrderedDict[str, Any]" = OrderedDict()
_jobs: Dict[str, crange.Job] = {}


def too_many(s: Any) -> bool:
    """Whether the points shown can't be held: values read by part, and more points than there is room for."""
    names = [n for n in rnd.needed_values(s.data, s.spec) if n in s.data.values]
    if not any(isinstance(s.data.values[n].data, memory.Cached) for n in names):
        return False
    return _points_in(s) * BYTES_PER_POINT > memory.shared().memory.room()


def _key(s: Any, *more: Any) -> str:
    spec = {k: s.spec.get(k) for k in ("values", "complex", "x", "color", "all", "index")}
    return json.dumps([str(Path(s.path).resolve()), s.version, spec, *more], sort_keys=True, default=str)


def _start(key: str, s: Any, work: Callable[[Any, crange.Job], Any], total: int, grow: bool) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """The result kept under `key`, or (None, how far it is): `work(d, job)` runs in the background."""
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key], None
        job = _jobs.get(key)
        if job is None:
            job = _jobs[key] = crange.Job(total)
            threading.Thread(target=_run, args=(key, job, s.path, work), daemon=True, name="lbd-scatter").start()
    return None, {**job.info(), "from": "scatter", "grow": grow}


def _run(key: str, job: crange.Job, path: Any, work: Callable[[Any, crange.Job], Any]) -> None:
    try:
        with crange._running:
            if job.cancelled:
                return
            d = rnd.flat(lbd.open(path, hold=False))
            try:
                result = work(d, job)
            finally:
                d.close()
        if job.cancelled:
            return
        with _lock:
            _results[key] = result
            _results.move_to_end(key)
            while len(_results) > KEEP:
                _results.popitem(last=False)
            _jobs.pop(key, None)
    except Exception as e:                            # said in the panel; nothing is drawn as if complete
        job.error = f"the points couldn't be counted ({e})"


def cancel_all() -> None:
    """Stop every count (tests; the server's end): `crange.cancel_all` comes here too."""
    with _lock:
        for job in _jobs.values():
            job.cancelled = True


def forget() -> None:
    """Drop every kept result (tests)."""
    cancel_all()
    with _lock:
        _results.clear()
        _jobs.clear()


crange.others.append(sys.modules[__name__])


def _span_work(spec: Dict[str, Any]) -> Callable[[Any, crange.Job], sc.Span]:
    def work(d: Any, job: crange.Job) -> sc.Span:
        ends = {"x": [np.inf, -np.inf], "y": [np.inf, -np.inf], "c": [np.inf, -np.inf]}
        for _, x, y, _, c in sc.iter_points(d, spec, block_size()):
            if job.cancelled:
                break
            for name, numbers in (("x", x), ("y", y), ("c", c)):
                good = numbers[np.isfinite(numbers)] if numbers is not None else ()
                if len(good):
                    ends[name] = [min(ends[name][0], float(good.min())), max(ends[name][1], float(good.max()))]
            job.done += x.size
        return sc.Span(*[tuple(e) if np.isfinite(e[0]) else (0.0, 1.0) for e in (ends["x"], ends["y"], ends["c"])])
    return work


def _count_work(spec: Dict[str, Any], m: sc.ScatterModel, xlim: Any, ylim: Any, w: int, h: int, scales: Tuple[str, str],
                colours: List[str]) -> Callable[[Any, crange.Job], sc.Density]:
    """Every point in this view into its pixel, as `sc.density`, from the file."""
    groups = sc.groups_of(m, colours)
    per = len(m.groups) if m.groups is not None else 1
    x_edges, y_edges = sc.side_edges(xlim, scales[0], FILE_SIDE_BINS), sc.side_edges(ylim, scales[1], FILE_SIDE_BINS)

    def work(d: Any, job: crange.Job) -> sc.Density:
        counts = [np.zeros(w * h, dtype=np.int64) for _ in groups]
        x_side = [np.zeros(FILE_SIDE_BINS, dtype=np.int64) for _ in groups]
        y_side = [np.zeros(FILE_SIDE_BINS, dtype=np.int64) for _ in groups]
        sums = np.zeros(w * h) if m.cvals is not None else None
        for k, x, y, step, number in sc.iter_points(d, spec, block_size()):
            if job.cancelled:
                break
            job.done += x.size
            ix, iy = sc._pixel(x * m.xf, xlim, w, scales[0]), sc._pixel(y * m.yf, ylim, h, scales[1])
            keep = (ix >= 0) & (iy >= 0)
            where = iy[keep] * w + ix[keep]
            xv, yv = x[keep] * m.xf, y[keep] * m.yf
            steps = step[keep] if m.groups is not None else np.zeros(where.size, dtype=np.int64)
            for g in range(per):
                mine = steps == g
                counts[k * per + g] += np.bincount(where[mine], minlength=w * h)
                x_side[k * per + g] += count_bins(xv[mine], x_edges)[1]
                y_side[k * per + g] += count_bins(yv[mine], y_edges)[1]
            if sums is not None:
                c = number[keep] * m.cf
                good = np.isfinite(c)
                sums += np.bincount(where[good], weights=c[good], minlength=w * h)
        shaped = [c.reshape(h, w) for c in counts]
        sides = {"x": {"edges": x_edges, "counts": x_side}, "y": {"edges": y_edges, "counts": y_side},
                 "labels": [g[3] for g in groups], "colours": [g[2] for g in groups]}
        return sc.Density(shaped, [g[2] for g in groups], None if sums is None else sums.reshape(h, w),
                          sc.counted_note(shaped), sides)
    return work


def _points_in(s: Any) -> int:
    total = 0
    for name in s.spec["values"]:
        v = s.data.values[name]
        fixed = sc._fixed(v, s.spec)
        total += int(np.prod([n for a, n in zip(v.axes, v.shape) if a not in fixed], dtype=np.int64))
    return total


class Scatter(Interaction):
    name = kind = "scatter"
    model = sc.ScatterModel
    cursor_types = ("cross",)
    strips = "histograms"

    def __init__(self, session: Any):
        super().__init__(session)
        self.sides: Optional[Dict[str, Any]] = None          # of the points in the last picture's view
        self.image: Any = None        # the density picture; None: markers
        self.bar: Any = None          # its "Points per pixel" colour bar

    @classmethod
    def prepare(cls, s: Any) -> sc.ScatterModel:
        s.scatter_span = None
        if not too_many(s):
            s.crange_info = None
            return sc.prepare_scatter(s.data, s.spec, s.style, whole_span=True)
        return cls._prepare_big(s)

    @classmethod
    def _prepare_big(cls, s: Any) -> sc.ScatterModel:
        span, s.crange_info = _start(_key(s, "ends"), s, _span_work(dict(s.spec)), _points_in(s), True)
        s.scatter_span = span
        return sc.prepare_scatter(s.data, s.spec, s.style, big=span or sc.Span())

    def _big(self) -> bool:
        """Points too many to hold: the model has none."""
        return hasattr(self.s, "scatter_span") and not self.s.model.series[0][0].size and too_many(self.s)

    def _points(self) -> int:
        return sum(x.size for x, _, _ in self.s.model.series)

    # -- operations on the points (16.8): Rotation and Auto-rotate turn the I/Q pair, Subtract the
    # mean moves each axis by its mean; the strips beside follow the changed points

    operations = "points"
    TURNS = ("rotation", "auto_rotate")

    def _why_not(self, op: Dict[str, Any]) -> Optional[str]:
        if self._big():
            return "not applied: these points are too many to hold, so they can't be changed (show fewer)"
        if op["op"] in self.TURNS and self.s.spec.get("complex") != "iq":
            return "not applied: rotation turns the I/Q plane (Complex values: I/Q plane)"
        return None

    def apply_ops(self, ops: List[Dict[str, Any]], eqs: Dict[str, str]) -> bool:
        """Run the operations on the points; True when the figure was set up again."""
        from .. import operations as ops_mod
        from ..explore import ExploreError

        s = self.s
        if eqs:
            raise ExploreError("Equations aren't available on a scatter plot")
        key = json.dumps(ops)
        if key == s.ops_key:
            return False
        s.ops_key, s.ops_list = None, ops
        model, notes, applied = s.raw_model, [], 0
        for op in ops:
            if not op["on"]:
                notes.append("off")
                continue
            why = self._why_not(op)
            if why:
                notes.append(why)
                continue
            model = turned(model, op) if op["op"] in self.TURNS else less_mean(model)
            notes.append(None)
            applied += 1
        s.ops_result, s.ops_shown = ops_mod.Result(None, notes, applied), None
        s.ops_key = key
        if model is s.model:
            return False
        s.model = model
        s._build()
        return True

    def calculate(self, what: str, index: int) -> Dict[str, Any]:
        """Rotation's Calculate: the angle that lays the shown points' spread onto the real axis."""
        from .. import operations as ops_mod
        from ..explore import ExploreError

        m = self.s.raw_model
        if what != "rotation" or self.s.spec.get("complex") != "iq" or self._big():
            raise ExploreError("Calculate works on the I/Q plane's points here: type the angle instead")
        z = np.concatenate([x / m.xf + 1j * y / m.yf for x, y, _ in m.series])
        return {"value": -float(np.degrees(ops_mod._principal_angle(z))), "unit": "°"}

    def setup(self) -> None:
        s = self.s
        spec = {**s.spec, "options": {**(s.spec.get("options") or {}), "sides": False}}    # (here: the strips)
        if self._points() > sc.DENSITY_ABOVE or self._big():
            self.image, self.bar = sc.draw_scatter(s.fig, s.ax, s.model, s.data, spec, s.style, image=np.zeros((2, 2, 4)))
        else:
            sc.draw_scatter(s.fig, s.ax, s.model, s.data, spec, s.style)
        s.ax.set_aspect("auto")                          # equal axes: `frame` widens the view itself

    def lay_out(self) -> None:
        s = self.s
        if s.bare:                                       # only the data: no colour bar beside it
            for extra in s.fig.axes[1:]:
                extra.remove()
        s._lay_out()

    def apply(self, settings: Dict[str, Any], chosen: Optional[set], clim: Any) -> None:
        s = self.s
        if self._big() and s.scatter_span is None:       # its ends may be known by now
            m = self._prepare_big(s)
            if s.scatter_span is not None:
                s.model = s.base_model = s.raw_model = m
                s.ax.set_xlabel(m.x_label)
                s.ax.set_ylabel(m.y_label)

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        s = self.s
        m = s.model
        xlog, ylog = s.ax.get_xscale() == "log", s.ax.get_yscale() == "log"
        if self._big():
            span = s.scatter_span or sc.Span()
            return (s._padded(tuple(v * m.xf for v in span.x), xlog), s._padded(tuple(v * m.yf for v in span.y), ylog))
        x = s._padded(s._range([p[0] for p in m.series], xlog), xlog)
        y = s._padded(s._range([p[1] for p in m.series], ylog), ylog)
        if m.ylim and None not in m.ylim and not ylog:
            y = tuple(m.ylim)
        return x, y

    def picture(self, pxe: np.ndarray, pye: np.ndarray, stat: str, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        s = self.s
        scales = (s.ax.get_xscale(), s.ax.get_yscale())
        xlim, ylim = (float(pxe[0]), float(pxe[-1])), (float(pye[0]), float(pye[-1]))
        colours = s.style.figure.axes.colors
        if not self._big():
            self.sides = sc.sides(s.model, xlim, ylim, scales, colours)
        if self.image is None:
            return "every point shown", False
        if self._big():
            if s.scatter_span is None or draft:          # (while moving: the last picture, stretched)
                return "counting the points…", True
            found, s.crange_info = _start(_key(s, xlim, ylim, w, h, scales), s,
                                          _count_work(dict(s.spec), s.model, xlim, ylim, w, h, scales, colours), _points_in(s), False)
            if found is None:
                return "counting the points in this view…", True
            self.sides = found.sides
        else:
            found = sc.density(s.model, xlim, ylim, w, h, scales, colours)
        self.image.set_data(sc.density_image(s.model, found))
        if self.bar is not None and s.model.cvals is None:
            self.bar.set_clim(1, max(int(found.total.max()), 2))
        return found.note, True

    def _nearest(self, x: float, y: float, view: Dict[str, Any], size: Sequence[int]) -> Optional[Tuple[int, int]]:
        """(series, point) of the point in view nearest (x, y) in pixels: in the numbers, not the
        picture, so it is found above the limit too."""
        from ..reading import nearest_point

        xlo, xhi = sorted(view["xlim"])
        ylo, yhi = sorted(view["ylim"])
        best: Optional[Tuple[float, int, int]] = None
        for k, (xs, ys, _) in enumerate(self.s.model.series):
            with np.errstate(invalid="ignore"):
                seen = np.flatnonzero((xs >= xlo) & (xs <= xhi) & (ys >= ylo) & (ys <= yhi))
            i = nearest_point(xs[seen], ys[seen], x, y, view, size)
            if i is None:
                continue
            i = int(seen[i])
            far = self._pixels_away(xs[i], ys[i], x, y, view, size)
            if best is None or far < best[0]:
                best = (far, k, i)
        return None if best is None else (best[1], best[2])

    @staticmethod
    def _pixels_away(px: float, py: float, x: float, y: float, view: Dict[str, Any], size: Sequence[int]) -> float:
        from ..reading import _pixels

        a = [_pixels(np.array([v, c], dtype=float), lim, view.get(scale, "linear"), n)
             for v, c, lim, scale, n in ((px, x, view["xlim"], "xscale", size[0]), (py, y, view["ylim"], "yscale", size[1]))]
        return float((a[0][0] - a[0][1]) ** 2 + (a[1][0] - a[1][1]) ** 2)

    def _colour_item(self, k: int, i: int) -> Optional[Dict[str, Any]]:
        s = self.s
        m = s.model
        c = s.spec.get("color")
        if m.groups is not None:
            step = int(m.index[k][c][i])
            axis = s.data.axes[c]
            return {"role": "series", "name": c, "label": axis.label or c, "unit": axis.unit, "index": step,
                    "value": float(np.asarray(axis.data, dtype=float)[step]), "text": position_text(axis, step)}
        if m.cvals is None:
            return None
        v = float(m.cvals[i])
        return {"role": "z", "name": c, "label": m.c_text[0], "unit": m.c_text[1],
                "value": v / m.cf if np.isfinite(v) else None}

    def read(self, cursor: Dict[str, Any], kind: str, geo: Any) -> Optional[Dict[str, Any]]:
        from ..reading import _check_point, _num

        s = self.s
        m = s.model
        if self._big():
            return None
        x, y = _check_point(cursor)
        xlim, ylim, w, h, scales = geo
        view = {"xlim": xlim, "ylim": ylim, "xscale": scales[0], "yscale": scales[1]}
        found = self._nearest(x, y, view, (w, h))
        if found is None:
            return None
        k, i = found
        xs, ys, label = m.series[k]
        px, py = float(xs[i]), float(ys[i])
        items = [{"role": "x", "name": m.x_text[0], "label": m.x_text[0], "unit": m.x_text[1], "value": _num(px / m.xf)},
                 {"role": "y", "name": m.y_text[0], "label": label if len(m.series) > 1 else m.y_text[0], "unit": m.y_text[1],
                  "value": _num(py / m.yf)}]
        colour = self._colour_item(k, i)
        if colour is not None:
            items.append(colour)
        free = bool(cursor.get("free"))
        return {"x": x if free else px, "y": y if free else py, "free": free, "items": items,
                "index": {a: int(m.index[k][a][i]) for a in s.data.values[s.spec["values"][k]].axes}}

    def room(self, cursor: Dict[str, Any]) -> List[Tuple[int, int]]:
        return [(0, 0), (0, 0)]                          # no next point between scattered points

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> tables.Table:
        """The points shown: x, each value, the colour, each point's stored index."""
        from ..explore import ExploreError

        s = self.s
        m = s.model
        if self._big():                                   # read from the file part by part when written (16.9)
            if self.s.ops_result is not None and self.s.ops_result.applied:
                raise ExploreError("these points are too many to hold, so the file's are saved: turn the operations off")
            return PointsTable.of(s, view)
        x = m.series[0][0] / m.xf
        same = [p for p in m.series if p[0].size == x.size]
        columns: List[Tuple[tables.Column, tables.Rows]] = []
        for n, (_, y, label) in enumerate(same):
            name = s.spec["values"][n]
            columns.append((tables.Column(name, label, m.y_text[1]), tables.Rows(y / m.yf)))
        if m.cvals is not None:
            columns.append((tables.Column("colour", m.c_text[0], m.c_text[1]), tables.Rows(m.cvals / m.cf)))
        for axis in s.data.values[s.spec["values"][0]].axes:
            columns.append((tables.Column(f"index_{axis}", f"Stored index of {axis}"), tables.Rows(m.index[0][axis].astype(float))))
        t = tables.Table(x=x, x_col=tables.Column("x", m.x_text[0], m.x_text[1]), values=columns)
        if view is not None:
            ys = m.series[0][1]
            (xlo, xhi), (ylo, yhi) = sorted(view["xlim"]), sorted(view["ylim"])
            xs = m.series[0][0]
            t.points = np.flatnonzero((xs >= xlo) & (xs <= xhi) & (ys >= ylo) & (ys <= yhi))
        t.comments = tables._comments(s.data, s.spec, "shown", False)
        return t

    def has_positive(self, which: str) -> bool:
        k = 0 if which == "horizontal" else 1
        with np.errstate(invalid="ignore"):
            return any(bool(np.any(np.isfinite(p[k]) & (p[k] > 0))) for p in self.s.model.series)

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        s = self.s
        series = s.model.series
        if self._big():
            info = s.crange_info or {}
            return ["Cursors can't choose a point here: these points are too many to hold in memory. Make some axes "
                    "sliders to read points."], info.get("error")
        notes: List[str] = []
        ok = [np.isfinite(x) & np.isfinite(y) for x, y, _ in series]
        empty = None if any(o.any() for o in ok) else s._why_empty("point")
        for k, which, name in ((0, s.ax.get_xscale(), "horizontal"), (1, s.ax.get_yscale(), "vertical")):
            with np.errstate(invalid="ignore"):
                n = sum(int(((p[k] <= 0) & o).sum()) for p, o in zip(series, ok)) if which == "log" else 0
            if n:
                notes.append(f"{n} point{'s' * (n != 1)} ≤ 0 aren't shown on the log {name} axis.")
        return notes, empty

    def meta(self) -> Dict[str, Any]:
        m = self.s.model
        out: Dict[str, Any] = super().meta()
        if self._big():
            out["crange"] = self.s.crange_info
        if self.sides is not None:
            out["sides"] = {
                "labels": self.sides["labels"], "colours": self.sides["colours"],
                **{a: {"edges": [float(e) for e in self.sides[a]["edges"]], "counts": [c.tolist() for c in self.sides[a]["counts"]],
                       "label": text[0], "unit": text[1], "factor": f}
                   for a, text, f in (("x", m.x_text, m.xf), ("y", m.y_text, m.yf))}}
        return out


INTERACTION = Scatter


def turned(m: sc.ScatterModel, op: Dict[str, Any]) -> sc.ScatterModel:
    """The I/Q points turned: by `phi` degrees (Rotation), or so that their spread lies on the real
    axis (Auto-rotate: all shown points together)."""
    from dataclasses import replace

    from .. import operations as ops_mod

    z = [x / m.xf + 1j * y / m.yf for x, y, _ in m.series]
    if op["op"] == "rotation":
        phi = np.radians(float(op.get("phi", 0.0)))
    else:
        both = np.concatenate(z) if z else np.zeros(0, complex)
        phi = -ops_mod._principal_angle(both[np.isfinite(both)])
    turn = np.exp(1j * phi)
    return replace(m, series=[((w * turn).real * m.xf, (w * turn).imag * m.yf, label) for w, (_, _, label) in zip(z, m.series)],
                   whole=None)


def less_mean(m: sc.ScatterModel) -> sc.ScatterModel:
    """Each axis minus the mean of all shown points on it."""
    from dataclasses import replace

    xs = np.concatenate([x for x, _, _ in m.series]) if m.series else np.zeros(0)
    ys = np.concatenate([y for _, y, _ in m.series]) if m.series else np.zeros(0)
    mx, my = (float(np.nanmean(v)) if v.size else 0.0 for v in (xs, ys))
    return replace(m, series=[(x - mx, y - my, label) for x, y, label in m.series], whole=None)


class PointsTable(tables.Table):
    """A scatter plot's points too many to hold, as a table (16.9): nothing is read until it is
    written, then the file is read block by block (`sc.iter_points`), so Save as CSV works for
    any size. One row per point: x, the value (and which value, when several), the colour; in
    the stored units, as the plot's other tables. The points' stored indices aren't written:
    there is no room to hold them. `x` is a list, so the table never joins another panel's."""

    @classmethod
    def of(cls, s: Any, view: Optional[Dict[str, Any]]) -> "PointsTable":
        m = s.model
        several = len(s.spec["values"]) > 1
        cols = [(tables.Column("value_name", "Which value"), tables.Rows(np.zeros((1, 0))))] if several else []
        cols.append((tables.Column("y", m.y_text[0], m.y_text[1]), tables.Rows(np.zeros((1, 0)))))
        if s.spec.get("color") not in (None, "none"):
            cols.append((tables.Column("colour", m.c_text[0], m.c_text[1]), tables.Rows(np.zeros((1, 0)))))
        t = cls(x=[], x_col=tables.Column("x", m.x_text[0], m.x_text[1]), values=cols)
        t.session, t.view, t.several = s, view, several
        t.colour = any(c.name == "colour" for c, _ in cols)
        t.comments = tables._comments(s.data, s.spec, "shown", False) + [
            "every point, read from the file part by part (too many to hold); no stored indices"]
        return t

    def _blocks(self):
        """The rows, a block at a time: an array with one row per point (value index first)."""
        s, m = self.session, self.session.model
        lim = None
        if self.view is not None:
            (xlo, xhi), (ylo, yhi) = sorted(self.view["xlim"]), sorted(self.view["ylim"])
            lim = (xlo / m.xf, xhi / m.xf, ylo / m.yf, yhi / m.yf)
        for k, x, y, step, number in sc.iter_points(s.data, s.spec, block_size()):
            keep = np.ones(x.size, dtype=bool) if lim is None else (x >= lim[0]) & (x <= lim[1]) & (y >= lim[2]) & (y <= lim[3])
            cols = ([np.full(int(keep.sum()), float(k))] if self.several else []) + [x[keep], y[keep]]
            if self.colour:
                c = number if number is not None else (step if step is not None else np.full(x.size, np.nan))
                cols.append(np.asarray(c, dtype=float)[keep])
            yield np.column_stack(cols) if cols[0].size else np.zeros((0, len(cols)))

    def _total(self) -> int:
        return _points_in(self.session)

    def check_matrix(self) -> None:
        raise ValueError("a scatter plot's points are saved one per row; a table (matrix) needs a grid")

    def estimate(self, layout: str = "rows") -> Dict[str, int]:
        if layout == "matrix":
            self.check_matrix()
        sample = self._sample_text(layout)
        per = (len(sample) / max(sample.count(",") + sample.count("\n"), 1)) if sample else 8
        rows, cols = self._total(), len(self.columns())
        header = sum(len(c) + 3 for c in self.header_lines(layout))
        return {"bytes": int(header + rows * cols * per), "rows": int(rows), "columns": int(cols)}

    def _sample_text(self, layout: str) -> str:
        for block in self._blocks():
            if len(block):
                return tables._lines(block[:400])
        return ""

    def _write_rows(self, f, progress) -> None:
        total, done = max(self._total(), 1), 0
        for block in self._blocks():
            if len(block):
                f.write(tables._lines(block) + "\n")
            done += len(block)
            if progress is not None:
                progress(min(done / total, 1.0))
