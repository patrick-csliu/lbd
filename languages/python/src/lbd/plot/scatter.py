"""Scatter: a marker per point.

Three sources: an axis against a value, a value against a value, Re against Im of a complex value
(`complex="iq"`, the I/Q plane). `color` is an axis (a colour and legend entry per step, or a colour
bar when it has many) or another value. Without `all`, every axis not fixed in `index` keeps all its
points (a figure saved before there was a choice); with `all`, every axis not listed, drawn or
giving the colours is a slider.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.cm import ScalarMappable

from lbd.io import _warn

from . import kinds
from .points import Points, points_of
from .render import (SCATTER_RASTER_ABOVE, RenderError, RenderWarning, _annotate, _auto_prefix, _axis_quantity, _check_log,
                     _colorbar, _fits_curve, _is_point, _legend, _legend_label, _norm, _slices, _swept, _unit_scale,
                     apply_complex, find_quantity, flat)
from .style import Style
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


def prepare_scatter(d: Any, spec: Dict[str, Any], style: Style, **kw: Any) -> ScatterModel:
    d = flat(d)
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

    all_x = np.concatenate([s[0] for s in raw])
    all_y = np.concatenate([s[1] for s in raw])
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
            cf, cunit = _unit_scale(cvals, cunit, q, ys.label.auto_prefix and q.vmin is None and q.vmax is None)
            cvals = cvals * cf
            cnorm = _norm(q, cf)
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
        auto_axes=auto_axes, ylim=ylim)


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
    points = sum(int(c.sum()) for c in counts)
    return Density(counts, used, None if sums is None else sums.reshape(height, width),
                   f"{points:,} points: each pixel shows how many are there")


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
