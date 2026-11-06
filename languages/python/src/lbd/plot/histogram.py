"""Histogram: counts how many numbers fall in each bin.

`count_bins` and `auto_bins` are the one way of counting: the plot type here, the operation
Histogram of LBD Viewer and the histograms beside a scatter plot all use them.
"""

import numbers
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np

from lbd.io import _warn

from . import kinds
from .points import _fixed
from .render import (RenderError, RenderWarning, _annotate, _auto_prefix, _legend, _legend_label, _slices, _unit_scale,
                     apply_complex, find_quantity, flat, position_text)
from .style import Style
from .units import axis_label, mathsafe

MOST_BINS = 10_000


def count_bins(values: Any, bins: Any = 50, range: Optional[Tuple[float, float]] = None) -> Tuple[np.ndarray, np.ndarray]:
    """(edges, counts) of the finite numbers in `values`. `bins`: how many, or the edges themselves
    (then `range` is ignored, and blocks counted with the same edges simply add up). `range`: (lo, hi);
    None: the numbers' own. lo == hi widens by 0.5 each way. As numpy: the last bin includes its
    right edge; numbers outside aren't counted. Counts are int64."""
    numbers = np.asarray(values).ravel()
    if np.iscomplexobj(numbers):
        raise ValueError("these numbers are complex: choose how to show complex values first")
    numbers = numbers.astype(float, copy=False)
    numbers = numbers[np.isfinite(numbers)]
    if np.ndim(bins) == 0:
        if isinstance(bins, (bool, np.bool_)) or int(bins) != bins or not 2 <= bins <= MOST_BINS:
            raise ValueError(f"a histogram needs 2 to {MOST_BINS} bins, not {bins!r}")
        if range is None:
            if not numbers.size:
                raise ValueError("no values to count")
            range = (float(numbers.min()), float(numbers.max()))
        lo, hi = float(range[0]), float(range[1])
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        counts, edges = np.histogram(numbers, int(bins), (lo, hi))
    else:
        counts, edges = np.histogram(numbers, np.asarray(bins, dtype=float))
    return edges, counts.astype(np.int64, copy=False)


def auto_bins(values: Any, most: int = 200, count: Optional[int] = None,
              span: Optional[Tuple[float, float]] = None) -> int:
    """How many bins suit these numbers: Freedman-Diaconis (width 2 IQR / n^(1/3)); Sturges when the
    IQR is 0. `values`: the numbers, or a sample of them; `count`: how many there are in all, when a
    sample; `span`: (lo, hi) when the sample's own ends aren't the real ones. At least 2, at most `most`."""
    numbers = np.asarray(values, dtype=float).ravel()
    numbers = numbers[np.isfinite(numbers)]
    n = int(count) if count is not None else numbers.size
    if n < 1 or not numbers.size:
        return 2
    lo, hi = span if span is not None else (float(numbers.min()), float(numbers.max()))
    q1, q3 = np.percentile(numbers, [25, 75])
    if q3 > q1 and hi > lo:
        wanted = (hi - lo) / (2 * (q3 - q1) / n ** (1 / 3))
    else:
        wanted = np.log2(n) + 1
    return int(min(max(np.ceil(wanted), 2), most))


BLOCK = 2 ** 22             # numbers read at a time
SAMPLE = 200_000            # numbers kept to choose the bins from (about; all of them when few)
AUTO_MOST = 200             # Auto chooses at most this many bins
INTEGER_SPAN = 200          # integers within this span get a bin each
MOST_SERIES = 32            # steps of the Colour by axis
BAR_STYLES = ("bars", "outline")
Y_MODES = ("count", "fraction", "density")
_NUMERIC = ("float", "int", "uint", "bool", "complex")
_UNWRAPPED = ("phase_unwrap", "phase_deg_unwrap")


@dataclass
class HistSeries:
    label: str
    counts: np.ndarray
    colour: str


@dataclass
class HistModel:
    """A histogram worked out from its counts. `edges` in plot units (the unit prefix applied)."""

    edges: np.ndarray
    series: List[HistSeries]
    xf: float
    x_label: str
    x_unit: str
    y_label: str
    y_mode: str
    y_scale: str
    style: str                                  # "bars", or "outline" (always with several series)
    left_out: int                               # numbers not finite: not counted
    auto_axes: List[Tuple[str, str]]
    yf: float = 1.0
    notes: List[str] = field(default_factory=list)
    label: str = ""                             # what is counted, and its stored unit
    unit: str = ""


@dataclass
class Counted:
    """What counting gives, in stored units: `counts` per series, on the same `edges`. `shown`:
    (label, unit) when operations made the numbers something else than the values."""

    edges: np.ndarray
    counts: List[np.ndarray]
    left_out: int = 0
    shown: Optional[Tuple[str, str]] = None
    ops: Optional[Dict[str, Any]] = None        # LBD Viewer: what the operations did


class Span:
    """The lowest and highest number, how many there are and a sample, from blocks of numbers."""

    def __init__(self) -> None:
        self.lo, self.hi = np.inf, -np.inf
        self.count = self.left_out = 0
        self._parts: List[np.ndarray] = []
        self._kept = 0
        self._rate = 1                          # one number in this many is kept
        self._rng = np.random.default_rng(0)

    def add(self, numbers: np.ndarray) -> None:
        good = numbers[np.isfinite(numbers)]
        self.left_out += numbers.size - good.size
        if not good.size:
            return
        self.lo, self.hi = min(self.lo, float(good.min())), max(self.hi, float(good.max()))
        self.count += good.size
        kept = good if self._rate == 1 else good[self._rng.random(good.size) < 1 / self._rate]
        self._parts.append(kept)
        self._kept += kept.size
        while self._kept > 2 * SAMPLE:
            self._rate *= 2
            self._parts = [p[self._rng.random(p.size) < 0.5] for p in self._parts]
            self._kept = sum(p.size for p in self._parts)

    def edges(self, bins: Any, integers: bool = False) -> np.ndarray:
        """The bins' edges for what was seen. `bins`: "auto" or how many. `integers`: every number
        is whole, so Auto gives each a bin of its own when they are few."""
        if not self.count:
            return count_bins([], 2 if bins == "auto" else bins, (0.0, 1.0))[0]
        if bins == "auto":
            if integers and self.hi - self.lo <= INTEGER_SPAN:
                return np.arange(self.lo - 0.5, self.hi + 1.0)
            bins = auto_bins(np.concatenate(self._parts), AUTO_MOST, self.count, (self.lo, self.hi))
        return count_bins([], bins, (self.lo, self.hi))[0]


def iter_parts(v: Any, spec: Dict[str, Any], block: int = BLOCK) -> Iterator[Tuple[Optional[int], np.ndarray]]:
    """The numbers of value `v` (flat view) as shown, part by part: `(colour_step or None, numbers)`.

    Slider axes are fixed, All axes whole, the Colour by axis one step at a time. The complex choice
    is applied; points not measured are left out. Reading goes through `Value._read`, so a value read
    by part stays on disk. Parts split along the leading dimensions; an unwrapped phase keeps the
    last dimension whole, as it runs along it."""
    index = _fixed(v, spec)
    colour = spec.get("color")
    steps: Any = range(v.shape[v.axes.index(colour)]) if colour in v.axes else [None]
    index.pop(colour, None)
    kept = [i for i, a in enumerate(v.axes) if a not in index and a != colour]
    whole_last = spec["complex"] in _UNWRAPPED
    for step in steps:
        where: Dict[int, Any] = {i: index[a] for i, a in enumerate(v.axes) if a in index}
        if step is not None:
            where[v.axes.index(colour)] = step
        for part in _parts(v.shape, kept, where, block, whole_last):
            sel = tuple(part.get(i, slice(None)) for i in range(len(v.axes)))
            arr = np.asarray(v._read(sel))
            numbers = apply_complex(arr, v.label, v.unit, spec["complex"], axis=-1)[0]
            if v.measured is not None:
                numbers = np.asarray(numbers)[np.asarray(v.measured[sel], dtype=bool)]
            yield step, np.asarray(numbers, dtype=float).ravel()


def _parts(shape: Tuple[int, ...], kept: List[int], where: Dict[int, Any], block: int,
           whole_last: bool) -> Iterator[Dict[int, Any]]:
    """Selections of at most about `block` numbers over the dimensions `kept`."""
    if not kept:
        yield where
        return
    head, rest = kept[0], kept[1:]
    per = int(np.prod([shape[i] for i in rest], dtype=np.int64))
    if not rest and whole_last:
        yield where
    elif per >= block:
        for i in range(shape[head]):
            yield from _parts(shape, rest, {**where, head: i}, block, whole_last)
    else:
        rows = max(block // max(per, 1), 1)
        for start in range(0, shape[head], rows):
            yield {**where, head: slice(start, min(start + rows, shape[head]))}


def series_of(d: Any, spec: Dict[str, Any]) -> List[Tuple[str, Optional[int], str]]:
    """Each series: (value name, Colour by step or None, its label): `S21`, `ground` or `I, ground`."""
    colour = spec.get("color")
    several = len(spec["values"]) > 1
    out: List[Tuple[str, Optional[int], str]] = []
    for name in spec["values"]:
        v = d.values[name]
        label = _shown(v, spec["complex"])[0]
        if colour not in v.axes:
            out.append((name, None, mathsafe(label)))
            continue
        axis = d.axes[colour]
        for step in range(v.shape[v.axes.index(colour)]):
            text = position_text(axis, step)
            step_label = mathsafe(text) if text is not None else _legend_label(axis, axis.data[step], step)
            out.append((name, step, f"{mathsafe(label)}, {step_label}" if several else step_label))
    return out


def _shown(v: Any, mode: str) -> Tuple[str, str]:
    """A value's label and unit after the complex choice (`v` may be header-only)."""
    probe = np.ones(1, dtype=complex if v.dtype.startswith("complex") else float)
    _, label, unit = apply_complex(probe, v.label, v.unit, mode)
    return label, unit


def blocks(d: Any, spec: Dict[str, Any], block: int = BLOCK) -> Iterator[Tuple[int, np.ndarray]]:
    """(series number, numbers), block by block."""
    first = 0
    for name in spec["values"]:
        v = d.values[name]
        for step, numbers in iter_parts(v, spec, block):
            yield first + (step or 0), numbers
        first += v.shape[v.axes.index(spec["color"])] if spec.get("color") in v.axes else 1


def is_integer(d: Any, spec: Dict[str, Any]) -> bool:
    """Whether every number counted is whole by its type."""
    return all(d.values[n].dtype.startswith(("int", "uint", "bool")) for n in spec["values"])


def count(d: Any, spec: Dict[str, Any], block: int = BLOCK) -> Counted:
    """Two passes over the numbers: the bins, then the counts; only the bins are held."""
    span = Span()
    for _, numbers in blocks(d, spec, block):
        span.add(numbers)
    edges = span.edges(spec["options"]["bins"], is_integer(d, spec))
    counts = [np.zeros(edges.size - 1, dtype=np.int64) for _ in series_of(d, spec)]
    for k, numbers in blocks(d, spec, block):
        counts[k] += count_bins(numbers, edges)[1]
    return Counted(edges, counts, span.left_out)


def prepare(d: Any, spec: Dict[str, Any], style: Style, big: Optional[Counted] = None) -> HistModel:
    """`big`: the counts when they are already worked out (LBD Viewer counts large files in the
    background); otherwise the numbers are counted here, part by part."""
    d = flat(d)
    counted = big if big is not None else count(d, spec)
    first = d.values[spec["values"][0]]
    xs, ys = style.axis_style("x"), style.axis_style("y")
    shown = [counted.shown] if counted.shown else [_shown(d.values[n], spec["complex"]) for n in spec["values"]]
    labels = {label for label, _ in shown}
    unit = shown[0][1]
    q = find_quantity(style, first.name, first.label, spec["complex"] if first.dtype.startswith("complex") else None)
    xf, xunit = _unit_scale(counted.edges[[0, -1]], unit, q, xs.label.auto_prefix)
    auto_axes = [(first.name, xunit)] if _auto_prefix(q, unit, xs.label.auto_prefix) else []
    colours = style.figure.axes.colors
    named = series_of(d, spec)
    series = [HistSeries(label, c, colours[k % len(colours)]) for k, ((_, _, label), c) in enumerate(zip(named, counted.counts))]
    options = spec["options"]
    y_mode = options["hist_y"]
    y_unit = f"1/{xunit}" if y_mode == "density" and xunit else ""
    notes = []
    groups = [a for n in spec["values"] for a in d.values[n].axes if getattr(d.axes[a], "group", None) is not None]
    if groups:
        notes.append(f"{', '.join(dict.fromkeys(groups))}: part of a variable sweep, so all its points are counted "
                     "(no slider or colours on it)")
    return HistModel(
        edges=counted.edges * xf, series=series, xf=xf,
        x_label=axis_label(spec.get("x_label") or (shown[0][0] if len(labels) == 1 else "Value"), xunit, xs.label.unit_format),
        x_unit=xunit, y_label=axis_label(spec.get("y_label") or y_mode.capitalize(), y_unit, ys.label.unit_format),
        y_mode=y_mode, y_scale=spec["y_scale"], style="outline" if len(series) > 1 else options["hist_style"],
        left_out=counted.left_out, auto_axes=auto_axes, notes=notes,
        label=shown[0][0] if len(labels) == 1 else "Value", unit=unit)


def heights(model: HistModel, series: HistSeries) -> np.ndarray:
    """What the vertical axis shows for a series. Worked out here, so changing it needs no recount."""
    h = series.counts.astype(float)
    total = h.sum()
    if model.y_mode == "count" or not total:
        return h
    return h / total if model.y_mode == "fraction" else h / total / np.diff(model.edges)


def y_limits(model: HistModel, log: bool) -> Tuple[float, float]:
    """0 to the highest bar plus 5 %; on a log axis from half the smallest height that isn't 0."""
    tops = np.concatenate([heights(model, s) for s in model.series])
    tops = tops[tops > 0]
    if not tops.size:
        return (0.5, 5.0) if log else (0.0, 1.0)
    if log:
        bottom, top = float(tops.min()) / 2, float(tops.max())
        return bottom, top * (top / bottom) ** 0.05
    return 0.0, float(tops.max()) * 1.05


def _stairs(model: HistModel, series: HistSeries, log: bool) -> Dict[str, Any]:
    """A filled series' `values`, `edges` and `baseline`. On a log axis empty bins are left out."""
    h = heights(model, series)
    return {"values": np.where(h > 0, h, np.nan) if log else h, "edges": model.edges,
            "baseline": y_limits(model, True)[0] if log else 0.0}


def _outline(model: HistModel, series: HistSeries, log: bool) -> Tuple[np.ndarray, np.ndarray]:
    """An outline's x and y, as a line, so that a legend finds a free place beside it. On a log
    axis empty bins run along the axis's bottom."""
    bottom = y_limits(model, True)[0] if log else 0.0
    h = heights(model, series)
    h = np.where(h > 0, h, bottom)
    return np.repeat(model.edges, 2), np.r_[bottom, np.repeat(h, 2), bottom]


def draw_series(ax: Any, model: HistModel, style: Style, log: bool) -> List[Any]:
    """The bars or outlines: one path per series, so many bins stay quick."""
    hist = style.figure.axes.histogram
    drawn = []
    for s in model.series:
        if model.style == "bars":
            drawn.append(ax.stairs(**_stairs(model, s, log), fill=True, color=s.colour, alpha=hist.fill_alpha,
                                   linewidth=0, label=s.label))
        else:
            drawn += ax.plot(*_outline(model, s, log), color=s.colour, linewidth=hist.line_width,
                             solid_joinstyle="miter", label=s.label)
    return drawn


def update_series(drawn: List[Any], model: HistModel, log: bool) -> None:
    """The artists of `draw_series` with new counts, or for another vertical axis."""
    for artist, s in zip(drawn, model.series):
        if model.style == "bars":
            artist.set_data(**_stairs(model, s, log))
        else:
            artist.set_data(*_outline(model, s, log))


def draw(fig: Any, ax: Any, model: HistModel, d: Any, spec: Dict[str, Any], style: Style, quiet: bool = False) -> List[Any]:
    """Draw a HistModel. `quiet`: the notes are told by the caller (Explore)."""
    log = model.y_scale == "log"
    drawn = draw_series(ax, model, style, log)
    ax.set_xlabel(model.x_label)
    ax.set_ylabel(model.y_label)
    ax.set_yscale(model.y_scale)
    ax.set_xlim(model.edges[0], model.edges[-1])
    ax.set_ylim(*y_limits(model, log))
    _annotate(ax, d, spec, model.auto_axes)
    _legend(ax, style.figure.axes)
    if not quiet:
        for note in notes_of(model):
            _warn(note, RenderWarning)
    return drawn


def notes_of(model: HistModel) -> List[str]:
    """What the user should know about these counts."""
    notes = list(model.notes)
    if model.left_out:
        n = model.left_out
        notes.append(f"{n:,} number{'s' * (n != 1)} {'aren' if n != 1 else 'isn'}'t finite: not counted")
    return notes


def fits(d: Any, name: str) -> Optional[str]:
    v = d.values[name]
    if len(v.shape) == 0:
        return f"'{name}' is a single number: there is nothing to count"
    if not v.dtype.startswith(_NUMERIC):
        return f"'{name}' doesn't hold numbers"
    return None if all(v.shape) else f"'{name}' has no points yet"


def _check_options(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RenderError(f"options must be a dict of a plot type's own choices, not {type(raw).__name__}")
    bins = raw.get("bins", "auto")
    if bins != "auto" and (isinstance(bins, bool) or not isinstance(bins, numbers.Real) or int(bins) != bins
                           or not 2 <= bins <= MOST_BINS):
        raise RenderError(f"bins must be auto or a whole number from 2 to {MOST_BINS}, not {bins!r}")
    style, y = raw.get("hist_style", "bars"), raw.get("hist_y", "count")
    if style not in BAR_STYLES:
        raise RenderError(f"hist_style must be one of {BAR_STYLES}, not {style!r}")
    if y not in Y_MODES:
        raise RenderError(f"hist_y must be one of {Y_MODES}, not {y!r}")
    return {"bins": bins if bins == "auto" else int(bins), "hist_style": style, "hist_y": y}


def _starting_colour(d: Any, first: Any) -> Optional[str]:
    """A short axis with texts gives the colours (as `startingAxes` on the page)."""
    return next((a for a, n in zip(first.axes, first.shape) if getattr(d.axes[a], "elements", None) is not None
                 and n <= MOST_SERIES and getattr(d.axes[a], "group", None) is None), None)


def _starting_all(d: Any, first: Any, colour: Optional[str], sliders: Any) -> List[str]:
    """The longest axis left: all its points go in."""
    free = [(n, a) for a, n in zip(first.axes, first.shape) if a != colour and a not in sliders
            and getattr(d.axes[a], "group", None) is None]
    return [max(free, key=lambda f: f[0])[1]] if free else []


def resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec) -> Dict[str, Any]:
    """Which numbers: each axis a slider or All, one axis or none for the colours (`color`)."""
    first = d.values[values[0]]
    units = {_shown(d.values[n], out["complex"])[1] for n in values}
    if len(units) > 1:
        names = ", ".join(repr(n) for n in values)
        raise RenderError(f"the values {names} have different units ({', '.join(sorted(u or 'no unit' for u in units))}), "
                          "so they can't share one histogram: show them in two panels")
    on_group = {a for n in values for a in d.values[n].axes if getattr(d.axes[a], "group", None) is not None}

    def check_color(c: Any) -> Optional[str]:
        if c == "none":
            return None
        lacking = [n for n in values if c not in d.values[n].axes]
        if lacking:
            raise RenderError(f"'{c}' can't give the colours: {', '.join(map(repr, lacking))} has no such axis; "
                              f"axes of '{first.name}': {list(first.axes)}")
        if c in on_group:
            raise RenderError(f"'{c}' is part of a variable sweep, so it can't give the colours: all its points are counted")
        steps_ = first.shape[first.axes.index(c)]
        if steps_ > MOST_SERIES:
            raise RenderError(f"'{c}' has {steps_} steps, too many for colours (at most {MOST_SERIES}): make it a "
                              "slider or All")
        return c

    colour = pick("color", check_color, _starting_colour(d, first))
    out["color"] = colour or "none"
    given = spec.get("all") is not None or file_spec.get("all") is not None
    sliders = spec.get("index") or {}
    whole = [a for a in out.get("all", []) if a != colour] if given else _starting_all(d, first, colour, sliders)
    whole += [a for a in first.axes if a in on_group and a not in whole]
    out["all"] = whole
    out["options"] = pick("options", _check_options, _check_options({}))
    all_axes: List[str] = []
    for name in values:
        all_axes += [a for a in d.values[name].axes if a not in all_axes]
    slider_axes = [a for a in all_axes if a not in whole and a != colour and a not in on_group]
    if warn_unused and spec.get("index"):
        unused = [a for a in spec["index"] if a not in slider_axes]
        if unused:
            _warn(f"index for {unused} is ignored: those axes aren't sliders of this histogram", RenderWarning)
    out["index"], out["slices"] = _slices(d, slider_axes, index_in, spec)
    return out


KIND = kinds.Kind("histogram", "Histogram", fits, resolve, prepare, draw,
                  frozenset({"color", "index", "y_scale", "x_label", "y_label", "annotations"}))
