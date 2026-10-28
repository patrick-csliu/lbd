"""Explore sessions: interactive views of a data file, drawn by matplotlib.

The Explore view is the figure engine (lbd.plot) made interactive. Each open Explore tab has a
session here that keeps, between requests:

- the file's data and the plot worked out from it (`prepare_curves` / `prepare_map`, the same
  code the figures use, so both look the same);
- the data reduced to the screen (lbd.plot.reduce): a pyramid for maps, min/max per pixel column
  for curves. matplotlib only ever gets about one value per pixel, so it never averages anything
  away, and a redraw stays fast however big the file is;
- one matplotlib figure the size of the browser's panel. Its layout is frozen after the first
  drawing, so the plot area doesn't move while zooming.

A render answers with the picture's pixels and the mapping between pixels and data, so the browser
can draw cursors and markers on top without asking again. Values the user picks are read from the
full data, never from the picture.

Renders share lbd.plot's RENDER_LOCK: matplotlib's settings are global.
"""

from __future__ import annotations

import io
import secrets
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import lbd
from lbd.plot import render as rnd
from lbd.plot.reduce import STATS, MapPyramid, cell_edges, curve_minmax
from lbd.plot.style import Style

KINDS = ("curve", "heatmap")
MAX_DPR = 2.0
PICK_RADIUS_PX = 12.0
FORMATS = ("raw", "png")


class ExploreError(ValueError):
    """A request the Explore view can't do; the message says what to do instead."""


def _is_sorted(x: np.ndarray) -> bool:
    """Increasing or decreasing (missing points aside): what curve_minmax needs."""
    f = x[np.isfinite(x)]
    if f.size < 2:
        return True
    d = np.diff(f)
    return bool(np.all(d >= 0) or np.all(d <= 0))


def _finite_range(arrays) -> Tuple[float, float]:
    lo, hi = np.inf, -np.inf
    for a in arrays:
        a = np.asarray(a, dtype=float)
        f = a[np.isfinite(a)]
        if f.size:
            lo, hi = min(lo, float(f.min())), max(hi, float(f.max()))
    if not np.isfinite(lo):
        return 0.0, 1.0
    return (lo - 0.5, hi + 0.5) if lo == hi else (lo, hi)


class ExploreSession:
    """One Explore tab's view of a file. Create with `open_session`; all drawing happens in
    `render`, under the render lock."""

    def __init__(self, path: Path, version: str, spec: Dict[str, Any], style: Style,
                 width: int, height: int, dpr: float):
        if width < 50 or height < 50:
            raise ExploreError(f"the plot area is too small ({width}×{height} px); make the window larger")
        self.id = secrets.token_urlsafe(9)
        self.path, self.version, self.style = path, version, style
        self.last_used = time.monotonic()
        header = lbd.info(path)
        with warnings.catch_warnings():               # the same checks run again on the loaded data
            warnings.simplefilter("ignore", rnd.RenderWarning)
            resolved = rnd.resolve_spec(header, spec, warn_unused=False)
        self.data = lbd.load(path, values=rnd.needed_values(header, resolved))
        self.spec = rnd.resolve_spec(self.data, spec, warn_unused=False)
        self.kind = self.spec["kind"]
        if self.kind not in KINDS:
            raise ExploreError(f"the Explore view shows curves and heat maps, not {self.kind} plots; "
                               "use the Figure view for this plot")
        self.dpr = float(min(max(dpr, 1.0), MAX_DPR))
        dpi = 96 * self.dpr                           # 1 CSS pixel = 1/96 inch, as in browsers
        with rnd.RENDER_LOCK, matplotlib.rc_context(style.to_rcparams()):
            self.fig = Figure(figsize=(width / 96, height / 96), dpi=dpi, layout="constrained")
            FigureCanvasAgg(self.fig)
            self.ax = self.fig.add_subplot()
            if self.kind == "curve":
                self._setup_curves()
            else:
                self._setup_map()
            # The layout is made for the whole data's tick labels (usually the widest)
            self.ax.set_xlim(*self.full[0])
            self.ax.set_ylim(*self.full[1])
            self.fig.canvas.draw()                    # lays the figure out once ...
            self.fig.set_layout_engine("none")        # ... and keeps it, so zooming doesn't move the plot
        self.highlight: Optional[int] = None
        self.last_lines: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None

    # -- setup

    def _setup_curves(self):
        m = self.model = rnd.prepare_curves(self.data, self.spec, self.style)
        # Lines that share one x (x is an axis) are reduced and picked together; with a value as x
        # each line has its own. Unsorted x (e.g. one value against another) is drawn as stored.
        groups: Dict[int, Tuple[np.ndarray, List[int]]] = {}
        for k, x in enumerate(m.xs):
            groups.setdefault(id(x), (np.asarray(x, dtype=float), []))[1].append(k)
        self.x_groups = [(x, ks, _is_sorted(x)) for x, ks in groups.values()]
        self.lines = rnd.draw_curves(self.fig, self.ax, m, self.data, self.spec, self.style,
                                     data=[(x[:0], y[:0]) for x, (y, _) in zip(m.xs, m.lines)])
        self.full = (_finite_range([x for x, _, _ in self.x_groups]), m.ylim if m.ylim and None not in m.ylim
                     else self._padded(_finite_range([y for y, _ in m.lines])))

    def _setup_map(self):
        m = self.model = rnd.prepare_map(self.data, self.spec, self.style)
        xe, ye = cell_edges(m.x), cell_edges(m.y)
        try:
            self.pyramid = MapPyramid(m.z, xe, ye)
        except ValueError as e:
            raise ExploreError(str(e)) from e
        self.x_edges, self.y_edges = np.sort(xe), np.sort(ye)
        m.norm.autoscale_None(np.ma.masked_invalid(m.z))   # colour limits from all the data, not the view
        self.image = rnd.draw_map(self.fig, self.ax, m, self.data, self.spec, self.style,
                                  image=np.full((2, 2), np.nan))
        self.full = ((float(self.x_edges[0]), float(self.x_edges[-1])), (float(self.y_edges[0]), float(self.y_edges[-1])))

    @staticmethod
    def _padded(r: Tuple[float, float]) -> Tuple[float, float]:
        pad = (r[1] - r[0]) * 0.05                      # matplotlib's default margin
        return r[0] - pad, r[1] + pad

    # -- drawing

    def _plot_area(self) -> Tuple[int, int, int, int]:
        """The axes' box in image pixels: left, top, width, height (top-left origin)."""
        bb = self.ax.get_window_extent()
        h = int(round(self.fig.bbox.height))
        left, right = int(round(bb.x0)), int(round(bb.x1))
        top, bottom = h - int(round(bb.y1)), h - int(round(bb.y0))
        return left, top, max(right - left, 1), max(bottom - top, 1)

    def _spills(self) -> bool:
        """Whether some text of the last drawing sticks out of the picture."""
        r = self.fig.canvas.get_renderer()
        box = self.fig.bbox
        for a in self.fig.axes:
            tb = a.get_tightbbox(r)
            if tb is not None and (tb.x0 < box.x0 - 0.5 or tb.y0 < box.y0 - 0.5 or
                                   tb.x1 > box.x1 + 0.5 or tb.y1 > box.y1 + 0.5):
                return True
        return False

    def _pixel_edges(self, w: int, h: int) -> Tuple[np.ndarray, np.ndarray]:
        """Data values at the pixel boundaries of the plot area (x left to right, y bottom to top)."""
        bb = self.ax.get_window_extent()
        inv = self.ax.transData.inverted()
        xs = np.linspace(bb.x0, bb.x1, w + 1)
        ys = np.linspace(bb.y0, bb.y1, h + 1)
        xe = inv.transform(np.column_stack([xs, np.full_like(xs, bb.y0)]))[:, 0]
        ye = inv.transform(np.column_stack([np.full_like(ys, bb.x0), ys]))[:, 1]
        return xe, ye

    def resize(self, width: int, height: int, dpr: float) -> None:
        """Draw for a panel of a new size from now on (the data and its reductions are kept)."""
        if width < 50 or height < 50:
            raise ExploreError(f"the plot area is too small ({width}×{height} px); make the window larger")
        dpr = float(min(max(dpr, 1.0), MAX_DPR))
        w, h = self.fig.get_size_inches()
        if (round(w * 96), round(h * 96), self.dpr) == (width, height, dpr):
            return
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self.dpr = dpr
            self.fig.set_dpi(96 * dpr)
            self.fig.set_size_inches(width / 96, height / 96)
            self.ax.set_xlim(*self.full[0])
            self.ax.set_ylim(*self.full[1])
            self.fig.set_layout_engine("constrained")
            self.fig.canvas.draw()
            self.fig.set_layout_engine("none")

    def render(self, xlim: Optional[Tuple[float, float]], ylim: Optional[Tuple[float, float]],
               stat: str = "max", fmt: str = "raw", _again: bool = False) -> Tuple[bytes, Dict[str, Any]]:
        if stat not in STATS:
            raise ExploreError(f"unknown reduction {stat!r}; use one of {', '.join(STATS)}")
        if fmt not in FORMATS:
            raise ExploreError(f"unknown picture format {fmt!r}; use one of {', '.join(FORMATS)}")
        xlim = tuple(xlim) if xlim else self.full[0]
        ylim = tuple(ylim) if ylim else self.full[1]
        for lim, name in ((xlim, "x"), (ylim, "y")):
            if not (np.isfinite(lim[0]) and np.isfinite(lim[1]) and lim[0] < lim[1]):
                raise ExploreError(f"the {name} range {lim} is not valid: it needs two numbers, lowest first")
        t0 = time.perf_counter()
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            t1 = time.perf_counter()
            self.last_used = time.monotonic()
            self.ax.set_xlim(*xlim)
            self.ax.set_ylim(*ylim)
            left, top, w, h = self._plot_area()
            pxe, pye = self._pixel_edges(w, h)
            if self.kind == "heatmap":
                r = self.pyramid.raster(pxe, pye, stat)
                self.image.set_data(r.image)
                note, reduced = r.note(), r.reduced
            else:
                ys = [y for y, _ in self.model.lines]
                lines: List[Tuple[np.ndarray, np.ndarray]] = [None] * len(ys)   # type: ignore[list-item]
                reduced = unsorted = False
                for x, ks, is_sorted in self.x_groups:
                    if is_sorted:
                        out, red = curve_minmax(x, [ys[k] for k in ks], pxe)
                        reduced |= red
                    else:
                        out, unsorted = [(x, ys[k]) for k in ks], True
                    for k, xy in zip(ks, out):
                        lines[k] = xy
                for artist, (x, y) in zip(self.lines, lines):
                    artist.set_data(x, y)
                self.last_lines = lines
                note = "min and max per pixel column" if reduced else "every point shown"
                if unsorted:
                    note += "; x is not sorted: drawn as stored"
            t2 = time.perf_counter()
            self.fig.canvas.draw()
            if not _again and self._spills():
                # Longer tick labels (zoomed in: more digits) no longer fit: lay out again, once.
                self.fig.set_layout_engine("constrained")
                self.fig.canvas.draw()
                self.fig.set_layout_engine("none")
                left, top, w, h = self._plot_area()
                if (w, h) != (len(pxe) - 1, len(pye) - 1):        # the plot area changed size
                    return self.render(xlim, ylim, stat, fmt, _again=True)
            rgba = np.asarray(self.fig.canvas.buffer_rgba())
            t3 = time.perf_counter()
        height, width = rgba.shape[:2]
        if fmt == "png":
            from PIL import Image

            buf = io.BytesIO()
            Image.fromarray(rgba).save(buf, format="png", compress_level=1)
            body = buf.getvalue()
        else:
            body = rgba.tobytes()
        t4 = time.perf_counter()
        meta = {
            "format": fmt, "width": width, "height": height, "dpr": self.dpr,
            "plot": [left, top, w, h], "xlim": list(xlim), "ylim": list(ylim),
            "xscale": self.ax.get_xscale(), "yscale": self.ax.get_yscale(),
            "full": [list(self.full[0]), list(self.full[1])],
            "note": note, "reduced": reduced, "stat": stat,
            "ms": {"wait": round((t1 - t0) * 1000, 1), "reduce": round((t2 - t1) * 1000, 1),
                   "draw": round((t3 - t2) * 1000, 1), "encode": round((t4 - t3) * 1000, 1)},
        }
        return body, meta

    # -- picking

    def _to_px(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Data (plot units) to image pixels, top-left origin."""
        pts = self.ax.transData.transform(np.column_stack([np.ravel(x), np.ravel(y)]))
        return pts[:, 0], self.fig.bbox.height - pts[:, 1]

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        """The stored point (curves) or cell (maps) at image pixel (px, py), from the full data."""
        self.last_used = time.monotonic()
        with rnd.RENDER_LOCK:
            disp = (px, self.fig.bbox.height - py)
            xd, yd = self.ax.transData.inverted().transform([disp])[0]
            if self.kind == "heatmap":
                return self._pick_cell(xd, yd)
            return self._pick_curve(px, py)

    def _pick_cell(self, xd: float, yd: float) -> Optional[Dict[str, Any]]:
        m = self.model
        i = self._cell(m.x, xd)
        j = self._cell(m.y, yd)
        if i is None or j is None:
            return None
        xe, ye = cell_edges(m.x), cell_edges(m.y)
        x0, x1 = sorted((xe[i], xe[i + 1]))
        y0, y1 = sorted((ye[j], ye[j + 1]))
        pxs, pys = self._to_px(np.array([x0, x1]), np.array([y0, y1]))
        value = m.z[j, i]
        return {"kind": "cell", "index": {self.spec["x"]: int(i), self.spec["y"]: int(j)},
                "x": self._stored(self.spec["x"], i), "y": self._stored(self.spec["y"], j),
                "value": None if not np.isfinite(value) else float(value / m.zf),
                "value_unit": self.data.values[self.spec["values"][0]].unit,
                "shown": {"x": float(m.x[i]), "y": float(m.y[j]), "value": None if not np.isfinite(value) else float(value)},
                "rect": [float(min(pxs)), float(min(pys)), float(abs(pxs[1] - pxs[0])), float(abs(pys[1] - pys[0]))]}

    @staticmethod
    def _cell(centres: np.ndarray, v: float) -> Optional[int]:
        e = cell_edges(centres)
        inc = e[0] < e[-1]
        es = e if inc else e[::-1]
        k = int(np.searchsorted(es, v, side="right")) - 1
        if not 0 <= k < len(centres):
            return None
        return k if inc else len(centres) - 1 - k

    def _stored(self, axis: str, i: int) -> Dict[str, Any]:
        a = self.data.axes[axis]
        return {"axis": axis, "value": float(np.asarray(a.data, dtype=float)[i]), "unit": a.unit, "label": a.label}

    def _near(self, x: np.ndarray, is_sorted: bool, px: float) -> np.ndarray:
        """Indices of the points of x that may be within the pick radius of pixel column px."""
        if not is_sorted or x.size < 2:
            return np.arange(x.size)
        xl, _ = self.ax.transData.inverted().transform([(px - PICK_RADIUS_PX, 0)])[0]
        xr, _ = self.ax.transData.inverted().transform([(px + PICK_RADIUS_PX, 0)])[0]
        lo, hi = sorted((xl, xr))
        inc = x[0] <= x[-1]
        xs = x if inc else x[::-1]
        a = max(int(np.searchsorted(xs, lo, side="left")) - 1, 0)
        b = min(int(np.searchsorted(xs, hi, side="right")) + 1, x.size)
        return np.arange(a, b) if inc else (x.size - 1 - np.arange(a, b))

    def _pick_curve(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        m = self.model
        best = None                                   # (distance², line, point index, x px, y px)
        for x, ks, is_sorted in self.x_groups:
            idx = self._near(x, is_sorted, px)
            if not idx.size:
                continue
            ys = np.stack([np.asarray(m.lines[k][0], dtype=float)[idx] for k in ks])   # lines × points
            xpx, ypx = self._to_px(np.broadcast_to(x[idx], ys.shape), ys)
            xpx, ypx = xpx.reshape(ys.shape), ypx.reshape(ys.shape)
            d = np.where(np.isfinite(ys), (xpx - px) ** 2 + (ypx - py) ** 2, np.inf)
            r, n = np.unravel_index(int(np.argmin(d)), d.shape)
            if best is None or d[r, n] < best[0]:
                best = (float(d[r, n]), ks[r], int(idx[n]), float(xpx[r, n]), float(ypx[r, n]))
        if best is None or best[0] > PICK_RADIUS_PX ** 2:
            return None
        _, k, i, at_x, at_y = best
        y_shown = float(m.lines[k][0][i])
        x_shown = float(m.xs[k][i])
        # The lines are: for each plotted value, one per series step (or just one).
        series = self.spec.get("series")
        per_value = len(self.data.axes[series].data) if series else 1
        name = self.spec["values"][min(k // per_value, len(self.spec["values"]) - 1)]
        along = self.spec.get("along", self.spec["x"])
        if self.spec["x"] in self.data.values:        # a value as x: its stored number at this point
            xv = self.data.values[self.spec["x"]]
            x_stored = {"axis": xv.name, "value": x_shown / m.xf, "unit": xv.unit, "label": xv.label}
        else:
            x_stored = self._stored(along, i)
        out = {"kind": "point", "trace": int(k), "label": m.lines[k][1], "value_name": name,
               "index": {along: i}, "x": x_stored,
               "y": float(y_shown / m.yf), "y_unit": self.data.values[name].unit,
               "shown": {"x": x_shown, "y": y_shown}, "at": [at_x, at_y]}
        if series:
            j = int(k % per_value)
            out["index"][series] = j
            out["series"] = self._stored(series, j)
        if self.last_lines is not None:
            lx, ly = self.last_lines[k]
            hx, hy = self._to_px(lx, ly)
            out["line"] = [[float(a), float(b)] if np.isfinite(b) else None for a, b in zip(hx, hy)]
        return out

    def close(self):
        self.fig = None


class Sessions:
    """The open Explore sessions, by id. Old ones are closed after `idle` seconds without use,
    and at most `limit` are open (each holds a file's data and a figure)."""

    def __init__(self, limit: int = 12, idle: float = 600.0):
        self.limit, self.idle = limit, idle
        self._by_id: Dict[str, ExploreSession] = {}
        self._lock = threading.Lock()

    def add(self, s: ExploreSession) -> None:
        with self._lock:
            self._expire()
            if len(self._by_id) >= self.limit:
                oldest = min(self._by_id.values(), key=lambda v: v.last_used)
                del self._by_id[oldest.id]
                oldest.close()
            self._by_id[s.id] = s

    def get(self, sid: str) -> ExploreSession:
        with self._lock:
            self._expire()
            s = self._by_id.get(sid)
        if s is None:
            raise KeyError(sid)
        return s

    def close(self, sid: str) -> None:
        with self._lock:
            s = self._by_id.pop(sid, None)
        if s is not None:
            s.close()

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [k for k, v in self._by_id.items() if now - v.last_used > self.idle]:
            self._by_id.pop(sid).close()

    def __len__(self) -> int:
        return len(self._by_id)
