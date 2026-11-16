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
import functools
import json
import re
import secrets
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import lbd
from lbd.plot import render as rnd
from lbd.plot.reduce import STATS, CurvePyramid, MapPyramid, cell_edges, curve_minmax, in_view, occupied_points, thin_in_order
from lbd.plot.style import Style
from lbd.plot.units import prefix_scale

from . import crange as crange_mod, equations, kinds, memory, summaries
from . import operations as ops_mod

KINDS = tuple(k for k in rnd.kinds.KINDS if k in kinds.interactions())
UNSORTED_LIMIT = 200_000   # a curve with unsorted x and more points than this is thinned for drawing
# Above this many curves on screen, they are painted into one picture with Pillow (paint_lines)
# instead of drawn line by line: matplotlib needs ~0.7 ms per line, so 1000 curves would take most
# of a second; Pillow paints them in a few tens of milliseconds (without antialiasing).
RASTER_ABOVE = 30
# Show points (16.39): finding the dots reads every stored point in view. Measured on 1000 traces
# of 10 000 points: about 100 ms more per picture at 1.6 million points in view, 380 ms at all
# 10 million (one curve of 1 million: 25 ms). Above this many points in view the dots are left
# out, with a note, so a picture stays quick.
DOTS_LIMIT = 1_500_000
# Tick labels the layout makes room for, so zooming (more digits) never needs a new layout.
WIDEST_TICK = "\u22128.888888"
# A colour bar's tick labels (its range changes with the data, not with zooming), and the part of
# the last x tick label that hangs over the plot's right edge (half of a label this wide).
COLORBAR_TICK = "\u22128888"
OVERHANG_TICK = "\u221288.88"
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


def paint_lines(lines, colors: np.ndarray, width: int, height: int, thickness: float,
                dots: Optional[Sequence[Tuple[np.ndarray, np.ndarray]]] = None, dot_size: int = 2) -> np.ndarray:
    """Paint polylines into an RGBA picture (height × width), in order, later lines on top.

    `lines`: (px, py) per line in pixels of the picture (x to the right, y down), NaN breaking a
    line; `colors`: RGBA (0-255) per line. Uses Pillow's line drawing (C, no antialiasing).
    `dots` (Show points, 16.39): (px, py) per line, each a square of `dot_size` pixels in the
    line's colour, painted over the lines, later lines' dots on top."""
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
    out = np.array(img)
    if dots:
        _paint_dots(out, dots, colors, dot_size)
    return out


def _paint_dots(out: np.ndarray, dots: Sequence[Tuple[np.ndarray, np.ndarray]], colors: np.ndarray, size: int) -> None:
    """Paint squares of `size` pixels around the dots of each line into `out` (height × width ×
    4), in the line's colour; where dots of several lines meet, the later line's. All lines at
    once with numpy: Pillow would take a call per pixel of the square and line."""
    height, width = out.shape[:2]
    counts = [len(px) for px, _ in dots]
    if not sum(counts):
        return
    line = np.repeat(np.arange(len(dots)), counts)
    # each dot's top-left pixel (px - pad/2 rounded down), on a grid with room for squares that
    # start above or left of the picture: shifted by pad, so dots in the picture never round below 0
    pad = size - 1
    left = (np.concatenate([px for px, _ in dots]) + pad / 2).astype(np.int64)
    top = (np.concatenate([py for _, py in dots]) + pad / 2).astype(np.int64)
    ok = (left >= 0) & (left < width + pad) & (top >= 0) & (top < height + pad)
    corner = np.full((height + pad, width + pad), -1, dtype=np.int64)   # the last line with a dot there
    np.maximum.at(corner.reshape(-1), top[ok] * (width + pad) + left[ok], line[ok])
    # a pixel shows the last line of the dots whose square covers it: its corner up to size-1 pixels up and left
    owner = np.full((height, width), -1, dtype=np.int64)
    for i in range(size):
        for j in range(size):
            np.maximum(owner, corner[pad - j:pad - j + height, pad - i:pad - i + width], out=owner)
    painted = owner >= 0
    out[painted] = colors[owner[painted]]


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


def full_text(label: Any) -> str:
    """A label's whole text, also when the layout shortened it to fit (`_shorten`); a text set
    anew since then (another plot) is taken as it is."""
    shown = label.get_text()
    return label._lbd_full if getattr(label, "_lbd_shown", None) == shown and hasattr(label, "_lbd_full") else shown


def _locked(method):
    """Run a session's step under the session's own lock (16.22): a change of the plot
    (`set_spec`) and a picture or read-out never overlap, so a step never sees the new kind with
    the old plot. The session lock is always taken before lbd.plot's RENDER_LOCK."""
    @functools.wraps(method)
    def run(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return run


class ExploreSession:
    """One Explore tab's view of a file. Create with `open_session`; all drawing happens in
    `render`, under the render lock. Every step that reads or changes the session holds
    `self.lock` (an RLock: the server holds it across several steps of one request)."""

    def __init__(self, path: Path, version: str, spec: Dict[str, Any], style: Style,
                 width: int, height: int, dpr: float, saved_view: bool = True, summarise: bool = True,
                 bare: bool = False, looks: Optional[Callable[[], Dict[str, Dict[str, bool]]]] = None):
        """`saved_view` False: the file's saved figure view (/plot) is not used at all (the
        Library's automatic previews, plan 8c, depend on the data only). `summarise` False: a
        map bigger than memory is refused instead of summarised (previews, drawn in the
        background, never start reading a whole large file). `bare` True: only the data, filling
        the picture: no axes, tick labels, axis labels, colour bar, legend or second axis (the
        Library's previews: a thumbnail of the data, small and the same for every file)."""
        if width < 50 or height < 50:
            raise ExploreError(f"the plot area is too small ({width}×{height} px); make the window larger")
        self.lock = threading.RLock()
        self.id = secrets.token_urlsafe(9)
        self.path, self.version, self.style = path, version, style
        self.saved_view = saved_view
        self.summarise = summarise
        self.looks = looks                            # Settings → Explore: look options a plot starts with (18.2)
        self.bare = bare
        self._memory_said = False                     # the low-memory note: told once per session
        self._notes: List[str] = []
        self.last_used = time.monotonic()
        self.header = self._read(lbd.info(path))
        # the file's data as read (flat view); `self.data` is what the plot kind draws from it
        # (curves: a variable sweep on its real axes, 16.41)
        self.flat_data = self._read(lbd.load(path, values=[]))
        self.data = self.flat_data
        self.dpr = float(min(max(dpr, 1.0), MAX_DPR))
        dpi = 96 * self.dpr                           # 1 CSS pixel = 1/96 inch, as in browsers
        self.fig = Figure(figsize=(width / 96, height / 96), dpi=dpi)
        FigureCanvasAgg(self.fig)
        self.set_spec(spec)

    @_locked
    def set_spec(self, spec: Dict[str, Any]) -> None:
        """Show other plot settings (values, kind, axes, slices, complex mode). The data already
        read is kept; values not read yet are read now."""
        with warnings.catch_warnings():               # the same checks run again on the loaded data
            warnings.simplefilter("ignore", rnd.RenderWarning)
            resolved = rnd.resolve_spec(self.header, spec, warn_unused=False)
        needed = rnd.needed_values(self.header, resolved)
        loaded = [n for n, v in self.flat_data.values.items() if v.data is not None]
        if not set(needed) <= set(loaded):
            # whole if they fit in the memory available, else read by part (plan 6d, memory.py)
            self.flat_data = self._read(memory.load_values(self.path, sorted(set(needed) | set(loaded)), self.version))
        new = rnd.resolve_spec(self.flat_data, spec, warn_unused=False)
        self.data = rnd.for_kind(self.flat_data, new["kind"])
        if new["kind"] not in KINDS:
            raise ExploreError(f"Explore can't show {rnd.kinds.KINDS[new['kind']].title} plots yet; use the Figure page")
        new = self._start_looks(new)
        self.spec, self.base_kind = new, new["kind"]
        # A map with more cells (curves with more points) than the memory available holds is shown
        # from its summary, made once (and kept on disk) by reading the file part by part
        # (summaries.py, plan 6d).
        big = None
        try:
            if self.base_kind == "curve":
                big = self._big_curves(new)
            elif self.base_kind == "heatmap":
                v = self.data.values[new["values"][0]]
                shape = (len(self.data.axes[new["y"]].data), len(self.data.axes[new["x"]].data))
                if new["y"] in v.axes and new["x"] in v.axes and summaries.too_big(shape):
                    if not self.summarise:
                        raise ExploreError(f"this map has {shape[0]:,} × {shape[1]:,} cells, too many for a preview; "
                                           "open it in Explore (it is summarised once, then kept)")
                    big = summaries.shared().summarise(
                        self.path, self.version, summaries.BigMap(v, new["x"], new["y"], new["index"], new["complex"]))
        except summaries.NothingToShrink:
            # a summary would be as large as the data: draw the data itself, read whole
            big = None
            self.flat_data = self._read(lbd.load(self.path, values=sorted(set(needed) | set(loaded))))
            self.data = rnd.for_kind(self.flat_data, new["kind"])
        if big is not None:
            self._note_memory(big)
        # The plot as prepared from the data; operations (view setting "ops") draw a model made
        # from it (operations.py), the base model stays for the stored values.
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            if self.base_kind == "curve":
                self.base_model = rnd.prepare_curves(self.data, self.spec, self.style, big=big, whole_span=True, two_axes=True)
            elif self.base_kind != "heatmap":
                self.base_model = kinds.interactions()[self.base_kind].prepare(self)
            else:
                # colours from every slider position (crange.py): the colour bar's prefix from
                # that range too, so it stays while the slider moves
                now = getattr(self, "settings", None) or {}
                whole = crange_mod.peek(self, now) if now.get("crange") == "all" else None
                self.zspan = (whole.lo, whole.hi) if whole is not None and np.isfinite(whole.lo) else None
                self.base_model = rnd.prepare_map(self.data, self.spec, self.style, big=big, zspan=self.zspan)
                if isinstance(self.base_model, rnd.groupmap.GroupMapModel) and summaries.too_big((self.base_model.z.size, 1)):
                    raise ExploreError("too many points to draw as a map; show it as curves, or save a part")
        for v in self.data.values.values():           # a value read by part: the next slider positions
            if isinstance(v.data, memory.Cached):
                v.data.read_ahead()
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

    def _note_memory(self, big: Any) -> None:
        """Data shown from its summary only because the computer's memory is short now (it would
        fit in what the computer has): say so once, with what to do."""
        if self._memory_said:
            return
        m = memory.shared().memory
        try:
            total, available = m._system()
        except Exception:                               # psutil missing or failing: nothing to tell
            return
        is_map = isinstance(big, summaries.BigMap)
        cells = int(np.prod(big.shape)) if is_map else big.traces * big.points
        if cells * summaries.BYTES_PER_CELL > total - m.reserve():
            return                                      # larger than the computer: summarised anyway
        self._memory_said = True
        what, each = ("map", "cell") if is_map else ("curves", "point")
        self._notes.append(f"This computer has little free memory ({available / memory.GB:.1f} GB free): this {what} "
                           f"is shown from a summary. Close other programs and open the file again to see every {each}.")

    def _start_looks(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """The look options the settings start this plot type with (18.2): one that is on there
        and not chosen in this plot is on. One that is off there is left to the plot (Grid: the
        style; Show points: off), as is one chosen here (a tick in Display)."""
        if self.looks is None:
            return spec
        on = [k for k, v in (self.looks().get(spec["kind"]) or {}).items() if v]
        options = dict(spec.get("options") or {})
        missing = [k for k in on if options.get(k) is None]
        if not missing:
            return spec
        return {**spec, "options": {**options, **{k: True for k in missing}}}

    @_locked
    def take_notes(self) -> List[str]:
        """Notes for the user not told yet (each once)."""
        out, self._notes = self._notes, []
        return out + self.view.notes()

    def _big_curves(self, spec: Dict[str, Any]) -> Optional[summaries.BigCurves]:
        """The curves of `spec` from their summary when their points don't fit in the memory
        available (None when they do); what such curves can't be shown as is refused, saying why."""
        along, series = spec.get("along", spec["x"]), spec.get("series")
        points = len(self.data.axes[along].data)
        traces = (len(self.data.axes[series].data) if series else 1) * len(spec["values"])
        if not summaries.too_big((traces, points)):
            return None
        what = f"these curves have {traces:,} × {points:,} points, more than the memory available"
        if not self.summarise:
            raise ExploreError(f"{what}: too many for a preview; open the file in Explore (they are summarised "
                               "once, then kept)")
        if len(spec["values"]) > 1:
            raise ExploreError(f"{what}; show one value at a time")
        if spec["x"] in self.data.values:
            raise ExploreError(f"{what}; show them against an axis, not against a value")
        if spec["complex"] in ("phase_unwrap", "phase_deg_unwrap"):
            raise ExploreError(f"{what}; an unwrapped phase needs each whole trace: choose the phase (not "
                               "unwrapped), or read the file in a script with lbd.open")
        x = np.asarray(self.data.axes[along].data, dtype=float)
        if not (np.all(np.isfinite(x)) and np.all(np.diff(x) > 0)):
            raise ExploreError(f"{what}; they can be shown only along an increasing axis without gaps, and "
                               f"'{along}' isn't one")
        v = self.data.values[spec["values"][0]]
        return summaries.shared().summarise(
            self.path, self.version, summaries.BigCurves(v, along, series, spec["index"], spec["complex"]))

    def _read(self, d: "lbd.Dataset") -> "lbd.Dataset":
        d = rnd.flat(d)                     # one axis per dimension, a data point's too
        if not self.saved_view:
            d.plot = None
        return d

    def _build(self) -> None:
        """Set the figure up for `self.model` (the base model, or the one after operations)."""
        self.view = kinds.for_session(self)
        self.kind = self.view.kind
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            self.fig.clear()
            self.fig.set_layout_engine("constrained")
            self.ax = self.view.make_axes()
            self.view.setup()
            self.visible = [True] * (len(self.model.lines) if self.kind == "curve" else 0)
            self.base_scales = (self.ax.get_xscale(), self.ax.get_yscale())
            self.full = self._full_view()
            self.ax.set_xlim(*self.full[0])
            self.ax.set_ylim(*self.full[1])
            self.view.lay_out()
        self.highlight: Optional[int] = None
        self.last_lines: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None

    def _lay_out(self) -> None:
        """Place the plot box from the picture's size and the style only (16.37): the margins
        make room for the widest tick labels zooming can bring (WIDEST_TICK), the axis labels,
        the title, a colour bar and a right-hand axis, all measured from their font sizes, never
        from what is drawn now. The same size gives the same box, whatever came before (another
        size, another value, another slider step), and no step needs a new layout. A label too
        long for its room is shortened with "…". Call under the render lock."""
        if self.bare:
            self._bare_out()
            return
        from matplotlib.axes._secondary_axes import SecondaryAxis
        from matplotlib.font_manager import FontProperties

        fig, ax = self.fig, self.ax
        fig.set_layout_engine("none")
        r = fig.canvas.get_renderer()
        W, H = fig.bbox.width, fig.bbox.height
        px = fig.dpi / 72                                 # pixels per point
        family = matplotlib.rcParams["font.family"]

        def size_of(text: str, points: float) -> Tuple[float, float]:
            w, h, _ = r.get_text_width_height_descent(text, FontProperties(family=family, size=points), ismath=False)
            return w, h

        def ticks(axis) -> Tuple[float, float, float]:
            """(tick label size in points, room outside the frame for tick and pad in pixels)."""
            t = axis.get_major_ticks()[0] if axis.get_major_ticks() else None
            labelsize = t.label1.get_fontsize() if t else matplotlib.rcParams["font.size"]
            length = t.tick1line.get_markersize() if t else 3.5
            pad = t.get_pad() if t else 3.5
            outward = matplotlib.rcParams[f"{axis.axis_name}tick.direction"] in ("out", "inout")
            return labelsize, (length if outward else 0) * px + pad * px, length

        def label_room(label) -> float:
            if not label.get_visible() or not label.get_text():
                return 0.0
            lines = label.get_text().count("\n") + 1
            return size_of("Mg", label.get_fontsize())[1] * 1.2 * lines

        edge = 3 * self.dpr
        xsize, xout, _ = ticks(ax.xaxis)
        ysize, yout, _ = ticks(ax.yaxis)
        xtick_w, xtick_h = size_of(WIDEST_TICK, xsize)
        ytick_w, ytick_h = size_of(WIDEST_TICK, ysize)
        xlabel, ylabel = ax.xaxis.label, ax.yaxis.label
        left = edge + ytick_w + yout + (label_room(ylabel) + ax.yaxis.labelpad * px if label_room(ylabel) else 0)
        bottom = edge + xtick_h + xout + (label_room(xlabel) + ax.xaxis.labelpad * px if label_room(xlabel) else 0)
        title = label_room(ax.title)
        top = edge + max(title + matplotlib.rcParams["axes.titlepad"] * px if title else 0, ytick_h * 1.2)
        right = edge + size_of(OVERHANG_TICK, xsize)[0] / 2   # the last x tick label hangs over the frame

        # what stands to the right of the plot: a right-hand axis, a colour bar (its own axes, or
        # inside the plot's as matrices have it)
        cb_style = self.style.figure.axes.image.colorbar
        beside: List[Any] = []
        for other in [*ax.child_axes, *(a for a in fig.axes if a is not ax and a not in ax.child_axes)]:
            if isinstance(other, SecondaryAxis):
                size, out, _ = ticks(other.yaxis)
                right += size_of(WIDEST_TICK, size)[0] + out
                if label_room(other.yaxis.label):
                    right += label_room(other.yaxis.label) + other.yaxis.labelpad * px
            elif hasattr(other, "_colorbar"):
                size, out, _ = ticks(other.yaxis)
                bar_w = cb_style.size_pct / 100 * W * 0.6   # as wide as matplotlib's own fraction gives
                gap = cb_style.pad_pct / 100 * W * 0.6
                room = gap + bar_w + size_of(COLORBAR_TICK, size)[0] + out
                if label_room(other.yaxis.label):
                    room += label_room(other.yaxis.label) + other.yaxis.labelpad * px
                right += room
                if other not in ax.child_axes:            # its own axes: placed beside the plot below
                    beside.append((other, gap, bar_w))

        x0, y0 = left / W, bottom / H
        w, h = max(W - left - right, W * 0.2) / W, max(H - bottom - top, H * 0.2) / H
        ax.set_position([x0, y0, w, h])
        for other, gap, bar_w in beside:
            other.set_box_aspect(None)                    # as tall as the plot (matplotlib's own: 20:1)
            other.set_position([x0 + w + gap / W, y0, bar_w / W, h])

        # labels longer than their room are shortened, never cut off at the picture's edge
        self._shorten(xlabel, w * W, size_of)
        self._shorten(ylabel, h * H, size_of)
        self._shorten(ax.title, W - 2 * edge, size_of)
        for other in fig.axes:
            if hasattr(other, "_colorbar"):
                self._shorten(other.yaxis.label, h * H, size_of)

    @staticmethod
    def _shorten(label: Any, room: float, size_of: Any) -> None:
        """A label wider than `room` pixels gets "…" in place of its end. Its whole text is kept
        (`full_text`): every layout starts from it, so a label shortened at a small size is whole
        again at a larger one, and what the label means (sync_keys) never changes."""
        text = full_text(label)
        label._lbd_full = text
        label.set_text(text)
        label._lbd_shown = text
        if not text or not label.get_visible() or size_of(text, label.get_fontsize())[0] <= room:
            return
        lo, hi = 0, len(text)
        while lo < hi:                                   # the longest start that fits with "…"
            mid = (lo + hi + 1) // 2
            if size_of(text[:mid].rstrip() + "…", label.get_fontsize())[0] <= room:
                lo = mid
            else:
                hi = mid - 1
        label.set_text(text[:lo].rstrip() + "…")
        label._lbd_shown = label.get_text()

    def _bare_out(self) -> None:
        """Only the data, over the whole picture (`bare`). Call under the render lock."""
        image = getattr(self, "image", None) if self.kind == "heatmap" else None
        if image is not None and image.colorbar is not None:
            image.colorbar.remove()
        legend = self.ax.get_legend()
        if legend is not None:
            legend.remove()
        for child in list(self.ax.child_axes):            # a second y axis (values of two units)
            child.remove()
        self.ax.set_title("")
        self.ax.set_axis_off()
        self.fig.set_layout_engine("none")
        self.ax.set_position([0, 0, 1, 1])

    # -- setup

    def _units_apart(self, m: "rnd.CurveModel") -> "rnd.CurveModel":
        """Values of two units in one plot (plan 4): the second unit's curves get a right-hand
        axis. They are drawn scaled onto the left axis (so zooming, picking and cursors work on
        one axis) and the right axis shows their own numbers. The model returned carries
        `units_apart`: per line (scale, offset) with drawn = stored × scale + offset, the right
        axis' lines, label and mapping; None when the plot has one unit. A third unit can't be
        shown (an ExploreError says to use another panel). Operations and equations give one
        quantity (no unit), so they show one axis."""
        log = getattr(self, "units_log", False)
        done = getattr(m, "units_apart", None)
        if done:
            if done["log"] == log:
                return m                                 # already worked out for this model and scale
            m = done["base"]                             # Log vertical changed: worked out again
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
            if log and left.min() > 0 and right.min() > 0:   # a log scale: the middles (geometric) line up
                a = float(np.sqrt(left.min() * left.max()) / np.sqrt(right.min() * right.max()))
            else:                                        # each side fills the height: the right's range over the left's (16.52)
                span_l, span_r = np.ptp(left) or 1.0, np.ptp(right) or 1.0
                a = float(span_l / span_r)
                b = float(left.min() - a * right.min())
        per_line = [(f1, 0.0) if k in groups[0] else (f2 * a, b) for k in range(len(m.lines))]
        lines = [(stored[k] * sc + off, label) for k, ((_, label), (sc, off)) in enumerate(zip(m.lines, per_line))]
        out = dataclasses.replace(m, lines=lines, yf=f1, ylim=None,
                                  y_label=f"{names[0]} ({u1})" if u1 else names[0])
        out.units_apart = {"per_line": per_line, "right": groups[1], "a": a, "b": b, "f2": f2,
                           "label": f"{names[1]} ({u2})" if u2 else names[1], "log": log, "base": m}
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
        if self.summarised:                              # one x, every trace: from the summary
            x = self.x_groups[0][0]
            self.pyramids = {id(x): summaries.curve_pyramid(m.lines[0][0].curves, x)}
        else:
            self.pyramids = {id(x): CurvePyramid(x, np.stack([m.lines[k][0] for k in ks]))
                             for x, ks, ok in self.x_groups if ok and len(ks) > 1 and x.size > 4096
                             and np.all(np.isfinite(x)) and x[0] < x[-1]}
        # One vertical axis: the traces are named in the list and when clicked, so the figure's
        # colour bar for many series (a second axis) is left out here.
        m.series_bar = None
        self.lines = rnd.draw_curves(self.fig, self.ax, m, self.data, self.spec, self.style,
                                     data=[(x[:0], y[:0]) for x, (y, _) in zip(m.xs, m.lines)])
        # Show points: the lines here are reduced to pixel columns, so their dots come from the
        # stored points instead (_dots): painted into the picture of many curves, or drawn as
        # square markers (dot_artists) on few curves. The legend keeps its dot.
        self.points = bool((self.spec.get("options") or {}).get("points"))
        self.dots_note = ""
        self.dot_artists = []
        if self.points:
            for artist in self.lines:
                artist.set_marker("None")
                self.dot_artists += self.ax.plot([], [], linestyle="None", marker="s", markeredgewidth=0,
                                                 color=artist.get_color(), antialiased=False, transform=self.ax.transAxes,
                                                 zorder=artist.get_zorder(), label="_dots")
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
        ys = [np.asarray(self._y_range(range(len(m.lines))))] if self.summarised else [y for y, _ in m.lines]
        self.full = (_finite_range([x for x, _, _ in self.x_groups]), m.ylim if m.ylim and None not in m.ylim
                     else self._padded(_finite_range(ys)))

    @property
    def summarised(self) -> bool:
        """The map or the curves are shown from their summary (too big for memory, summaries.py)."""
        if self.kind == "heatmap":
            return isinstance(self.model.z, summaries.BigMap)
        lines = getattr(self.model, "lines", None)
        return bool(lines) and isinstance(lines[0][0], summaries.BigTrace)

    def _y_range(self, traces: Sequence[int]) -> Tuple[float, float]:
        """Summarised curves: the lowest and highest value of these traces (plot units, exact)."""
        return self.model.lines[0][0].curves.range(traces)

    def _finite_z(self) -> np.ndarray:
        """The map's numbers (finite ones); of a summarised map, its blocks' means (approximate)
        with its lowest and highest number."""
        if self.summarised:                              # the lowest and highest are exact
            return np.concatenate([summaries.histogram_cells(self.model.z)[0], self.model.z.range()])
        z = self.model.z
        return z[np.isfinite(z)]

    def _setup_map(self):
        m = self.model
        xe, ye = cell_edges(m.x), cell_edges(m.y)
        try:
            if isinstance(m.z, summaries.BigMap):
                self.pyramid = summaries.pyramid(m.z, xe, ye)
            else:
                self.pyramid = MapPyramid(m.z, xe, ye)
        except ValueError as e:
            raise ExploreError(str(e)) from e
        self.x_edges, self.y_edges = np.sort(xe), np.sort(ye)
        # colour limits from all the data, not the view (a summarised map: its lowest and highest)
        whole = np.asarray(m.z.range()) if isinstance(m.z, summaries.BigMap) else m.z
        self.style_fixed = m.norm.vmin is not None or m.norm.vmax is not None   # the style's own colour range
        m.norm.autoscale_None(np.ma.masked_invalid(whole))
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

    @_locked
    def apply(self, settings: Optional[Dict[str, Any]]) -> List[str]:
        """Show the data with these view settings; returns notes for the user.

        `select` {axis: [positions]}: which traces are drawn (curves: along the series axis) or
        make the map (its vertical axis; left-out rows stay empty, so every row keeps its place).
        `cmap` and `invert`: the map's colour map. `xscale`, `yscale`, `cscale`: "linear" or "log".
        `clim` [from, to]: the colour range (None: from the data). `crange` "all" (a map with a
        slider): that range from every slider position (crange.py), "slice" (or missing): from
        the slice shown. Missing settings keep the plot's own (its style and saved figure
        settings)."""
        settings = dict(settings or {})
        try:
            # operations this plot type doesn't offer (a saved view made on another) are left out (16.50)
            if settings.get("ops"):
                settings["ops"], self.left_out = ops_mod.offered_only(self.view.name, ops_mod.check(settings["ops"]))
            else:
                self.left_out = {}
        except ops_mod.BadOps as e:
            raise ExploreError(str(e)) from None
        if settings == self.settings and (getattr(self, "crange_info", None) or {}).get("state") != "working":
            return []                                    # (a range of every slice still coming: again)
        if settings.get("crange", "slice") not in ("slice", "all"):
            raise ExploreError(f"crange must be 'slice' or 'all', not {settings['crange']!r}")
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
        if self.base_kind == "heatmap":
            # every slider position's range newly known (or no longer wanted): the map again, with
            # the colour bar's unit prefix chosen for it (set_spec)
            whole = crange_mod.peek(self, settings) if settings.get("crange") == "all" else None
            span = (whole.lo, whole.hi) if whole is not None and np.isfinite(whole.lo) else None
            if span != getattr(self, "zspan", None):
                self.settings = settings
                self.set_spec({k: v for k, v in self.spec.items() if k in rnd.SPEC_KEYS})
                self.settings = {}                       # every setting again, on the new map
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
        apart = getattr(self.model, "units_apart", None) if self.kind == "curve" else None
        if apart and (settings.get("yscale", self.base_scales[1]) == "log") != apart["log"]:
            # a right-hand axis is placed one way on a linear scale and another on a log one (16.52)
            self.units_log = not apart["log"]
            self.model = apart["base"]
            self._build()
            self.settings = {}
        with rnd.RENDER_LOCK, matplotlib.rc_context(self.style.to_rcparams()):
            self._check_open()
            self.log_refused: List[str] = []
            self.view.apply(settings, chosen, clim)
            for key, which, base in (("xscale", "horizontal", self.base_scales[0]),
                                     ("yscale", "vertical", self.base_scales[1])):
                want = settings.get(key, base)
                if key == "xscale" and not self.view.log_x:
                    want = "linear"
                if want == "log" and not self._has_positive(which):
                    want = "linear"                      # nothing could be drawn on a log axis
                    self.log_refused.append(f"The {which} axis has no value above 0, so it stays linear.")
                if want != (self.ax.get_xscale if key == "xscale" else self.ax.get_yscale)():
                    (self.ax.set_xscale if key == "xscale" else self.ax.set_yscale)(want)    # (this resets the ticks)
            self.full = self._full_view()
        self.settings = settings
        return notes

    @_locked
    def crange_state(self) -> Optional[Dict[str, Any]]:
        """For the page: a map with sliders, its colour range's source ("slice" or "all") and,
        while every slice's range is worked out, how far ("working", fraction) or why it failed."""
        if self.kind != "heatmap" or not crange_mod.sliders(self):
            return None
        info = getattr(self, "crange_info", None)
        out: Dict[str, Any] = {"from": self.settings.get("crange", "slice")}
        if info:
            out.update(info)
        return out

    def _has_positive(self, which: str) -> bool:
        """Whether the data shown has a value above 0 along this axis (else a log scale shows nothing)."""
        if self.kind not in ("curve", "heatmap"):
            return self.view.has_positive(which)
        m = self.model
        if self.kind == "curve":
            shown = [k for k, v in enumerate(self.visible) if v]
            if self.summarised and which != "horizontal":
                arrays = [np.asarray(self._y_range(shown))]
            else:
                arrays = [m.xs[k] if which == "horizontal" else m.lines[k][0] for k in shown]
        else:
            arrays = [m.x if which == "horizontal" else m.y]
        with np.errstate(invalid="ignore"):
            return any(bool(np.any(np.isfinite(v := np.asarray(a, dtype=float)) & (v > 0))) for a in arrays)

    @_locked
    def hidden(self) -> Tuple[List[str], Optional[str]]:
        """What the scales hide (points ≤ 0 on a log scale, …), and why nothing is shown when
        nothing can be: notes the page keeps on screen. Worked out once per model and scales."""
        if self.kind not in ("curve", "heatmap"):
            return self.view.hidden()
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
                if self.summarised:                      # their lowest and highest value say enough
                    lo, hi = self._y_range(shown) if shown else (np.nan, np.nan)
                    if not np.isfinite([lo, hi]).any():
                        empty = self._why_empty("point")
                    if ylog and lo <= 0:
                        notes.append("Points ≤ 0 aren't shown on the log vertical axis.")
                    if xlog and (n := int((m.xs[0] <= 0).sum())):        # the axis is in memory
                        notes.append(f"{n} point{'s' * (n != 1)} of each trace at x ≤ 0 aren't shown on the log "
                                     "horizontal axis.")
                # stops at the first trace with a value: cheap however many points there are
                elif not any(np.isfinite(np.asarray(m.lines[k][0], dtype=float)).any() for k in shown):
                    empty = self._why_empty("point")
                if (xlog or ylog) and not self.summarised:   # counting what a log scale hides: only then
                    pairs = [(np.asarray(m.xs[k], dtype=float), np.asarray(m.lines[k][0], dtype=float)) for k in shown]
                    ok = [np.isfinite(x) & np.isfinite(y) for x, y in pairs]
                    if xlog and (n := sum(int(((x <= 0) & o).sum()) for (x, _), o in zip(pairs, ok))):
                        notes.append(f"{n} point{'s' * (n != 1)} at x ≤ 0 aren't shown on the log horizontal axis.")
                    if ylog and (n := sum(int(((y <= 0) & o).sum()) for (_, y), o in zip(pairs, ok))):
                        notes.append(f"{n} point{'s' * (n != 1)} ≤ 0 aren't shown on the log vertical axis.")
            elif self.summarised:                        # its lowest and highest number say enough
                if not np.isfinite(m.z.range()).any():
                    empty = self._why_empty("cell")
                if self.settings.get("cscale") == "log" and m.z.range()[0] <= 0:
                    notes.append("Cells ≤ 0 aren't shown on the log colour scale.")
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

    def _apply_curves(self, chosen: Optional[set]) -> None:
        axis = self.spec.get("series") if self.base_kind == "curve" else self.spec.get("y")
        per = len(self.data.axes[axis].data) if axis else 1
        if self.base_kind != "curve" or len(self.model.lines) != len(self.base_model.lines):
            per, chosen = 1, None                        # other traces after an operation: all shown
        self.visible = [chosen is None or k % per in chosen for k in range(len(self.model.lines))]
        for artist, shown in zip(self.lines, self.visible):
            artist.set_visible(shown)

    def _apply_ops(self, ops: List[Dict[str, Any]], chosen: Optional[set], eqs: Dict[str, str]) -> bool:
        """Run the operations (on the chosen traces), then the equations, when any of them or the
        choice changed; True when the figure was set up again for another model."""
        if (any(op["on"] for op in ops) or eqs) and not self.view.operations:
            raise ExploreError(self.view.no_operations)
        if self.view.operations in ("shape", "points"):
            return self.view.apply_ops(ops, eqs)
        if self.view.operations == "before":             # the type runs them itself, on its numbers
            self.ops_list = ops
            return False
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

    @_locked
    def calculate(self, what: str, index: int, xlim: Sequence[float], trace: Optional[int]) -> Dict[str, Any]:
        """Delay or rotation for operation `index` from the data in x range `xlim` (plot units) of
        cursor 1's trace (or all shown traces); see operations.calculate."""
        ops = self.ops_list
        if not 0 <= index < len(ops) or ops[index]["op"] != what:
            raise ExploreError(f"operation {index + 1} is not a {what}")
        if self.base_kind == "scatter":                  # the points shown (16.8)
            return self.view.calculate(what, index)
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

    @_locked
    def ops_info(self) -> Dict[str, Any]:
        """For the page: each operation's state (None: applied, "off", or why not), each equation
        field's (error or note), what is shown, the names equations can use (the legend), and
        which operations this plot type offers (16.50)."""
        info = self._ops_info()
        left = getattr(self, "left_out", {})
        if left:
            info["notes"] = [left.get(i, n) for i, n in enumerate(info["notes"])]
        info["offered"] = ops_mod.OFFERED.get(self.view.name, [])
        return info

    def _ops_info(self) -> Dict[str, Any]:
        if self.view.operations == "before":
            return self.view.ops_info()
        r = self.ops_result
        if getattr(self, "eq_legend", None) is None and not self.summarised and self.view.operations is True:
            # the legend of the plain plot
            self.eq_legend = equations.names_of(self, ops_mod.grid_of(self, None), arrays=False)[1]
        info: Dict[str, Any] = {"notes": r.notes if r else ["off"] * len(self.ops_list), "applied": r.applied if r else 0,
                                "equations": getattr(self, "eq_state", {}), "names": self.eq_legend}
        if self.summarised:                              # no legend: equations aren't used on a summary
            info["names_note"] = ("Equations need the full data, and this plot is shown from a summary "
                                  "(the data is larger than the memory free now).")
        if r is not None and r.applied and self.ops_shown is not None:
            info["shows"] = r.grid.value.label
            info["unit"] = self.ops_shown.value_unit
            info["one_to_one"] = r.grid.one_to_one
        return info

    def _apply_map(self, settings: Dict[str, Any], chosen: Optional[set], clim) -> None:
        old = (self.settings.get("select") or {}).get(self.spec.get("y"))
        if chosen is not None and self.summarised:
            raise ExploreError("choosing rows isn't possible on a map this large (it is shown from its summary); "
                               "show all rows, or save a cut and open that")
        if not self.summarised and ((None if old is None else set(old)) != chosen or not hasattr(self, "pyramid")):
            z = self.model.z
            if chosen is not None:                       # left-out rows are empty, in their place
                z = z.copy()
                z[[j for j in range(z.shape[0]) if j not in chosen], :] = np.nan
            self.pyramid = MapPyramid(z, cell_edges(self.model.x), cell_edges(self.model.y))
        self._apply_colours(settings, clim)

    def _apply_colours(self, settings: Dict[str, Any], clim) -> None:
        """The colour map, its limits and scale, on the picture and the colour bar."""
        name = settings.get("cmap") or self.model.cmap
        if settings.get("invert"):
            name = name[:-2] if name.endswith("_r") else name + "_r"
        self.image.set_cmap(name)
        # every slider position's range (crange "all"): unless both ends are typed or the style
        # fixes its own; until it is worked out, this slice's (meta["crange"] says how far)
        whole, self.crange_info = None, None
        if settings.get("crange") == "all" and None in clim and not getattr(self, "style_fixed", False):
            whole, self.crange_info = crange_mod.get(self, settings)
            if whole is not None and np.isfinite(whole.lo) and (whole.lo, whole.hi) != getattr(self, "zspan", None):
                # ready just now: once more, for the colour bar's unit prefix (apply, set_spec)
                self.crange_info = {"state": "working", "fraction": 1.0, "slices": whole.slices, "error": None}
        if "cscale" in settings or any(v is not None for v in clim) or whole is not None:
            log = settings.get("cscale") == "log"
            z = self._finite_z()
            if log:
                z = z[z > 0]
            lo = clim[0] if clim[0] is not None else (float(z.min()) if z.size else 1.0)
            hi = clim[1] if clim[1] is not None else (float(z.max()) if z.size else 10.0)
            if whole is not None:
                wlo, whi = crange_mod.norm_limits(whole, float(self.model.zf or 1.0), log)
                if wlo is not None:
                    lo = clim[0] if clim[0] is not None else wlo
                    hi = clim[1] if clim[1] is not None else whi
            if log and not z.size:
                log = False                              # nothing above 0: a log scale would show nothing
                self.log_refused.append("The map has no value above 0, so the colour scale stays linear.")
                z = self._finite_z()
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
        positive part only). While a slider chooses what is drawn, all of it means every slider
        position (16.49): the limits stay the same while the slider moves, so steps compare."""
        (x0, x1), (y0, y1) = self.view.limits()
        whole = getattr(self.model, "whole", None)
        if whole is None or self.model is not self.base_model or not self._slider_moves():
            return (x0, x1), (y0, y1)
        linear = self.ax.get_xscale() == "linear", self.ax.get_yscale() == "linear"
        if self.kind == "curve" and linear[1] and not (self.model.ylim and None not in self.model.ylim):
            y0, y1 = self._padded(whole, False)          # padded as each step's own limits are
        elif self.kind == "scatter":
            if linear[0]:
                x0, x1 = self._padded(whole[0], False)
            if linear[1] and not (self.model.ylim and None not in self.model.ylim):
                y0, y1 = self._padded(whole[1], False)
        return (x0, x1), (y0, y1)

    def _slider_moves(self) -> bool:
        """Whether a slider chooses what is drawn: an axis with more than one position that isn't
        drawn along (x, series) nor shown whole (All)."""
        drawn = {self.spec.get("x"), self.spec.get("along"), self.spec.get("series"), *(self.spec.get("all") or [])}
        return any(a not in drawn and a in self.data.axes and len(self.data.axes[a].data) > 1
                   for a in (self.spec.get("index") or {}))

    @staticmethod
    def _range(arrays: Sequence[Any], log: bool) -> Tuple[float, float]:
        arrays = [np.asarray(a, dtype=float) for a in arrays]
        if log:
            arrays = [a[a > 0] for a in arrays]
        lo, hi = _finite_range(arrays)
        if log and lo <= 0:                              # one value (or none): a decade around it
            return (hi / 10, hi * 10) if hi > 0 else (0.1, 10.0)
        return lo, hi

    def _map_limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        xlog, ylog = self.ax.get_xscale() == "log", self.ax.get_yscale() == "log"
        return (self._range([self.x_edges], xlog), self._range([self.y_edges], ylog))

    def _curve_limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        xlog, ylog = self.ax.get_xscale() == "log", self.ax.get_yscale() == "log"
        rng = self._range
        shown = [k for k, v in enumerate(self.visible) if v] or list(range(len(self.model.lines)))
        x = rng([self.model.xs[k] for k in shown], xlog)
        m = self.model
        if m.ylim and None not in m.ylim and not ylog:
            return x, m.ylim
        if self.summarised:
            return x, self._padded(rng([np.asarray(self._y_range(shown))], ylog), ylog)
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

        scale = 0.5 if draft else 1.0
        width = self.lines[shown[0]].get_linewidth() * self.fig.dpi / 72 * scale
        # each column's lowest and highest value, joined column to column: as the curves look
        xx = np.repeat(np.arange(w) + 0.5, 2)
        yy = np.empty((len(shown), 2 * w))
        yy[:, 0::2], yy[:, 1::2] = rows(lo[shown]), rows(hi[shown])
        dots, size = self._dots(shown, w, h, scale)
        self.line_image.set_data(paint_lines([(xx, y) for y in yy], self.line_colors[shown], w, h, width, dots, size))
        self.line_image.set_visible(True)
        for artist in self.lines + self.dot_artists:
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
        dots, size = self._dots(shown, w, h, scale)
        self.line_image.set_data(paint_lines(px, self.line_colors[shown], w, h, width, dots, size))

    def _dots(self, shown: List[int], w: int, h: int, scale: float
              ) -> Tuple[Optional[List[Tuple[np.ndarray, np.ndarray]]], int]:
        """Show points (16.39): per shown curve, its dots in pixels of a w × h picture of the
        current limits (x to the right, y down): one real stored point per occupied pixel
        (lbd.plot.reduce.occupied_points); and a dot's side in pixels (`scale` < 1 in a draft).
        None when points are off, or (with a note) when more than DOTS_LIMIT stored points are
        in view.

        A dot is matplotlib's `.` marker of the style's marker size (half of it: 2.3 screen
        pixels by default), rounded up, as its antialiased edge looks that wide. Where a curve has
        more than two points per pixel column (its line is reduced), the dots would only make the
        line heavier: they shrink to the line's width."""
        self.dots_note = ""
        lw = self.lines[shown[0]].get_linewidth() * self.fig.dpi / 72 if shown else 1.0
        size = 0.5 * self.style.figure.axes.lines.marker_size_pt * self.fig.dpi / 72
        size = max(1, int(np.ceil(max(size, 2.0) * scale)))
        if not self.points:
            return None, size
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        xlog, ylog = self.ax.get_xscale() == "log", self.ax.get_yscale() == "log"
        # the curves on one x together, and the stretch in view: all of x unless it is sorted without gaps
        on = set(shown)
        groups = []
        for x, ks, is_sorted in self.x_groups:
            ks = [k for k in ks if k in on]
            if ks:
                is_sorted = is_sorted and bool(np.all(np.isfinite(x)))
                groups.append((x, ks, in_view(x, min(xl), max(xl)) if is_sorted else slice(0, x.size), is_sorted))
        many = sum(len(ks) * (part.stop - part.start) for _, ks, part, _ in groups)
        if many > DOTS_LIMIT:
            self.dots_note = (f"points not shown: {many / 1e6:.1f} million stored points in view, more than "
                              f"{DOTS_LIMIT / 1e6:g} million; zoom in or show fewer curves to see them")
            return None, size
        across = [part.stop - part.start if is_sorted else int(np.count_nonzero((x >= min(xl)) & (x <= max(xl))))
                  for x, _, part, is_sorted in groups]     # a curve's points in view
        if across and max(across) > 2 * self._plot_area()[2]:      # per column of the screen, also in a draft
            size = max(1, int(round(lw * scale)))

        def to_px(v, lim, log, size):
            f = (lambda a: np.log10(np.where(a > 0, a, np.nan))) if log else (lambda a: a)
            a, b = f(np.asarray(lim, dtype=float))
            return (f(v) - a) / (b - a) * size

        dots: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
        for x, ks, part, _ in groups:
            if self.summarised:                           # read from the file: the points in view only
                try:
                    ys = np.asarray(self.pyramids[id(x)].y[ks, part], dtype=float)
                except ExploreError as e:                 # more than the memory available holds
                    self.dots_note = f"points not shown: {e}"
                    return None, size
            else:
                ys = np.stack([np.asarray(self.model.lines[k][0][part], dtype=float) for k in ks])
            xv = x[part]
            found = occupied_points(xv, ys, xl, yl, w, h, xlog, ylog)
            # every curve's dots at once, then split per curve
            idx = np.concatenate(found)
            row = np.repeat(np.arange(len(ks)), [len(f) for f in found])
            px, py = to_px(xv[idx], xl, xlog, w), h - to_px(ys[row, idx], yl, ylog, h)
            ends = np.cumsum([len(f) for f in found])[:-1]
            dots.update(zip(ks, zip(np.split(px, ends), np.split(py, ends))))
        return [dots[k] for k in shown], size

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

    @_locked
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
            self.view.lay_out()

    def _curve_picture(self, pxe: np.ndarray, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        """The curves for these pixel edges: (the note, whether they are reduced)."""
        if self._fast_picture(pxe, w, h, draft):
            return "lowest and highest point per pixel column" + (f"; {self.dots_note}" if self.dots_note else ""), True
        full_w = self._plot_area()[2]
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
            elif self.summarised:                # some traces of summarised curves
                out, red = self.pyramids[id(x)].minmax(pxe, rows=ks)
                reduced |= red
            elif is_sorted:
                out, red = curve_minmax(x, [ys[k] for k in ks], pxe)
                reduced |= red
            else:
                unsorted = True
                if x.size > UNSORTED_LIMIT:              # thinned in stored order (drawing only)
                    out = [thin_in_order(x, ys[k], 4 * full_w) for k in ks]
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
            self._raster(lines, shown, w, h, 0.5 if draft else 1.0)
            for artist in self.dot_artists:
                artist.set_visible(False)
        else:
            # Show points on lines drawn by matplotlib: square markers at the dots, placed in
            # the plot box (0 to 1), always sharp (a draft's pixels are only coarser for the lines)
            dots, size = self._dots(shown, w, h, 1.0)
            for k, artist in enumerate(self.dot_artists):
                artist.set_visible(dots is not None and self.visible[k])
            for k, (px, py) in zip(shown, dots or []):
                self.dot_artists[k].set_data(px / w, 1 - py / h)
                self.dot_artists[k].set_markersize(size * 72 / self.fig.dpi)
        self.last_lines = lines
        note = "lowest and highest point per pixel column" if reduced else "every point shown"
        if unsorted:
            note += ("; x is not sorted: drawn in stored order, thinned to the lowest and highest "
                     "point of each stretch" if thinned else "; x is not sorted: drawn as stored")
        return note + (f"; {self.dots_note}" if self.dots_note else ""), reduced

    @_locked
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
            self.view.frame(xlim, ylim)
            asked = (list(xlim), list(ylim))              # before equal axes widen it (16.49)
            xlim, ylim = self.view.shown_limits(xlim, ylim)
            left, top, w, h = self._plot_area()
            dw, dh = (max(w // 2, 1), max(h // 2, 1)) if draft else (w, h)
            pxe, pye = self._pixel_edges(dw, dh)
            note, reduced = self.view.picture(pxe, pye, stat, draft, dw, dh)
            t2 = time.perf_counter()
            self.fig.canvas.draw()                    # (the layout never changes here: 16.37)
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
            "plot": [left, top, w, h], "xlim": list(xlim), "ylim": list(ylim), "asked": asked,
            "xscale": self.ax.get_xscale(), "yscale": self.ax.get_yscale(),
            "full": [list(self.full[0]), list(self.full[1])],
            "note": note, "reduced": reduced, "stat": stat, "draft": draft, "ops": self.ops_info(),
            "hidden": hidden, "empty": empty, "sync": self.sync_keys(),
            "crange": self.crange_state(), "strips": self.view.strips, **self.view.meta(),
            "ms": {"wait": round((t1 - t0) * 1000, 1), "reduce": round((t2 - t1) * 1000, 1),
                   "draw": round((t3 - t2) * 1000, 1), "encode": round((t4 - t3) * 1000, 1)},
        }
        return body, meta

    @_locked
    def sync_keys(self) -> Dict[str, str]:
        """What panels must share to follow each other's zoom (plan 4): the horizontal axis as
        drawn (its label, unit prefix included: an equation or an FFT changes it), and the
        vertical axis (maps: its label; curves: its unit, prefix included)."""
        if not self.view.syncs:
            return {}
        ylabel = full_text(self.ax.yaxis.label)
        if self.kind == "heatmap":
            y = ylabel
        else:
            m = re.search(r"\(([^()]*)\)\s*$", ylabel)
            y = m.group(1) if m else ""
        return {"x": full_text(self.ax.xaxis.label), "y": y}

    # -- picking

    def _to_px(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Data (plot units) to image pixels, top-left origin."""
        pts = self.ax.transData.transform(np.column_stack([np.ravel(x), np.ravel(y)]))
        return pts[:, 0], self.fig.bbox.height - pts[:, 1]

    @_locked
    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        """The stored point (curves) or cell (maps) at image pixel (px, py), from the full data."""
        self.last_used = time.monotonic()
        with rnd.RENDER_LOCK:
            self._check_open()
            return self.view.pick(px, py)

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
            ys = np.stack([np.asarray(m.lines[k][0][idx], dtype=float) for k in ks])   # lines × points
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
        """Free the figure (and a summarised map's summary file); a request still using the
        session then gets ExploreClosed."""
        with self.lock, rnd.RENDER_LOCK:
            self.fig = None
            for model in {id(m): m for m in (getattr(self, "base_model", None), getattr(self, "model", None))}.values():
                if isinstance(getattr(model, "z", None), summaries.BigMap):
                    model.z.close()
                lines = getattr(model, "lines", None)
                if lines and isinstance(lines[0][0], summaries.BigTrace):
                    lines[0][0].curves.close()


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
            oldest = None
            if len(self._by_id) >= self.limit:
                oldest = min(self._by_id.values(), key=lambda v: v.last_used)
                del self._by_id[oldest.id]
            self._by_id[s.id] = s
        if oldest is not None:
            oldest.close()

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
        """Close sessions unused for `idle` seconds; closed in a thread of their own, since one may
        be busy drawing (its lock), and nobody should wait for that while holding this list's lock."""
        now = time.monotonic()
        gone = [self._by_id.pop(k) for k, v in list(self._by_id.items()) if now - v.last_used > self.idle]
        if gone:
            threading.Thread(target=lambda: [s.close() for s in gone], daemon=True).start()

    def __len__(self) -> int:
        return len(self._by_id)
