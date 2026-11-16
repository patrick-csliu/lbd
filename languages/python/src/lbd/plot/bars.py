"""Bars: bars with labels, grouped or stacked, for few named positions, where a line between them
would mean nothing. `read_bars` gives the numbers; what a group and a bar in it are depends on the
data (see its table in plan 15b): an axis's positions, another axis's, several values, or single
numbers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from matplotlib.text import Text
from matplotlib.ticker import NullLocator

from lbd.io import _warn

from . import render as r
from .kinds import Kind
from .matrix import CellNumbers, checked_options, number_text, position_labels, usual_length
from .style import Style
from .units import axis_label, mathsafe

LAYOUTS = ("grouped", "stacked")
SERIES_AT_MOST = 12        # a second axis longer than this starts as a slider, not as bars in a group
MARGIN = 0.05              # of the vertical range, as matplotlib's default

# With All of an axis one bar stands for many numbers: what it shows of them (16.48). The
# nan-functions leave empty points out.
STATS = {"mean": ("Mean", np.nanmean), "median": ("Median", np.nanmedian), "max": ("Max", np.nanmax),
         "min": ("Min", np.nanmin), "sum": ("Sum", np.nansum)}

OPTIONS = {
    "layout": (lambda v: v in LAYOUTS, f"layout must be one of {LAYOUTS}"),
    "numbers": (lambda v: isinstance(v, bool), "numbers must be true or false"),
    "stat": (lambda v: v in STATS, f"stat must be one of {tuple(STATS)}"),
    "errors": (lambda v: isinstance(v, bool), "errors must be true or false"),
}


@dataclass
class BarSet:
    """The numbers of a bar chart: each bar is (one of `names`, one of `groups`)."""

    groups: List[str]          # along the horizontal axis
    names: List[str]           # bars in a group: [""] for one
    heights: np.ndarray        # (bars in a group, groups), plot units; NaN: no bar
    raw: np.ndarray            # stored units
    unit_of: np.ndarray        # the same shape, 0 or 1: which vertical axis each bar uses
    bar_labels: np.ndarray     # the same shape: what each number is
    bar_units: np.ndarray      # the same shape: its stored unit
    columns: List[str]         # a short name for each of `names`, for tables
    units: List[str]           # the stored units of the left and right axes
    labels: List[str]          # what each axis shows
    shown_units: List[str]     # with their prefix
    factors: List[float]       # plot units per stored unit, per axis
    right_scale: float         # drawn height / right axis number (bars of the right axis)
    auto_axes: List[Tuple[str, str]]
    spread: Optional[np.ndarray] = None    # with All: one standard deviation per bar, plot units as `heights`


def fits(d, name: str) -> Optional[str]:
    return None                # any numbers can be bars: a size limit isn't needed (plan 15, Limits)


def starting_x(d, value) -> str:
    """An axis with `elements`, otherwise the shortest swept axis."""
    size = dict(zip(value.axes, value.shape))
    swept = r._swept(value) or list(value.axes)
    named = [a for a in swept if getattr(d.axes[a], "elements", None) is not None]
    return (named or sorted(swept, key=lambda a: size[a]))[0]


def starting_series(d, value, x: str, whole: Tuple[str, ...] = ()) -> Optional[str]:
    """A second short axis gives the bars in a group, but not one chosen as All (`whole`). A vector
    in each point has one bar per element."""
    if r._is_point(d, x):
        return None
    size = dict(zip(value.axes, value.shape))
    short = [a for a in r._swept(value) if a != x and a not in whole and size[a] <= SERIES_AT_MOST]
    return min(short, key=lambda a: size[a]) if short else None


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec) -> Dict[str, Any]:
    """`x`: the groups; `series`: the bars in a group (one value only); every other axis gets a slider,
    or with `all` its points all go into each bar (16.48)."""
    checked_options(d, out, spec, OPTIONS)
    single = [n for n in values if not d.values[n].shape]
    if single:
        if len(single) < len(values):
            raise r.RenderError(f"single numbers ({', '.join(single)}) and values with axes can't be bars of "
                                "one chart: choose either")
        out["index"], out["slices"] = {}, []
        return out
    first = d.values[values[0]]
    axes = list(first.axes)
    x = pick("x", lambda v: r._pick(v, axes, role="the groups"), starting_x(d, first))
    out["x"] = x
    for name in values[1:]:
        if x not in d.values[name].axes:
            raise r.RenderError(f"'{name}' has no axis '{x}', so it can't share the groups with '{values[0]}'")
    keep = [x]
    if len(values) == 1:
        others = [a for a in axes if a != x]
        chosen = spec.get("series") if spec.get("series") not in (None, "") else file_spec.get("series")
        if chosen != "none":
            series = pick("series", lambda v: r._pick(v, others, role="the bars in a group"), starting_series(d, first, x, tuple(out.get("all", []))))
            if series:
                out["series"] = series
                keep.append(series)
    elif spec.get("series") not in (None, "", "none") and warn_unused:
        _warn(f"series={spec['series']!r} is ignored: several values are plotted", r.RenderWarning)
    drawn = [a for a in out.get("all", []) if a in keep]
    if drawn and warn_unused and spec.get("all") is not None:
        roles = {x: "the groups", out.get("series"): "the bars in a group"}
        _warn(f"all: {', '.join(f'{a!r} gives {roles[a]}' for a in drawn)}, so it can't be All too; ignored",
              r.RenderWarning)
    whole = [a for a in out.pop("all", []) if a not in keep]
    if whole:
        out["all"] = whole
    every: List[str] = []
    for name in values:
        every += [a for a in d.values[name].axes if a not in every]
    out["index"], out["slices"] = r._slices(d, [a for a in every if a not in keep + whole], index_in, spec)
    return out


@dataclass
class _Row:
    """The bars of one name, one per group."""

    name: str
    column: str
    numbers: np.ndarray
    labels: List[str]
    units: List[str]
    spread: Optional[np.ndarray] = None      # with All: one standard deviation of each bar's numbers


def _statistic(numbers: np.ndarray, stat: str) -> Tuple[np.ndarray, np.ndarray]:
    """(what each bar shows, its standard deviation) of `numbers` (groups, many each); a group
    with no numbers has no bar (NaN), also for Sum."""
    flat = numbers.reshape(numbers.shape[0], -1)
    some = np.isfinite(flat).any(axis=1)
    out, spread = np.full(len(flat), np.nan), np.full(len(flat), np.nan)
    if some.any():
        out[some] = STATS[stat][1](flat[some], axis=1)
        spread[some] = np.nanstd(flat[some], axis=1)
    return out, spread


def _parts(numbers: np.ndarray, v, mode: str) -> List[Tuple[str, np.ndarray, str, str]]:
    """(Re or Im or nothing, numbers, label, unit) of a value as plotted."""
    if mode == "re_im" and np.iscomplexobj(numbers):
        return [("Re", numbers.real, f"Re {v.label}", v.unit), ("Im", numbers.imag, f"Im {v.label}", v.unit)]
    shown, label, unit = r.apply_complex(numbers, v.label, v.unit, "abs" if mode == "re_im" else mode)
    return [("", shown, label, unit)]


def _rows(d, spec) -> Tuple[List[str], List[_Row]]:
    """The groups, and the bars of each name in a group."""
    mode = spec["complex"]
    values = [d.values[n] for n in spec["values"]]
    if not values[0].shape:                              # single numbers: one bar each
        parts = [(v, _parts(np.asarray(r._take(v, [], {})), v, mode)) for v in values]
        names = list(dict.fromkeys(p[0] for _, ps in parts for p in ps))
        rows = []
        for name in names:
            found = [next((p for p in ps if p[0] == name), None) for _, ps in parts]
            rows.append(_Row(name, f"value_{name.lower()}" if name else "value",
                             np.array([float(p[1]) if p else np.nan for p in found]),
                             [p[2] if p else "" for p in found], [p[3] if p else "" for p in found]))
        return [mathsafe(v.label) for v in values], rows
    x, series = spec["x"], spec.get("series")
    groups = position_labels(d.axes[x])
    stat = (spec.get("options") or {}).get("stat", "mean")
    rows = []
    for v in values:
        whole = [a for a in spec.get("all", []) if a in v.axes]     # after the groups: each bar's many numbers
        if series:
            arr = r._take(v, [series, x, *whole], spec["index"])
            sa = d.axes[series]
            traces = [(r._legend_label(sa, sa.data[j], j), f"{v.name}_{j}", arr[j]) for j in range(arr.shape[0])]
        else:
            traces = [(mathsafe(v.label) if len(values) > 1 else "", v.name, r._take(v, [x, *whole], spec["index"]))]
        for name, column, numbers in traces:
            for part, shown, label, unit in _parts(np.asarray(numbers), v, mode):
                shown, spread = np.asarray(shown, dtype=float), None
                if spec.get("all"):
                    shown, spread = _statistic(shown, stat)
                    label = f"{STATS[stat][0]} of {label}"
                rows.append(_Row(", ".join(t for t in (name, part) if t), f"{column}_{part.lower()}" if part else column,
                                 shown, [label] * len(groups), [unit] * len(groups), spread))
    return groups, rows


def read_bars(d, spec, style: Style) -> BarSet:
    d = r.flat(d)
    groups, rows = _rows(d, spec)
    raw = np.array([row.numbers for row in rows], dtype=float)
    labels = np.array([row.labels for row in rows], dtype=object)
    units_each = np.array([row.units for row in rows], dtype=object)
    used = units_each[np.isfinite(raw)]
    units = list(dict.fromkeys(used.tolist())) or [""]
    if len(units) > 2:
        raise r.RenderError(f"these values have {len(units)} units ({', '.join(u or 'no unit' for u in units)}); a chart "
                            "shows two (left and right axis): choose fewer values")
    if len(units) == 2 and (spec.get("options") or {}).get("layout") == "stacked":
        raise r.RenderError(f"stacked bars need one unit; these have two ({', '.join(u or 'no unit' for u in units)})")
    unit_of = np.where(units_each == units[0], 0, 1)
    first = d.values[spec["values"][0]]
    q = r.find_quantity(style, first.name, first.label, spec["complex"] if first.dtype.startswith("complex") else None)
    auto = style.axis_style("y").label.auto_prefix
    factors, shown_units, texts, auto_axes = [], [], [], []
    scale = np.ones_like(raw)                            # drawn height per stored unit, per bar
    many = STATS[(spec.get("options") or {}).get("stat", "mean")][0] if spec.get("all") else ""
    for k, unit in enumerate(units):
        mine = unit_of == k
        f, shown = r._unit_scale(raw[mine], unit, q if k == 0 else r.QuantityStyle(), auto)
        factors.append(f)
        shown_units.append(shown)
        names = list(dict.fromkeys(str(t) for t in labels[mine & (labels != "")]))
        several = f"{many} of values" if many else "Value"
        texts.append(names[0] if len(names) == 1 else ", ".join(names) if k else several if len(units) == 1 else ", ".join(names))
        scale[mine] = f
        if k == 0 and r._auto_prefix(q, unit, auto):
            auto_axes.append((first.name, shown))
    heights = raw * scale
    right_scale = 1.0
    if len(units) == 2:                                  # both from zero, the tallest bars equally tall
        left, right = np.abs(heights[unit_of == 0]), np.abs(heights[unit_of == 1])
        tops = np.nanmax(left), np.nanmax(right)
        right_scale = float(tops[0] / tops[1]) if tops[0] > 0 and tops[1] > 0 else 1.0
        scale[unit_of == 1] *= right_scale
        heights = raw * scale
    spread = (np.array([row.spread for row in rows], dtype=float) * scale
              if all(row.spread is not None for row in rows) else None)
    names = [row.name for row in rows]
    return BarSet(groups=groups, names=names if len(names) > 1 else [""], heights=heights, raw=raw, unit_of=unit_of,
                  bar_labels=labels, bar_units=units_each, columns=[row.column for row in rows], units=units, labels=texts, shown_units=shown_units, factors=factors, right_scale=right_scale,
                  auto_axes=auto_axes, spread=spread)


@dataclass
class BarsModel:
    """Bars worked out from the data, with where each one is: bar (k, g) has its left side at
    `left[k, g]`, from `bottom[k, g]` up by `bars.heights[k, g]` (down when negative)."""

    bars: BarSet
    left: np.ndarray
    width: float
    bottom: np.ndarray
    x: np.ndarray               # the groups' centres
    y: np.ndarray               # every height
    z: np.ndarray               # (bars in a group, groups), plot units
    yf: float
    zf: float
    limits: Tuple[Tuple[float, float], Tuple[float, float]]
    x_label: str
    y_label: str
    right_label: str
    y_scale: str
    numbers: bool
    stacked: bool
    xf: float = 1.0
    errors: Optional[np.ndarray] = None    # error bars: one standard deviation each way, plot units
    lines: Tuple = ()
    artists: Dict[str, Any] = field(default_factory=dict)    # what `draw` made


def _stacked(heights: np.ndarray) -> np.ndarray:
    """Each bar's foot: positive bars pile up from zero, negative ones down from it."""
    h = np.nan_to_num(heights)
    up = np.cumsum(np.where(h > 0, h, 0), axis=0) - np.where(h > 0, h, 0)
    down = np.cumsum(np.where(h < 0, h, 0), axis=0) - np.where(h < 0, h, 0)
    return np.where(h >= 0, up, down)


def _vertical_limits(heights: np.ndarray, bottom: np.ndarray, q, f: float, log: bool, numbers: bool,
                     errors: Optional[np.ndarray] = None) -> Tuple[float, float]:
    """Zero is always in the axis (a log axis has none: its lowest bar's top, lower). Error bars fit in."""
    tops = bottom + heights
    if errors is not None:
        tops = np.concatenate([np.ravel(tops), np.ravel(tops + errors), np.ravel(tops - errors)])
    finite = tops[np.isfinite(tops)]
    if log:
        above = finite[finite > 0]
        lo, hi = (float(above.min()) / 2, float(above.max()) * 2) if above.size else (0.1, 10.0)
    else:
        lo, hi = min(0.0, float(finite.min(initial=0.0))), max(0.0, float(finite.max(initial=0.0)))
        if lo == hi:
            hi = 1.0
        margin = (hi - lo) * (3 * MARGIN if numbers else MARGIN)
        lo, hi = lo - margin * (lo < 0), hi + margin * (hi > 0)
    return (lo if q.vmin is None else q.vmin * f, hi if q.vmax is None else q.vmax * f)


def prepare(d, spec, style: Style, **kw) -> BarsModel:
    d = r.flat(d)
    bars = read_bars(d, spec, style)
    options = spec.get("options") or {}
    stacked = options.get("layout") == "stacked"
    a = style.figure.axes.bars
    count, groups = bars.heights.shape
    x = np.arange(groups, dtype=float)
    width = a.width if stacked else a.width / count
    if stacked:
        left, bottom = np.broadcast_to(x - width / 2, (count, groups)), _stacked(bars.heights)
    else:
        left = x[None, :] - a.width / 2 + width * np.arange(count)[:, None]
        bottom = np.zeros_like(bars.heights)
    first = d.values[spec["values"][0]]
    q = r.find_quantity(style, first.name, first.label, spec["complex"] if first.dtype.startswith("complex") else None)
    y_scale = "log" if q.scale == "log" else spec["y_scale"]
    if y_scale == "log":
        r._check_log(bars.heights, "the vertical axis")
    numbers = options.get("numbers", False)
    errors = bars.spread if options.get("errors") else None        # only with All: one bar, many numbers
    ylim = _vertical_limits(bars.heights, bottom, q, bars.factors[0], y_scale == "log", numbers, errors)
    xs, ys = style.axis_style("x"), style.axis_style("y")
    xa = d.axes[spec["x"]] if spec.get("x") else None
    named = xa is not None and not r._is_point(d, spec["x"])      # a data point's axis: its value says it
    x_text = spec.get("x_label") or (xa.label if named else "")
    x_unit = xa.unit if xa is not None and xa.elements is None else ""
    return BarsModel(
        bars=bars, left=left, width=width, bottom=bottom, x=x, y=np.ravel(bars.heights), z=bars.heights,
        yf=bars.factors[0], zf=bars.factors[0], limits=((-0.5, groups - 0.5), ylim),
        x_label=axis_label(x_text, x_unit, xs.label.unit_format) if x_text else "",
        y_label=axis_label(spec.get("y_label") or bars.labels[0], bars.shown_units[0], ys.label.unit_format),
        right_label=(axis_label(bars.labels[1], bars.shown_units[1], ys.label.unit_format)
                     if len(bars.units) == 2 else ""),
        y_scale=y_scale, numbers=numbers, stacked=stacked, errors=errors)


def operated(m: BarsModel, raw: np.ndarray, factor: float, unit: str, label: str, y_label: str, style: Style) -> BarsModel:
    """The same bars with other numbers (`raw` in stored units), for Explore's operations; error bars,
    of the numbers before, are left out."""
    heights = raw * factor
    bottom = _stacked(heights) if m.stacked else m.bottom
    bars = dataclasses.replace(m.bars, heights=heights, raw=raw, factors=[factor], shown_units=[unit], labels=[label],
                               bar_labels=np.full(raw.shape, label, dtype=object), spread=None)
    ylim = _vertical_limits(heights, bottom, r.QuantityStyle(), factor, False, m.numbers)
    return dataclasses.replace(m, bars=bars, bottom=bottom, y=np.ravel(heights), z=heights, yf=factor, zf=factor,
                               limits=(m.limits[0], ylim), y_label=y_label, errors=None, artists={})


def _colours(m: BarsModel, style: Style) -> np.ndarray:
    """Each bar's place in the style's colour cycle: per bar of a group, or per unit for single bars."""
    count, groups = m.z.shape
    if count > 1:
        return np.broadcast_to(np.arange(count)[:, None], (count, groups))
    return m.bars.unit_of


def _labels(ax, m: BarsModel, style: Style) -> None:
    """The groups' texts; every n-th when there are many, and slanted when they wouldn't fit side by side."""
    groups = m.bars.groups
    step = max(1, int(np.ceil(len(groups) / r.MAX_ELEMENT_TICKS)))
    shown = groups[::step]
    ax.xaxis.set_ticks(m.x[::step], shown)
    ax.xaxis.set_minor_locator(NullLocator())
    room_pt = style.figure.width_mm / 25.4 * 72 * 0.7 / max(len(shown), 1)
    if max((len(t) for t in shown), default=0) * 0.6 * style.figure.font.size_pt > room_pt:
        ax.tick_params(axis="x", labelrotation=30)
        for t in ax.get_xticklabels():
            t.set_ha("right")


def _numbers(ax, m: BarsModel, style: Style) -> Optional[CellNumbers]:
    """Each bar's number at its end."""
    size = style.figure.font.size_pt
    stored = m.bars.raw * np.array(m.bars.factors)[m.bars.unit_of]    # the number on its own axis
    finite = stored[np.isfinite(stored)]
    largest = float(np.abs(finite).max()) if finite.size else 0.0
    gap = (m.limits[1][1] - m.limits[1][0]) * 0.01
    texts = []
    for k, g in np.ndindex(m.z.shape):
        h = m.z[k, g]
        if np.isfinite(h):
            end = m.bottom[k, g] + h
            texts.append(Text(m.left[k, g] + m.width / 2, end + (gap if h >= 0 else -gap),
                              number_text(float(stored[k, g]), 3, largest), ha="center",
                              va="bottom" if h >= 0 else "top", fontsize=size, clip_on=True))
    return CellNumbers(ax, texts, usual_length(texts), size, cell=(m.width, 0.0))


def draw(fig, ax, m: BarsModel, d, spec, style: Style) -> List[Any]:
    """Draw a BarsModel: returns one container of bars per name."""
    a = style.figure.axes
    cycle = _colours(m, style)
    count = m.z.shape[0]
    drawn = []
    for k in range(count):
        colours = [a.colors[int(c) % len(a.colors)] for c in cycle[k]]
        name = m.bars.names[k]
        drawn.append(ax.bar(m.left[k], m.z[k], m.width * (1 - a.bars.gap), bottom=m.bottom[k], align="edge", color=colours,
                            edgecolor=a.frame.color, linewidth=a.bars.edge_width_pt, label=name or None))
    if m.errors is not None:                             # at each bar's end, in the frame's colour
        ok = np.isfinite(m.z) & np.isfinite(m.errors)
        centres, ends = (m.left + m.width / 2)[ok], (m.bottom + m.z)[ok]
        lw = style.to_rcparams()["axes.linewidth"]
        m.artists["errors"] = ax.errorbar(centres, ends, yerr=m.errors[ok], fmt="none", ecolor=a.frame.color,
                                          elinewidth=lw, capthick=lw, capsize=3, zorder=2.5)
    ax.axhline(0, color=a.frame.color, linewidth=style.to_rcparams()["axes.linewidth"], zorder=1.5)
    ax.set_axisbelow(True)
    ax.set_xlabel(m.x_label)
    ax.set_ylabel(m.y_label)
    ax.set_yscale(m.y_scale)
    ax.set_xlim(*m.limits[0])
    ax.set_ylim(*m.limits[1])
    _labels(ax, m, style)
    if m.right_label:
        scale = m.bars.right_scale
        right = ax.secondary_yaxis("right", functions=(lambda v: v / scale, lambda n: n * scale))
        colour = a.colors[int(cycle[m.bars.unit_of == 1][0]) % len(a.colors)]
        right.set_ylabel(m.right_label, color=colour)
        right.tick_params(colors=colour)
        m.artists["right"] = right
    if m.numbers:
        m.artists["numbers"] = _numbers(ax, m, style)
    r._annotate(ax, d, spec, m.bars.auto_axes)
    handles, _ = ax.get_legend_handles_labels()
    if a.legend.visible and 1 < len(handles) <= a.legend.max_entries:      # above the bars: they fill the plot
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncols=min(len(handles), 4), frameon=False)
    return drawn


KIND = Kind("bars", "Bars", fits, resolve, prepare, draw,
            frozenset({"x", "series", "index", "all", "y_scale", "x_label", "y_label", "annotations", "re_im"}))
