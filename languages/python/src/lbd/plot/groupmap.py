"""Maps of variable sweeps: a value on an axis group, drawn with its real coordinates.

A group stores only measured points, so it has no rectangular grid. Two drawings cover it:

- **rows**: each outer point is a strip, and each stored point in it owns a cell reaching halfway to
  its neighbours. Nothing is interpolated, and nothing is drawn where nothing was measured.
- **nearest**: for scattered points, each pixel shows the nearest stored point inside their outline.

**smooth** (only when asked for) shades between the points, so its colours are worked out.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.colors as mcolors
import numpy as np
from matplotlib.tri import LinearTriInterpolator, Triangulation

from lbd import groups
from lbd.io import _warn

from . import render as rnd
from .reduce import cell_edges
from .units import axis_label

CELLS = ("auto", "rows", "nearest", "smooth")
ROWS_FROM = 3               # points per row (the median) from which a group is drawn as rows
FIGURE_PIXELS = 1200        # the picture of a nearest-point map in a figure, on each side


@dataclass
class GroupMapModel:
    """What is drawn, in plot units, one entry per point: `point` is its index on the group's level,
    `row` its row (the outer point). `rows_on`: the axis the rows are stacked along."""

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    point: np.ndarray
    row: np.ndarray
    row_at: np.ndarray
    cells: str
    rows_on: str
    xf: float
    yf: float
    zf: float
    norm: mcolors.Normalize
    cmap: str
    x_label: str
    y_label: str
    z_label: str
    x_scale: str
    y_scale: str
    auto_axes: List[Tuple[str, str]]
    x_ticks: Any = None
    y_ticks: Any = None
    tri: Dict[str, Any] = field(default_factory=dict, repr=False)   # the triangulation, once made


def _source(d: Any) -> Any:
    return getattr(d, "_unflat", None) or d


def _group_dims(d: Any, name: str) -> List[Tuple[str, ...]]:
    src = _source(d)
    v = src.values.get(name)
    return [dim for dim in v.dims if groups.is_group_dim(src, dim)] if v is not None else []


def levels(d: Any, name: str) -> Optional[List[str]]:
    """The group levels of a value of two levels or more; None if it isn't on such a group."""
    dims = [dim for dim in _group_dims(d, name) if len(dim) >= 2]
    return list(dims[0]) if dims else None


def fits(d: Any, name: str) -> Optional[str]:
    if len(_group_dims(d, name)) > 1:
        return f"'{name}' lies on two axis groups: draw it as curves"
    return None if levels(d, name) else f"'{name}' isn't on two levels of an axis group"


def _real_axes(d: Any, names: List[str]) -> Any:
    """`d` with these axes as stored: real coordinates, not point numbers."""
    out = copy.copy(d)
    out.axes = {**d.axes, **{a: _source(d).axes[a] for a in names}}
    return out


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec) -> Dict[str, Any]:
    """The axes of a map of a variable sweep: x the inner level and y the one above it, or swapped.
    A level further out is a slider, and so is a fixed axis."""
    if len(values) > 1 and warn_unused:
        _warn(f"a heat map shows one value; {values[1:]} ignored", rnd.RenderWarning)
    out["values"] = values[:1]
    name = values[0]
    names = levels(d, name)
    inner, outer = names[-1], names[-2]

    def check(a: Any) -> str:
        if a not in (inner, outer):
            raise rnd.RenderError(f"'{name}' is drawn along '{outer}' and '{inner}', not {a!r}")
        return a

    x = pick("x", check, inner)
    y = pick("y", check, outer if x == inner else inner)
    if y == x:
        y = outer if x == inner else inner
    out["x"], out["y"], out["levels"] = x, y, names
    sliders = names[-3:-2] + [a for a in d.values[name].axes if a != inner]
    out["index"], out["slices"] = rnd._slices(_real_axes(d, names[-3:-2]), sliders, index_in, spec)
    return out


def auto_cells(row: np.ndarray) -> str:
    """Rows when most rows have some points of their own, otherwise nearest point."""
    return "rows" if row.size and np.median(np.bincount(row)) >= ROWS_FROM else "nearest"


def _option(spec: Dict[str, Any]) -> str:
    cells = (spec.get("options") or {}).get("cells", "auto")
    if cells not in CELLS:
        raise rnd.RenderError(f"cells must be one of {', '.join(CELLS)}, not {cells!r}")
    return cells


def prepare(d, spec, style, zspan: Optional[Tuple[float, float]] = None) -> GroupMapModel:
    d = rnd.flat(d)
    src = _source(d)
    a = style.figure.axes
    xs, ys = style.axis_style("x"), style.axis_style("y")
    name = spec["values"][0]
    v = d.values[name]
    names = levels(d, name)
    inner, outer = names[-1], names[-2]
    z = rnd._take(v, [inner], spec["index"])
    z, label, unit = rnd.apply_complex(z, v.label, v.unit, spec["complex"])
    ancestors = groups.ancestors(src, tuple(names))          # per point: its index on every level
    keep = np.arange(z.size)
    if len(names) > 2:                                       # the branch of the slider's point
        keep = np.flatnonzero(ancestors[-3] == spec["index"].get(names[-3], 0))
    coords = {a_: np.asarray(src.axes[a_].data, dtype=float)[ix][keep] for a_, ix in zip(names, ancestors)}
    z = np.asarray(z)[keep]
    rows, row = np.unique(ancestors[-2][keep], return_inverse=True)
    row_at = np.asarray(src.axes[outer].data, dtype=float)[rows]
    xa, ya = src.axes[spec["x"]], src.axes[spec["y"]]
    x_raw, y_raw = coords[spec["x"]], coords[spec["y"]]
    xq, yq = rnd._axis_quantity(style, src, spec["x"]), rnd._axis_quantity(style, src, spec["y"])
    xf, xunit = rnd._unit_scale(x_raw, xa.unit, xq, xs.label.auto_prefix)
    yf, yunit = rnd._unit_scale(y_raw, ya.unit, yq, ys.label.auto_prefix)
    auto_axes = [(n, u) for n, q, unit_, auto, u in ((spec["x"], xq, xa.unit, xs.label.auto_prefix, xunit),
                                                     (spec["y"], yq, ya.unit, ys.label.auto_prefix, yunit))
                 if rnd._auto_prefix(q, unit_, auto)]
    q = rnd.find_quantity(style, name, v.label, spec["complex"] if np.iscomplexobj(v.data) else None)
    span = np.asarray(zspan if zspan is not None else z, dtype=float)
    zf, zunit = rnd._unit_scale(span, unit, q, ys.label.auto_prefix and q.vmin is None and q.vmax is None)
    if q.scale == "log":
        rnd._check_log(span, f"the colour scale of '{name}'")
    for scale, raw, axis in ((spec["x_scale"], x_raw, xa), (spec["y_scale"], y_raw, ya)):
        if scale == "log":
            rnd._check_log(raw, f"axis '{axis.name}'")
    chosen = _option(spec)
    model = GroupMapModel(
        x=x_raw * xf, y=y_raw * yf, z=np.asarray(z, dtype=float) * zf, point=keep, row=row,
        row_at=row_at * (yf if spec["y"] == outer else xf),
        cells=auto_cells(row) if chosen == "auto" else chosen, rows_on="y" if spec["y"] == outer else "x",
        xf=xf, yf=yf, zf=zf, norm=rnd._norm(q, zf), cmap=q.cmap or a.image.cmap,
        x_label=axis_label(spec.get("x_label") or xa.label, xunit, xs.label.unit_format),
        y_label=axis_label(spec.get("y_label") or ya.label, yunit, ys.label.unit_format),
        z_label=axis_label(spec.get("z_label") or label, zunit, ys.label.unit_format),
        x_scale=spec["x_scale"], y_scale=spec["y_scale"], auto_axes=auto_axes)
    if model.cells != "rows" and _triangles(model) is None:
        model.cells = "rows"                                 # on one line: no outline to fill
    if model.cells == "rows" and not model.z.size:
        raise rnd.RenderError(f"'{name}' has no points to draw here")
    return model


def _edges(centres: np.ndarray, log: bool, width: float) -> np.ndarray:
    """Cell edges of sorted centres: halfway between neighbours (on a log axis in log); a single
    point gets `width`, so it isn't lost."""
    if centres.size == 1:
        c = centres[0]
        return np.array([c / width, c * width]) if log else np.array([c - width / 2, c + width / 2])
    return 10 ** cell_edges(np.log10(centres)) if log else cell_edges(centres)


def _typical(values: List[np.ndarray], log: bool) -> float:
    """The usual step between neighbours, for a row of one point."""
    steps = [np.diff(np.log10(v) if log else v) for v in values if v.size > 1]
    if not steps:
        return 10.0 if log else 1.0
    step = float(np.median(np.concatenate(steps)))
    return 10 ** step if log else (step or 1.0)


def row_cells(m: GroupMapModel) -> List[Tuple[Tuple[float, float], np.ndarray, np.ndarray]]:
    """Each row's strip and its cells: `((low, high), cell edges, numbers)`, in plot units. The
    same place given twice: the later point is kept, with a warning."""
    along = m.x if m.rows_on == "y" else m.y
    log_along = (m.x_scale if m.rows_on == "y" else m.y_scale) == "log"
    log_rows = (m.y_scale if m.rows_on == "y" else m.x_scale) == "log"
    order = np.argsort(m.row_at, kind="stable")
    each = []
    for r in order:
        sel = np.flatnonzero(m.row == r)
        at, first = np.unique(along[sel][::-1], return_index=True)
        if at.size < sel.size:
            _warn(f"{sel.size - at.size} points of a variable sweep have the same place; the later one is drawn",
                  rnd.RenderWarning)
        each.append((at, m.z[sel[::-1][first]]))
    width = _typical([a for a, _ in each], log_along)
    strips = _edges(m.row_at[order], log_rows, _typical([m.row_at[order]], log_rows))
    return [((strips[k], strips[k + 1]), _edges(at, log_along, width), z) for k, (at, z) in enumerate(each)]


def _unit_box(m: GroupMapModel, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Coordinates scaled to a unit box (log axes in log), so that distance means the same both ways."""
    def scaled(v, all_, log):
        v, all_ = (np.log10(v), np.log10(all_)) if log else (v, all_)
        lo, hi = float(np.nanmin(all_)), float(np.nanmax(all_))
        return (v - lo) / ((hi - lo) or 1.0)

    return scaled(x, m.x, m.x_scale == "log"), scaled(y, m.y, m.y_scale == "log")


def _triangles(m: GroupMapModel) -> Optional[Triangulation]:
    """The points' triangulation, or None when they don't span an area."""
    if "t" not in m.tri:
        try:
            if m.z.size < 3:
                raise ValueError("fewer than 3 points")
            t = Triangulation(*_unit_box(m, m.x, m.y))
            t.get_trifinder()
            m.tri["t"] = t
        except (ValueError, RuntimeError):
            m.tri["t"] = None
    return m.tri["t"]


def _centres(edges: np.ndarray, log: bool) -> np.ndarray:
    return np.sqrt(edges[:-1] * edges[1:]) if log else (edges[:-1] + edges[1:]) / 2


def raster(m: GroupMapModel, pxe: np.ndarray, pye: np.ndarray) -> np.ndarray:
    """The picture for these pixel edges: (rows bottom to top, columns), NaN where nothing is."""
    cx, cy = _centres(np.asarray(pxe, float), m.x_scale == "log"), _centres(np.asarray(pye, float), m.y_scale == "log")
    if m.cells == "rows":
        return _raster_rows(m, cx, cy)
    t = _triangles(m)
    gx, gy = np.meshgrid(cx, cy)
    ux, uy = _unit_box(m, gx.ravel(), gy.ravel())
    if m.cells == "smooth":
        return np.ma.filled(LinearTriInterpolator(t, m.z)(ux, uy), np.nan).reshape(gx.shape)
    found = t.get_trifinder()(ux, uy)
    out = np.full(ux.shape, np.nan)
    inside = found >= 0
    corners = t.triangles[found[inside]]
    d2 = (t.x[corners] - ux[inside, None]) ** 2 + (t.y[corners] - uy[inside, None]) ** 2
    out[inside] = m.z[corners[np.arange(corners.shape[0]), np.argmin(d2, axis=1)]]
    return out.reshape(gx.shape)


def _raster_rows(m: GroupMapModel, cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    along, across = (cx, cy) if m.rows_on == "y" else (cy, cx)
    flip_a, flip_c = along[0] > along[-1], across[0] > across[-1]      # (an axis drawn downwards)
    a, c = (along[::-1] if flip_a else along), (across[::-1] if flip_c else across)
    out = np.full((c.size, a.size), np.nan)
    for (lo, hi), edges, z in row_cells(m):
        rows = slice(int(np.searchsorted(c, lo)), int(np.searchsorted(c, hi)))
        if rows.start == rows.stop:
            continue
        k = np.searchsorted(edges, a, side="right") - 1
        ok = (k >= 0) & (k < z.size)
        line = np.full(a.size, np.nan)
        line[ok] = z[k[ok]]
        out[rows] = line
    out = out[::-1] if flip_c else out
    out = out[:, ::-1] if flip_a else out
    return out if m.rows_on == "y" else out.T


def bounds(m: GroupMapModel) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """The limits that hold every cell: (x, y)."""
    if m.cells != "rows":
        return (float(np.nanmin(m.x)), float(np.nanmax(m.x))), (float(np.nanmin(m.y)), float(np.nanmax(m.y)))
    cells = row_cells(m)
    across = (float(cells[0][0][0]), float(cells[-1][0][1]))
    along = (float(min(c[1][0] for c in cells)), float(max(c[1][-1] for c in cells)))
    return (along, across) if m.rows_on == "y" else (across, along)


def _equal_rows(cells: List[Any]) -> bool:
    return len({c[2].size for c in cells}) == 1 and cells[0][2].size > 1 and len(cells) > 1


def draw(fig, ax, m: GroupMapModel, d, spec, style):
    """Draw it on matplotlib's axes (a figure, an export, a script). Returns the mappable."""
    (x0, x1), (y0, y1) = bounds(m)
    if m.cells == "rows":
        mappable = _draw_rows(ax, m)
    elif m.cells == "smooth":
        t = _triangles(m)
        mappable = ax.tripcolor(Triangulation(m.x, m.y, t.triangles), m.z, shading="gouraud", norm=m.norm,
                                cmap=m.cmap, rasterized=True)
    else:
        n = FIGURE_PIXELS
        space = np.geomspace if m.x_scale == "log" else np.linspace
        pxe = space(x0, x1, n + 1)
        pye = (np.geomspace if m.y_scale == "log" else np.linspace)(y0, y1, n + 1)
        mappable = ax.imshow(raster(m, pxe, pye), extent=(0, 1, 0, 1), transform=ax.transAxes, origin="lower",
                             interpolation="nearest", aspect="auto", norm=m.norm, cmap=m.cmap)
    ax.set_xlabel(m.x_label)
    ax.set_ylabel(m.y_label)
    ax.set_xscale(m.x_scale)
    ax.set_yscale(m.y_scale)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    rnd._annotate(ax, d, spec, m.auto_axes)
    rnd._colorbar(fig, mappable, ax, style, m.z_label)
    return mappable


def _draw_rows(ax, m: GroupMapModel):
    cells = row_cells(m)
    m.norm.autoscale_None(np.ma.masked_invalid(m.z))
    style = dict(norm=m.norm, cmap=m.cmap, rasterized=True)
    if _equal_rows(cells):                                   # one bent grid
        along = np.array([c[1] for c in cells])
        z = np.array([c[2] for c in cells])
        across = np.array([c[0][0] for c in cells] + [cells[-1][0][1]])
        rows = np.repeat(across[:, None], along.shape[1], axis=1)
        grid = np.vstack([along, along[-1]])
        if m.rows_on == "y":
            return ax.pcolormesh(grid, rows, z, shading="flat", **style)
        return ax.pcolormesh(rows, grid, z, shading="flat", **style)
    mappable = None
    for (lo, hi), edges, z in cells:
        strip = np.array([lo, hi])
        if m.rows_on == "y":
            mappable = ax.pcolormesh(edges, strip, z[None, :], shading="flat", **style)
        else:
            mappable = ax.pcolormesh(strip, edges, z[:, None], shading="flat", **style)
    return mappable
