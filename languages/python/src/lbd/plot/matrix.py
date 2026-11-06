"""Matrix: cells with their numbers, for density and assignment matrices, covariance.

`read_grid` gives the numbers of a value on two axes, which may be the two dimensions inside a data
point; 3D bars show the same data. The other axes are fixed at `spec["index"]`, as on a map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.artist import Artist
from matplotlib.text import Text
from matplotlib.ticker import NullLocator

from lbd.io import _warn

from . import render as r
from .kinds import Kind
from .style import Style
from .units import axis_label, mathsafe

MATRIX_NUMBERS = 32        # the numbers are drawn up to this many rows and columns (drawing them is slow)
RANGES = ("auto", "unit", "signed")
DIGITS = 3


@dataclass
class GridBlock:
    """One picture of the cells: the whole value, or its real or imaginary part."""

    title: str                  # "", "Re" or "Im"
    z: np.ndarray               # (rows, columns), plot units
    raw: np.ndarray             # the same, stored units (for numbers, row sums, tables)


@dataclass
class Grid:
    """The cells of a value, with what is needed to name them."""

    value: str
    row_axis: str
    col_axis: str
    row_labels: List[str]
    col_labels: List[str]
    blocks: List[GridBlock]     # one, or two for re_im (same shape, same factor)
    label: str
    unit: str                   # with the prefix, e.g. "S", "mV"
    raw_unit: str               # without it
    zf: float                   # plot units per stored unit, shared by the blocks


def fits(d, name: str) -> Optional[str]:
    """None if `name` can be drawn as cells, otherwise why not. `d`: the flat view (`render.flat`)."""
    v = d.values[name]
    swept = r._swept(v)
    needs = "this needs two axes, or a matrix in each point"
    if sum(r._is_point(d, a) for a in v.axes) == 1:
        return f"'{name}' is a vector in each point; {needs}"
    if len(swept) < 2:
        return f"'{name}' has {'one axis' if swept else 'no axis'} with more than one point; {needs}"
    return None


def position_labels(axis) -> List[str]:
    """The axis's `elements`, otherwise its numbers as short text."""
    elements = getattr(axis, "elements", None)
    if elements is not None:
        return [mathsafe(e) for e in elements]
    return [f"{v:.4g}".replace("-", "−") for v in np.asarray(axis.data, dtype=float)]


def read_grid(d, spec, style: Style) -> Grid:
    """The cells of `spec["values"][0]`: rows on `spec["y"]`, columns on `spec["x"]`."""
    d = r.flat(d)
    name = spec["values"][0]
    v = d.values[name]
    why = fits(d, name)
    if why:
        raise r.RenderError(why)
    z = r._take(v, [spec["y"], spec["x"]], spec["index"])
    mode = spec["complex"]
    if mode == "re_im" and np.iscomplexobj(z):
        raws = [("Re", z.real), ("Im", z.imag)]
        label, unit = v.label, v.unit
    else:
        shown, label, unit = r.apply_complex(z, v.label, v.unit, "abs" if mode == "re_im" else mode, axis=1)
        raws = [("", shown)]
    q = r.find_quantity(style, name, v.label, mode if np.iscomplexobj(z) else None)
    auto = style.axis_style("y").label.auto_prefix and q.vmin is None and q.vmax is None
    zf, shown_unit = r._unit_scale(np.concatenate([np.ravel(a) for _, a in raws]), unit, q, auto)
    return Grid(value=name, row_axis=spec["y"], col_axis=spec["x"],
                row_labels=position_labels(d.axes[spec["y"]]), col_labels=position_labels(d.axes[spec["x"]]),
                blocks=[GridBlock(title, a * zf, a) for title, a in raws], label=label, unit=shown_unit,
                raw_unit=unit, zf=zf)


def _whole_digits(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 9


OPTIONS = {
    "numbers": (lambda v: isinstance(v, bool), "numbers must be true or false"),
    "digits": (_whole_digits, "digits must be a whole number from 1 to 9"),
    "range": (lambda v: v in RANGES, f"range must be one of {RANGES}"),
}


def checked_options(d, out: Dict[str, Any], spec: Dict[str, Any], rules: Dict[str, Tuple[Any, str]]) -> None:
    """Check a plot type's own choices in `out["options"]`. Another type's are left alone: a panel
    keeps them for when it goes back. A wrong one raises, or from a saved view is dropped with a warning."""
    options = out.get("options")
    if not options:
        return
    for key, (good, text) in rules.items():
        if key in options and not good(options[key]):
            if "options" in spec:
                raise r.RenderError(f"options: {text}, not {options[key]!r}")
            _warn(f"{r._where(d)}saved view: options: {text}; using the default instead", r.RenderWarning)
            del options[key]


def starting_axes(d, value) -> Tuple[str, str]:
    """(y, x) to start from: a data point's own two dimensions, otherwise the two shortest axes."""
    axes = r._swept(value)
    point = [a for a in axes if r._is_point(d, a)]
    if len(point) >= 2:
        return point[-2], point[-1]
    size = dict(zip(value.axes, value.shape))
    short = sorted(sorted(axes, key=lambda a: size[a])[:2], key=axes.index)
    return short[0], short[1]


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec) -> Dict[str, Any]:
    """Rows and columns are chosen like a map's axes: `y`, `x`; every other axis gets a slider."""
    first = d.values[values[0]]
    if len(values) > 1 and warn_unused:
        _warn(f"a matrix shows one value; {values[1:]} ignored", r.RenderWarning)
    out["values"] = values[:1]
    axes = list(first.axes)
    y_start, x_start = starting_axes(d, first)
    x = pick("x", lambda v: r._pick(v, axes, role="the columns"), x_start)
    rest = [a for a in axes if a != x]
    if spec.get("x") not in (None, "") and spec.get("y") in (None, "") and file_spec.get("y") == x:
        y = file_spec.get("x") if file_spec.get("x") in rest else (y_start if y_start != x else x_start)
    else:
        y = pick("y", lambda v: r._pick(v, rest, role="the rows"), y_start if y_start != x else x_start)
    out["x"], out["y"] = x, y
    if first.dtype.startswith("complex") and spec.get("complex") in (None, "") and not file_spec.get("complex"):
        out["complex"] = "re_im"
    checked_options(d, out, spec, OPTIONS)
    if warn_unused and spec.get("index"):
        drawn = [a for a in spec["index"] if a in (x, y) or a not in axes]
        if drawn:
            _warn(f"index for {drawn} is ignored: those axes are drawn, not sliced", r.RenderWarning)
    out["index"], out["slices"] = r._slices(d, [a for a in axes if a not in (x, y)], index_in, spec)
    return out


class CellNumbers(Artist):
    """The cells' numbers as one artist: drawn when a number fits its cell, and only those in view.

    Whether they fit is known only at drawing, after the layout, and changes with zooming."""

    def __init__(self, ax, texts: List[Text], chars: int, size_pt: float):
        super().__init__()
        self.texts, self.chars, self.size_pt = texts, chars, size_pt
        self.set_in_layout(False)
        self.set_zorder(3)
        ax.add_artist(self)
        for t in texts:
            t.set_figure(ax.figure)
            t.axes = ax
            t.set_transform(ax.transData)
            t.set_clip_path(ax.patch)

    def fit(self) -> bool:
        ax = self.axes
        (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
        size = self.size_pt * ax.figure.dpi / 72
        return abs(x1 - x0) >= self.chars * 0.6 * size and abs(y1 - y0) >= 1.2 * size

    def draw(self, renderer) -> None:
        if not self.get_visible() or not self.fit():
            return
        (xa, xb), (ya, yb) = sorted(self.axes.get_xlim()), sorted(self.axes.get_ylim())
        for t in self.texts:
            x, y = t.get_position()
            if xa <= x <= xb and ya <= y <= yb:
                t.draw(renderer)
        self.stale = False


@dataclass
class MatrixModel:
    """A matrix worked out from the data. Everything is drawn in one axes, cell (row i, column j)
    at x = j, y = rows - 1 - i, so row 0 is at the top while the limits still run low to high. Re
    and Im are side by side with an empty column between: `x` and `z` hold both."""

    grid: Grid
    x: np.ndarray               # each column's centre
    y: np.ndarray               # each row's centre, row 0 first
    z: np.ndarray               # (rows, columns), plot units; NaN in the gap
    starts: List[int]           # the first column of each block
    extent: Tuple[Tuple[float, float], Tuple[float, float]]
    zf: float
    norm: mcolors.Normalize
    cmap: str
    range: str                  # the colour range in use: "auto", "unit", "signed"
    x_label: str
    y_label: str
    z_label: str
    number_digits: int
    numbers: bool               # the numbers are wanted, and not too many
    note: Optional[str]         # why there are no numbers
    xf: float = 1.0
    yf: float = 1.0
    lines: Tuple = ()
    artists: Dict[str, Any] = field(default_factory=dict)    # what `draw` made


def starting_range(raw: np.ndarray, unit: str) -> str:
    """Numbers without a unit between 0 and 1, or −1 and 1, start on that fixed range, which makes
    matrices comparable. With a unit, 0 to 1 means nothing."""
    finite = raw[np.isfinite(raw)]
    if unit or not finite.size or finite.min() < -1 or finite.max() > 1:
        return "auto"
    return "signed" if finite.min() < 0 else "unit"


def colours(grid: Grid, q, chosen: Optional[str], style: Style) -> Tuple[mcolors.Normalize, str, str]:
    """(norm, colour map, range in use). A range set in the style for this quantity wins, as on a map."""
    a = style.figure.axes
    raw = np.concatenate([np.ravel(b.raw) for b in grid.blocks]).astype(float)
    fixed = q.vmin is not None or q.vmax is not None
    use = "auto" if fixed else chosen or starting_range(raw, grid.unit)
    if use == "signed":
        return mcolors.Normalize(-grid.zf, grid.zf), q.cmap or a.matrix.cmap_signed, use
    if use == "unit":
        return mcolors.Normalize(0, grid.zf), q.cmap or a.image.cmap, use
    norm = r._norm(q, grid.zf)
    norm.autoscale_None(np.ma.masked_invalid(raw * grid.zf))
    return norm, q.cmap or a.image.cmap, use


def prepare(d, spec, style: Style, **kw) -> MatrixModel:
    d = r.flat(d)
    grid = read_grid(d, spec, style)
    options = spec.get("options") or {}
    name, v = grid.value, d.values[grid.value]
    q = r.find_quantity(style, name, v.label, spec["complex"] if v.dtype.startswith("complex") else None)
    norm, cmap, use = colours(grid, q, options.get("range"), style)
    rows, columns = grid.blocks[0].z.shape
    pieces, starts = [], []
    for k, block in enumerate(grid.blocks):
        if k:
            pieces.append(np.full((rows, 1), np.nan))
        starts.append(sum(p.shape[1] for p in pieces))
        pieces.append(block.z)
    z = np.hstack(pieces)
    many = rows > MATRIX_NUMBERS or columns > MATRIX_NUMBERS
    wanted = options.get("numbers", True)
    note = (f"Numbers are shown up to {MATRIX_NUMBERS} × {MATRIX_NUMBERS}; this has {rows} × {columns} cells."
            if many and wanted else None)
    xs, ys = style.axis_style("x"), style.axis_style("y")
    xa, ya = d.axes[spec["x"]], d.axes[spec["y"]]
    return MatrixModel(
        grid=grid, x=np.arange(z.shape[1], dtype=float), y=rows - 1.0 - np.arange(rows), z=z, starts=starts,
        extent=((-0.5, z.shape[1] - 0.5), (-0.5, rows - 0.5)), zf=grid.zf, norm=norm, cmap=cmap, range=use,
        x_label=axis_label(spec.get("x_label") or xa.label, "" if xa.elements is not None else xa.unit, xs.label.unit_format),
        y_label=axis_label(spec.get("y_label") or ya.label, "" if ya.elements is not None else ya.unit, ys.label.unit_format),
        z_label=axis_label(spec.get("z_label") or grid.label, grid.unit, ys.label.unit_format),
        number_digits=options.get("digits", DIGITS), numbers=wanted and not many, note=note)


def number_text(v: float, digits: int, largest: float) -> str:
    """A cell's number. Rounding noise (1e-17 beside 0.5) reads as 0."""
    if v == 0 or abs(v) < largest * 1e-12:
        return "0"
    return f"{v:.{digits}g}".replace("-", "−")


def text_colour(rgba) -> str:
    """Dark text on a light cell, light on a dark one (by the cell's luminance)."""
    red, green, blue = rgba[:3]
    return "black" if 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.45 else "white"


def _ticks(axis, places: np.ndarray, texts: List[str]) -> None:
    step = max(1, int(np.ceil(len(texts) / r.MAX_ELEMENT_TICKS)))
    axis.set_ticks(places[::step], texts[::step])
    axis.set_minor_locator(NullLocator())


def draw(fig, ax, m: MatrixModel, d, spec, style: Style):
    """Draw a MatrixModel; returns the mappable. A line between the cells, equal cells, row 0 on top."""
    a = style.figure.axes
    rows, block_columns = m.grid.blocks[0].z.shape
    line = a.matrix.line_width_pt if max(rows, block_columns) <= MATRIX_NUMBERS else 0
    mappable = None
    for start, block in zip(m.starts, m.grid.blocks):
        mesh = ax.pcolormesh(start - 0.5 + np.arange(block_columns + 1), np.arange(rows + 1) - 0.5, block.z[::-1],
                             norm=m.norm, cmap=m.cmap, edgecolors=a.matrix.line_color, linewidth=line,
                             rasterized=line == 0)
        mappable = mappable or mesh
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(*m.extent[0])
    ax.set_ylim(*m.extent[1])
    ax.set_xlabel(m.x_label)
    ax.set_ylabel(m.y_label)
    ax.grid(False)
    _ticks(ax.xaxis, np.concatenate([s + np.arange(block_columns, dtype=float) for s in m.starts]),
           m.grid.col_labels * len(m.grid.blocks))
    _ticks(ax.yaxis, m.y, m.grid.row_labels)
    m.artists["titles"] = [ax.text(s + (block_columns - 1) / 2, 1.01, b.title, ha="center", va="bottom",
                                   transform=ax.get_xaxis_transform())
                           for s, b in zip(m.starts, m.grid.blocks) if b.title]
    if m.numbers:
        m.artists["numbers"] = _numbers(ax, m, style)
    if m.note:
        _warn(m.note, r.RenderWarning)
    r._annotate(ax, d, spec, [])
    r._colorbar(fig, mappable, ax, style, m.z_label, beside=True)
    return mappable


def _numbers(ax, m: MatrixModel, style: Style) -> CellNumbers:
    size = style.figure.axes.matrix.number_size_pt or style.figure.font.size_pt
    finite = m.z[np.isfinite(m.z)]
    largest = float(np.abs(finite).max()) if finite.size else 0.0
    cmap = matplotlib.colormaps[m.cmap]
    texts = []
    for i, y in enumerate(m.y):
        for j, x in enumerate(m.x):
            v = m.z[i, j]
            if np.isfinite(v):
                texts.append(Text(x, y, number_text(float(v), m.number_digits, largest), ha="center", va="center",
                                  fontsize=size, color=text_colour(cmap(m.norm(v))), clip_on=True))
    return CellNumbers(ax, texts, max((len(t.get_text()) for t in texts), default=1), size)


KIND = Kind("matrix", "Matrix", fits, resolve, prepare, draw,
            frozenset({"x", "y", "index", "x_label", "y_label", "z_label", "annotations", "re_im"}))
