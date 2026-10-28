"""Reading values in the Explore view: cursors on the stored data, max / min / peak, the cuts
through a map, the histogram of a map's values, and saving a cut as a file of its own.

Everything here reads the session's full data (explore.py `ExploreSession`), never its picture.
Positions travel in plot units (the axes' unit prefixes applied, as the picture's limits);
read-outs are given as plotted (e.g. |S21| in dB) in the plotted value's own unit, with the
stored indices they come from.

One `cursors` answer holds everything the page draws for one cursor state: the snapped
positions, their read-outs and, for maps, the cuts. The page draws them together, so the cursor,
its numbers and the cuts never disagree (docs/viewer/explore.md, "Reading values").
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

import lbd
from lbd.plot import render as rnd
from lbd.plot.reduce import cell_edges, curve_minmax

from .explore import ExploreError

if TYPE_CHECKING:
    from .explore import ExploreSession

CURSOR_TYPES = ("cross", "vertical", "horizontal")
FIND = ("max", "min", "peak")
TABLE_LIMIT = 2000      # a vertical cursor lists at most this many traces' values
HIST_BINS = 128
AUTO_RANGE = (0.5, 99.5)  # "Auto" colour range: leave out 0.5 % of the cells at each end


# -- pixels of a view (plot units <-> plot-area pixels; x to the right, y up) ---------------------

def _f(scale: str, v):
    return np.log10(v) if scale == "log" else v


def _pixels(v, lim: Sequence[float], scale: str, n: int):
    a, b = _f(scale, lim[0]), _f(scale, lim[1])
    with np.errstate(invalid="ignore", divide="ignore"):
        return (_f(scale, np.asarray(v, dtype=float)) - a) / (b - a) * n


def _edges(lim: Sequence[float], scale: str, n: int) -> np.ndarray:
    """The n + 1 pixel boundaries of a view, in plot units, increasing."""
    a, b = sorted((_f(scale, lim[0]), _f(scale, lim[1])))
    e = np.linspace(a, b, max(n, 1) + 1)
    return 10 ** e if scale == "log" else e


def _num(v) -> Optional[float]:
    v = float(v)
    return v if np.isfinite(v) else None


# -- what is plotted ---------------------------------------------------------------------------------

def _plotted(s: "ExploreSession", name: str) -> Tuple[str, str]:
    """The plotted value's label and unit (after the complex mode, e.g. |S21| in dB)."""
    v = s.data.values[name]
    probe = np.array([1 + 1j]) if np.iscomplexobj(v.data) else np.array([1.0])
    _, label, unit = rnd.apply_complex(probe, v.label or v.name, v.unit, s.spec["complex"])
    return label, unit


def _operated(s: "ExploreSession") -> bool:
    """Operations are on and change what is shown (explore.py `_apply_ops`; complex corrections
    alone count too: their result is shown, the file's value is the stored one)."""
    return s.ops_result is not None and s.ops_result.applied > 0 and s.ops_shown is not None


def _value_item(s: "ExploreSession", role: str, name: str, plot_value) -> Dict[str, Any]:
    """A shown value read out, in its own unit; after operations as they made it (a ratio such as
    dB/GHz as shown, so it reads like the axis)."""
    factor = s.model.zf if s.kind == "heatmap" else s.model.yf
    if _operated(s):
        q, sh = s.ops_result.grid.value, s.ops_shown
        if "/" in sh.value_unit:
            return {"role": role, "name": name, "label": q.label, "unit": sh.value_unit, "value": _num(plot_value)}
        return {"role": role, "name": name, "label": q.label, "unit": q.unit, "value": _num(plot_value / factor)}
    label, unit = _plotted(s, name)
    return {"role": role, "name": name, "label": label, "unit": unit, "value": _num(plot_value / factor)}


def _model_axis_item(s: "ExploreSession", role: str, q, plot_value, factor: float, i: int) -> Dict[str, Any]:
    """An axis the operations made (FFT: frequency; histogram: the value): no stored axis."""
    return {"role": role, "name": q.label, "label": q.label, "unit": q.unit, "index": int(i),
            "value": _num(plot_value / factor)}


def _stored(s: "ExploreSession", name: str, base_value, factor: float) -> Optional[Dict[str, Any]]:
    """The stored value behind a shown point (the file's, as plotted) when operations or complex
    corrections changed what is shown and the point is still a stored one; else None."""
    if _operated(s) and not s.ops_result.grid.one_to_one:
        return None
    if not _operated(s) and s.base_model is s.raw_model:
        return None
    label, unit = _plotted(s, name)
    return {"label": label, "unit": unit, "value": _num(base_value / factor)}


def _axis_item(s: "ExploreSession", role: str, axis: str, i: int) -> Dict[str, Any]:
    a = s.data.axes[axis]
    return {"role": role, "name": axis, "label": a.label or axis, "unit": a.unit, "index": int(i),
            "value": _num(np.asarray(a.data, dtype=float)[i])}


def _per_value(s: "ExploreSession") -> int:
    series = s.spec.get("series")
    return len(s.data.axes[series].data) if series else 1


def _trace_value(s: "ExploreSession", k: int) -> str:
    """The plotted value a curve belongs to (lines: per value, one per series step)."""
    vals = s.spec["values"]
    return vals[min(k // _per_value(s), len(vals) - 1)]


def _visible(s: "ExploreSession") -> List[int]:
    return [k for k, v in enumerate(s.visible) if v]


def _selected_rows(s: "ExploreSession") -> Optional[set]:
    sel = (s.settings.get("select") or {}).get(s.spec.get("y"))
    return None if sel is None else set(sel)


def _map_z(s: "ExploreSession") -> np.ndarray:
    """The map as shown: rows left out of the selection are empty."""
    z = s.model.z
    rows = _selected_rows(s)
    if rows is not None:
        z = z.copy()
        z[[j for j in range(z.shape[0]) if j not in rows], :] = np.nan
    return z


def _nearest(arr: np.ndarray, v: float) -> int:
    """Index of the finite entry of arr closest to v (arr may be unsorted)."""
    d = np.abs(np.asarray(arr, dtype=float) - v)
    d[~np.isfinite(d)] = np.inf
    return int(np.argmin(d))


# -- cursors ---------------------------------------------------------------------------------------

def cursors(s: "ExploreSession", items: List[Dict[str, Any]], kind: str, view: Dict[str, Any],
            size: Sequence[int], cuts: bool = True, lines: bool = True) -> Dict[str, Any]:
    """Snap each cursor to the stored data and read it out; with a map, the cuts through cursor 1.

    `items`: per cursor {x, y} in plot units, optionally `trace` (curves: stay on this trace),
    `free` (keep the position: Alt), `step` [along x, along y or traces] in stored points.
    `kind`: cross, vertical or horizontal. `view` {xlim, ylim} and `size` [w, h] are the plot area
    as the page shows it (for the nearest point in pixels and the cuts' pixel columns). `lines`:
    with each curve cursor's trace as last drawn (plot units; None breaks it), to highlight it.
    `factors`: plot units per stored unit, to turn typed stored values into positions."""
    if kind not in CURSOR_TYPES:
        raise ExploreError(f"unknown cursor type {kind!r}; use one of {', '.join(CURSOR_TYPES)}")
    if not 1 <= len(items) <= 2:
        raise ExploreError("there are one or two cursors")
    xlim, ylim = view.get("xlim"), view.get("ylim")
    if not xlim or not ylim:
        xlim, ylim = s.full
    w, h = (max(int(v), 1) for v in size)
    with rnd.RENDER_LOCK:
        s._check_open()
        scales = (s.ax.get_xscale(), s.ax.get_yscale())
    geo = (xlim, ylim, w, h, scales)
    m = s.model
    out: Dict[str, Any] = {"type": kind, "factors": {"x": m.xf, "y": m.yf, "z": getattr(m, "zf", 1.0)}}
    if s.kind == "heatmap":
        out["cursors"] = [_map_cursor(s, c, kind) for c in items]
        first = out["cursors"][0]
        if cuts and first is not None:
            out["cuts"] = _cuts(s, first, kind, geo)
    else:
        out["cursors"] = [_curve_cursor(s, c, kind, geo) for c in items]
        if lines and len(_visible(s)) > 1:          # a single curve needs no highlight: it would only cover it
            for c in out["cursors"]:
                drawn = s._drawn(c["trace"]) if c else None
                if drawn is not None:
                    c["line"] = [[float(a), float(b)] if np.isfinite(a) and np.isfinite(b) else None
                                 for a, b in zip(*drawn)]
    return out


def _check_point(c: Dict[str, Any]) -> Tuple[float, float]:
    try:
        x, y = float(c["x"]), float(c["y"])
    except (KeyError, TypeError, ValueError):
        raise ExploreError("a cursor needs a position: x and y numbers") from None
    if not (np.isfinite(x) and np.isfinite(y)):
        raise ExploreError("a cursor's position must be finite numbers")
    return x, y


def _map_cursor(s: "ExploreSession", c: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
    m = s.model
    x, y = _check_point(c)
    i = _clip_cell(m.x, x)
    j = _clip_cell(m.y, y)
    step = c.get("step") or [0, 0]
    i = int(np.clip(i + int(step[0]), 0, len(m.x) - 1))
    j = int(np.clip(j + int(step[1]), 0, len(m.y) - 1))
    free = bool(c.get("free")) and not any(step)
    px = x if free or kind == "horizontal" else float(m.x[i])
    py = y if free or kind == "vertical" else float(m.y[j])
    z = _map_z(s)[j, i]
    name = s.spec["values"][0]
    sh = s.ops_shown if _operated(s) else None
    g = s.ops_result.grid if sh else None
    x_item = (_model_axis_item(s, "x", g.xq, m.x[i], m.xf, i) if sh and sh.x_changed
              else _axis_item(s, "x", s.spec["x"], i))
    y_item = (_model_axis_item(s, "y", g.tq, m.y[j], m.yf, j) if sh and sh.t_changed
              else _axis_item(s, "y", s.spec["y"], j))
    out = {"x": px, "y": py, "free": free, "items": [x_item, y_item, _value_item(s, "z", name, z)],
           "index": {s.spec["x"]: i, s.spec["y"]: j} if not sh or g.one_to_one else {},
           "cell": [float(v) for v in _cell_box(m, i, j)], "at": [i, j]}
    # only for a stored cell: an operation's own cells (an I/Q histogram) have no stored value
    keeps = s.kind == s.base_kind and (not sh or g.one_to_one)
    stored = _stored(s, name, s.raw_model.z[j, i], s.raw_model.zf) if keeps else None
    if stored:
        out["stored"] = stored
    return out


def _clip_cell(centres: np.ndarray, v: float) -> int:
    """The cell holding v, or the nearest cell at the map's edge."""
    e = cell_edges(centres)
    inc = e[0] < e[-1]
    es = e if inc else e[::-1]
    k = int(np.clip(np.searchsorted(es, v, side="right") - 1, 0, len(centres) - 1))
    return k if inc else len(centres) - 1 - k


def _cell_box(m, i: int, j: int) -> Tuple[float, float, float, float]:
    xe, ye = cell_edges(m.x), cell_edges(m.y)
    x0, x1 = sorted((xe[i], xe[i + 1]))
    y0, y1 = sorted((ye[j], ye[j + 1]))
    return x0, y0, x1, y1


def _curve_cursor(s: "ExploreSession", c: Dict[str, Any], kind: str, geo) -> Optional[Dict[str, Any]]:
    m = s.model
    x, y = _check_point(c)
    shown = _visible(s)
    if not shown:
        return None
    step = c.get("step") or [0, 0]
    k = c.get("trace")
    if not isinstance(k, int) or k not in shown:
        k = None
    if k is not None and step[1]:                    # the next / previous visible trace
        pos = shown.index(k)
        k = shown[int(np.clip(pos - int(step[1]), 0, len(shown) - 1))]   # up the list: earlier traces
    if k is None:
        k, i = _nearest_point(s, x, y, shown, geo)
        if k is None:
            return None
    else:
        xs = np.asarray(m.xs[k], dtype=float)
        ys = np.asarray(m.lines[k][0], dtype=float)
        ok = np.isfinite(ys) & np.isfinite(xs)
        if not ok.any():
            return None
        d = np.abs(xs - x)
        d[~ok] = np.inf
        i = int(np.argmin(d))
    if step[0]:
        i = _step_point(m, k, i, int(step[0]))
    free = bool(c.get("free")) and not any(step)
    xs_k, ys_k = m.xs[k], m.lines[k][0]
    px = x if free else float(xs_k[i])
    py = y if free or kind == "horizontal" else _num(ys_k[i])
    if py is None:
        py = y
    name = _trace_value(s, k)
    items = [_curve_x_item(s, k, i), _value_item(s, "y", name, ys_k[i])]
    series = s.spec.get("series")
    index = {s.spec.get("along", s.spec["x"]): int(i)}
    same_traces = s.base_kind == "curve" and len(m.lines) == len(s.base_model.lines)   # the file's traces still
    if series and same_traces:
        j = k % _per_value(s)
        items.append(_axis_item(s, "series", series, j))
        index[series] = int(j)
    one_to_one = not _operated(s) or s.ops_result.grid.one_to_one
    out = {"x": px, "y": py, "free": free, "trace": int(k), "label": m.lines[k][1],
           "index": index if one_to_one else {}, "items": items}
    if one_to_one and same_traces:
        stored = _stored(s, name, s.raw_model.lines[k][0][i], s.raw_model.yf)
        if stored:
            out["stored"] = stored
    if kind == "vertical":
        out["table"] = _table(s, k, i, shown)
    return out


def _curve_x_item(s: "ExploreSession", k: int, i: int) -> Dict[str, Any]:
    m = s.model
    if _operated(s) and s.ops_shown.x_changed:       # FFT, histogram: an axis the operations made
        return _model_axis_item(s, "x", s.ops_result.grid.xq, m.xs[k][i], m.xf, i)
    if s.spec["x"] in s.data.values:                 # a value as x: its stored number at this point
        xv = s.data.values[s.spec["x"]]
        return {"role": "x", "name": xv.name, "label": xv.label or xv.name, "unit": xv.unit, "index": int(i),
                "value": _num(m.xs[k][i] / m.xf)}
    return _axis_item(s, "x", s.spec.get("along", s.spec["x"]), i)


def _nearest_point(s: "ExploreSession", x: float, y: float, shown: List[int], geo) -> Tuple[Optional[int], int]:
    """The visible trace and point nearest to (x, y) on screen (pixels, not data units)."""
    xlim, ylim, w, h, (xscale, yscale) = geo
    m = s.model
    cx, cy = _pixels(x, xlim, xscale, w), _pixels(y, ylim, yscale, h)
    best = (np.inf, None, 0)
    for xg, ks, is_sorted in s.x_groups:
        ks = [k for k in ks if s.visible[k]]
        if not ks:
            continue
        if is_sorted and xg.size > 64:
            # the points near x on screen: a window of pixels each side, at least two points
            inc = xg[0] <= xg[-1]
            xs = xg if inc else xg[::-1]
            span = abs(_f(xscale, xlim[1]) - _f(xscale, xlim[0])) / w * 12      # 12 pixels
            a, b = _f(xscale, x) - span, _f(xscale, x) + span
            a, b = (10 ** a, 10 ** b) if xscale == "log" else (a, b)
            i0 = max(int(np.searchsorted(xs, a, side="left")) - 2, 0)
            i1 = min(int(np.searchsorted(xs, b, side="right")) + 2, xs.size)
            idx = np.arange(i0, i1) if inc else xg.size - 1 - np.arange(i0, i1)
        else:
            idx = np.arange(xg.size)
        if not idx.size:
            continue
        ys = np.stack([np.asarray(m.lines[k][0], dtype=float)[idx] for k in ks])
        dx = _pixels(xg[idx], xlim, xscale, w) - cx
        dy = _pixels(ys, ylim, yscale, h) - cy
        d = dx[None, :] ** 2 + dy ** 2
        d[~np.isfinite(d)] = np.inf
        r, n = np.unravel_index(int(np.argmin(d)), d.shape)
        if d[r, n] < best[0]:
            best = (float(d[r, n]), ks[r], int(idx[n]))
    if best[1] is None:
        return None, 0
    return best[1], best[2]


def _step_point(m, k: int, i: int, n: int) -> int:
    """Move n stored points along curve k (in the direction of increasing x), over missing ones."""
    xs = np.asarray(m.xs[k], dtype=float)
    ys = np.asarray(m.lines[k][0], dtype=float)
    ok = np.flatnonzero(np.isfinite(ys) & np.isfinite(xs))
    if not ok.size:
        return i
    order = ok[np.argsort(xs[ok], kind="stable")]
    pos = int(np.searchsorted(xs[order], xs[i]))
    pos = int(np.clip(pos + n, 0, order.size - 1))
    return int(order[pos])


def _table(s: "ExploreSession", k: int, i: int, shown: List[int]) -> Dict[str, Any]:
    """A vertical cursor: every visible trace's value at the cursor's x (cursor's trace first)."""
    m = s.model
    x0 = m.xs[k][i]
    order = [k] + [t for t in shown if t != k]
    rows = []
    for t in order[:TABLE_LIMIT]:
        xs = m.xs[t]
        it = i if xs is m.xs[k] else _nearest(xs, x0)
        rows.append({"trace": int(t), "label": m.lines[t][1], "value": _value_item(s, "y", _trace_value(s, t), m.lines[t][0][it])["value"],
                     "x": _num(xs[it] / m.xf)})
    name = _trace_value(s, k)
    shown_item = _value_item(s, "y", name, 0.0)
    label, unit = shown_item["label"], shown_item["unit"]
    return {"rows": rows, "more": max(len(order) - TABLE_LIMIT, 0), "label": label, "unit": unit}


# -- cuts through a map ----------------------------------------------------------------------------

def _cuts(s: "ExploreSession", cur: Dict[str, Any], kind: str, geo) -> Dict[str, Any]:
    """The row and the column through a cursor, as stored, reduced to the plot area's pixels
    (min and max per pixel when they have more points than pixels)."""
    xlim, ylim, w, h, (xscale, yscale) = geo
    m = s.model
    z = _map_z(s)
    i, j = cur["at"]                                  # the cell shown (a stored one, or made by an operation)
    out: Dict[str, Any] = {"zf": m.zf}
    if kind != "vertical":
        out["row"] = _cut(m.x, z[j, :], xlim, xscale, w, s.spec.get("y") or "y", j)
    if kind != "horizontal":
        out["column"] = _cut(m.y, z[:, i], ylim, yscale, h, s.spec.get("x") or "x", i)
    return out


def _cut(pos: np.ndarray, vals: np.ndarray, lim, scale: str, n: int, fixed: str, at: int) -> Dict[str, Any]:
    pos = np.asarray(pos, dtype=float)
    order = np.argsort(pos, kind="stable")
    (p, v) = curve_minmax(pos[order], [np.asarray(vals, dtype=float)[order]], _edges(lim, scale, n))[0][0]
    inside = (p >= min(lim)) & (p <= max(lim)) & np.isfinite(v)
    shown = v[inside]
    rng = [_num(shown.min()), _num(shown.max())] if shown.size else [None, None]
    return {"pos": [float(a) for a in p], "z": [_num(b) for b in v], "range": rng, "fixed": fixed, "index": int(at)}


# -- max, min, peak --------------------------------------------------------------------------------

def find(s: "ExploreSession", what: str, xlim: Sequence[float], ylim: Sequence[float],
         trace: Optional[int] = None) -> Dict[str, Any]:
    """The stored point (curves) or cell (maps) with the highest (max) or lowest (min) value, or
    the one farthest from the median (peak: a dip or a spike), in this x range (curves: of `trace`,
    else of every visible trace) or this rectangle (maps). Returns its position in plot units."""
    if what not in FIND:
        raise ExploreError(f"unknown search {what!r}; use one of {', '.join(FIND)}")
    x0, x1 = sorted(float(v) for v in xlim)
    y0, y1 = sorted(float(v) for v in ylim)
    m = s.model
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    if s.kind == "heatmap":
        ii = np.flatnonzero((m.x >= x0) & (m.x <= x1))
        jj = np.flatnonzero((m.y >= y0) & (m.y <= y1))
        part = _map_z(s)[np.ix_(jj, ii)] if ii.size and jj.size else np.empty((0, 0))
        if not np.isfinite(part).any():
            raise ExploreError("no stored values in this range to search")
        score = _score(part, what)
        r, c = np.unravel_index(int(np.nanargmax(score)), score.shape)
        return {"x": float(m.x[ii[c]]), "y": float(m.y[jj[r]])}
    shown = _visible(s)
    traces = [trace] if isinstance(trace, int) and trace in shown else shown
    for k in traces:
        xs = np.asarray(m.xs[k], dtype=float)
        ys = np.asarray(m.lines[k][0], dtype=float)
        sel = np.flatnonzero((xs >= x0) & (xs <= x1) & np.isfinite(ys))
        if not sel.size:
            continue
        score = _score(ys[sel], what)
        n = int(np.argmax(score))
        if best is None or score[n] > best[0]:
            best = (float(score[n]), {"x": float(xs[sel[n]]), "y": float(ys[sel[n]]), "trace": int(k)})
    if best is None:
        raise ExploreError("no stored values in this range to search")
    return best[1]


def _score(v: np.ndarray, what: str) -> np.ndarray:
    """Higher is better: the value (max), minus the value (min), the distance from the median (peak)."""
    v = np.asarray(v, dtype=float)
    if what == "max":
        out = v.copy()
    elif what == "min":
        out = -v
    else:
        out = np.abs(v - np.nanmedian(v))
    out[~np.isfinite(out)] = -np.inf
    return out


# -- the histogram of a map's values (contrast) ----------------------------------------------------

def histogram(s: "ExploreSession", bins: int = HIST_BINS) -> Dict[str, Any]:
    """Counts of the map's shown cells (all of them, not the view) in `bins` bins, in plot units;
    on a log colour scale in log-spaced bins of the positive cells. With the lowest and highest
    value and the automatic range (AUTO_RANGE percentiles). Cached per selection and scale."""
    if s.kind != "heatmap":
        raise ExploreError("the contrast histogram is for maps")
    log = s.settings.get("cscale") == "log"
    key = (tuple(sorted(_selected_rows(s) or [])), _selected_rows(s) is None, log, bins)
    cache = getattr(s, "_hist", None)
    if cache and cache[0] == key and cache[2] is s.model:
        return cache[1]
    z = _map_z(s)
    v = z[np.isfinite(z)]
    if log:
        v = v[v > 0]
    if not v.size:
        raise ExploreError("the map has no values to count" + (" above 0 (log colour scale)" if log else ""))
    t = np.log10(v) if log else v
    lo, hi = float(t.min()), float(t.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    fine = 64 * bins                                  # percentiles from a fine histogram: one pass
    counts, _ = np.histogram(t, bins=fine, range=(lo, hi))
    cum = np.cumsum(counts) / counts.sum()
    step = (hi - lo) / fine
    auto = [lo + step * int(np.searchsorted(cum, q / 100)) for q in AUTO_RANGE]
    auto[1] = min(auto[1] + step, hi)
    back = (lambda a: 10 ** np.asarray(a)) if log else (lambda a: np.asarray(a))
    out = {"edges": [float(e) for e in back(np.linspace(lo, hi, bins + 1))],
           "counts": [int(c) for c in counts.reshape(bins, 64).sum(axis=1)],
           "lowest": float(back(lo)), "highest": float(back(hi)),
           "auto": [float(a) for a in back(auto)], "log": log, "cells": int(v.size)}
    s._hist = (key, out, s.model)
    return out


# -- taking a cut out ------------------------------------------------------------------------------

def cut_plan(s: "ExploreSession", which: str, index: Dict[str, int], trace: Optional[int] = None):
    """What a cut keeps and fixes: (kept axis, {fixed axis: index}, value names)."""
    if _operated(s) and not s.ops_result.grid.one_to_one or s.kind != s.base_kind:
        raise ExploreError("after this operation the shown points aren't stored ones; turn the operations "
                           "off to save the stored data of a cut")
    spec = s.spec
    fixed = dict(spec.get("index") or {})
    if s.kind == "heatmap":
        if which == "row":
            keep, fixed[spec["y"]] = spec["x"], int(index[spec["y"]])
        elif which == "column":
            keep, fixed[spec["x"]] = spec["y"], int(index[spec["x"]])
        else:
            raise ExploreError("a map's cut is a 'row' or a 'column'")
        return keep, fixed, [spec["values"][0]]
    if which != "trace" or not isinstance(trace, int) or not 0 <= trace < len(s.model.lines):
        raise ExploreError("a curve plot's cut is a 'trace': give the cursor's trace")
    keep = spec.get("along", spec["x"])
    if spec.get("series"):
        fixed[spec["series"]] = int(trace % _per_value(s))
    names = [_trace_value(s, trace)]
    if spec["x"] in s.data.values:
        names.append(spec["x"])
    return keep, fixed, names


def _fixed_text(s: "ExploreSession", fixed: Dict[str, int]) -> str:
    parts = []
    for a, i in fixed.items():
        ax = s.data.axes[a]
        parts.append(f"{ax.label or a} = {si_text(float(np.asarray(ax.data, dtype=float)[i]), ax.unit)}")
    return ", ".join(parts)


def si_text(v: float, unit: str) -> str:
    """A number with an SI prefix for its unit, e.g. 0.0003 A -> '300 µA' (file names, titles)."""
    if unit and v != 0 and np.isfinite(v):
        for p, f in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)):
            if abs(v) >= f * 0.9999999:
                return f"{v / f:.6g} {p}{unit}"
        return f"{v:.6g} {unit}"
    return f"{v:.6g}" + (f" {unit}" if unit else "")


def suggest_cut_path(s: "ExploreSession", which: str, index: Dict[str, int], trace: Optional[int] = None) -> Path:
    keep, fixed, _ = cut_plan(s, which, index, trace)
    new = {a: i for a, i in fixed.items() if (s.spec.get("index") or {}).get(a) != i or a not in (s.spec.get("index") or {})}
    text = _fixed_text(s, new or fixed).replace("/", "-").replace(":", "-").replace("\\", "-")
    base = f"{s.path.stem} – {text}"
    path = s.path.with_name(base + ".lbd")
    n = 2
    while path.exists():
        path = s.path.with_name(f"{base} ({n}).lbd")
        n += 1
    return path


def save_cut(s: "ExploreSession", which: str, index: Dict[str, int], path: Path,
             trace: Optional[int] = None) -> Path:
    """Write a cut (a map's row or column, or one trace) as a new .lbd file: the stored data
    (complex values stay complex) along the kept axis, with metadata saying where it came from.
    The source file is never changed; an existing file is never overwritten."""
    keep, fixed, names = cut_plan(s, which, index, trace)
    path = Path(path)
    if path.suffix.lower() != ".lbd":
        raise ExploreError(f"a cut is saved as a .lbd file, not '{path.name}'")
    if path.exists():
        raise ExploreError(f"'{path.name}' exists already; choose another name")
    if not path.parent.is_dir():
        raise ExploreError(f"the folder '{path.parent}' doesn't exist")
    src = s.data
    d = lbd.Dataset(title=f"{src.title or s.path.stem} – {_fixed_text(s, fixed)}",
                    description=f"Cut from '{s.path.name}' by LBD Viewer's Explore view.")
    a = src.axes[keep]
    d.add_axis(keep, a.data, unit=a.unit, label=a.label)
    for name in names:
        v = src.values[name]
        if keep not in v.axes:
            raise ExploreError(f"'{name}' doesn't run along '{keep}'")
        missing = [ax for ax in v.axes if ax != keep and ax not in fixed]
        if missing:
            raise ExploreError(f"'{name}' has axes {missing} that the cut doesn't fix")
        data = np.asarray(v.data)[tuple(slice(None) if ax == keep else fixed[ax] for ax in v.axes)]
        d.add_value(name, data, axes=keep, unit=v.unit, label=v.label)
    d.meta = {"cut_from": s.path.name,
              "cut_index": {ax: int(i) for ax, i in fixed.items()},
              "cut_at": {ax: float(np.asarray(src.axes[ax].data, dtype=float)[i]) for ax, i in fixed.items()}}
    if src.meta:
        d.meta["source_meta"] = src.meta
    d.plot = {"kind": "curve", "values": names[:1]}
    if np.iscomplexobj(src.values[names[0]].data):
        d.plot["complex"] = s.spec["complex"]
    d.save(path)
    return path
