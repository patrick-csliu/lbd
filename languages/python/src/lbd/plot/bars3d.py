"""3D bars: the data of Matrix, a bar per cell. The classic picture of a density matrix.

Drawn by matplotlib, so the screen and an export are the same picture. Row 0 is at the back and
column 0 on the left, so that from the default angle it reads like the Matrix of the same data.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.artist import Artist
from matplotlib.cm import ScalarMappable
from mpl_toolkits.mplot3d import proj3d
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from lbd.io import _warn

from . import matrix
from . import render as r
from .kinds import Kind
from .style import Style
from .units import axis_label

MOST = 64                  # 3D bars show at most this many rows and columns: bars hide each other beyond
QUICK_ABOVE = 32 * 32      # with more bars, a quick picture is drawn while turning; fewer are quick anyway
# The six faces of a box of size 1, and how light each is: `bar3d` works this out for every bar, and
# with thousands of collections that is most of the time.
BOX = np.array([[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
                [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)],
                [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)], [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]], dtype=float)
SHADE = np.array([0.45, 1.0, 0.75, 0.75, 0.6, 0.9])


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and bool(np.isfinite(v))


OPTIONS = {
    "elev": (lambda v: _number(v) and -90 <= v <= 90, "elev must be a number from -90 to 90"),
    "azim": (_number, "azim must be a number"),
    "zoom": (lambda v: _number(v) and 0.5 <= v <= 3, "zoom must be a number from 0.5 to 3"),
}


def too_many(rows: int, columns: int) -> Optional[str]:
    if max(rows, columns) <= MOST:
        return None
    return f"3D bars show at most {MOST} × {MOST} cells; this has {rows} × {columns}. Use Matrix."


def fits(d, name: str) -> Optional[str]:
    """None if `name` can be drawn as 3D bars, otherwise why not. `d`: the flat view."""
    why = matrix.fits(d, name)
    if why:
        return why
    v = d.values[name]
    y, x = matrix.starting_axes(d, v)
    size = dict(zip(v.axes, v.shape))
    return too_many(size[y], size[x])


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec) -> Dict[str, Any]:
    out = matrix.resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec)
    matrix.checked_options(d, out, spec, OPTIONS)
    return out


@dataclass
class Panel:
    """One picture of bars: the whole value, or its real or imaginary part."""

    title: str                  # "", "Re" or "Im"
    height: np.ndarray          # (rows, columns), plot units
    raw: np.ndarray             # the same, stored units
    colour: Optional[np.ndarray] = None    # what the colours show, when it isn't the height


@dataclass
class Bars3dModel:
    grid: matrix.Grid
    panels: List[Panel]
    x: np.ndarray               # each column's centre
    y: np.ndarray               # each row's centre, row 0 first: at the back
    z: np.ndarray               # the first panel's heights
    zf: float
    zlim: Tuple[float, float]
    norm: mcolors.Normalize
    cmap: str
    x_label: str
    y_label: str
    z_label: str
    colour_label: Optional[str]            # the colour bar, when the colours aren't the heights
    elev: float
    azim: float
    zoom: float
    note: Optional[str]         # cells without a number
    sums: Optional[np.ndarray] = None      # (a matrix's row sums aren't shown here)
    xf: float = 1.0
    yf: float = 1.0
    lines: Tuple = ()
    axes: List[Any] = field(default_factory=list)            # a 3D axes per panel
    bars: List[List[Any]] = field(default_factory=list)      # per panel, a collection per bar
    quick: List[Any] = field(default_factory=list)           # per panel, all bars in one collection


def _panels(d, spec, style: Style) -> Tuple[matrix.Grid, List[Panel]]:
    """Re and Im side by side (two panels), or one. `abs_phase`: height the magnitude, colour the phase."""
    if spec["complex"] == "abs_phase" and d.values[spec["values"][0]].dtype.startswith("complex"):
        g = matrix.read_grid(d, {**spec, "complex": "abs"}, style)
        phase = matrix.read_grid(d, {**spec, "complex": "phase"}, style).blocks[0].raw
        return g, [Panel("", g.blocks[0].z, g.blocks[0].raw, colour=phase)]
    g = matrix.read_grid(d, {**spec, "complex": "abs" if spec["complex"] == "abs_phase" else spec["complex"]}, style)
    return g, [Panel(b.title, b.z, b.raw) for b in g.blocks]


def prepare(d, spec, style: Style, **kw) -> Bars3dModel:
    d = r.flat(d)
    a = style.figure.axes
    g, panels = _panels(d, spec, style)
    rows, columns = panels[0].height.shape
    why = too_many(rows, columns)
    if why:
        raise r.RenderError(why)
    heights = np.concatenate([np.ravel(p.height) for p in panels]).astype(float)
    finite = heights[np.isfinite(heights)]
    low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    empty = int(np.isnan(heights).sum())
    zlim = (min(low, 0.0), max(high, 0.0))
    if zlim[0] == zlim[1]:
        zlim = (0.0, 1.0)
    options = spec.get("options") or {}
    v = d.values[g.value]
    q = r.find_quantity(style, g.value, v.label, spec["complex"] if v.dtype.startswith("complex") else None)
    xs, ys = style.axis_style("x"), style.axis_style("y")
    xa, ya = d.axes[spec["x"]], d.axes[spec["y"]]
    phase = panels[0].colour is not None
    norm = mcolors.Normalize(-np.pi, np.pi) if phase else mcolors.Normalize(low, high if high > low else low + 1)
    cmap = a.bars3d.phase_cmap if phase else q.cmap or a.bars3d.cmap or a.image.cmap
    colour_label = axis_label(f"arg {v.label}", "rad", ys.label.unit_format) if phase else None
    return Bars3dModel(
        grid=g, panels=panels, x=np.arange(columns, dtype=float), y=rows - 1.0 - np.arange(rows), z=panels[0].height,
        zf=g.zf, zlim=zlim, norm=norm, cmap=cmap, colour_label=colour_label,
        x_label=axis_label(spec.get("x_label") or xa.label, "" if xa.elements is not None else xa.unit, xs.label.unit_format),
        y_label=axis_label(spec.get("y_label") or ya.label, "" if ya.elements is not None else ya.unit, ys.label.unit_format),
        z_label=axis_label(spec.get("z_label") or g.label, g.unit, ys.label.unit_format),
        elev=options.get("elev", a.bars3d.elev), azim=options.get("azim", a.bars3d.azim), zoom=options.get("zoom", 1.0),
        note=f"{empty} cell{'s' * (empty != 1)} {'are' if empty != 1 else 'is'} empty" if empty else None)


def operated(m: Bars3dModel, raw: np.ndarray, factor: float, unit: str, label: str, z_label: str) -> Bars3dModel:
    """The same bars with other numbers (`raw` in stored units), for Explore's operations."""
    height = raw * factor
    finite = height[np.isfinite(height)]
    low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    grid = dataclasses.replace(m.grid, blocks=[matrix.GridBlock("", height, raw)], label=label, unit=unit, zf=factor)
    return dataclasses.replace(m, grid=grid, panels=[Panel("", height, raw)], z=height, zf=factor, z_label=z_label,
                               zlim=(min(low, 0.0), max(high, 0.0) or 1.0), colour_label=None,
                               norm=mcolors.Normalize(low, high if high > low else low + 1), axes=[], bars=[], quick=[])


def make_axes(fig, m: Bars3dModel):
    m.axes = [fig.add_subplot(1, len(m.panels), k + 1, projection="3d", computed_zorder=False)
              for k in range(len(m.panels))]
    return m.axes[0]


def _ticks(places: np.ndarray, texts: List[str]) -> Tuple[np.ndarray, List[str]]:
    step = max(1, int(np.ceil(len(texts) / r.MAX_ELEMENT_TICKS)))
    return places[::step], texts[::step]


def _bar_colours(m: Bars3dModel, p: Panel) -> np.ndarray:
    cmap = matplotlib.colormaps[m.cmap]
    return cmap(m.norm(p.height if p.colour is None else p.colour))


def _draw_bars(ax, m: Bars3dModel, p: Panel, style: Style) -> List[Any]:
    """A collection per bar: whole bars can be put in order, one behind the other. `bar3d` alone
    sorts the faces of all bars by their mean depth, which can show a far side in front of a near bar."""
    s = style.figure.axes.bars3d
    colours = _bar_colours(m, p)
    bars = []
    for i, y in enumerate(m.y):
        for j, x in enumerate(m.x):
            h = p.height[i, j]
            if np.isfinite(h):
                faces = BOX * (s.width, s.width, h) + (x - s.width / 2, y - s.width / 2, 0.0)
                shaded = np.c_[colours[i, j][None, :3] * SHADE[:, None], np.full(6, s.alpha)]
                bar = Poly3DCollection(faces, facecolors=shaded, edgecolors=s.edge_color, linewidths=s.edge_width_pt)
                ax.add_collection3d(bar, autolim=False)
                bars.append(bar)
    return bars


def _quick_bars(ax, m: Bars3dModel, p: Panel, style: Style) -> Any:
    """All bars in one collection, for the moments of turning: quicker, its faces sorted one by one."""
    s = style.figure.axes.bars3d
    x, y = np.meshgrid(m.x, m.y)
    ok = np.isfinite(p.height)
    half = s.width / 2
    quick = ax.bar3d(x[ok] - half, y[ok] - half, np.zeros(int(ok.sum())), s.width, s.width, p.height[ok],
                     color=_bar_colours(m, p)[ok], edgecolor="none", alpha=s.alpha)
    quick.set_visible(False)
    return quick


def order_bars(m: Bars3dModel) -> None:
    """Far bars first: bars don't overlap, so whole bars drawn far to near are always right."""
    for a, p, bars in zip(m.axes, m.panels, m.bars):
        x, y = np.meshgrid(m.x, m.y)
        ok = np.isfinite(p.height)
        depth = proj3d.proj_transform(x[ok], y[ok], np.zeros(x[ok].size), a.get_proj())[2]
        for rank, k in enumerate(np.argsort(-depth)):
            bars[k].set_zorder(rank + 1)


def set_draft(m: Bars3dModel, draft: bool) -> None:
    """The quick picture while turning, where there is one."""
    for bars, quick in zip(m.bars, m.quick):
        if quick is not None:
            quick.set_visible(draft)
            for bar in bars:
                bar.set_visible(not draft)


class _InOrder(Artist):
    """Puts the bars in order at each drawing, whatever the angle is by then, also for an export.
    It belongs to the figure and comes first, so the axes sort their bars after it."""

    def __init__(self, m: Bars3dModel):
        super().__init__()
        self.model = m
        self.set_zorder(-1)
        self.set_in_layout(False)

    def draw(self, renderer) -> None:
        order_bars(self.model)


def set_angle(fig, elev: float, azim: float, zoom: float) -> None:
    """Every panel of the figure at one angle and zoom."""
    for ax in fig.axes:
        if hasattr(ax, "view_init"):
            box = ax.get_box_aspect()
            ax.view_init(elev=elev, azim=azim)
            ax.set_box_aspect(box, zoom=zoom)


def draw(fig, ax, m: Bars3dModel, d, spec, style: Style):
    """Draw a Bars3dModel on the axes of `make_axes`; returns the colour scale."""
    if not m.axes:
        raise r.RenderError("3D bars need a figure of their own: leave out ax=")
    rows, columns = len(m.y), len(m.x)
    m.bars, m.quick = [], []
    for a, p in zip(m.axes, m.panels):
        m.bars.append(_draw_bars(a, m, p, style))
        m.quick.append(_quick_bars(a, m, p, style) if rows * columns > QUICK_ABOVE else None)
        a.set_xlim(-0.5, columns - 0.5)
        a.set_ylim(-0.5, rows - 0.5)
        a.set_zlim(*m.zlim)
        a.set_xticks(*_ticks(m.x, m.grid.col_labels))
        a.set_yticks(*_ticks(m.y, m.grid.row_labels))
        a.set_xlabel(m.x_label)
        a.set_ylabel(m.y_label)
        a.set_box_aspect((columns, rows, 0.75 * max(rows, columns)), zoom=m.zoom)
        a.view_init(elev=m.elev, azim=m.azim)
        if p.title:
            a.text2D(0.5, 0.97, p.title, transform=a.transAxes, ha="center", va="top")
        if m.colour_label or not style.figure.axes.image.colorbar.visible:     # the colour bar doesn't say the height
            a.text2D(0.0, 1.0, m.z_label, transform=a.transAxes, ha="left", va="top")
    fig.add_artist(_InOrder(m))
    if m.note:
        _warn(m.note, r.RenderWarning)
    scale = ScalarMappable(norm=m.norm, cmap=m.cmap)
    bar = r._colorbar(fig, scale, m.axes, style, m.colour_label or m.z_label)
    if bar is not None and m.colour_label:
        bar.set_ticks([-np.pi, 0, np.pi], labels=["−π", "0", "π"])
    return scale


KIND = Kind("bars3d", "3D bars", fits, resolve, prepare, draw,
            frozenset({"x", "y", "index", "x_label", "y_label", "z_label", "re_im", "abs_phase"}), make_axes=make_axes)
