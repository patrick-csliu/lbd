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
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import lbd
from lbd.plot import render as rnd
from lbd.plot.reduce import STATS, MapPyramid, cell_edges, curve_minmax, raster_columns, raster_lines, thin_in_order
from lbd.plot.style import Style

KINDS = ("curve", "heatmap")
UNSORTED_LIMIT = 200_000   # a curve with unsorted x and more points than this is thinned for drawing
# Above this many curves on screen, they are drawn as one picture (reduce.raster_lines) instead of
# line by line: matplotlib needs ~0.7 ms per line, so 1000 curves would take most of a second.
RASTER_ABOVE = 30
# Tick labels the layout makes room for, so zooming (more digits) never needs a new layout.
WIDEST_TICK = "\u22128.888888"
MAX_DPR = 2.0
PICK_RADIUS_PX = 12.0
FORMATS = ("raw", "png")
# Colour maps offered in the Explore view: perceptually even ones, a diverging one for signed data,
# a cyclic one for phases. Any matplotlib colour map name is accepted.
CMAPS = ("viridis", "plasma", "magma", "cividis", "gray", "RdBu", "twilight")


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
        self.header = lbd.info(path)
        self.data = lbd.load(path, values=[])
        self.dpr = float(min(max(dpr, 1.0), MAX_DPR))
        dpi = 96 * self.dpr                           # 1 CSS pixel = 1/96 inch, as in browsers
        self.fig = Figure(figsize=(width / 96, height / 96), dpi=dpi)
        FigureCanvasAgg(self.fig)
        self.set_spec(spec)

    def set_spec(self, spec: Dict[str, Any]) -> None:
        """Show other plot settings (values, kind, axes, slices, complex mode). The data already
        read is kept; values not read yet are read now."""
        with warnings.catch_warnings():               # the same checks run again on the loaded data
            warnings.simplefilter("ignore", rnd.RenderWarning)
            resolved = rnd.resolve_spec(self.header, spec, warn_unused=False)
        needed = rnd.needed_values(self.header, resolved)
        loaded = [n for n, v in self.data.values.items() if v.data is not None]
        if not set(needed) <= set(loaded):
            self.data = lbd.load(self.path, values=sorted(set(needed) | set(loaded)))
        new = rnd.resolve_spec(self.data, spec, warn_unused=False)
        if new["kind"] not in KINDS:
            raise ExploreError(f"the Explore view shows curves and heat maps, not {new['kind']} plots; "
                               "use the Figure view for this plot")
        self.spec, self.kind = new, new["kind"]
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self.fig.clear()
            self.fig.set_layout_engine("constrained")
            self.ax = self.fig.add_subplot()
            if self.kind == "curve":
                self._setup_curves()
            else:
                self._setup_map()
            self.settings: Dict[str, Any] = {}           # view settings (apply), reset with the plot
            self.visible = [True] * (len(self.model.lines) if self.kind == "curve" else 0)
            self.base_scales = (self.ax.get_xscale(), self.ax.get_yscale())
            self.full = self._full_view()
            self.ax.set_xlim(*self.full[0])
            self.ax.set_ylim(*self.full[1])
            self._lay_out()
        self.highlight: Optional[int] = None
        self.last_lines: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None

    def _lay_out(self) -> None:
        """Place the plot area once, with room for tick labels as wide as zooming in can make
        them; then keep it, so the plot doesn't move while zooming and no zoom step needs a new
        layout (that would cost a second drawing). Call under the render lock."""
        from matplotlib.ticker import FuncFormatter

        kept = [(a, a.get_major_formatter()) for a in (self.ax.xaxis, self.ax.yaxis)]
        for a, _ in kept:
            a.set_major_formatter(FuncFormatter(lambda v, pos: WIDEST_TICK))
        self.fig.set_layout_engine("constrained")
        self.fig.canvas.draw()
        self.fig.set_layout_engine("none")
        for a, formatter in kept:
            a.set_major_formatter(formatter)

    # -- setup

    def _setup_curves(self):
        m = self.model = rnd.prepare_curves(self.data, self.spec, self.style)
        # Lines that share one x (x is an axis) are reduced and picked together; with a value as x
        # each line has its own. Unsorted x (e.g. one value against another) is drawn as stored.
        groups: Dict[int, Tuple[np.ndarray, List[int]]] = {}
        for k, x in enumerate(m.xs):
            groups.setdefault(id(x), (np.asarray(x, dtype=float), []))[1].append(k)
        self.x_groups = [(x, ks, _is_sorted(x)) for x, ks in groups.values()]
        # One vertical axis: the traces are named in the list and when clicked, so the figure's
        # colour bar for many series (a second axis) is left out here.
        m.series_bar = None
        self.lines = rnd.draw_curves(self.fig, self.ax, m, self.data, self.spec, self.style,
                                     data=[(x[:0], y[:0]) for x, (y, _) in zip(m.xs, m.lines)])
        # Many curves are drawn as one picture over the plot area (see render).
        self.line_image = self.ax.imshow(np.zeros((1, 1, 4), np.uint8), extent=(0, 1, 0, 1), transform=self.ax.transAxes,
                                         interpolation="nearest", aspect="auto", zorder=2, visible=False)
        self.line_colors = np.array([[*mcolors.to_rgba_array(a.get_color())[0][:3] * 255, 255] for a in self.lines],
                                    dtype=np.uint8).reshape(-1, 4)
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
    def _padded(r: Tuple[float, float], log: bool = False) -> Tuple[float, float]:
        """matplotlib's default margin of 5 %, on a log axis in decades."""
        if log:
            a, b = np.log10(r[0]), np.log10(r[1])
            pad = (b - a) * 0.05
            return 10 ** (a - pad), 10 ** (b + pad)
        pad = (r[1] - r[0]) * 0.05
        return r[0] - pad, r[1] + pad

    # -- view settings: how the same data is shown (never written into the file)

    def apply(self, settings: Optional[Dict[str, Any]]) -> List[str]:
        """Show the data with these view settings; returns notes for the user.

        `select` {axis: [positions]}: which traces are drawn (curves: along the series axis) or
        make the map (its vertical axis; left-out rows stay empty, so every row keeps its place).
        `cmap` and `invert`: the map's colour map. `xscale`, `yscale`, `cscale`: "linear" or "log".
        `clim` [from, to]: the colour range (None: from the data). Missing settings keep the plot's
        own (its style and saved figure settings)."""
        settings = dict(settings or {})
        if settings == self.settings:
            return []
        for key in ("xscale", "yscale", "cscale"):
            if settings.get(key, "linear") not in ("linear", "log"):
                raise ExploreError(f"{key} must be 'linear' or 'log', not {settings[key]!r}")
        cmap = settings.get("cmap")
        if cmap is not None and cmap not in matplotlib.colormaps:
            raise ExploreError(f"unknown colour map {cmap!r}; for example {', '.join(CMAPS)}")
        clim = settings.get("clim") or [None, None]
        if (not isinstance(clim, (list, tuple)) or len(clim) != 2
                or any(v is not None and not isinstance(v, (int, float)) for v in clim)):
            raise ExploreError("the colour range must be two numbers (or empty for automatic)")
        if None not in clim and clim[0] >= clim[1]:
            raise ExploreError("the colour range needs 'from' lower than 'to'")
        notes: List[str] = []
        axis = self.spec.get("series") if self.kind == "curve" else self.spec.get("y")
        select = settings.get("select") or {}
        chosen: Optional[set] = None
        for name, positions in select.items():
            if name != axis:
                where = "the series axis" if self.kind == "curve" else "the map's vertical axis"
                raise ExploreError(f"traces can be chosen along {where} ('{axis}') only, not '{name}'")
            n = len(self.data.axes[name].data)
            kept = [i for i in positions if isinstance(i, int) and 0 <= i < n]
            if len(kept) < len(positions):
                notes.append(f"{len(positions) - len(kept)} chosen positions of '{name}' no longer exist; left out")
            chosen = set(kept)
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            if self.kind == "curve":
                per = len(self.data.axes[axis].data) if axis else 1
                self.visible = [chosen is None or k % per in chosen for k in range(len(self.model.lines))]
                for artist, shown in zip(self.lines, self.visible):
                    artist.set_visible(shown)
            else:
                self._apply_map(settings, chosen, clim)
            self.ax.set_xscale(settings.get("xscale", self.base_scales[0]))
            self.ax.set_yscale(settings.get("yscale", self.base_scales[1]))
            self.full = self._full_view()
        self.settings = settings
        return notes

    def _apply_map(self, settings: Dict[str, Any], chosen: Optional[set], clim) -> None:
        old = (self.settings.get("select") or {}).get(self.spec["y"])
        if (None if old is None else set(old)) != chosen or not hasattr(self, "pyramid"):
            z = self.model.z
            if chosen is not None:                       # left-out rows are empty, in their place
                z = z.copy()
                z[[j for j in range(z.shape[0]) if j not in chosen], :] = np.nan
            self.pyramid = MapPyramid(z, cell_edges(self.model.x), cell_edges(self.model.y))
        name = settings.get("cmap") or self.model.cmap
        if settings.get("invert"):
            name = name[:-2] if name.endswith("_r") else name + "_r"
        self.image.set_cmap(name)
        if "cscale" in settings or any(v is not None for v in clim):
            log = settings.get("cscale") == "log"
            z = self.model.z[np.isfinite(self.model.z)]
            if log:
                z = z[z > 0]
            lo = clim[0] if clim[0] is not None else (float(z.min()) if z.size else 1.0)
            hi = clim[1] if clim[1] is not None else (float(z.max()) if z.size else 10.0)
            if log and lo <= 0:
                raise ExploreError("a log colour scale needs a range above 0")
            norm = mcolors.LogNorm(lo, hi) if log else mcolors.Normalize(lo, hi)
        else:
            norm = self.model.norm                       # the style's (and the data's) own
        self.image.set_norm(norm)
        if self.image.colorbar is not None:
            self.image.colorbar.update_normal(self.image)

    def _full_view(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """The limits that show all the data drawn now (the chosen traces; on a log axis the
        positive part only)."""
        xlog, ylog = self.ax.get_xscale() == "log", self.ax.get_yscale() == "log"

        def rng(arrays, log):
            arrays = [np.asarray(a, dtype=float) for a in arrays]
            if log:
                arrays = [a[a > 0] for a in arrays]
            return _finite_range(arrays)

        if self.kind == "heatmap":
            xe, ye = self.x_edges, self.y_edges
            return (rng([xe], xlog), rng([ye], ylog))
        shown = [k for k, v in enumerate(self.visible) if v] or list(range(len(self.model.lines)))
        x = rng([self.model.xs[k] for k in shown], xlog)
        m = self.model
        if m.ylim and None not in m.ylim and not ylog:
            return x, m.ylim
        return x, self._padded(rng([m.lines[k][0] for k in shown], ylog), ylog)

    # -- drawing

    def _raster(self, lines, shown: List[int], w: int, h: int) -> None:
        """Draw the curves `shown` into one picture of the plot area (w × h pixels), in their
        colours, later curves on top, as matplotlib would draw them (without antialiasing)."""
        def to_px(v, lim, scale, size):
            f = (lambda a: np.log10(np.where(a > 0, a, np.nan))) if scale == "log" else (lambda a: a)
            a, b = f(np.asarray(lim, dtype=float))
            return (f(np.asarray(v, dtype=float)) - a) / (b - a) * size

        xs, ys = self.ax.get_xscale(), self.ax.get_yscale()
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        width = self.lines[shown[0]].get_linewidth() * self.fig.dpi / 72 if shown else 1.0
        groups = [ks for _, ks, ok in self.x_groups if ok and any(k in shown for k in ks)]
        if len(groups) == 1 and all(len(lines[k][0]) == len(lines[shown[0]][0]) for k in shown):
            # the usual case: the curves share one sorted x, so they are drawn column by column
            x = to_px(lines[shown[0]][0], xl, xs, w)
            y = h - to_px(np.stack([lines[k][1] for k in shown]), yl, ys, h)
            owner = raster_columns(x, y, w, h, width)
        else:
            px = [(to_px(lines[k][0], xl, xs, w), h - to_px(lines[k][1], yl, ys, h)) for k in shown]
            owner = raster_lines(px, w, h, width)
        table = np.vstack([self.line_colors[shown], [[0, 0, 0, 0]]])     # -1: transparent
        self.line_image.set_data(table[owner])

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
            # a few pixels over the edge are harmless (antialiased glyph edges, the top tick label)
            if tb is not None and (tb.x0 < box.x0 - 4 or tb.y0 < box.y0 - 4 or
                                   tb.x1 > box.x1 + 4 or tb.y1 > box.y1 + 4):
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
            self._lay_out()

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
                reduced = unsorted = thinned = False
                for x, ks, is_sorted in self.x_groups:
                    for k in ks:                         # left-out traces: nothing to draw
                        lines[k] = (x[:0], ys[k][:0])
                    ks = [k for k in ks if self.visible[k]]
                    if not ks:
                        continue
                    if is_sorted:
                        out, red = curve_minmax(x, [ys[k] for k in ks], pxe)
                        reduced |= red
                    else:
                        unsorted = True
                        if x.size > UNSORTED_LIMIT:              # thinned in stored order (drawing only)
                            out = [thin_in_order(x, ys[k], 4 * w) for k in ks]
                            thinned = True
                        else:
                            out = [(x, ys[k]) for k in ks]
                    for k, xy in zip(ks, out):
                        lines[k] = xy
                shown = [k for k, v in enumerate(self.visible) if v]
                as_picture = len(shown) > RASTER_ABOVE
                for k, (artist, (x, y)) in enumerate(zip(self.lines, lines)):
                    artist.set_data(x, y)
                    artist.set_visible(self.visible[k] and not as_picture)
                self.line_image.set_visible(as_picture)
                if as_picture:
                    self._raster(lines, shown, w, h)
                self.last_lines = lines
                note = "min and max per pixel column" if reduced else "every point shown"
                if unsorted:
                    note += ("; x is not sorted: drawn in stored order, thinned to the lowest and highest "
                             "point of each stretch" if thinned else "; x is not sorted: drawn as stored")
            t2 = time.perf_counter()
            self.fig.canvas.draw()
            if not _again and self._spills():
                # Text that still doesn't fit (rare: the layout leaves room for wide tick labels):
                # lay out again, once.
                self._lay_out()
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
            ks = [k for k in ks if self.visible[k]]      # only the traces drawn can be picked
            idx = self._near(x, is_sorted, px)
            if not ks:
                continue
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
