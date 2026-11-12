"""Scatter: a marker per point.

Three sources: an axis against a value, a value against a value, Re against Im of a complex value
(`complex="iq"`, the I/Q plane). `color` is an axis (a colour and legend entry per step, or a colour
bar when it has many) or another value. Without `all`, every axis not fixed in `index` keeps all its
points (a figure saved before there was a choice); with `all`, every axis not listed, drawn or
giving the colours is a slider.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.cm import ScalarMappable

from lbd.io import _warn

from . import kinds
from .histogram import BLOCK, _parts, auto_bins, count_bins
from .points import Points, _fixed
from .points import points_of as read_points
from .render import (SCATTER_RASTER_ABOVE, RenderError, RenderWarning, _annotate, _auto_prefix, _axis_quantity, _check_log,
                     _colorbar, _fits_curve, _is_point, _legend, _legend_label, _norm, _slices, _swept, _unit_scale,
                     apply_complex, find_quantity, flat, whole_numbers, whole_range)
from .style import MM, Style
from .units import axis_label, mathsafe

DENSITY_ABOVE = 200_000     # more points than this: LBD Viewer shows how many are in each pixel


@dataclass
class ScatterModel:
    """A scatter plot worked out from the data: what `draw_scatter` draws, in plot units.

    `series`: (x, y, label) of each value. `index`: per series, each point's stored index on every
    dimension. `groups`: colour by a short axis: (mask, label) per step. `cvals`: colour by a long
    axis or a value: a number per point, with `cnorm`, `cmap` and `c_label`."""

    series: List[Tuple[np.ndarray, np.ndarray, str]]
    index: List[Dict[str, np.ndarray]]
    groups: Optional[List[Tuple[np.ndarray, str]]]
    cvals: Optional[np.ndarray]
    cnorm: Optional[mcolors.Normalize]
    cmap: Optional[str]
    xf: float
    yf: float
    x_label: str
    y_label: str
    c_label: str
    x_scale: str
    y_scale: str
    equal: bool
    auto_axes: List[Tuple[str, str]]
    ylim: Optional[Tuple[Optional[float], Optional[float]]] = None
    x_text: Tuple[str, str] = ("", "")          # what x, y and the colours are: label and stored unit
    y_text: Tuple[str, str] = ("", "")
    c_text: Tuple[str, str] = ("", "")
    cf: float = 1.0                             # plot units of `cvals` per stored unit
    # x and y at every slider position (plot units), when asked for (`whole_span`): one prefix
    # and one range while a slider moves (16.49)
    whole: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None


def _numbers(v: Any, points: Points, mode: str) -> Tuple[np.ndarray, str, str]:
    """The points of a value as shown, 1-D: (numbers, label, unit). On the value's own shape, so that
    an unwrapped phase runs along its first dimension, as a figure always did."""
    numbers, label, unit = apply_complex(points.data.reshape(points.shape), v.label, v.unit, mode)
    return np.ravel(numbers), label, unit


def _axis_of(d: Any, v: Any, name: str) -> Any:
    """The axis `name` with its real label and unit: an axis group's are the owner's."""
    owner = getattr(v, "_owner", None)
    if owner is not None and getattr(d.axes.get(name), "group", None) is not None and name in owner.axes:
        return owner.axes[name]
    return d.axes[name]


@dataclass
class Span:
    """The lowest and highest x, y and colour number of points too many to hold (stored units)."""

    x: Tuple[float, float] = (0.0, 1.0)
    y: Tuple[float, float] = (0.0, 1.0)
    c: Tuple[float, float] = (0.0, 1.0)


def _no_points(v: Any) -> Points:
    """No points, for a model made from a `Span`: its labels, units and colours, not its numbers."""
    none = np.zeros(0, dtype=np.int64)
    return Points(np.zeros(0, dtype=complex if v.dtype.startswith("complex") else float),
                  {a: np.zeros(0) for a in v.axes}, {a: none for a in v.axes}, (0,))


def _steps_of(v: Any, sel: Tuple[Any, ...], axis: str, shape: Tuple[int, ...]) -> np.ndarray:
    """The stored index on `axis` of each number of the part `v[sel]`, 1-D."""
    i = v.axes.index(axis)
    at = np.arange(v.shape[i])[sel[i]]
    if np.ndim(at) == 0:
        return np.full(int(np.prod(shape, dtype=np.int64)), int(at))
    kept = [j for j, s in enumerate(sel) if not isinstance(s, (int, np.integer))]
    view = [1] * len(kept)
    view[kept.index(i)] = at.size
    return np.broadcast_to(at.reshape(view), shape).ravel()


def iter_points(d: Any, spec: Dict[str, Any], block: int = BLOCK) -> Iterator[Tuple[int, np.ndarray, np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]]:
    """Every point shown, part by part, never a whole value: (series, x, y, Colour by step or None,
    colour number or None), in stored units."""
    d = flat(d)
    mode = spec["complex"]
    colour = spec.get("color")
    if colour == "none":
        colour = None
    for k, name in enumerate(spec["values"]):
        v = d.values[name]
        index = _fixed(v, spec)
        kept = [i for i, a in enumerate(v.axes) if a not in index]
        where = {i: index[a] for i, a in enumerate(v.axes) if a in index}
        for part in _parts(v.shape, kept, where, block, False):
            sel = tuple(part.get(i, slice(None)) for i in range(len(v.axes)))
            arr = np.asarray(v._read(sel))

            def shown(value: Any, how: str) -> np.ndarray:
                return np.ravel(apply_complex(np.asarray(value._read(sel)), value.label, value.unit, how, axis=-1)[0])

            if mode == "iq":
                x, y = arr.real.ravel(), arr.imag.ravel()
            else:
                y = np.ravel(apply_complex(arr, v.label, v.unit, mode, axis=-1)[0])
                if spec["x"] in d.values:
                    x = shown(d.values[spec["x"]], mode)
                else:
                    x = np.asarray(d.axes[spec["x"]].data, dtype=float)[_steps_of(v, sel, spec["x"], arr.shape)]
            step = number = None
            if colour in d.values:
                number = shown(d.values[colour], mode if mode != "iq" else "abs")
            elif colour:
                step = _steps_of(v, sel, colour, arr.shape)
                number = np.asarray(d.axes[colour].data, dtype=float)[step]
            yield k, x, y, step, number


def prepare_scatter(d: Any, spec: Dict[str, Any], style: Style, big: Optional[Span] = None, whole_span: bool = False,
                    **kw: Any) -> ScatterModel:
    """`big`: the numbers' ends, for points too many to hold: the model has no points then (LBD
    Viewer counts them per pixel, part by part). `whole_span`: the unit prefixes are chosen from
    the numbers at every slider position, not only the ones shown, so they stay while a slider
    moves (Explore, 16.49); the model's `whole` then holds their ranges."""
    d = flat(d)

    def points_of(d_: Any, spec_: Dict[str, Any], name: str) -> Points:
        return _no_points(d_.values[name]) if big is not None else read_points(d_, spec_, name)

    a = style.figure.axes
    xs, ys = style.axis_style("x"), style.axis_style("y")
    mode = spec["complex"]
    first = d.values[spec["values"][0]]
    raw: List[Tuple[np.ndarray, np.ndarray, str]] = []
    index: List[Dict[str, np.ndarray]] = []
    points = points_of(d, spec, first.name)
    if mode == "iq":
        raw.append((points.data.real, points.data.imag, first.label))
        index.append(points.stored)
        xlab, xunit, ylab, yunit = f"Re {first.label}", first.unit, f"Im {first.label}", first.unit
        xq = yq = find_quantity(style, first.name, first.label, "iq")
    else:
        x = spec["x"]
        labels, units = [], []
        for name in spec["values"]:
            v = d.values[name]
            p = points if name == first.name else points_of(d, spec, name)
            yarr, lab, unit = _numbers(v, p, mode)
            if x in d.values:
                xv = d.values[x]
                xarr, xlab, xunit = _numbers(xv, points_of(d, spec, x), mode)
            else:
                axis = _axis_of(d, v, x)
                xarr, xlab, xunit = np.asarray(p.coords[x], dtype=float), axis.label, axis.unit
            raw.append((xarr, yarr, lab))
            index.append(p.stored)
            labels.append(lab)
            units.append(unit)
        ylab = labels[0] if len(set(labels)) == 1 else "Value"
        if len(set(units)) > 1:
            _warn(f"the values have different units {sorted(set(units))}; the vertical axis shows no unit", RenderWarning)
        yunit = units[0] if len(set(units)) == 1 else ""
        xq = _axis_quantity(style, d, x)
        yq = find_quantity(style, first.name, first.label, mode if first.dtype.startswith("complex") else None)

    stored_x, stored_y = xunit, yunit
    all_x = np.concatenate([s[0] for s in raw]) if big is None else np.asarray(big.x)
    all_y = np.concatenate([s[1] for s in raw]) if big is None else np.asarray(big.y)
    whole = None
    if whole_span and big is None:
        if mode == "iq":
            held = first.data if isinstance(first.data, np.ndarray) else None
            wx = None if held is None else np.ravel(held.real).astype(float)
            wy = None if held is None else np.ravel(held.imag).astype(float) if np.iscomplexobj(held) else np.zeros(1)
            wys = [wy]
        else:
            x = spec["x"]
            wx = whole_numbers(d.values[x], mode) if x in d.values else np.asarray(_axis_of(d, first, x).data, dtype=float)
            wys = [whole_numbers(d.values[n], mode) for n in spec["values"]]
        xr, yr = whole_range([wx]), whole_range(wys)
        whole = (xr, yr) if xr and yr else None
    if whole is not None:                  # the prefixes from every slider position
        all_x, all_y = np.array(whole[0]), np.array(whole[1])
    if mode == "iq":  # one scale for both axes keeps the I/Q plane undistorted
        base = xunit
        both = xs.label.auto_prefix and ys.label.auto_prefix
        xf, xunit = _unit_scale(np.concatenate([all_x, all_y]), xunit, xq, both)
        yf, yunit = xf, xunit
        auto_axes = [(first.name, xunit)] if _auto_prefix(xq, base, both) else []
    else:
        xbase, ybase = xunit, yunit
        xf, xunit = _unit_scale(all_x, xunit, xq, xs.label.auto_prefix)
        yf, yunit = _unit_scale(all_y, yunit, yq, ys.label.auto_prefix)
        auto_axes = [(n, u) for n, q, unit, auto, u in ((spec["x"], xq, xbase, xs.label.auto_prefix, xunit),
                                                       (first.name, yq, ybase, ys.label.auto_prefix, yunit))
                     if _auto_prefix(q, unit, auto)]

    cvals = cnorm = cmap = groups = None
    clabel = ""
    c_text = ("", "")
    cf = 1.0
    c = spec.get("color")
    if c and c != "none":
        cq = _axis_quantity(style, d, c)
        fixed_scale = cq.vmin is not None or cq.vmax is not None or cq.cmap is not None
        if c in d.axes and len(d.axes[c].data) <= len(a.colors) and not fixed_scale:
            ca = d.axes[c]
            groups = [(points.stored[c] == k, _legend_label(ca, val, k)) for k, val in enumerate(ca.data)]
        else:
            if c in d.axes:
                cvals = np.asarray(points.coords.get(c, np.asarray(d.axes[c].data)[points.stored[c]]))
                cname, clab, cunit, cmode = c, d.axes[c].label, d.axes[c].unit, None
            else:
                cv = d.values[c]
                cmode = mode if mode != "iq" else "abs"
                cvals, clab, cunit = _numbers(cv, points_of(d, spec, c), cmode)
                cname = c
                cmode = cmode if cv.dtype.startswith("complex") else None
            q = find_quantity(style, cname, clab, cmode)
            c_text = (clab, cunit)
            cspan = cvals if big is None else np.asarray(big.c)
            cf, cunit = _unit_scale(cspan, cunit, q, ys.label.auto_prefix and q.vmin is None and q.vmax is None)
            cvals = cvals * cf
            cnorm = _norm(q, cf)
            if big is not None:
                cnorm.autoscale_None(cspan * cf)
            cmap = q.cmap or a.image.cmap
            clabel = axis_label(spec.get("z_label") or clab, cunit, ys.label.unit_format)

    y_scale = "log" if yq.scale == "log" and mode != "iq" else spec["y_scale"]
    if spec["x_scale"] == "log":
        _check_log(all_x, "the horizontal axis")
    if y_scale == "log":
        _check_log(all_y, "the vertical axis")
    ylim = None
    if mode != "iq" and (yq.vmin is not None or yq.vmax is not None):
        ylim = (None if yq.vmin is None else yq.vmin * yf, None if yq.vmax is None else yq.vmax * yf)
    return ScatterModel(
        series=[(x * xf, y * yf, lab) for x, y, lab in raw], index=index, groups=groups, cvals=cvals, cnorm=cnorm, cmap=cmap,
        xf=xf, yf=yf, x_label=axis_label(spec.get("x_label") or xlab, xunit, xs.label.unit_format),
        y_label=axis_label(spec.get("y_label") or ylab, yunit, ys.label.unit_format), c_label=clabel,
        x_scale=spec["x_scale"], y_scale=y_scale, equal=(spec.get("options") or {}).get("equal", mode == "iq"),
        auto_axes=auto_axes, ylim=ylim, x_text=(xlab, stored_x), y_text=(ylab, stored_y), c_text=c_text, cf=cf,
        whole=None if whole is None else ((whole[0][0] * xf, whole[0][1] * xf), (whole[1][0] * yf, whole[1][1] * yf)))


def draw_scatter(fig: Any, ax: Any, model: ScatterModel, d: Any, spec: Dict[str, Any], style: Style,
                 image: Optional[np.ndarray] = None, top: int = 2) -> Any:
    """Draw a ScatterModel: markers, a colour per group or a colour bar. Returns the artists.
    `image` replaces the markers by a picture of the plot area's pixels (`density_image`, `top`
    points in the fullest pixel): returns it and the colour bar's mappable."""
    if image is not None:
        drawn, bar = _draw_density(fig, ax, model, style, image, top)
        label = (model.c_label if model.cvals is not None else "Points per pixel") if bar is not None else ""
        _finish(fig, ax, model, d, spec, style, bar, label)
        return drawn, bar
    a = style.figure.axes
    sc = a.scatter
    kw = dict(s=sc.size_pt ** 2, alpha=sc.alpha, marker=sc.marker, edgecolors=sc.edgecolor, linewidths=sc.edgewidth_pt)
    mappable = None
    drawn = []
    several = len(model.series) > 1
    for x, y, lab in model.series:
        raster = x.size > SCATTER_RASTER_ABOVE
        if model.groups is not None:
            for k, (mask, glab) in enumerate(model.groups):
                drawn.append(ax.scatter(x[mask], y[mask], color=a.colors[k], rasterized=raster,
                                        label=f"{lab}, {glab}" if several else glab, **kw))
        elif model.cvals is not None:
            mappable = ax.scatter(x, y, c=model.cvals, cmap=model.cmap, norm=model.cnorm, label=lab, rasterized=raster, **kw)
            drawn.append(mappable)
        else:
            drawn.append(ax.scatter(x, y, label=lab, rasterized=raster, **kw))
    _finish(fig, ax, model, d, spec, style, mappable, model.c_label)
    if (spec.get("options") or {}).get("sides"):
        draw_sides(fig, ax, model, spec, style)
    return drawn


def _finish(fig: Any, ax: Any, model: ScatterModel, d: Any, spec: Dict[str, Any], style: Style, mappable: Any,
            label: str) -> None:
    ax.set_xlabel(model.x_label)
    ax.set_ylabel(model.y_label)
    ax.set_xscale(model.x_scale)
    ax.set_yscale(model.y_scale)
    if model.ylim is not None:
        ax.set_ylim(*model.ylim)
    if model.equal:
        ax.set_aspect("equal", adjustable="datalim")
    _annotate(ax, d, spec, model.auto_axes)
    if mappable is not None:
        _colorbar(fig, mappable, ax, style, label)
    else:
        _legend(ax, style.figure.axes)


# ---- many points: how many are in each pixel --------------------------------------------------

@dataclass
class Density:
    """Points per pixel of a view, rows bottom to top. `counts`: per colour (group or value), with
    its `colours`. `sums`: colour by a value: the sum of that value per pixel."""

    counts: List[np.ndarray]
    colours: List[str]
    sums: Optional[np.ndarray]
    note: str
    sides: Optional[Dict[str, Any]] = None      # counted in the same pass, when from a file

    @property
    def total(self) -> np.ndarray:
        return np.sum(self.counts, axis=0)


def _pixel(v: np.ndarray, lim: Tuple[float, float], size: int, scale: str) -> np.ndarray:
    """The pixel column (or row) of each number; -1 outside the view."""
    with np.errstate(invalid="ignore", divide="ignore"):
        if scale == "log":
            v, lim = np.log10(v), tuple(np.log10(lim))
        at = (v - lim[0]) / (lim[1] - lim[0]) * size
    ok = (at >= 0) & (at <= size)                      # (NaN is neither)
    return np.where(ok, np.minimum(at, size - 1), -1).astype(np.int64)


def groups_of(model: ScatterModel, colours: List[str]) -> List[Tuple[int, Optional[np.ndarray], str, str]]:
    """What gets a colour of its own: (series, mask or None, colour, label)."""
    several = len(model.series) > 1
    out = []
    for k, (_, _, lab) in enumerate(model.series):
        if model.groups is None:
            out.append((k, None, colours[k % len(colours)], lab))
        else:
            out += [(k, mask, colours[g % len(colours)], f"{lab}, {glab}" if several else glab)
                    for g, (mask, glab) in enumerate(model.groups)]
    return out


def density(model: ScatterModel, xlim: Tuple[float, float], ylim: Tuple[float, float], width: int, height: int,
            scales: Tuple[str, str], colours: List[str]) -> Density:
    """Every point in the view counted into its pixel: none is dropped."""
    counts, used = [], []
    sums = np.zeros(width * height) if model.cvals is not None else None
    for k, mask, colour, _ in groups_of(model, colours):
        x, y, _ = model.series[k]
        ix, iy = _pixel(x, xlim, width, scales[0]), _pixel(y, ylim, height, scales[1])
        keep = (ix >= 0) & (iy >= 0) if mask is None else (ix >= 0) & (iy >= 0) & mask
        where = iy[keep] * width + ix[keep]
        counts.append(np.bincount(where, minlength=width * height).reshape(height, width))
        used.append(colour)
        if sums is not None:
            good = np.isfinite(model.cvals[keep])
            sums += np.bincount(where[good], weights=model.cvals[keep][good], minlength=width * height)
    return Density(counts, used, None if sums is None else sums.reshape(height, width), counted_note(counts))


def counted_note(counts: List[np.ndarray]) -> str:
    return f"{sum(int(c.sum()) for c in counts):,} points: each pixel shows how many are there"


# ---- histograms of the points in view ----------------------------------------------------------

SIDE_BINS = 100             # the most bins of a side histogram (a strip is about this many pixels)


def side_edges(lim: Tuple[float, float], scale: str, bins: int) -> np.ndarray:
    """Bins over a view: on a log axis even in the logarithm, so a bar's height is what counts."""
    if scale == "log":
        return 10.0 ** count_bins([], bins, tuple(np.log10(lim)))[0]
    return count_bins([], bins, lim)[0]


def _in_log(v: np.ndarray, scale: str) -> np.ndarray:
    return np.log10(v[v > 0]) if scale == "log" else v


def side_bins(values: List[np.ndarray], lim: Tuple[float, float], scale: str) -> Dict[str, Any]:
    """{edges, counts: per group} of numbers in view, in as many bins as suit them all."""
    both = np.concatenate(values) if values else np.zeros(0)
    span = tuple(np.log10(lim)) if scale == "log" else lim
    bins = auto_bins(_in_log(both, scale), SIDE_BINS, span=span)
    edges = side_edges(lim, scale, bins)
    return {"edges": edges, "counts": [count_bins(v, edges)[1] for v in values]}


def sides(model: ScatterModel, xlim: Tuple[float, float], ylim: Tuple[float, float], scales: Tuple[str, str],
          colours: List[str]) -> Dict[str, Any]:
    """Histograms of the points in view (both limits applied), per group: `x`, `y`, `labels`, `colours`."""
    xs, ys, labels, used = [], [], [], []
    (xlo, xhi), (ylo, yhi) = sorted(xlim), sorted(ylim)
    for k, mask, colour, label in groups_of(model, colours):
        x, y, _ = model.series[k]
        with np.errstate(invalid="ignore"):
            seen = (x >= xlo) & (x <= xhi) & (y >= ylo) & (y <= yhi)
        if mask is not None:
            seen &= mask
        xs.append(x[seen])
        ys.append(y[seen])
        labels.append(label)
        used.append(colour)
    return {"x": side_bins(xs, xlim, scales[0]), "y": side_bins(ys, ylim, scales[1]), "labels": labels, "colours": used}


def draw_sides(fig: Any, ax: Any, model: ScatterModel, spec: Dict[str, Any], style: Style) -> Tuple[Any, Any]:
    """Histograms of the points in the figure's limits, above and beside the plot, on its axes:
    bars for one group, outlines for several. Returns the two axes."""
    a = style.figure.axes
    sc = a.scatter
    if model.equal:                                      # (matplotlib: no datalim on axes shared both ways)
        ax.set_aspect("equal", adjustable="box", anchor="SW")     # (the strips go above and to the right of it)
    ax.apply_aspect()
    found = sides(model, ax.get_xlim(), ax.get_ylim(), (ax.get_xscale(), ax.get_yscale()), a.colors)
    width_mm, height_mm = (v / MM for v in fig.get_size_inches())
    top = ax.inset_axes([0, 1.03, 1, sc.sides_size_mm / height_mm * 1.3], sharex=ax)
    right = ax.inset_axes([1.03, 0, sc.sides_size_mm / width_mm * 1.3, 1], sharey=ax)
    one = len(found["colours"]) == 1
    for strip, bins, orientation in ((top, found["x"], "vertical"), (right, found["y"], "horizontal")):
        for counts, colour, label in zip(bins["counts"], found["colours"], found["labels"]):
            if one:
                strip.stairs(counts, bins["edges"], orientation=orientation, fill=True, color=colour, alpha=sc.sides_alpha,
                             linewidth=0)
            else:
                strip.stairs(counts, bins["edges"], orientation=orientation, color=colour, linewidth=a.lines.width_pt)
    top.tick_params(labelbottom=False, labelleft=False, left=False, bottom=False, top=False, right=False, which="both")
    right.tick_params(labelbottom=False, labelleft=False, left=False, bottom=False, top=False, right=False, which="both")
    top.set_ylim(bottom=0)
    right.set_xlim(left=0)
    _make_room(fig, ax)
    return top, right


def _make_room(fig: Any, ax: Any) -> None:
    """The strips take the room a legend and a colour bar had: the legend goes under the figure, a
    colour bar a little away, and the top strip's frame stays inside the picture."""
    legend = ax.get_legend()
    if legend is not None:
        handles, labels = ax.get_legend_handles_labels()
        legend.remove()
        short = [label.split(" = ", 1)[-1] for label in labels]      # (one row, under a narrow figure)
        fig.legend(handles, short, loc="outside lower center", ncols=len(labels), markerscale=2)
    for other in fig.axes:
        info = getattr(other, "_colorbar_info", None)
        if info:
            info["pad"] = max(info["pad"], 0.04)
    engine = fig.get_layout_engine()
    if engine is not None and hasattr(engine, "set"):
        engine.set(rect=(0, 0, 1, 0.95 if ax.get_aspect() != "auto" else 0.985))


def _visibility(n: np.ndarray) -> np.ndarray:
    """Opacity from a pixel's count: on a log scale, and a pixel with one point stays visible."""
    top = max(int(n.max()), 2)
    return np.where(n > 0, 0.35 + 0.65 * np.log(np.maximum(n, 1)) / np.log(top), 0.0)


def density_image(model: ScatterModel, found: Density) -> np.ndarray:
    """The RGBA picture of a Density (float, 0 to 1). Colour by a value: the mean there; several
    groups: their colours, mixed by each one's share of the pixel."""
    total = found.total
    out = np.zeros(total.shape + (4,))
    out[..., 3] = _visibility(total)
    if found.sums is not None:
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = found.sums / total
        norm = model.cnorm
        if norm.vmin is None or norm.vmax is None:
            norm.autoscale_None(np.ma.masked_invalid(model.cvals))
        out[..., :3] = matplotlib.colormaps[model.cmap](norm(np.ma.masked_invalid(mean)))[..., :3]
        return out
    safe = np.maximum(total, 1)
    for n, colour in zip(found.counts, found.colours):
        out[..., :3] += (n / safe)[..., None] * np.asarray(mcolors.to_rgb(colour))
    return out


def _draw_density(fig: Any, ax: Any, model: ScatterModel, style: Style, image: np.ndarray, top: int) -> Tuple[Any, Any]:
    """The picture on the axes box (as a map's), a legend for groups, or a colour bar: the value's,
    or Points per pixel. Returns the picture and the colour bar's mappable (None: a legend)."""
    a = style.figure.axes
    drawn = ax.imshow(image, extent=(0, 1, 0, 1), transform=ax.transAxes, origin="lower",
                      interpolation="nearest", aspect="auto", zorder=1)
    colours = groups_of(model, a.colors)
    if model.cvals is not None:
        return drawn, ScalarMappable(norm=model.cnorm, cmap=model.cmap)
    if len(colours) > 1:
        for _, _, colour, label in colours:
            ax.scatter([], [], color=colour, label=label)
        return drawn, None
    faint = mcolors.to_rgba(colours[0][2], 0.35)
    scale = mcolors.LinearSegmentedColormap.from_list("points", [faint, mcolors.to_rgba(colours[0][2], 1.0)])
    return drawn, ScalarMappable(norm=mcolors.LogNorm(1, max(top, 2)), cmap=scale)


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec=None) -> Dict[str, Any]:
    file_spec = file_spec or {}
    first = d.values[values[0]]
    axes = list(first.axes)
    same_shape = [n for n, v in d.values.items() if v.axes == axes]   # values usable point by point
    if out["complex"] == "iq":
        if not first.dtype.startswith("complex"):
            raise RenderError(f"'{first.name}' is not complex; the I/Q plane needs complex data")
        if warn_unused:
            ignored = [k for k in ("x",) if spec.get(k) not in (None, "")]
            if len(values) > 1:
                ignored.append(f"values {values[1:]}")
            if ignored:
                _warn(f"the I/Q plane plots one complex value against itself; {', '.join(ignored)} ignored",
                      RenderWarning)
        out["values"] = values[:1]
    else:
        def check_x(x: Any) -> str:
            if x not in axes and x not in same_shape:
                raise RenderError(f"'{x}' can't be the horizontal axis: use one of the axes {axes} "
                                  f"or a value with the same axes ({[n for n in same_shape if n not in values]})")
            return x

        x = pick("x", check_x, ([a for a in _swept(first) if not _is_point(d, a)] or _swept(first) or axes)[-1])
        out["x"] = x
        for name in values[1:]:
            v = d.values[name]
            ok = (x in v.axes) if x in axes else (v.axes == axes)
            if not ok:
                raise RenderError(f"'{name}' can't be plotted against '{x}' together with '{values[0]}'")

    def check_color(c: Any) -> Optional[str]:
        if c == "none":
            return None
        if c not in axes and c not in same_shape:
            raise RenderError(f"'{c}' can't colour the points: use one of the axes {axes} "
                              f"or a value with the same axes {same_shape}")
        return c

    color = pick("color", check_color, None)
    if color:
        for name in out["values"][1:]:
            if d.values[name].axes != axes:
                raise RenderError(f"colouring by '{color}' needs every value to have the axes {axes}; "
                                  f"'{name}' has {d.values[name].axes}")
        out["color"] = color
    elif warn_unused and spec.get("z_label") not in (None, ""):
        _warn("z_label is the colour bar label; it is ignored without color=", RenderWarning)
    chosen = spec.get("all") is not None or file_spec.get("all") is not None
    whole = out.get("all", [])
    on_group = [a for a in axes if getattr(d.axes[a], "group", None) is not None]
    if chosen:
        # each axis a slider or All; what is drawn or gives the colours has no slider
        out["all"] = whole + [a for a in on_group if a not in whole]
        fixed = [a for a in axes if a not in out["all"] and a != color and a != out.get("x")]
    else:
        # a figure from before the choice: every point, but for axes fixed explicitly in `index`
        fixed = [a for a in axes if a in index_in]
        for role, name in (("horizontal axis", out.get("x")), ("colour", color)):
            if name in fixed:
                raise RenderError(f"index fixes '{name}', which is the {role} of this scatter plot; remove it "
                                  "from index or choose another axis")
    if warn_unused and spec.get("index"):
        unused_idx = [a for a in spec["index"] if a not in axes]
        if unused_idx:
            _warn(f"index for {unused_idx} is ignored: '{first.name}' has no such axes", RenderWarning)
    out["index"], out["slices"] = _slices(d, fixed, index_in, spec)
    return out


KIND = kinds.Kind("scatter", "Scatter", _fits_curve, resolve, prepare_scatter, draw_scatter,
                  frozenset({"x", "color", "index", "x_scale", "y_scale", "x_label", "y_label", "z_label", "annotations"}))
