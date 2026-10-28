"""Operations on the data the Explore view shows: subtract the mean, normalize, d/dx, smoothing,
between traces, FFT, histogram (and, in step 3 and 4, complex corrections and the I/Q histogram).

They are a viewing tool: the viewer computes them from the full data and remembers the list with
the Explore view in its database, never in the file (docs/viewer/explore.md, "Operations").

The data is a **grid**: traces × points. A curve plot's lines (one per series step) are its
traces, sharing one x; a map's rows are its traces, its vertical axis their coordinate. So an
operation runs **along x** (within each trace or row) or **across traces** (along a map's y,
or across the curves of a series): the same functions serve both. Curves whose x differs per
trace (a value as x) only allow operations along x.

Each operation is a small function from a grid to a grid, NaN-aware, working in stored units
(as plotted: e.g. |S21| in dB); the result knows its label and unit, and whether each shown
point still comes from one stored point (`one_to_one`), so read-outs can name the stored value.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from lbd.plot.units import PREFIXES, axis_label, prefix_scale


@dataclass(frozen=True)
class Quantity:
    """What numbers mean: a label and a unit (stored units, no prefix)."""

    label: str
    unit: str = ""


@dataclass
class Grid:
    """Traces × points, in stored units (as plotted).

    `a` (traces, points); `x` the points' coordinate, shared (points,) or one array per trace
    (`ragged`, a value as x); `t` the traces' coordinate (series values, a map's y) or None."""

    a: np.ndarray
    x: Any
    t: Optional[np.ndarray]
    value: Quantity
    xq: Quantity
    tq: Optional[Quantity]
    ragged: bool = False
    one_to_one: bool = True          # each point is still the stored point at the same indices
    labels: Optional[List[str]] = None   # the traces' names (curves)


class OpError(Exception):
    """An operation that can't apply here; the message says why (shown at its row)."""


class BadOps(ValueError):
    """A list of operations that isn't valid at all (the session answers with ExploreError)."""


# -- the operations ---------------------------------------------------------------------------------

ALONG = ("x", "traces")


def _rows(g: Grid, along: str) -> Tuple[np.ndarray, np.ndarray, bool]:
    """The data as rows to work along, their coordinate, and whether it was transposed."""
    if along == "x":
        return g.a, (g.x if not g.ragged else None), False
    if g.ragged:
        raise OpError("across traces needs one shared horizontal axis (not a value as x)")
    if g.t is None or g.a.shape[0] < 2:
        raise OpError("across traces needs several traces")
    return g.a.T, g.t, True


def _back(g: Grid, rows: np.ndarray, flipped: bool) -> np.ndarray:
    return rows.T if flipped else rows


def _per_row(g: Grid, along: str, fn: Callable[[np.ndarray, Optional[np.ndarray]], np.ndarray]) -> np.ndarray:
    """Apply fn(values, coordinate) to each row along `along` (ragged x: each trace its own)."""
    rows, coord, flipped = _rows(g, along)
    if g.ragged and along == "x":
        return np.array([fn(r, np.asarray(x, dtype=float)) for r, x in zip(rows, g.x)])
    return _back(g, np.array([fn(r, coord) for r in rows]), flipped)


def _axis_q(g: Grid, along: str) -> Quantity:
    return g.xq if along == "x" else g.tq  # type: ignore[return-value]


def subtract_mean(g: Grid, along: str = "x") -> Grid:
    def f(r, _):
        return r - np.nanmean(r) if np.isfinite(r).any() else r
    with np.errstate(invalid="ignore"):
        a = _per_row(g, along, f)
    return replace(g, a=a, value=Quantity(f"{g.value.label} − mean", g.value.unit))


def normalize(g: Grid, along: str = "x") -> Grid:
    def f(r, _):
        if not np.isfinite(r).any():
            return r
        sd = np.nanstd(r)
        return (r - np.nanmean(r)) / sd if sd > 0 else r * np.nan
    with np.errstate(invalid="ignore"):
        a = _per_row(g, along, f)
    return replace(g, a=a, value=Quantity(f"({g.value.label} − mean)/σ", ""))


def derivative(g: Grid, along: str = "x") -> Grid:
    q = _axis_q(g, along)

    def f(r, x):
        out = np.full(r.shape, np.nan)
        ok = np.isfinite(r) & np.isfinite(x)
        if ok.sum() >= 2:
            xs, ys = x[ok], r[ok]
            order = np.argsort(xs, kind="stable")
            if np.any(np.diff(xs[order]) == 0):
                raise OpError(f"d/d{q.label}: '{q.label}' has repeated values")
            d = np.empty(xs.size)
            d[order] = np.gradient(ys[order], xs[order])
            out[ok] = d
        return out
    a = _per_row(g, along, f)
    unit = _ratio_unit(g.value.unit, q.unit)
    return replace(g, a=a, value=Quantity(f"d{g.value.label}/d{_short(q.label)}", unit))


def smooth(g: Grid, along: str = "x", n: int = 5) -> Grid:
    if not isinstance(n, int) or n < 2:
        raise OpError("smoothing needs a whole number of points, 2 or more")

    def f(r, _):
        ok = np.isfinite(r)
        v, c = np.where(ok, r, 0.0), ok.astype(float)
        cv, cc = np.r_[0.0, np.cumsum(v)], np.r_[0.0, np.cumsum(c)]
        lo = np.clip(np.arange(r.size) - n // 2, 0, r.size)
        hi = np.clip(np.arange(r.size) - n // 2 + n, 0, r.size)        # windows shrink at the ends
        with np.errstate(invalid="ignore", divide="ignore"):
            out = (cv[hi] - cv[lo]) / (cc[hi] - cc[lo])
        out[~ok] = np.nan                                                 # gaps stay gaps
        return out
    return replace(g, a=_per_row(g, along, f), value=Quantity(f"{g.value.label} (smoothed over {n})", g.value.unit))


def _first_rows(g: Grid) -> np.ndarray:
    """Indices of the traces that have data (left-out traces are all NaN)."""
    return np.flatnonzero(np.isfinite(g.a).any(axis=1))


def subtract_first(g: Grid, along: str = "traces") -> Grid:
    _rows(g, "traces")
    have = _first_rows(g)
    if not have.size:
        raise OpError("no trace has data")
    return replace(g, a=g.a - g.a[have[0]], value=Quantity(f"{g.value.label} − first", g.value.unit))


def subtract_previous(g: Grid, along: str = "traces") -> Grid:
    _rows(g, "traces")
    out = np.full(g.a.shape, np.nan)
    have = _first_rows(g)
    for prev, k in zip(have[:-1], have[1:]):          # the first shown trace has no previous one
        out[k] = g.a[k] - g.a[prev]
    return replace(g, a=out, value=Quantity(f"{g.value.label} − previous", g.value.unit))


def _reduce(g: Grid, fn, name: str) -> Grid:
    _rows(g, "traces")
    have = _first_rows(g)
    if not have.size:
        raise OpError("no trace has data")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)              # an all-empty column: NaN, as wanted
        row = fn(g.a[have], axis=0)
    return replace(g, a=row[None, :], t=None, tq=None, one_to_one=False,
                   labels=[f"{name} of {have.size} traces"], value=Quantity(f"{name} of {g.value.label}", g.value.unit))


def average(g: Grid, along: str = "traces") -> Grid:
    return _reduce(g, np.nanmean, "average")


def std(g: Grid, along: str = "traces") -> Grid:
    return _reduce(g, np.nanstd, "std")


def fft(g: Grid, along: str = "x") -> Grid:
    """Amplitude spectrum of each row (positive frequencies): 2|rfft|/N, the DC term not doubled,
    so a sine of amplitude A shows a peak of height A. Needs evenly spaced points, no gaps."""
    rows, coord, flipped = _rows(g, along)
    if g.ragged:
        raise OpError("FFT needs one shared horizontal axis (not a value as x)")
    q = _axis_q(g, along)
    x = np.asarray(coord, dtype=float)
    d = np.diff(x)
    if x.size < 4 or not np.all(np.isfinite(d)) or d.mean() == 0 or np.ptp(d) > 1e-6 * abs(d.mean()):
        raise OpError(f"FFT needs evenly spaced '{q.label}' (it isn't)")
    if not np.isfinite(rows[np.isfinite(rows).any(axis=1)]).all():
        raise OpError("FFT needs traces without missing points")
    n = x.size
    spec = np.abs(np.fft.rfft(np.nan_to_num(rows), axis=1)) * 2 / n
    spec[:, 0] /= 2
    spec[~np.isfinite(rows).any(axis=1)] = np.nan                      # left-out traces stay empty
    freq = np.fft.rfftfreq(n, abs(d.mean()))
    fq = Quantity({"s": "Frequency", "Hz": "Time"}.get(q.unit, f"1/{q.label}"), _inverse_unit(q.unit))
    out = replace(g, a=_back(g, spec, flipped), one_to_one=False,
                  value=Quantity(f"FFT of {g.value.label}", g.value.unit))
    return replace(out, x=freq, xq=fq) if along == "x" else replace(out, t=freq, tq=fq)


def histogram(g: Grid, along: str = "x", bins: int = 50) -> Grid:
    """Counts of each trace's values (along x: per trace; across traces: per point column) in
    `bins` bins over the common value range; x becomes the value."""
    if not isinstance(bins, int) or not 2 <= bins <= 10_000:
        raise OpError("a histogram needs 2 to 10000 bins")
    rows, _, flipped = _rows(g, along)
    finite = rows[np.isfinite(rows)]
    if not finite.size:
        raise OpError("no values to count")
    lo, hi = float(finite.min()), float(finite.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    edges = np.linspace(lo, hi, bins + 1)
    counts = np.array([np.histogram(r[np.isfinite(r)], edges)[0] for r in rows], dtype=float)
    counts[~np.isfinite(rows).any(axis=1)] = np.nan
    centres = (edges[:-1] + edges[1:]) / 2
    out = replace(g, a=counts, x=centres, xq=g.value, ragged=False, one_to_one=False,
                  value=Quantity("Counts", ""))
    if flipped:                                         # one histogram per point column: those are the traces now
        out = replace(out, t=np.asarray(g.x, dtype=float), tq=g.xq, labels=None)
    return out


OPS: Dict[str, Tuple[Callable[..., Grid], Tuple[str, ...], Dict[str, Any]]] = {
    # name: (function, allowed "along", parameters with defaults)
    "subtract_mean": (subtract_mean, ALONG, {}),
    "normalize": (normalize, ALONG, {}),
    "derivative": (derivative, ALONG, {}),
    "smooth": (smooth, ALONG, {"n": 5}),
    "subtract_first": (subtract_first, ("traces",), {}),
    "subtract_previous": (subtract_previous, ("traces",), {}),
    "average": (average, ("traces",), {}),
    "std": (std, ("traces",), {}),
    "fft": (fft, ALONG, {}),
    "histogram": (histogram, ALONG, {"bins": 50}),
}


def check(ops: Any) -> List[Dict[str, Any]]:
    """The list as sent by the page, checked: each {op, along?, on?, <parameters>}."""
    if ops is None:
        return []
    if not isinstance(ops, list):
        raise BadOps("operations are a list")
    out = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise BadOps(f"operation {i + 1}: unknown; use one of {', '.join(OPS)}")
        _, alongs, params = OPS[op["op"]]
        along = op.get("along", alongs[0])
        if along not in alongs:
            raise BadOps(f"operation {i + 1} ({op['op']}): along must be one of {', '.join(alongs)}")
        clean = {"op": op["op"], "along": along, "on": op.get("on", True) is not False}
        for k, default in params.items():
            v = op.get(k, default)
            if not isinstance(v, int) or isinstance(v, bool):
                raise BadOps(f"operation {i + 1} ({op['op']}): {k} must be a whole number")
            clean[k] = v
        out.append(clean)
    return out


@dataclass
class Result:
    grid: Grid
    notes: List[Optional[str]]       # per operation: None (applied), or why not
    applied: int                     # how many were applied


def run(g: Grid, ops: Sequence[Dict[str, Any]]) -> Result:
    """Apply the operations that are on, in order. One that can't apply stops the chain there:
    its row says why, the rows after it say they weren't applied, and the result is the grid
    before it (never a silent half-result)."""
    notes: List[Optional[str]] = [None] * len(ops)
    applied = 0
    for i, op in enumerate(ops):
        if not op.get("on", True):
            notes[i] = "off"
            continue
        fn, _, params = OPS[op["op"]]
        try:
            g = fn(g, along=op["along"], **{k: op[k] for k in params})
            applied += 1
        except OpError as e:
            notes[i] = str(e)
            for j in range(i + 1, len(ops)):
                notes[j] = "not applied (an operation above can't apply)"
            break
    return Result(g, notes, applied)


# -- units --------------------------------------------------------------------------------------------

def _short(label: str) -> str:
    """'Frequency' -> 'Frequency'; long labels stay as they are (used in d…/d…)."""
    return label


def _ratio_unit(num: str, den: str) -> str:
    if not den:
        return num
    if not num:
        return f"1/{den}"
    return f"{num}/{den}"


def _inverse_unit(unit: str) -> str:
    return {"s": "Hz", "Hz": "s", "": ""}.get(unit, f"1/{unit}")


def shown(values: np.ndarray, q: Quantity, fmt: str) -> Tuple[float, str, str]:
    """(factor, unit shown, axis label) for numbers in stored units: an SI prefix where the unit
    takes one (Hz, V, s, …), and for a ratio (dB/Hz, V/s) on its denominator, so a derivative
    reads per GHz or per µs like its axis."""
    unit = q.unit
    if "/" in unit and not unit.startswith("1/"):
        num, den = unit.split("/", 1)
        # the denominator's prefix from the size of the numbers: dB/Hz of 3e-9 reads 3 dB/GHz
        f, pre = _den_prefix(values, den)
        return f, f"{num}/{pre}{den}", axis_label(q.label, f"{num}/{pre}{den}", fmt)
    f, u = prefix_scale(values, unit, warn=False) if unit else (1.0, "")
    return f, u, axis_label(q.label, u, fmt)


def _den_prefix(values: np.ndarray, den: str) -> Tuple[float, str]:
    """A prefix p for the denominator, so values per (p den) are between 1 and 1000."""
    from lbd.plot.units import AUTO_UNITS

    finite = np.abs(np.asarray(values, dtype=float))
    finite = finite[np.isfinite(finite) & (finite > 0)]
    if den not in AUTO_UNITS or not finite.size:
        return 1.0, ""
    exp = int(math.floor(math.log10(float(finite.max())) / 3) * 3)      # per unit; per p·unit: × 10^-exp
    best = ""
    for p, e in PREFIXES.items():
        if e == -exp and e % 3 == 0 and p not in ("c", "d", "da", "h"):
            best = p
    if not best and exp != 0:
        return 1.0, ""
    return 10.0 ** -exp, best



# -- from a session's plot to a grid, and back ------------------------------------------------------

@dataclass
class Shown:
    """How an operated grid is drawn: factors (plot units per stored unit) and units shown."""

    value_factor: float
    value_unit: str                  # as shown (with its prefix)
    x_changed: bool                  # the horizontal axis is another quantity now (FFT, histogram)
    t_changed: bool                  # the traces' coordinate too (operations across traces)


def grid_of(s, chosen: Optional[set]) -> Grid:
    """The session's plot before operations (its base model), as a grid in stored units. Traces
    left out of the selection are empty (NaN), so operations across traces skip them."""
    from .reading import _plotted

    m, spec, d = s.base_model, s.spec, s.data
    if s.base_kind == "heatmap":
        xa, ya = d.axes[spec["x"]], d.axes[spec["y"]]
        a = np.array(m.z, dtype=float) / m.zf
        if chosen is not None:
            a[[j for j in range(a.shape[0]) if j not in chosen], :] = np.nan
        label, unit = _plotted(s, spec["values"][0])
        return Grid(a=a, x=m.x / m.xf, t=m.y / m.yf, value=Quantity(label, unit),
                    xq=Quantity(xa.label or xa.name, xa.unit), tq=Quantity(ya.label or ya.name, ya.unit))
    shared = all(x is m.xs[0] for x in m.xs)
    ys = [np.asarray(y, dtype=float) / m.yf for y, _ in m.lines]
    a = np.array(ys) if shared or len({y.size for y in ys}) == 1 else None
    if a is None:
        raise BadOps("these curves have different lengths; operations need traces of one length")
    series = spec.get("series")
    per = len(d.axes[series].data) if series else 1
    if chosen is not None:
        for k in range(a.shape[0]):
            if k % per not in chosen:
                a[k] = np.nan
    one_value = len(spec["values"]) == 1
    t = np.asarray(d.axes[series].data, dtype=float) if series and one_value else None
    tq = Quantity(d.axes[series].label or series, d.axes[series].unit) if t is not None else None
    xname = spec["x"]
    xa = d.values[xname] if xname in d.values else d.axes[xname]
    label, unit = _plotted(s, spec["values"][0])
    x = m.xs[0] / m.xf if shared else [x / m.xf for x in m.xs]
    return Grid(a=a, x=x, t=t, value=Quantity(label, unit), xq=Quantity(xa.label or xa.name, xa.unit), tq=tq,
                ragged=not shared, labels=[lab for _, lab in m.lines])


def model_of(s, base: Grid, g: Grid) -> Tuple[Any, Shown]:
    """The plot model (lbd.plot's CurveModel / MapModel, plot units) that draws grid `g`. Axes the
    operations left alone keep the base model's factor and label (as the style made them)."""
    from matplotlib.colors import Normalize

    from lbd.plot.render import CurveModel, MapModel

    m = s.base_model
    fmt = s.style.axis_style("y").label.unit_format
    x_changed = g.x is not base.x
    t_changed = g.t is not base.t
    vf, vu, vlabel = shown(g.a, g.value, fmt)
    if s.base_kind == "heatmap":
        if x_changed:
            xf, _, xlabel = shown(np.asarray(g.x), g.xq, fmt)
        else:
            xf, xlabel = m.xf, m.x_label
        if t_changed:
            tf, _, tlabel = shown(np.asarray(g.t), g.tq, fmt)
        else:
            tf, tlabel = m.yf, m.y_label
        model = MapModel(x=np.asarray(g.x, dtype=float) * xf, y=np.asarray(g.t, dtype=float) * tf, z=g.a * vf,
                         xf=xf, yf=tf, zf=vf, norm=Normalize(), cmap=m.cmap, x_label=xlabel, y_label=tlabel,
                         z_label=vlabel, x_scale="linear" if x_changed else m.x_scale,
                         y_scale="linear" if t_changed else m.y_scale, auto_axes=[])
        return model, Shown(vf, vu, x_changed, t_changed)
    if x_changed:
        xf, _, xlabel = shown(np.asarray(g.x), g.xq, fmt)
    else:
        xf, xlabel = m.xf, m.x_label
    n = g.a.shape[0]
    if g.ragged:
        xs = [np.asarray(x, dtype=float) * xf for x in g.x]
    else:
        x_plot = np.asarray(g.x, dtype=float) * xf
        xs = [x_plot] * n                              # one array: the lines are reduced together
    labels = g.labels if g.labels and len(g.labels) == n else [lab for _, lab in m.lines][:n]
    if len(labels) < n:                                 # one curve per point column (histogram across traces)
        labels = [f"{base.xq.label} = {v:g}" for v in np.asarray(base.x, dtype=float)[:n]]
    model = CurveModel(xs=xs, lines=[(g.a[k] * vf, labels[k]) for k in range(n)],
                       colors=m.colors if n == len(m.lines) else None, xf=xf, yf=vf, x_label=xlabel,
                       y_label=vlabel, x_scale="linear" if x_changed else m.x_scale,
                       y_scale="linear", ylim=None, series_bar=None, auto_axes=[])
    return model, Shown(vf, vu, x_changed, t_changed)
