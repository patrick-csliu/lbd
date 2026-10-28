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
import dataclasses
import json
import re
import secrets
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import lbd
from lbd.plot import render as rnd
from lbd.plot.reduce import STATS, CurvePyramid, MapPyramid, cell_edges, curve_minmax, thin_in_order
from lbd.plot.style import Style
from lbd.plot.units import prefix_scale

from . import equations
from . import operations as ops_mod

KINDS = ("curve", "heatmap")
UNSORTED_LIMIT = 200_000   # a curve with unsorted x and more points than this is thinned for drawing
# Above this many curves on screen, they are painted into one picture with Pillow (paint_lines)
# instead of drawn line by line: matplotlib needs ~0.7 ms per line, so 1000 curves would take most
# of a second; Pillow paints them in a few tens of milliseconds (without antialiasing).
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


class ExploreClosed(ExploreError):
    """The session was closed (unused for a while, or its page moved on) while a request used it."""


def paint_lines(lines, colors: np.ndarray, width: int, height: int, thickness: float) -> np.ndarray:
    """Paint polylines into an RGBA picture (height × width), in order, later lines on top.

    `lines`: (px, py) per line in pixels of the picture (x to the right, y down), NaN breaking a
    line; `colors`: RGBA (0-255) per line. Uses Pillow's line drawing (C, no antialiasing)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w = max(1, int(round(thickness)))
    for (px, py), color in zip(lines, colors):
        ok = np.isfinite(px) & np.isfinite(py)
        # each unbroken stretch is one polyline
        bounds = np.flatnonzero(np.diff(np.r_[False, ok, False].astype(np.int8)))
        fill = tuple(int(c) for c in color)
        for a, b in zip(bounds[0::2], bounds[1::2]):
            pts = np.column_stack([px[a:b], py[a:b]]).ravel()
            if b - a == 1:                                 # a single point: a dot
                pts = np.r_[pts, pts]
            draw.line(pts.tolist(), fill=fill, width=w)
    return np.asarray(img)


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
        self.spec, self.base_kind = new, new["kind"]
        # The plot as prepared from the data; operations (view setting "ops") draw a model made
        # from it (operations.py), the base model stays for the stored values.
        prepare = rnd.prepare_curves if self.base_kind == "curve" else rnd.prepare_map
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            self.base_model = prepare(self.data, self.spec, self.style)
        self.raw_model = self.base_model                 # the file's data: read-outs' stored values
        self.complex_key: Optional[str] = None
        self.model = self.base_model
        self.ops_key: Optional[str] = None
        self.ops_result: Optional[ops_mod.Result] = None
        self.ops_shown: Optional[ops_mod.Shown] = None
        self.ops_list: List[Dict[str, Any]] = []
        self.eq_legend: Optional[List[Dict[str, str]]] = None
        self.eq_state: Dict[str, Dict[str, str]] = {}
        self.settings: Dict[str, Any] = {}               # view settings (apply), reset with the plot
        self._build()

    def _build(self) -> None:
        """Set the figure up for `self.model` (the base model, or the one after operations)."""
        self.kind = "curve" if isinstance(self.model, rnd.CurveModel) else "heatmap"
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            self.fig.clear()
            self.fig.set_layout_engine("constrained")
            self.ax = self.fig.add_subplot()
            if self.kind == "curve":
                self.model = self._units_apart(self.model)
                self._setup_curves()
            else:
                self._setup_map()
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
            wide = FuncFormatter(lambda v, pos: WIDEST_TICK)
            wide.set_offset_string("1e−8")              # room for a multiplier too (tiny ranges)
            a.set_major_formatter(wide)
        self.fig.set_layout_engine("constrained")
        self.fig.canvas.draw()
        self.fig.set_layout_engine("none")
        for a, formatter in kept:
            a.set_major_formatter(formatter)

    # -- setup

    def _units_apart(self, m: "rnd.CurveModel") -> "rnd.CurveModel":
        """Values of two units in one plot (plan 4): the second unit's curves get a right-hand
        axis. They are drawn scaled onto the left axis (so zooming, picking and cursors work on
        one axis) and the right axis shows their own numbers. The model returned carries
        `units_apart`: per line (scale, offset) with drawn = stored × scale + offset, the right
        axis' lines, label and mapping; None when the plot has one unit. A third unit can't be
        shown (an ExploreError says to use another panel). Operations and equations give one
        quantity (no unit), so they show one axis."""
        if getattr(m, "units_apart", None):
            return m                                     # already worked out for this model
        values = self.spec["values"]
        operated = self.ops_result is not None and self.ops_result.applied > 0
        if len(values) < 2 or len(m.lines) != len(values) or operated:
            return m
        units = [self._plotted_unit(v) for v in values]
        distinct = list(dict.fromkeys(units))
        if len(distinct) < 2:
            return m
        if len(distinct) > 2:
            raise ExploreError(f"these values have three units ({', '.join(u or 'no unit' for u in distinct)}); a panel "
                               "shows two (left and right axis): show the third value in another panel")
        stored = [np.asarray(y, dtype=float) / m.yf for y, _ in m.lines]
        groups = [[k for k, u in enumerate(units) if u == g] for g in distinct]
        scaled, names = [], []
        for g, unit in zip(groups, distinct):
            allv = np.concatenate([stored[k] for k in g])
            f, shown_unit = prefix_scale(allv[np.isfinite(allv)], unit, "auto", warn=False)
            scaled.append((f, shown_unit))
            names.append(", ".join(m.lines[k][1] for k in g))
        (f1, u1), (f2, u2) = scaled
        left = np.concatenate([stored[k] * f1 for k in groups[0]])
        right = np.concatenate([stored[k] * f2 for k in groups[1]])
        left, right = left[np.isfinite(left)], right[np.isfinite(right)]
        a, b = 1.0, 0.0
        if left.size and right.size:
            if left.min() > 0 and right.min() > 0:       # ratios kept: a log scale shows both
                a = float(np.sqrt(left.min() * left.max()) / np.sqrt(right.min() * right.max()))
            else:                                        # the right's range over the left's
                span_l, span_r = np.ptp(left) or 1.0, np.ptp(right) or 1.0
                a = float(span_l / span_r)
                b = float(left.min() - a * right.min())
        per_line = [(f1, 0.0) if k in groups[0] else (f2 * a, b) for k in range(len(m.lines))]
        lines = [(stored[k] * sc + off, label) for k, ((_, label), (sc, off)) in enumerate(zip(m.lines, per_line))]
        out = dataclasses.replace(m, lines=lines, yf=f1, ylim=None,
                                  y_label=f"{names[0]} ({u1})" if u1 else names[0])
        out.units_apart = {"per_line": per_line, "right": groups[1], "a": a, "b": b, "f2": f2,
                           "label": f"{names[1]} ({u2})" if u2 else names[1]}
        return out

    def _plotted_unit(self, name: str) -> str:
        """A value's unit as plotted (after the complex mode: dB, rad …)."""
        v = self.data.values[name]
        probe = np.array([1 + 1j]) if np.iscomplexobj(v.data) else np.array([1.0])
        return rnd.apply_complex(probe, v.label or v.name, v.unit, self.spec["complex"])[2]

    def _setup_curves(self):
        m = self.model
        # Lines that share one x (x is an axis) are reduced and picked together; with a value as x
        # each line has its own. Unsorted x (e.g. one value against another) is drawn as stored.
        groups: Dict[int, Tuple[np.ndarray, List[int]]] = {}
        for k, x in enumerate(m.xs):
            groups.setdefault(id(x), (np.asarray(x, dtype=float), []))[1].append(k)
        self.x_groups = [(x, ks, _is_sorted(x)) for x, ks in groups.values()]
        # Many curves on one sorted x without gaps in x: min/max blocks made once (CurvePyramid)
        self.pyramids = {id(x): CurvePyramid(x, np.stack([m.lines[k][0] for k in ks]))
                         for x, ks, ok in self.x_groups if ok and len(ks) > 1 and x.size > 4096
                         and np.all(np.isfinite(x)) and x[0] < x[-1]}
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
        apart = getattr(m, "units_apart", None)
        if apart:
            a, b = apart["a"], apart["b"]
            right = self.ax.secondary_yaxis("right", functions=(lambda d: (d - b) / a, lambda r: r * a + b))
            colour = self.lines[apart["right"][0]].get_color()
            right.set_ylabel(apart["label"], color=colour)
            right.tick_params(colors=colour)
            for k in apart["right"]:
                self.lines[k].set_linestyle("--")
            legend = self.ax.get_legend()
            right_labels = {m.lines[k][1] for k in apart["right"]}
            for handle, text in zip(legend.legend_handles if legend else [], legend.get_texts() if legend else []):
                if text.get_text() in right_labels:
                    handle.set_linestyle("--")
        self.full = (_finite_range([x for x, _, _ in self.x_groups]), m.ylim if m.ylim and None not in m.ylim
                     else self._padded(_finite_range([y for y, _ in m.lines])))

    def _setup_map(self):
        m = self.model
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
        axis = self.spec.get("series") if self.base_kind == "curve" else self.spec.get("y")
        select = settings.get("select") or {}
        chosen: Optional[set] = None
        for name, positions in select.items():
            if name != axis:
                where = "the series axis" if self.base_kind == "curve" else "the map's vertical axis"
                raise ExploreError(f"traces can be chosen along {where} ('{axis}') only, not '{name}'")
            n = len(self.data.axes[name].data)
            kept = [i for i in positions if isinstance(i, int) and 0 <= i < n]
            if len(kept) < len(positions):
                notes.append(f"{len(positions) - len(kept)} chosen positions of '{name}' no longer exist; left out")
            chosen = set(kept)
        try:
            op_list = ops_mod.check(settings.get("ops"))
            if settings.get("ops_on") is False:          # the section's switch: all off, the list kept
                op_list = [{**op, "on": False} for op in op_list]
            eqs = settings.get("equations") or {}
            if not isinstance(eqs, dict) or any(k not in ("x", "y", "z") or not isinstance(v, str) for k, v in eqs.items()):
                raise ExploreError("equations are {x, y, z}: text each")
            if settings.get("ops_on") is False:          # off with the operations
                eqs = {}
            changed = self._apply_ops(op_list, chosen, {k: v for k, v in eqs.items() if v.strip()})
        except ops_mod.BadOps as e:
            raise ExploreError(str(e)) from None
        if changed:
            self.settings = {}                           # a new figure: every setting again
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            if self.kind == "curve":
                per = len(self.data.axes[axis].data) if axis else 1
                if self.base_kind != "curve" or len(self.model.lines) != len(self.base_model.lines):
                    per, chosen = 1, None                # other traces after an operation: all shown
                self.visible = [chosen is None or k % per in chosen for k in range(len(self.model.lines))]
                for artist, shown in zip(self.lines, self.visible):
                    artist.set_visible(shown)
            self.log_refused: List[str] = []
            if self.kind != "curve":
                self._apply_map(settings, chosen if self.base_kind == "heatmap" else None, clim)
            for key, which, base in (("xscale", "horizontal", self.base_scales[0]),
                                     ("yscale", "vertical", self.base_scales[1])):
                want = settings.get(key, base)
                if want == "log" and not self._has_positive(which):
                    want = "linear"                      # nothing could be drawn on a log axis
                    self.log_refused.append(f"The {which} axis has no value above 0, so it stays linear.")
                (self.ax.set_xscale if key == "xscale" else self.ax.set_yscale)(want)
            self.full = self._full_view()
        self.settings = settings
        return notes

    def _has_positive(self, which: str) -> bool:
        """Whether the data shown has a value above 0 along this axis (else a log scale shows nothing)."""
        m = self.model
        if self.kind == "curve":
            shown = [k for k, v in enumerate(self.visible) if v]
            arrays = [m.xs[k] if which == "horizontal" else m.lines[k][0] for k in shown]
        else:
            arrays = [m.x if which == "horizontal" else m.y]
        with np.errstate(invalid="ignore"):
            return any(bool(np.any(np.isfinite(v := np.asarray(a, dtype=float)) & (v > 0))) for a in arrays)

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        """What the scales hide (points ≤ 0 on a log scale, …), and why nothing is shown when
        nothing can be: notes the page keeps on screen. Worked out once per model and scales."""
        key = (id(self.model), tuple(self.visible), self.ax.get_xscale(), self.ax.get_yscale(),
               self.settings.get("cscale"), tuple(getattr(self, "log_refused", [])))
        if key == getattr(self, "_hidden_key", None):
            return self._hidden_value
        notes = list(getattr(self, "log_refused", []))
        m, empty = self.model, None
        xlog, ylog = self.ax.get_xscale() == "log", self.ax.get_yscale() == "log"
        with np.errstate(invalid="ignore"):
            if self.kind == "curve":
                shown = [k for k, v in enumerate(self.visible) if v]
                # stops at the first trace with a value: cheap however many points there are
                if not any(np.isfinite(np.asarray(m.lines[k][0], dtype=float)).any() for k in shown):
                    empty = self._why_empty("point")
                if xlog or ylog:                         # counting what a log scale hides: only then
                    pairs = [(np.asarray(m.xs[k], dtype=float), np.asarray(m.lines[k][0], dtype=float)) for k in shown]
                    ok = [np.isfinite(x) & np.isfinite(y) for x, y in pairs]
                    if xlog and (n := sum(int(((x <= 0) & o).sum()) for (x, _), o in zip(pairs, ok))):
                        notes.append(f"{n} point{'s' * (n != 1)} at x ≤ 0 aren't shown on the log horizontal axis.")
                    if ylog and (n := sum(int(((y <= 0) & o).sum()) for (_, y), o in zip(pairs, ok))):
                        notes.append(f"{n} point{'s' * (n != 1)} ≤ 0 aren't shown on the log vertical axis.")
            else:
                z = np.asarray(m.z, dtype=float)
                finite = np.isfinite(z)
                if not finite.any():
                    empty = self._why_empty("cell")
                if xlog and (n := int((np.asarray(m.x) <= 0).sum())):
                    notes.append(f"{n} column{'s' * (n != 1)} at x ≤ 0 aren't shown on the log horizontal axis.")
                if ylog and (n := int((np.asarray(m.y) <= 0).sum())):
                    notes.append(f"{n} row{'s' * (n != 1)} at y ≤ 0 aren't shown on the log vertical axis.")
                if self.settings.get("cscale") == "log" and (n := int(((z <= 0) & finite).sum())):
                    notes.append(f"{n} cell{'s' * (n != 1)} ≤ 0 aren't shown on the log colour scale.")
        self._hidden_key, self._hidden_value = key, (notes, empty)
        return notes, empty

    def _why_empty(self, what: str) -> str:
        r = self.ops_result
        if r is not None and r.applied:
            return (f"Nothing to show: no {what} of '{r.grid.value.label}' has a value. The operations made "
                    "it so (e.g. Normalize of a constant trace); change them, or turn them off for the stored data.")
        return f"Nothing to show: no {what} of the data shown has a value (they are all missing)."

    def _apply_ops(self, ops: List[Dict[str, Any]], chosen: Optional[set], eqs: Dict[str, str]) -> bool:
        """Run the operations (on the chosen traces), then the equations, when any of them or the
        choice changed; True when the figure was set up again for another model."""
        key = json.dumps([ops, sorted(chosen) if chosen is not None else None, eqs])
        if key == self.ops_key:
            return False
        self.ops_key, self.ops_list = None, ops
        self._apply_complex(ops)
        model, result, shown = self.base_model, None, None
        self.eq_state: Dict[str, Dict[str, str]] = {}
        if any(op["on"] for op in ops) or eqs:
            base = ops_mod.grid_of(self, chosen)
            iq = next((op for op in ops if op["op"] == "iq_histogram" and op["on"]), None)
            start = base
            if iq is not None:
                try:
                    start = ops_mod.iq_grid(self.complex_data, self.spec, self.base_kind, chosen, iq["bins"])
                except ops_mod.OpError as e:
                    result = ops_mod.Result(base, [str(e) if o is iq else None for o in ops], 0)
            if result is None:
                result = ops_mod.run(start, ops, iq_done=start is not base)
            before = result.grid if result.applied else base
            self.eq_legend = equations.names_of(self, before, arrays=False)[1]
            if eqs:
                after, self.eq_state, _ = equations.apply(self, before, eqs)
                done = sum(1 for f in eqs if f in self.eq_state and "error" not in self.eq_state[f])
                if done:
                    result = ops_mod.Result(after, result.notes, result.applied + done)
            if result.applied:
                model, shown = ops_mod.model_of(self, base, result.grid)
        else:
            self.eq_legend = None                        # worked out when asked for (ops_info)
        self.ops_result, self.ops_shown = result, shown
        if model is self.model:
            self.ops_key = key
            return False
        self.model = model
        self._build()
        self.ops_key = key
        return True

    def _per_value(self) -> int:
        series = self.spec.get("series")
        return len(self.data.axes[series].data) if series else 1

    def _apply_complex(self, ops: List[Dict[str, Any]]) -> None:
        """Delay, rotation, auto-rotate: the plot prepared again from the corrected complex values
        (only when they changed); then the other operations start from it."""
        cx = [op for op in ops if op["op"] in ("delay", "rotation", "auto_rotate") and op["on"]]
        key = json.dumps(cx)
        if key == self.complex_key:
            return
        self.complex_key = key
        self.complex_data = ops_mod.complex_data(self.data, self.spec, cx)
        if self.complex_data is self.data:
            self.base_model = self.raw_model
            return
        prepare = rnd.prepare_curves if self.base_kind == "curve" else rnd.prepare_map
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()), warnings.catch_warnings():
            warnings.simplefilter("ignore", rnd.RenderWarning)     # the same data, warned about at opening
            self._check_open()
            self.base_model = prepare(self.complex_data, self.spec, self.style)

    def calculate(self, what: str, index: int, xlim: Sequence[float], trace: Optional[int]) -> Dict[str, Any]:
        """Delay or rotation for operation `index` from the data in x range `xlim` (plot units) of
        cursor 1's trace (or all shown traces); see operations.calculate."""
        ops = self.ops_list
        if not 0 <= index < len(ops) or ops[index]["op"] != what:
            raise ExploreError(f"operation {index + 1} is not a {what}")
        m = self.raw_model
        xf = m.xf
        traces = None
        if trace is not None and self.base_kind == "curve":
            traces = [int(trace) % self._per_value()]
        try:
            out = ops_mod.calculate(self.data, self.spec, self.base_kind, ops, index, what,
                                    [v / xf for v in xlim], traces)
        except ops_mod.BadOps as e:
            raise ExploreError(str(e)) from None
        return out

    def ops_info(self) -> Dict[str, Any]:
        """For the page: each operation's state (None: applied, "off", or why not), each equation
        field's (error or note), what is shown, and the names equations can use (the legend)."""
        r = self.ops_result
        if getattr(self, "eq_legend", None) is None:      # nothing applied: the legend of the plain plot
            self.eq_legend = equations.names_of(self, ops_mod.grid_of(self, None), arrays=False)[1]
        info: Dict[str, Any] = {"notes": r.notes if r else ["off"] * len(self.ops_list), "applied": r.applied if r else 0,
                                "equations": getattr(self, "eq_state", {}), "names": self.eq_legend}
        if r is not None and r.applied and self.ops_shown is not None:
            info["shows"] = r.grid.value.label
            info["unit"] = self.ops_shown.value_unit
            info["one_to_one"] = r.grid.one_to_one
        return info

    def _apply_map(self, settings: Dict[str, Any], chosen: Optional[set], clim) -> None:
        old = (self.settings.get("select") or {}).get(self.spec.get("y"))
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
            if log and not z.size:
                log = False                              # nothing above 0: a log scale would show nothing
                self.log_refused.append("The map has no value above 0, so the colour scale stays linear.")
                z = self.model.z[np.isfinite(self.model.z)]
                lo = clim[0] if clim[0] is not None else (float(z.min()) if z.size else 0.0)
                hi = clim[1] if clim[1] is not None else (float(z.max()) if z.size else 1.0)
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
            lo, hi = _finite_range(arrays)
            if log and lo <= 0:                          # one value (or none): a decade around it
                return (hi / 10, hi * 10) if hi > 0 else (0.1, 10.0)
            return lo, hi

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

    def _fast_picture(self, pxe: np.ndarray, w: int, h: int, draft: bool) -> bool:
        """Many curves on one x, reduced to pixel columns by their pyramid: drawn straight from
        each column's lowest and highest value (no lists of points). False when this doesn't
        apply (few curves, several x, or zoomed in to the stored points)."""
        shown = [k for k, v in enumerate(self.visible) if v]
        if len(shown) <= RASTER_ABOVE or len(self.x_groups) != 1 or id(self.x_groups[0][0]) not in self.pyramids:
            return False
        spans = self.pyramids[id(self.x_groups[0][0])].spans(pxe)
        if spans is None:
            return False
        lo, hi = spans
        ys, yl = self.ax.get_yscale(), self.ax.get_ylim()

        def rows(v):                                      # data -> pixel rows (y down)
            f = (lambda a: np.log10(np.where(a > 0, a, np.nan))) if ys == "log" else (lambda a: a)
            a, b = f(np.asarray(yl, dtype=float))
            return h - (f(v) - a) / (b - a) * h

        width = self.lines[shown[0]].get_linewidth() * self.fig.dpi / 72 * (0.5 if draft else 1.0)
        # each column's lowest and highest value, joined column to column: as the curves look
        xx = np.repeat(np.arange(w) + 0.5, 2)
        yy = np.empty((len(shown), 2 * w))
        yy[:, 0::2], yy[:, 1::2] = rows(lo[shown]), rows(hi[shown])
        self.line_image.set_data(paint_lines([(xx, y) for y in yy], self.line_colors[shown], w, h, width))
        self.line_image.set_visible(True)
        for artist in self.lines:
            artist.set_visible(False)
        # what was drawn, for highlighting a picked curve: per column its lowest and highest value
        self.spans = (np.repeat((pxe[:-1] + pxe[1:]) / 2, 2), lo, hi)
        self.last_lines = None
        return True

    def _drawn(self, k: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Curve k as drawn in the last picture (x, y in plot units), for highlighting it."""
        if getattr(self, "spans", None) is not None:
            xx, lo, hi = self.spans
            yy = np.empty(xx.size)
            yy[0::2], yy[1::2] = lo[k], hi[k]
            return xx, yy
        return self.last_lines[k] if self.last_lines is not None else None

    def _group(self, x: np.ndarray) -> List[int]:
        return next(ks for gx, ks, _ in self.x_groups if gx is x)

    def _plain_tick_numbers(self) -> None:
        """Tick numbers as plain text, not math text: they look the same, but every new label
        (each zoom step makes some) would otherwise be parsed as math, ~50 ms per picture. Log
        axes keep their math text (10 to a power), whose few labels repeat."""
        from matplotlib.ticker import ScalarFormatter

        for ax in self.fig.axes:
            for axis in (ax.xaxis, ax.yaxis):
                f = axis.get_major_formatter()
                if isinstance(f, ScalarFormatter) and f.get_useMathText():
                    f.set_useMathText(False)

    def _raster(self, lines, shown: List[int], w: int, h: int, scale: float = 1.0) -> None:
        """Draw the curves `shown` into one picture of the plot area (w × h pixels; `scale`: its
        pixels per screen pixel, below 1 for a draft), in their colours, later curves on top, as
        matplotlib would draw them (without antialiasing)."""
        def to_px(v, lim, scale, size):
            f = (lambda a: np.log10(np.where(a > 0, a, np.nan))) if scale == "log" else (lambda a: a)
            a, b = f(np.asarray(lim, dtype=float))
            return (f(np.asarray(v, dtype=float)) - a) / (b - a) * size

        xs, ys = self.ax.get_xscale(), self.ax.get_yscale()
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        width = (self.lines[shown[0]].get_linewidth() * self.fig.dpi / 72 if shown else 1.0) * scale
        px = [(to_px(lines[k][0], xl, xs, w), h - to_px(lines[k][1], yl, ys, h)) for k in shown]
        self.line_image.set_data(paint_lines(px, self.line_colors[shown], w, h, width))

    def _plot_area(self) -> Tuple[int, int, int, int]:
        """The axes' box in image pixels: left, top, width, height (top-left origin)."""
        bb = self.ax.get_window_extent()
        h = int(round(self.fig.bbox.height))
        left, right = int(round(bb.x0)), int(round(bb.x1))
        top, bottom = h - int(round(bb.y1)), h - int(round(bb.y0))
        return left, top, max(right - left, 1), max(bottom - top, 1)

    def _spills(self) -> bool:
        """Whether some text of the last drawing sticks out of the picture. Only the plot's tick
        labels and multipliers change while zooming; they were just measured by the drawing."""
        r = self.fig.canvas.get_renderer()
        box = self.fig.bbox
        a = self.ax
        texts = [a.xaxis.get_offset_text(), a.yaxis.get_offset_text()]
        for labels, locs, (lo, hi) in ((a.get_xticklabels(), a.get_xticks(), sorted(a.get_xlim())),
                                       (a.get_yticklabels(), a.get_yticks(), sorted(a.get_ylim()))):
            # only the ticks drawn: matplotlib also keeps labels for ticks just outside the view
            texts += [t for t, v in zip(labels, locs) if lo <= v <= hi]
        for t in texts:
            if not t.get_visible() or not t.get_text():
                continue
            tb = t.get_window_extent(r)
            # a few pixels over the edge are harmless (antialiased glyph edges, the top tick label)
            if tb.x0 < box.x0 - 4 or tb.y0 < box.y0 - 4 or tb.x1 > box.x1 + 4 or tb.y1 > box.y1 + 4:
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
        self._check_open()
        w, h = self.fig.get_size_inches()
        if (round(w * 96), round(h * 96), self.dpr) == (width, height, dpr):
            return
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            self.dpr = dpr
            self.fig.set_dpi(96 * dpr)
            self.fig.set_size_inches(width / 96, height / 96)
            self.ax.set_xlim(*self.full[0])
            self.ax.set_ylim(*self.full[1])
            self._lay_out()

    def render(self, xlim: Optional[Tuple[float, float]], ylim: Optional[Tuple[float, float]],
               stat: str = "max", fmt: str = "raw", draft: bool = False,
               _again: bool = False) -> Tuple[bytes, Dict[str, Any]]:
        """A picture of a view. `draft` (while the user zooms or pans): the data is reduced to half
        the pixels each way, which is about four times less work; the axes and text are drawn as
        always, so the picture is complete and its axes match its data. The sharp picture follows
        when the user stops."""
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
            self._check_open()
            t1 = time.perf_counter()
            self.last_used = time.monotonic()
            self.ax.set_xlim(*xlim)
            self.ax.set_ylim(*ylim)
            self._plain_tick_numbers()
            left, top, w, h = self._plot_area()
            dw, dh = (max(w // 2, 1), max(h // 2, 1)) if draft else (w, h)
            pxe, pye = self._pixel_edges(dw, dh)
            if self.kind == "heatmap":
                r = self.pyramid.raster(pxe, pye, stat)
                self.image.set_data(r.image)
                note, reduced = r.note(), r.reduced
            elif self._fast_picture(pxe, dw, dh, draft):
                note, reduced = "min and max per pixel column", True
            else:
                self.spans = None
                ys = [y for y, _ in self.model.lines]
                lines: List[Tuple[np.ndarray, np.ndarray]] = [None] * len(ys)   # type: ignore[list-item]
                reduced = unsorted = thinned = False
                for x, ks, is_sorted in self.x_groups:
                    for k in ks:                         # left-out traces: nothing to draw
                        lines[k] = (x[:0], ys[k][:0])
                    ks = [k for k in ks if self.visible[k]]
                    if not ks:
                        continue
                    if is_sorted and id(x) in self.pyramids and len(ks) == len(self._group(x)):
                        out, red = self.pyramids[id(x)].minmax(pxe)
                        reduced |= red
                    elif is_sorted:
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
                    self._raster(lines, shown, dw, dh, 0.5 if draft else 1.0)
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
                    return self.render(xlim, ylim, stat, fmt, draft, _again=True)
            rgba = np.asarray(self.fig.canvas.buffer_rgba())
            t3 = time.perf_counter()
        height, width = rgba.shape[:2]
        hidden, empty = self.hidden()
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
            "note": note, "reduced": reduced, "stat": stat, "draft": draft, "ops": self.ops_info(),
            "hidden": hidden, "empty": empty, "sync": self.sync_keys(),
            "ms": {"wait": round((t1 - t0) * 1000, 1), "reduce": round((t2 - t1) * 1000, 1),
                   "draw": round((t3 - t2) * 1000, 1), "encode": round((t4 - t3) * 1000, 1)},
        }
        return body, meta

    def sync_keys(self) -> Dict[str, str]:
        """What panels must share to follow each other's zoom (plan 4): the horizontal axis as
        drawn (its label, unit prefix included: an equation or an FFT changes it), and the
        vertical axis (maps: its label; curves: its unit, prefix included)."""
        ylabel = self.ax.get_ylabel()
        if self.kind == "heatmap":
            y = ylabel
        else:
            m = re.search(r"\(([^()]*)\)\s*$", ylabel)
            y = m.group(1) if m else ""
        return {"x": self.ax.get_xlabel(), "y": y}

    # -- picking

    def _to_px(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Data (plot units) to image pixels, top-left origin."""
        pts = self.ax.transData.transform(np.column_stack([np.ravel(x), np.ravel(y)]))
        return pts[:, 0], self.fig.bbox.height - pts[:, 1]

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        """The stored point (curves) or cell (maps) at image pixel (px, py), from the full data."""
        self.last_used = time.monotonic()
        with rnd.RENDER_LOCK:
            self._check_open()
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
        drawn = self._drawn(k)
        if drawn is not None:
            lx, ly = drawn
            hx, hy = self._to_px(lx, ly)
            out["line"] = [[float(a), float(b)] if np.isfinite(b) else None for a, b in zip(hx, hy)]
        return out

    def _check_open(self) -> None:
        if self.fig is None:
            raise ExploreClosed("this Explore view was closed on the server (unused for a while, or the "
                                "viewer restarted); it reopens by itself")

    def close(self):
        """Free the figure; a request still using the session then gets ExploreClosed."""
        with rnd.RENDER_LOCK:
            self.fig = None


class Sessions:
    """The open Explore sessions, by id. Old ones are closed after `idle` seconds without use,
    and at most `limit` are open (each holds a file's data and a figure; each panel of a file is
    one session, so a few files with four panels each fit). A closed one reopens when used."""

    def __init__(self, limit: int = 24, idle: float = 600.0):
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
