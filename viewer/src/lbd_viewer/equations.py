"""Equations in the Explore view: `x = …`, `y = …` (maps also `z = …`), applied after the
operations (operations.py), like Labber's equation fields.

An equation is written with numbers, + − * / **, parentheses, names and a fixed list of
functions; LBD parses it itself (Python's `ast`, checked node by node) and never runs it as code.

Names, all in **stored units** (Hz, not GHz; the legend says which):
- `x`, `y` — curves: the horizontal axis and the value as shown (after the complex mode and the
  operations); maps: `x`, `y` the axes and `z` the value;
- every value of the file with the plot's axes, as stored (complex stays complex: `abs(S21)`);
- every axis of the plot, as its coordinates (an axis held fixed by a slider: its one value).
Names that aren't plain words are written in backticks: `` `S21 (ref)` ``.

The result of an equation has no unit (its label is the equation). `x =` and `y =` both use the
data from before the equations. A field whose equation can't be used shows why at the field and
is left out; empty points it makes (sqrt of a negative, log of 0, 0/0) are drawn as gaps and
counted in a note.
"""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

import lbd

from .operations import Grid, Quantity

MAX_LENGTH = 500


class EquationError(ValueError):
    """An equation that can't be used; the message says why (shown at its field)."""


def _reduce(fn) -> Callable[[np.ndarray], np.ndarray]:
    def per_trace(a):
        a = np.asarray(a)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # an empty trace: empty
            return fn(a, axis=-1, keepdims=True) if a.ndim else a
    return per_trace


FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arcsin": np.arcsin, "arccos": np.arccos,
    "arctan": np.arctan, "arctan2": np.arctan2, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "exp": np.exp, "log": np.log, "log10": np.log10, "log2": np.log2, "sqrt": np.sqrt, "abs": np.abs,
    "real": np.real, "imag": np.imag, "angle": np.angle, "conj": np.conj, "floor": np.floor,
    "ceil": np.ceil, "round": np.round, "clip": np.clip,
    # per trace (along the points), e.g. y - mean(y)
    "mean": _reduce(np.nanmean), "median": _reduce(np.nanmedian), "std": _reduce(np.nanstd),
    "min": _reduce(np.nanmin), "max": _reduce(np.nanmax),
}
CONSTANTS = {"pi": np.pi, "e": np.e}
_OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.true_divide, ast.Pow: np.power}
ALLOWED = "only numbers, + − * / **, parentheses, names and the listed functions can be used"


# -- parsing -----------------------------------------------------------------------------------------

def parse(text: str) -> Tuple[ast.Expression, Dict[str, str]]:
    """The checked syntax tree of an equation, and the backtick names it uses (safe name → name)."""
    if len(text) > MAX_LENGTH:
        raise EquationError(f"an equation is at most {MAX_LENGTH} characters")
    quoted: Dict[str, str] = {}

    def unquote(m):
        safe = f"_q{len(quoted)}_"
        quoted[safe] = m.group(1)
        return safe
    plain = re.sub(r"`([^`]+)`", unquote, text.replace("−", "-").replace("×", "*"))
    if "`" in plain:
        raise EquationError("a name in backticks needs a closing backtick")
    try:
        tree = ast.parse(plain.strip(), mode="eval")
    except SyntaxError as e:
        at = f" at character {e.offset}" if e.offset else ""
        raise EquationError(f"this isn't a formula LBD can read{at}: {e.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load)) or type(node) in _OPS:
            continue
        if isinstance(node, (ast.UAdd, ast.USub)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                name = node.func.id if isinstance(node.func, ast.Name) else "this"
                raise EquationError(f"'{name}' isn't one of the functions: {', '.join(FUNCTIONS)}")
            if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
                raise EquationError(f"{node.func.id}(…) takes plain values, no names= or *")
            continue
        raise EquationError(ALLOWED)
    return tree, quoted


def _eval(node, names: Dict[str, Any]):
    if isinstance(node, ast.Expression):
        return _eval(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if node.id in FUNCTIONS:
            raise EquationError(f"'{node.id}' is a function: write {node.id}(…)")
        known = ", ".join(n for n in names if not n.startswith("_q"))
        raise EquationError(f"'{node.id}' isn't a value or axis of this plot; there are: {known}")
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, names)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.Call):
        fn = FUNCTIONS[node.func.id]
        try:
            return fn(*[_eval(a, names) for a in node.args])
        except TypeError:
            raise EquationError(f"{node.func.id}(…) was given {len(node.args)} value(s); check how many it takes") from None
    raise EquationError(ALLOWED)


def evaluate(text: str, names: Dict[str, Any], shape: Tuple[int, ...]) -> np.ndarray:
    """An equation's numbers, shaped like the plot (traces × points); real; errors as EquationError."""
    tree, quoted = parse(text)
    scope = dict(names)
    for safe, name in quoted.items():
        if name not in names:
            known = ", ".join(n for n in names if not n.startswith("_q"))
            raise EquationError(f"'{name}' isn't a value or axis of this plot; there are: {known}")
        scope[safe] = names[name]
    with np.errstate(all="ignore"):
        try:
            out = np.asarray(_eval(tree, scope))
        except EquationError:
            raise
        except ValueError as e:                       # shapes that don't fit together
            raise EquationError(f"the parts of this equation don't fit together ({e})") from None
    if np.iscomplexobj(out):
        if np.any(np.imag(out[np.isfinite(out)]) != 0):
            raise EquationError("the result is complex: take abs(), real(), imag() or angle() of it")
        out = np.real(out)
    if out.dtype.kind not in "fiub":
        raise EquationError("the result isn't numbers")
    try:
        return np.broadcast_to(out.astype(float), shape).copy()
    except ValueError:
        raise EquationError(f"the result has {out.shape} numbers, the plot {shape}") from None


# -- the names an equation can use ------------------------------------------------------------------

def names_of(s, g: Grid, arrays: bool = True) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """The arrays behind each name (broadcastable to traces × points) and the legend that says
    what each is: [{name, means}]. `g` is the grid before the equations. `arrays=False`: the
    legend only (the file's values aren't copied)."""
    from lbd.plot.render import _take

    from .reading import _plotted

    spec, d = s.spec, s.data
    shape = g.a.shape
    rows = shape[0]
    names: Dict[str, Any] = {}
    legend: List[Dict[str, str]] = []

    def say(q: Quantity, extra: str = "") -> str:
        return f"{q.label}" + (f", in {q.unit}" if q.unit else "") + extra

    x = np.array(g.x, dtype=float) if g.ragged else np.asarray(g.x, dtype=float)[None, :]
    if g.kind == "heatmap":
        names.update(x=x, y=np.asarray(g.t, dtype=float)[:, None], z=g.a)
        legend += [{"name": "x", "means": say(g.xq)}, {"name": "y", "means": say(g.tq)},
                   {"name": "z", "means": say(g.value, ", the map's value")}]
    else:
        names.update(x=x, y=g.a)
        legend += [{"name": "x", "means": say(g.xq)}, {"name": "y", "means": say(g.value)}]

    # the file's data, where it still lines up with what is shown (the operations kept the points)
    lined_up = g.one_to_one and g.kind == s.base_kind
    if s.base_kind == "heatmap":
        keep = [spec["y"], spec["x"]]
    else:
        keep = [spec.get("along", spec["x"])] + ([spec["series"]] if spec.get("series") else [])
    plotted_axes = d.values[spec["values"][0]].axes
    usable = [n for n, v in s.header.values.items()
              if n not in names and v.axes and sorted(v.axes) == sorted(plotted_axes)]
    if arrays and lined_up:                           # the viewer reads only what plots need: read these too
        missing = [n for n in usable if d.values[n].data is None]
        if missing:
            loaded = [n for n, v in d.values.items() if v.data is not None]
            s.data = d = lbd.load(s.path, values=sorted(set(loaded) | set(missing)))
    for vname in usable:
        v = d.values[vname] if d.values[vname].data is not None else s.header.values[vname]
        if not lined_up:
            continue
        if arrays:
            arr = np.asarray(_take(v, keep, spec["index"]))
            arr = arr if s.base_kind == "heatmap" else (arr.T if arr.ndim == 2 else arr[None, :])
            if arr.shape != shape:
                continue
        else:
            arr = np.empty(0, dtype=complex if "complex" in str(v.dtype) else float)
        names[vname] = arr
        kind = "complex" if np.iscomplexobj(arr) else "as stored"
        legend.append({"name": vname, "means": f"{v.label or vname}" + (f", in {v.unit}" if v.unit else "") + f", {kind}"})
    for aname in plotted_axes:
        if aname in names:
            continue
        a = d.axes[aname]
        coords = np.asarray(a.data, dtype=float)
        if aname in (spec.get("index") or {}):
            names[aname] = coords[spec["index"][aname]]
            legend.append({"name": aname, "means": say(Quantity(a.label or aname, a.unit), f", {names[aname]:g}: held by a slider")})
        elif not lined_up:
            continue
        elif aname == (spec["y"] if s.base_kind == "heatmap" else spec.get("series")):   # the traces' axis
            names[aname] = coords[:, None]
            per = "one per row" if s.base_kind == "heatmap" else "one per trace"
            legend.append({"name": aname, "means": say(Quantity(a.label or aname, a.unit), f", an axis: {per}")})
        else:
            names[aname] = coords[None, :]
            legend.append({"name": aname, "means": say(Quantity(a.label or aname, a.unit), ", an axis")})
    for nm in list(names):
        if not nm.isidentifier():                       # usable in backticks only
            for item in legend:
                if item["name"] == nm:
                    item["name"] = f"`{nm}`"
    return names, legend


# -- applying them -----------------------------------------------------------------------------------

def apply(s, g: Grid, eqs: Dict[str, str]) -> Tuple[Grid, Dict[str, Dict[str, str]], List[Dict[str, str]]]:
    """The grid after the equations (fields that can't be used are left out), the state of each
    field ({"error": …} or {"note": …}), and the legend of names."""
    names, legend = names_of(s, g)
    state: Dict[str, Dict[str, str]] = {}
    out = g
    shape = g.a.shape
    fields = ("x", "y", "z") if g.kind == "heatmap" else ("x", "y")
    for field in fields:
        text = (eqs.get(field) or "").strip()
        if not text:
            continue
        try:
            values = evaluate(text, names, shape)
        except EquationError as e:
            state[field] = {"error": str(e)}
            continue
        target = g.a if field in ("y", "z") and not (field == "y" and g.kind == "heatmap") else None
        lost = int((~np.isfinite(values) & (np.isfinite(target) if target is not None else True)).sum())
        if field in ("y", "z") and not (field == "y" and g.kind == "heatmap"):
            out = replace(out, a=values, value=Quantity(text, ""))
        elif field == "x":
            if g.kind == "heatmap":
                col = values[0]
                if not np.all(values == col[None, :]) or not _monotonic(col):
                    state[field] = {"error": "a map's x must stay one sorted row of numbers (increasing or decreasing)"}
                    continue
                out = replace(out, x=col, xq=Quantity(text, ""))
            elif np.all(values == values[0][None, :]):
                out = replace(out, x=values[0], xq=Quantity(text, ""), ragged=False)
            else:
                out = replace(out, x=list(values), xq=Quantity(text, ""), ragged=True)
        else:                                            # a map's y
            col = values[:, 0]
            if not np.all(values == col[:, None]) or not _monotonic(col):
                state[field] = {"error": "a map's y must stay one sorted column of numbers (increasing or decreasing)"}
                continue
            out = replace(out, t=col, tq=Quantity(text, ""))
        state[field] = {"note": f"{lost} point{'s' * (lost != 1)} have no value (e.g. a square root of a negative "
                                "number, log of 0, 0/0): they are gaps"} if lost else {}
    return out, state, legend


def _monotonic(v: np.ndarray) -> bool:
    d = np.diff(v)
    return bool(np.all(np.isfinite(v)) and (np.all(d > 0) or np.all(d < 0)))
