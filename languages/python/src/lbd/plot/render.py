"""Draw LBD datasets with matplotlib, using a Style.

LBD Viewer and `lbd.plot` both use these functions, so a figure looks the same whether it was
made in the viewer or in a Python script. This module is internal: use `lbd.plot.plot` and
`lbd.plot.quick`.

Plot settings given explicitly are checked strictly: anything invalid raises RenderError, and
settings that don't apply to the chosen plot type give a RenderWarning. A dataset's *saved*
view (d.plot) may be older than the data; its invalid parts are ignored with a warning.
"""

from __future__ import annotations

import difflib
import io
import math
import numbers
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure

import lbd
from lbd.io import PLOT_SPEC_KEYS, _warn

from .style import QuantityStyle, Style
from .units import AUTO_UNITS, UnitWarning, axis_label, mathsafe, prefix_scale

KINDS = ("auto", "curve", "heatmap", "scatter", "scalar")
COMPLEX_MODES = ("abs", "db", "phase", "phase_deg", "real", "imag", "iq")
SCALES = ("linear", "log")
FORMATS = {"svg": "image/svg+xml", "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}
DISPLAY_RASTER_DPI = 200  # raster layers (heat-map pixels, dense scatter) in the on-screen SVG
SCATTER_RASTER_ABOVE = 5000  # rasterize scatter plots with more points than this (vector files stay small)
SPEC_KEYS = PLOT_SPEC_KEYS
# Settings used by each plot type (kind, values, complex and title apply to all).
_APPLIES = {
    "curve": {"x", "series", "index", "x_scale", "y_scale", "x_label", "y_label", "annotations"},
    "heatmap": {"x", "y", "index", "x_scale", "y_scale", "x_label", "y_label", "z_label", "annotations"},
    "scatter": {"x", "color", "index", "x_scale", "y_scale", "x_label", "y_label", "z_label", "annotations"},
    "scalar": {"annotations"},
}

# rcParams are global in matplotlib, so renders are serialized.
RENDER_LOCK = threading.RLock()


class RenderError(ValueError):
    """The requested plot can't be made from this data (e.g. a heat map of a 1-D value, an unknown axis).

    The message says what is wrong and lists the valid choices.
    """


class RenderWarning(lbd.LBDWarning):
    """A plot was drawn, but a setting was ignored (it doesn't apply to this plot type, or the
    file's saved view refers to something that no longer exists).
    """


# ---- spec resolution ----------------------------------------------------------


def resolve_spec(d: "lbd.Dataset", spec: Optional[Dict[str, Any]], warn_unused: bool = True) -> Dict[str, Any]:
    """Fill in defaults and check a plot spec against a dataset. `d` may be header-only.

    Keys in `spec` win over the dataset's saved view (d.plot). Invalid explicit settings raise
    RenderError; invalid saved settings are ignored with a RenderWarning. With `warn_unused`,
    explicit settings that the chosen plot type doesn't use give a RenderWarning.
    """
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise RenderError(f"plot settings must be a dict, not {type(spec).__name__}")
    unknown = sorted(str(k) for k in spec if k not in SPEC_KEYS)
    if unknown:
        raise RenderError(f"unknown plot setting(s) {unknown}; allowed: {sorted(SPEC_KEYS)}")
    file_spec = d.plot if isinstance(d.plot, dict) else {}
    names = list(d.values)
    if not names:
        raise RenderError("this dataset has no values to plot")

    def explicit(key: str) -> bool:
        return spec.get(key) not in (None, "")

    def pick(key: str, check: Callable[[Any], Any], default: Any = None) -> Any:
        """The checked setting: from `spec` (errors raise) or else the saved view (errors warn)."""
        if explicit(key):
            return check(spec[key])
        raw = file_spec.get(key)
        if raw in (None, ""):
            return default
        try:
            return check(raw)
        except RenderError as e:
            _warn(f"{_where(d)}saved view: {e}; using the default instead", RenderWarning)
            return default

    # values
    def check_values(v: Any) -> List[str]:
        items = [v] if isinstance(v, str) else v
        if not isinstance(items, (list, tuple)) or not all(isinstance(x, str) for x in items) or not items:
            raise RenderError(f"values must be a value name or a list of names, not {v!r}")
        missing = [x for x in items if x not in d.values]
        if missing:
            raise RenderError(f"no value named {', '.join(map(repr, missing))}; this file has {names}")
        return list(items)

    default_value = next((n for n in names if len(d.values[n].shape) > 0), names[0])
    values = pick("values", check_values, [default_value])
    first = d.values[values[0]]
    nd = len(first.shape)

    # kind
    def check_kind(k: Any) -> str:
        if k not in KINDS:
            raise RenderError(f"unknown plot kind {k!r}; use one of {KINDS}")
        if k == "auto":
            return "scalar" if nd == 0 else ("curve" if nd == 1 else "heatmap")
        if nd == 0 and k != "scalar":
            raise RenderError(f"'{first.name}' is a single number; it can only be shown as a number "
                              "(kind='auto' or 'scalar')")
        if k == "scalar" and nd != 0:
            raise RenderError(f"'{first.name}' is {nd}-D; kind='scalar' is only for single numbers")
        if k == "heatmap" and nd < 2:
            raise RenderError(f"'{first.name}' is {nd}-D; a heat map needs 2 dimensions")
        return k

    kind = pick("kind", check_kind, check_kind("auto"))

    # complex
    def check_complex(m: Any) -> str:
        if m not in COMPLEX_MODES:
            raise RenderError(f"unknown complex mode {m!r}; use one of {COMPLEX_MODES}")
        if m == "iq" and kind != "scatter":
            raise RenderError("complex='iq' (the I/Q plane) only exists for scatter plots")
        return m

    complex_mode = pick("complex", check_complex, "abs")
    if explicit("complex") and complex_mode not in ("abs", "iq") and warn_unused \
            and not any(d.values[n].dtype.startswith("complex") for n in values):
        _warn(f"complex={complex_mode!r} has no effect: {values} {'is' if len(values) == 1 else 'are'} real",
              RenderWarning)

    out: Dict[str, Any] = {"kind": kind, "values": values, "complex": complex_mode}

    def check_scale(v: Any) -> str:
        if v not in SCALES:
            raise RenderError(f"scale must be 'linear' or 'log', not {v!r}")
        return v

    for key in ("x_scale", "y_scale"):
        out[key] = pick(key, check_scale, "linear")
    annotations = pick("annotations", check_annotations, [])
    if annotations:
        out["annotations"] = annotations
    for key in ("title", "x_label", "y_label", "z_label"):
        val = spec[key] if key in spec else file_spec.get(key)
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            if key in spec:
                raise RenderError(f"{key} must be text, not {type(val).__name__}")
            _warn(f"{_where(d)}saved view: {key} is not text; ignored", RenderWarning)
            continue
        out[key] = val

    def check_index(v: Any) -> Dict[str, int]:
        if not isinstance(v, dict):
            raise RenderError(f"index must be a dict {{axis name: position}}, not {type(v).__name__}")
        for a in v:
            if a not in d.axes:
                raise RenderError(f"index: no axis named {a!r}; axes: {list(d.axes)}")
        return dict(v)

    index_in = {**pick_dict(file_spec, "index", check_index, d), **(check_index(spec["index"]) if explicit("index") else {})}

    if warn_unused:
        unused = sorted(k for k in spec if explicit(k) and k not in {"kind", "values", "complex", "title"}
                        and k not in _APPLIES[kind])
        if unused:
            _warn(f"{unused} {'is' if len(unused) == 1 else 'are'} not used by a {kind} plot; ignored", RenderWarning)

    if kind == "scalar":
        if len(values) > 1 and warn_unused:
            _warn(f"a single number is shown; {values[1:]} ignored", RenderWarning)
        out["values"] = values[:1]
        out["index"], out["slices"] = {}, []
        return out
    if kind == "scatter":
        return _resolve_scatter(d, out, values, pick, spec, index_in, warn_unused)

    axes = list(first.axes)

    def check_x(v: Any) -> str:
        return _pick(v, axes, role="horizontal axis")

    x = pick("x", check_x, axes[-1])
    out["x"] = x
    keep = [x]
    if kind == "heatmap":
        if len(values) > 1 and warn_unused:
            _warn(f"a heat map shows one value; {values[1:]} ignored", RenderWarning)
        out["values"] = values[:1]
        rest = [a for a in axes if a != x]
        y = pick("y", lambda v: _pick(v, rest, role="vertical axis"), rest[-1])
        out["y"] = y
        keep.append(y)
    else:
        for name in values[1:]:
            if x not in d.values[name].axes:
                raise RenderError(f"'{name}' has no axis '{x}', so it can't share the x axis with '{values[0]}'")
        others = [a for a in axes if a != x]
        if len(values) == 1 and others:
            series = spec.get("series") if explicit("series") else file_spec.get("series")
            if series != "none":
                series = pick("series", lambda v: _pick(v, others, role="series"), others[0])
                out["series"] = series
                keep.append(series)
        elif explicit("series") and spec["series"] != "none" and warn_unused:
            why = "several values are plotted" if len(values) > 1 else f"'{first.name}' is 1-D"
            _warn(f"series={spec['series']!r} is ignored: {why}", RenderWarning)

    # Every remaining dimension is fixed at one index (a slice).
    all_axes: List[str] = []
    for name in out["values"]:
        all_axes += [a for a in d.values[name].axes if a not in all_axes]
    if warn_unused and explicit("index"):
        unused_idx = [a for a in spec["index"] if a in keep or a not in all_axes]
        if unused_idx:
            _warn(f"index for {unused_idx} is ignored: those axes are drawn, not sliced", RenderWarning)
    out["index"], out["slices"] = _slices(d, [a for a in all_axes if a not in keep], index_in, spec)
    return out


# ---- annotations ------------------------------------------------------------------

# Axes methods that would wreck the plot instead of drawing on it (get_* only read, so they are
# refused as well: they would do nothing).
BLOCKED_METHODS = frozenset({"clear", "cla", "remove", "draw", "draw_artist", "redraw_in_frame"})
_ANNOTATION_KEYS = {"method", "patch", "args", "kwargs"}


def _axes_methods() -> List[str]:
    from matplotlib.axes import Axes

    return sorted(n for n in dir(Axes) if not n.startswith("_") and n not in BLOCKED_METHODS
                  and not n.startswith("get_") and callable(getattr(Axes, n, None)))


def _patch_classes() -> List[str]:
    import matplotlib.patches as mpatches

    return sorted(n for n, c in vars(mpatches).items()
                  if isinstance(c, type) and issubclass(c, mpatches.Patch) and not n.startswith("_"))


def _suggest(name: str, choices: List[str]) -> str:
    close = difflib.get_close_matches(name, choices, n=3)
    return f"; did you mean {', '.join(close)}?" if close else ""


def check_annotations(v: Any) -> List[Dict[str, Any]]:
    """Check the `annotations` setting: a list of {"method" or "patch", "args", "kwargs"}.

    Only checks that matplotlib has the method (an Axes method) or the patch class
    (matplotlib.patches); the arguments are matplotlib's business and are checked when drawing.
    """
    if not isinstance(v, list):
        raise RenderError(f"annotations must be a list, not {type(v).__name__}")
    out = []
    for i, item in enumerate(v):
        where = f"annotations[{i}]"
        if not isinstance(item, dict):
            raise RenderError(f"{where} must be an object like {{\"method\": \"axvline\", \"args\": [1.0]}}, "
                              f"not {type(item).__name__}")
        extra = sorted(str(k) for k in item if k not in _ANNOTATION_KEYS)
        if extra:
            raise RenderError(f"{where}: unknown key(s) {extra}; use method or patch, args, kwargs")
        if ("method" in item) == ("patch" in item):
            raise RenderError(f"{where} needs exactly one of 'method' (an Axes method, e.g. axvline) "
                              "or 'patch' (a matplotlib.patches class, e.g. Rectangle)")
        if not isinstance(item.get("args", []), list):
            raise RenderError(f"{where}: args must be a list, not {type(item['args']).__name__}")
        if not isinstance(item.get("kwargs", {}), dict):
            raise RenderError(f"{where}: kwargs must be an object, not {type(item['kwargs']).__name__}")
        if "method" in item:
            name = item["method"]
            if not isinstance(name, str):
                raise RenderError(f"{where}: method must be text, not {type(name).__name__}")
            if name in BLOCKED_METHODS or name.startswith("get_"):
                raise RenderError(f"{where}: '{name}' can't be used in annotations (it doesn't draw anything "
                                  "or would remove the plot)")
            methods = _axes_methods()
            if name not in methods:
                raise RenderError(f"{where}: matplotlib's Axes has no method {name!r}{_suggest(name, methods)}")
        else:
            name = item["patch"]
            if not isinstance(name, str):
                raise RenderError(f"{where}: patch must be text, not {type(name).__name__}")
            patches = _patch_classes()
            if name not in patches:
                raise RenderError(f"{where}: matplotlib.patches has no shape {name!r}{_suggest(name, patches)}")
        out.append(dict(item))
    return out


def _auto_prefix(q: QuantityStyle, unit: str, auto: bool) -> bool:
    """Whether _unit_scale picks this axis' unit prefix automatically (so it may change)."""
    return auto and q.prefix is None and unit in AUTO_UNITS


def _annotate(ax, d, spec, auto_axes: List[Tuple[str, str]]) -> None:
    """Draw the spec's annotations: each calls one Axes method, or adds one patch."""
    items = spec.get("annotations") or []
    if not items:
        return
    if auto_axes:
        names = ", ".join(f"'{n}' (now {u})" for n, u in auto_axes)
        _warn(f"annotations use the units shown on the axes, but the unit prefix of {names} is chosen "
              "automatically and may change with the data or style; set a fixed prefix "
              f"(style quantities, e.g. quantities.{auto_axes[0][0]}.prefix)", RenderWarning)
    saved = getattr(d, "matplotlib", None)
    for i, item in enumerate(items):
        args, kwargs = list(item.get("args", [])), dict(item.get("kwargs", {}))
        try:
            if "patch" in item:
                import matplotlib.patches as mpatches

                name = item["patch"]
                ax.add_patch(getattr(mpatches, name)(*args, **kwargs))
            else:
                name = item["method"]
                getattr(ax, name)(*args, **kwargs)
        except Exception as e:
            versions = (f" (the view was saved with matplotlib {saved}; this is {matplotlib.__version__})"
                        if saved and saved != matplotlib.__version__ else "")
            raise RenderError(f"annotations[{i}] ({name}): {type(e).__name__}: {e}{versions}") from e


def _legend(ax, a) -> None:
    """The legend, when there is more than one labelled entry (curves, and annotations with a label)."""
    handles, _ = ax.get_legend_handles_labels()
    if a.legend.visible and 1 < len(handles) <= a.legend.max_entries:
        ax.legend()


def pick_dict(file_spec: Dict[str, Any], key: str, check: Callable[[Any], Any], d) -> Dict[str, Any]:
    raw = file_spec.get(key)
    if not raw:
        return {}
    try:
        return check(raw)
    except RenderError as e:
        _warn(f"{_where(d)}saved view: {e}; ignored", RenderWarning)
        return {k: v for k, v in raw.items() if k in d.axes} if isinstance(raw, dict) else {}


def _resolve_scatter(d, out, values, pick, spec, index_in, warn_unused) -> Dict[str, Any]:
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

        x = pick("x", check_x, axes[-1])
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
    # Scatter plots use every point; only axes fixed explicitly in `index` are sliced.
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


def _slices(d, axes: List[str], index_in: Dict[str, Any], spec: Dict[str, Any]):
    slices = []
    explicit = spec.get("index") or {}
    for a in axes:
        n = len(d.axes[a])
        raw = index_in.get(a, 0)
        try:
            i = _as_index(raw, a, n)
        except RenderError as e:
            if a in explicit:
                raise
            _warn(f"{_where(d)}saved view: {e}; using the first point", RenderWarning)
            i = 0
        ax = d.axes[a]
        slices.append({"axis": a, "index": i, "length": n, "label": ax.label, "unit": ax.unit,
                       "value": _num(ax.data[i])})
    return {s["axis"]: s["index"] for s in slices}, slices


def _as_index(raw: Any, axis: str, n: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
        raise RenderError(f"index of '{axis}' must be a whole number, not {raw!r}")
    if not float(raw).is_integer():
        raise RenderError(f"index of '{axis}' must be a whole number, not {raw!r}")
    i = int(raw)
    if not -n <= i < n:
        raise RenderError(f"index {i} is out of range for axis '{axis}' (it has {n} points: 0…{n - 1}, "
                          f"or -1…-{n} from the end)")
    return i % n


def _pick(requested: Any, choices: List[str], role: str) -> str:
    if requested not in choices:
        raise RenderError(f"{requested!r} can't be used as {role}; choose from {choices}")
    return requested


def _where(d) -> str:
    return f"{d.path.name}: " if getattr(d, "path", None) else ""


def _num(x: Any) -> Any:
    x = x.item() if hasattr(x, "item") else x
    return x if not isinstance(x, float) or math.isfinite(x) else None


def _legend_label(axis, value: Any) -> str:
    """'Power = −60 dBm': one point of an axis in a legend (with a real minus, like the tick labels)."""
    number = _fmt(value).replace("-", "−")
    return f"{mathsafe(axis.label)} = {number} {axis.unit}".strip()


def _fmt(x: Any) -> str:
    """A coordinate for a legend or slider label (NaN-safe)."""
    v = x.item() if hasattr(x, "item") else x
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


# ---- data helpers ---------------------------------------------------------------


def _take(v: "lbd.Value", keep: List[str], index: Dict[str, int]) -> np.ndarray:
    """Slice a value down to the axes in `keep`, in that order."""
    idx = tuple(slice(None) if a in keep else index.get(a, 0) for a in v.axes)
    arr = np.asarray(v.data)[idx] if v.axes else np.asarray(v.data)
    remaining = [a for a in v.axes if a in keep]
    order = [remaining.index(a) for a in keep if a in remaining]
    return np.transpose(arr, order) if len(order) > 1 else arr


def _points(d, v: "lbd.Value", index: Dict[str, int]) -> Tuple[np.ndarray, List[str]]:
    """All points of a value (only axes in `index` are fixed), and the axes left."""
    idx = tuple(index[a] if a in index else slice(None) for a in v.axes)
    arr = np.asarray(v.data)[idx] if v.axes else np.asarray(v.data)
    return arr, [a for a in v.axes if a not in index]


def _coords(d, axis: str, axes_left: List[str], shape: Tuple[int, ...]) -> np.ndarray:
    """Coordinates of `axis` broadcast to the shape of the points."""
    data = np.asarray(d.axes[axis].data, dtype=float)
    view = [1] * len(axes_left)
    view[axes_left.index(axis)] = len(data)
    return np.broadcast_to(data.reshape(view), shape)


def apply_complex(arr: np.ndarray, label: str, unit: str, mode: str) -> Tuple[np.ndarray, str, str]:
    """Turn data into what is plotted for a complex mode: (numbers, label, unit).

    Real data is returned unchanged for every mode (see resolve_spec, which warns).
    """
    if mode not in COMPLEX_MODES:
        raise RenderError(f"unknown complex mode {mode!r}; use one of {COMPLEX_MODES}")
    if not np.iscomplexobj(arr):
        return (arr.astype(float, copy=False) if arr.dtype.kind in "biu" else arr), label, unit
    if mode in ("abs", "iq"):
        return np.abs(arr), f"|{label}|", unit
    if mode == "db":
        mag = np.abs(arr)
        if np.any(mag == 0):
            _warn(f"'{label}' has zeros; their dB value (-inf) is not drawn", RenderWarning)
        with np.errstate(divide="ignore"):
            return 20 * np.log10(mag), f"|{label}|", "dB"
    if mode == "phase":
        return np.angle(arr), f"arg {label}", "rad"
    if mode == "phase_deg":
        return np.degrees(np.angle(arr)), f"arg {label}", "°"
    if mode == "real":
        return arr.real, f"Re {label}", unit
    return arr.imag, f"Im {label}", unit


def find_quantity(style: Style, name: str, label: str, mode: Optional[str]) -> QuantityStyle:
    """The fixed scale for a quantity: by `<name>.<mode>`, then name, then label; else defaults."""
    q = style.quantities
    for key in ([f"{name}.{mode}"] if mode else []) + [name, label]:
        if key in q:
            return q[key]
    return QuantityStyle()


def _unit_scale(values, unit: str, q: QuantityStyle, auto: bool) -> Tuple[float, str]:
    """(factor, unit) for one axis or colour scale: the quantity's fixed prefix, else automatic."""
    if q.prefix is not None:
        if q.prefix and not unit:
            _warn(f"a unit prefix {q.prefix!r} is set for a quantity without a unit; ignored", UnitWarning)
            return 1.0, unit
        return prefix_scale(values, unit, q.prefix)
    if auto:
        return prefix_scale(values, unit, "auto", warn=False)
    return 1.0, unit


def _norm(q: QuantityStyle, factor: float = 1.0) -> mcolors.Normalize:
    vmin = None if q.vmin is None else q.vmin * factor
    vmax = None if q.vmax is None else q.vmax * factor
    return mcolors.LogNorm(vmin=vmin, vmax=vmax) if q.scale == "log" else mcolors.Normalize(vmin=vmin, vmax=vmax)


def _check_log(values: np.ndarray, what: str) -> None:
    finite = values[np.isfinite(values)] if values.size else values
    if finite.size and np.any(finite <= 0):
        _warn(f"{what} uses a log scale but has values <= 0; those points are not drawn", RenderWarning)


# ---- drawing ---------------------------------------------------------------------


def new_figure(style: Style) -> Figure:
    """A Figure of the style's size (no pyplot involved; safe in servers and threads)."""
    from .style import MM

    return Figure(figsize=(style.figure.width_mm * MM, style.figure.height_mm * MM), layout="constrained")


def build_figure(d: "lbd.Dataset", spec: Dict[str, Any], style: Style,
                 fig: Optional[Figure] = None, ax=None):
    """Draw a resolved spec. Call inside `matplotlib.rc_context(style.to_rcparams())`.

    `d` must have the data of the plotted values loaded (and of `x`/`color` if they are values).
    Returns (figure, axes).
    """
    if ax is None:
        fig = fig or new_figure(style)
        ax = fig.add_subplot()
    else:
        fig = ax.figure
    kind = spec["kind"]
    if kind == "scalar":
        _draw_scalar(ax, d, spec, style)
    elif kind == "curve":
        _draw_curves(fig, ax, d, spec, style)
    elif kind == "scatter":
        _draw_scatter(fig, ax, d, spec, style)
    else:
        _draw_heatmap(fig, ax, d, spec, style)
    if spec.get("title"):
        ax.set_title(mathsafe(spec["title"]))
    apply_axis_text(ax, style)
    return fig, ax


def apply_axis_text(ax, style: Style) -> None:
    """Per-axis label size and padding (rcParams only have one setting for both axes), and the
    tick settings pinned on the Axes.

    matplotlib creates tick marks lazily while drawing and gives new ticks the *current*
    rcParams. Pinning them with tick_params keeps a figure identical when it is saved later
    outside the style (e.g. a plain fig.savefig after lp.plot)."""
    rc = style.to_rcparams()
    font = style.figure.font
    for name, axis, s in (("x", ax.xaxis, style.axis_style("x")), ("y", ax.yaxis, style.axis_style("y"))):
        if s.label.size_pt:
            axis.label.set_size(s.label.size_pt)
        axis.labelpad = s.label.pad_pt
        side = {"top": s.ticks.mirror, "bottom": True} if name == "x" else {"right": s.ticks.mirror, "left": True}
        common = dict(direction=s.ticks.direction, color=style.figure.axes.frame.color,
                      labelfontfamily=rc["font.family"][0], **side)
        ax.tick_params(axis=name, which="major", length=s.ticks.length_pt, width=rc[f"{name}tick.major.width"],
                       labelsize=s.ticks.label_size_pt or font.size_pt, **common)
        ax.tick_params(axis=name, which="minor", length=s.minor.length_pt, width=rc[f"{name}tick.minor.width"],
                       **common)


def _colorbar(fig, mappable, ax, style: Style, label: str):
    cb_style = style.figure.axes.image.colorbar
    if not cb_style.visible:
        return
    cb = fig.colorbar(mappable, ax=ax, fraction=cb_style.size_pct / 100, pad=cb_style.pad_pct / 100, label=label)
    # Pin the colour bar's ticks like the plot's (see apply_axis_text).
    rc = style.to_rcparams()
    s = style.axis_style("y")
    common = dict(direction=s.ticks.direction, color=style.figure.axes.frame.color,
                  labelfontfamily=rc["font.family"][0])
    cb.ax.tick_params(which="major", length=s.ticks.length_pt, width=rc["ytick.major.width"],
                      labelsize=s.ticks.label_size_pt or style.figure.font.size_pt, **common)
    cb.ax.tick_params(which="minor", length=s.minor.length_pt, width=rc["ytick.minor.width"], **common)
    if s.label.size_pt:
        cb.ax.yaxis.label.set_size(s.label.size_pt)


def _draw_scalar(ax, d, spec, style: Style) -> None:
    v = d.values[spec["values"][0]]
    arr, label, unit = apply_complex(np.asarray(v.data), v.label, v.unit, spec["complex"])
    q = find_quantity(style, v.name, v.label, spec["complex"] if np.iscomplexobj(v.data) else None)
    factor, unit = _unit_scale(np.atleast_1d(arr), unit, q, style.axis_style("y").label.auto_prefix)
    ax.set_axis_off()
    ax.text(0.5, 0.5, f"{mathsafe(label)} = {float(arr) * factor:.6g} {unit}".strip(), ha="center", va="center",
            transform=ax.transAxes, fontsize="large")
    _annotate(ax, d, spec, [])


def _axis_quantity(style: Style, d, name: str) -> QuantityStyle:
    a = d.axes[name] if name in d.axes else d.values[name]
    return find_quantity(style, name, a.label, None)


def _draw_curves(fig: Figure, ax, d, spec, style: Style) -> None:
    a = style.figure.axes
    xs, ys = style.axis_style("x"), style.axis_style("y")
    xa = d.axes[spec["x"]]
    x_raw = np.asarray(xa.data, dtype=float)
    xq = _axis_quantity(style, d, spec["x"])
    xf, xunit = _unit_scale(x_raw, xa.unit, xq, xs.label.auto_prefix)
    auto_axes = [(spec["x"], xunit)] if _auto_prefix(xq, xa.unit, xs.label.auto_prefix) else []
    lines: List[Tuple[np.ndarray, str]] = []
    labels, units = [], []
    quantity: Optional[QuantityStyle] = None
    series_colors = None
    series_mappable = None
    for name in spec["values"]:
        v = d.values[name]
        keep = [spec["x"]] + ([spec["series"]] if spec.get("series") else [])
        arr = _take(v, keep, spec["index"])
        arr, label, unit = apply_complex(arr, v.label, v.unit, spec["complex"])
        labels.append(label)
        units.append(unit)
        if quantity is None:  # the first value's fixed scale sets the vertical axis
            quantity = find_quantity(style, name, v.label, spec["complex"] if np.iscomplexobj(v.data) else None)
        if spec.get("series"):
            sa = d.axes[spec["series"]]
            n = arr.shape[1]
            if n > len(a.colors):
                cmap = matplotlib.colormaps[a.image.cmap]
                series_colors = cmap(np.linspace(0, 1, n))
                norm = mcolors.Normalize(float(np.min(sa.data)), float(np.max(sa.data)))
                series_mappable = (ScalarMappable(norm=norm, cmap=cmap), sa)
            for j in range(n):
                lines.append((arr[:, j], _legend_label(sa, sa.data[j])))
        else:
            lines.append((arr, label))
    quantity = quantity or QuantityStyle()

    yall = np.concatenate([np.ravel(y) for y, _ in lines]) if lines else np.array([])
    if len(set(units)) > 1:
        _warn(f"the curves have different units {sorted(set(units))}; the vertical axis shows no unit", RenderWarning)
    common_unit = units[0] if len(set(units)) == 1 else ""
    yf, yunit = _unit_scale(yall, common_unit, quantity, ys.label.auto_prefix)
    if _auto_prefix(quantity, common_unit, ys.label.auto_prefix):
        auto_axes.append((spec["values"][0], yunit))
    for j, (y, lab) in enumerate(lines):
        kw = {"color": series_colors[j]} if series_colors is not None else {}
        ax.plot(x_raw * xf, np.asarray(y) * yf, label=lab, **kw)

    ax.set_xlabel(axis_label(spec.get("x_label") or xa.label, xunit, xs.label.unit_format))
    # Several values: the legend names them, so the axis gets a generic label.
    ylabel = spec.get("y_label") or (labels[0] if len(set(labels)) == 1 else "Value")
    ax.set_ylabel(axis_label(ylabel, yunit, ys.label.unit_format))
    y_scale = "log" if quantity.scale == "log" else spec["y_scale"]
    if spec["x_scale"] == "log":
        _check_log(x_raw, f"the horizontal axis '{xa.name}'")
    if y_scale == "log":
        _check_log(yall.real if np.iscomplexobj(yall) else yall, "the vertical axis")
    ax.set_xscale(spec["x_scale"])
    ax.set_yscale(y_scale)
    if quantity.vmin is not None or quantity.vmax is not None:
        ax.set_ylim(None if quantity.vmin is None else quantity.vmin * yf,
                    None if quantity.vmax is None else quantity.vmax * yf)
    ax.margins(x=0)
    _annotate(ax, d, spec, auto_axes)
    if series_mappable is not None:
        sm, sa = series_mappable
        _colorbar(fig, sm, ax, style, axis_label(sa.label, sa.unit, ys.label.unit_format))
    else:
        _legend(ax, a)


def _draw_heatmap(fig: Figure, ax, d, spec, style: Style) -> None:
    a = style.figure.axes
    xs, ys = style.axis_style("x"), style.axis_style("y")
    name = spec["values"][0]
    v = d.values[name]
    xa, ya = d.axes[spec["x"]], d.axes[spec["y"]]
    z = _take(v, [spec["y"], spec["x"]], spec["index"])     # rows = y, columns = x
    z, label, unit = apply_complex(z, v.label, v.unit, spec["complex"])
    q = find_quantity(style, name, v.label, spec["complex"] if np.iscomplexobj(v.data) else None)
    x_raw = np.asarray(xa.data, dtype=float)
    y_raw = np.asarray(ya.data, dtype=float)
    xq, yq = _axis_quantity(style, d, spec["x"]), _axis_quantity(style, d, spec["y"])
    xf, xunit = _unit_scale(x_raw, xa.unit, xq, xs.label.auto_prefix)
    yf, yunit = _unit_scale(y_raw, ya.unit, yq, ys.label.auto_prefix)
    auto_axes = [(n, u) for n, q, unit, auto, u in ((spec["x"], xq, xa.unit, xs.label.auto_prefix, xunit),
                                                   (spec["y"], yq, ya.unit, ys.label.auto_prefix, yunit))
                 if _auto_prefix(q, unit, auto)]
    # With fixed limits, the colour bar keeps the value's own unit so the limits read as entered.
    zf, zunit = _unit_scale(z, unit, q, ys.label.auto_prefix and q.vmin is None and q.vmax is None)
    if q.scale == "log":
        _check_log(np.asarray(z, dtype=float), f"the colour scale of '{name}'")
    for scale, raw, axis in ((spec["x_scale"], x_raw, xa), (spec["y_scale"], y_raw, ya)):
        if scale == "log":
            _check_log(raw, f"axis '{axis.name}'")
    mesh = ax.pcolormesh(x_raw * xf, y_raw * yf, z * zf, shading="nearest", norm=_norm(q, zf),
                         cmap=q.cmap or a.image.cmap, rasterized=True)
    ax.set_xlabel(axis_label(spec.get("x_label") or xa.label, xunit, xs.label.unit_format))
    ax.set_ylabel(axis_label(spec.get("y_label") or ya.label, yunit, ys.label.unit_format))
    ax.set_xscale(spec["x_scale"])
    ax.set_yscale(spec["y_scale"])
    _annotate(ax, d, spec, auto_axes)
    _colorbar(fig, mesh, ax, style, axis_label(spec.get("z_label") or label, zunit, ys.label.unit_format))


def _draw_scatter(fig: Figure, ax, d, spec, style: Style) -> None:
    a = style.figure.axes
    sc = a.scatter
    xs, ys = style.axis_style("x"), style.axis_style("y")
    index = spec["index"]
    mode = spec["complex"]
    first = d.values[spec["values"][0]]

    # (x points, y points, legend label) for every series, plus axis labels and units
    series: List[Tuple[np.ndarray, np.ndarray, str]] = []
    if mode == "iq":
        arr, shape_axes = _points(d, first, index)
        arr = np.asarray(arr)
        series.append((arr.real.ravel(), arr.imag.ravel(), first.label))
        xlab, xunit, ylab, yunit = f"Re {first.label}", first.unit, f"Im {first.label}", first.unit
        point_shape = arr.shape
        xq = yq = find_quantity(style, first.name, first.label, "iq")
    else:
        x = spec["x"]
        xlab = xunit = ylab = yunit = ""
        labels, units = [], []
        point_shape, shape_axes = None, None
        for name in spec["values"]:
            v = d.values[name]
            arr, left = _points(d, v, index)
            yarr, lab, unit = apply_complex(np.asarray(arr), v.label, v.unit, mode)
            if x in d.axes:
                xarr = _coords(d, x, left, yarr.shape)
                xlab, xunit = d.axes[x].label, d.axes[x].unit
            else:
                xv = d.values[x]
                xraw, _ = _points(d, xv, index)
                xarr, xlab, xunit = apply_complex(np.asarray(xraw), xv.label, xv.unit, mode)
            if point_shape is None:
                point_shape, shape_axes = yarr.shape, left
            series.append((np.ravel(xarr), np.ravel(yarr), lab))
            labels.append(lab)
            units.append(unit)
        ylab = labels[0] if len(set(labels)) == 1 else "Value"
        if len(set(units)) > 1:
            _warn(f"the values have different units {sorted(set(units))}; the vertical axis shows no unit",
                  RenderWarning)
        yunit = units[0] if len(set(units)) == 1 else ""
        xq = _axis_quantity(style, d, x)
        yq = find_quantity(style, first.name, first.label, mode if np.iscomplexobj(first.data) else None)

    all_x = np.concatenate([s[0] for s in series])
    all_y = np.concatenate([s[1] for s in series])
    if mode == "iq":  # one scale for both axes keeps the I/Q plane undistorted
        base = xunit
        xf, xunit = _unit_scale(np.concatenate([all_x, all_y]), xunit, xq,
                                xs.label.auto_prefix and ys.label.auto_prefix)
        yf, yunit = xf, xunit
        auto_axes = ([(first.name, xunit)] if _auto_prefix(xq, base, xs.label.auto_prefix and ys.label.auto_prefix)
                     else [])
    else:
        xbase, ybase = xunit, yunit
        xf, xunit = _unit_scale(all_x, xunit, xq, xs.label.auto_prefix)
        yf, yunit = _unit_scale(all_y, yunit, yq, ys.label.auto_prefix)
        auto_axes = [(n, u) for n, q, unit, auto, u in ((spec["x"], xq, xbase, xs.label.auto_prefix, xunit),
                                                       (first.name, yq, ybase, ys.label.auto_prefix, yunit))
                     if _auto_prefix(q, unit, auto)]

    # colour by a third quantity
    cvals = None
    cnorm = None
    cmap = None
    clabel = ""
    groups = None      # colour by a short axis: one cycle colour and legend entry per point of it
    if spec.get("color"):
        c = spec["color"]
        cq = _axis_quantity(style, d, c)
        fixed_scale = cq.vmin is not None or cq.vmax is not None or cq.cmap is not None
        if c in d.axes and len(d.axes[c].data) <= len(a.colors) and not fixed_scale:
            ca = d.axes[c]
            where = np.ravel(_coords(d, c, shape_axes, point_shape))
            groups = [(where == val, _legend_label(ca, val)) for val in ca.data]
        else:
            if c in d.axes:
                cvals = _coords(d, c, shape_axes, point_shape)
                cname, clab, cunit = c, d.axes[c].label, d.axes[c].unit
                cmode = None
            else:
                cv = d.values[c]
                craw, _ = _points(d, cv, index)
                cmode = mode if mode != "iq" else "abs"
                cvals, clab, cunit = apply_complex(np.asarray(craw), cv.label, cv.unit, cmode)
                cname = c
                cmode = cmode if np.iscomplexobj(cv.data) else None
            q = find_quantity(style, cname, clab, cmode)
            cf, cunit = _unit_scale(cvals, cunit, q, ys.label.auto_prefix and q.vmin is None and q.vmax is None)
            cvals = np.ravel(cvals) * cf
            cnorm = _norm(q, cf)
            cmap = q.cmap or a.image.cmap
            clabel = axis_label(spec.get("z_label") or clab, cunit, ys.label.unit_format)

    kw = dict(s=sc.size_pt ** 2, alpha=sc.alpha, marker=sc.marker, edgecolors=sc.edgecolor,
              linewidths=sc.edgewidth_pt)
    mappable = None
    for xpts, ypts, lab in series:
        raster = xpts.size > SCATTER_RASTER_ABOVE
        if groups is not None:
            for k, (mask, glab) in enumerate(groups):
                ax.scatter(xpts[mask] * xf, ypts[mask] * yf, color=a.colors[k], rasterized=raster,
                           label=glab if len(series) == 1 else f"{lab}, {glab}", **kw)
        elif cvals is not None:
            mappable = ax.scatter(xpts * xf, ypts * yf, c=cvals, cmap=cmap, norm=cnorm, label=lab,
                                  rasterized=raster, **kw)
        else:
            ax.scatter(xpts * xf, ypts * yf, label=lab, rasterized=raster, **kw)

    ax.set_xlabel(axis_label(spec.get("x_label") or xlab, xunit, xs.label.unit_format))
    ax.set_ylabel(axis_label(spec.get("y_label") or ylab, yunit, ys.label.unit_format))
    y_scale = "log" if yq.scale == "log" and mode != "iq" else spec["y_scale"]
    if spec["x_scale"] == "log":
        _check_log(all_x, "the horizontal axis")
    if y_scale == "log":
        _check_log(all_y, "the vertical axis")
    ax.set_xscale(spec["x_scale"])
    ax.set_yscale(y_scale)
    if mode != "iq" and (yq.vmin is not None or yq.vmax is not None):
        ax.set_ylim(None if yq.vmin is None else yq.vmin * yf, None if yq.vmax is None else yq.vmax * yf)
    if mode == "iq":
        ax.set_aspect("equal", adjustable="datalim")
    _annotate(ax, d, spec, auto_axes)
    if mappable is not None:
        _colorbar(fig, mappable, ax, style, clabel)
    else:
        _legend(ax, a)


# ---- output ---------------------------------------------------------------------


def check_format(fmt: Any) -> str:
    if isinstance(fmt, str) and fmt.lower() == "jpeg":
        fmt = "jpg"
    if not isinstance(fmt, str) or fmt.lower() not in FORMATS:
        raise RenderError(f"unknown format {fmt!r}; use one of {sorted(FORMATS)}")
    return fmt.lower()


def figure_bytes(fig: Figure, style: Style, fmt: str, display: bool, metadata: Dict[str, Any]) -> bytes:
    """Save a figure built with build_figure. `display` lowers the raster dpi for on-screen SVG."""
    fmt = check_format(fmt)
    buf = io.BytesIO()
    dpi = DISPLAY_RASTER_DPI if display and fmt == "svg" else style.figure.dpi
    if fmt == "jpg":          # JPEG has no room for matplotlib's metadata; high quality keeps text readable
        fig.savefig(buf, format=fmt, dpi=dpi, pil_kwargs={"quality": 95})
    else:
        fig.savefig(buf, format=fmt, dpi=dpi, metadata=metadata)
    return buf.getvalue()


def _from_matplotlib(e: BaseException) -> bool:
    tb = e.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    return tb is not None and "matplotlib" in tb.tb_frame.f_code.co_filename.replace("\\", "/")


def render_dataset(d: "lbd.Dataset", spec: Optional[Dict[str, Any]], style: Style, fmt: str = "svg",
                   display: bool = False, creator: Optional[str] = None,
                   warn_unused: bool = True) -> Tuple[bytes, Dict[str, Any]]:
    """Render an in-memory (fully loaded) dataset. Returns (image bytes, resolved spec)."""
    fmt = check_format(fmt)
    resolved = resolve_spec(d, spec, warn_unused=warn_unused)
    meta = metadata(fmt, d, creator)
    with RENDER_LOCK, matplotlib.rc_context(style.to_rcparams()):
        try:
            fig, _ = build_figure(d, resolved, style)
            data = figure_bytes(fig, style, fmt, display, meta)
        except ValueError as e:
            if isinstance(e, RenderError) or not _from_matplotlib(e):
                raise
            # e.g. a label with invalid $math$, or data matplotlib can't draw
            raise RenderError(f"matplotlib couldn't draw this plot: {e}") from e
    return data, resolved


def render_file(path, spec: Optional[Dict[str, Any]], style: Style, fmt: str = "svg",
                display: bool = True, creator: Optional[str] = None,
                warn_unused: bool = True) -> Tuple[bytes, Dict[str, Any]]:
    """Render a file, reading only the values the plot needs."""
    fmt = check_format(fmt)
    header = lbd.info(path)
    import warnings as _w

    with _w.catch_warnings():  # the same checks run again below on the loaded data
        _w.simplefilter("ignore", RenderWarning)
        resolved = resolve_spec(header, spec, warn_unused=warn_unused)
    d = lbd.load(path, values=needed_values(header, resolved))
    return render_dataset(d, spec, style, fmt, display, creator, warn_unused=warn_unused)


def needed_values(d: "lbd.Dataset", resolved: Dict[str, Any]) -> List[str]:
    names = list(resolved["values"])
    for key in ("x", "color"):
        n = resolved.get(key)
        if n and n in d.values and n not in names:
            names.append(n)
    return names


def metadata(fmt: str, d: "lbd.Dataset", creator: Optional[str] = None) -> Dict[str, Any]:
    creator = creator or f"LBD {lbd.__version__} (matplotlib {matplotlib.__version__})"
    title = d.title or (d.path.name if d.path else "")
    if fmt == "png":
        return {"Software": creator, "Title": title, "Source": d.path.name if d.path else ""}
    if fmt == "pdf":
        return {"Creator": creator, "Title": title}
    if fmt == "jpg":
        return {}
    return {"Creator": creator, "Title": title, "Date": None}


def safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "figure"
