"""What a plot shows, as a table of numbers, and that table as a CSV file (LBD Viewer's Explore
view writes its "Save as CSV" with this code).

    import lbd.plot as lp

    t = lp.table("sweep.lbd", "curve", "S21", complex="db", series="power")
    t.to_csv("sweep_S21_dB.csv")                       # one data point per row
    t.to_csv("sweep_matrix.csv", layout="matrix")      # rows = power, columns = frequency

The file reads back with `numpy.loadtxt(path, delimiter=",")`, and with its column names with
`numpy.genfromtxt(path, delimiter=",", names=True)`: the first line is `# name,name,…`, then
comment lines say where the numbers come from, then the numbers (full precision, `.` as decimal
point, `,` between columns).
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import lbd

from . import render as _r
from .units import PREFIXES

NUMBERS = ("shown", "stored", "both")
UNITS = ("stored", "shown")
LAYOUTS = ("rows", "matrix")
BLOCK_NUMBERS = 1 << 20          # numbers read and written at a time (memory stays small)
_WHOLE = re.compile(r"(?<![\w.])(-?\d+)\.0(?=,|$)", re.MULTILINE)   # 3.0 -> 3 (whole numbers)


@dataclass
class Column:
    """One column's name (as in the file's first line), label and unit."""

    name: str
    label: str = ""
    unit: str = ""

    def heading(self) -> str:
        text = self.label or self.name
        if text != self.name:
            text = f"{self.name}: {text}"
        return f"{text} ({self.unit})" if self.unit else text


class Rows:
    """Numbers as traces × points, read a block at a time: `block(j0, j1, i0, i1)` → a float
    array. Made from a 2-D array (or anything indexable by [rows, columns], like LBD Viewer's
    maps read by part), or from a list of 1-D traces; `scale` multiplies what is read."""

    def __init__(self, source: Any, scale: float = 1.0, part: Optional[str] = None):
        self.source, self.scale, self.part = source, float(scale), part
        if not isinstance(source, (list, tuple)) and len(np.shape(source) if not hasattr(source, "shape")
                                                          else source.shape) == 1:
            source = [source]                            # one trace
        if isinstance(source, (list, tuple)):
            self.source = list(source)
            self.shape = (len(source), len(source[0]) if len(source) else 0)
        else:
            self.shape = tuple(source.shape)

    def block(self, j0: int, j1: int, i0: int, i1: int) -> np.ndarray:
        s = self.source
        if isinstance(s, list):
            a = np.array([np.asarray(s[j][i0:i1]) for j in range(j0, j1)]).reshape(j1 - j0, max(i1 - i0, 0))
        else:
            a = np.asarray(s[j0:j1, i0:i1])
        if self.part == "re":
            a = a.real
        elif self.part == "im":
            a = a.imag
        return scaled(np.asarray(a, dtype=float), self.scale)


class ValueRows(Rows):
    """A value read straight from its file (only the block asked for): rows along axis `rows`
    (or one row), columns along `cols`, the other axes at `index`. `mode`: a complex mode applied
    (as plotted), or `part` "re" / "im" of the stored numbers; `scale` as for Rows."""

    def __init__(self, value: Any, cols: str, rows: Optional[str], index: Dict[str, int],
                 part: Optional[str] = None, mode: Optional[str] = None, scale: float = 1.0):
        self.value, self.cols, self.rows, self.index = value, cols, rows, dict(index)
        self.scale, self.part, self.mode, self.source = float(scale), part, mode, None
        n = dict(zip(value.axes, value.shape))
        self.shape = (n[rows] if rows else 1, n[cols])

    def block(self, j0: int, j1: int, i0: int, i1: int) -> np.ndarray:
        v = self.value
        unwrap = self.mode in ("phase_unwrap", "phase_deg_unwrap")   # along the whole trace
        c0, c1 = (0, self.shape[1]) if unwrap else (i0, i1)
        idx = tuple(slice(c0, c1) if a == self.cols else slice(j0, j1) if a == self.rows else self.index.get(a, 0)
                    for a in v.axes)
        a = np.asarray(v._read(idx))
        if self.rows is None:
            a = a[None, :]
        elif v.axes.index(self.cols) < v.axes.index(self.rows):
            a = a.T
        if self.mode is not None:
            import warnings

            with warnings.catch_warnings():              # said when the plot was made
                warnings.simplefilter("ignore", _r.RenderWarning)
                a = _r.apply_complex(a, "", "", self.mode, axis=1)[0]
        elif self.part == "re":
            a = a.real
        elif self.part == "im":
            a = a.imag
        if unwrap:
            a = a[:, i0 - c0:i1 - c0]
        return scaled(np.asarray(a, dtype=float), self.scale)


def scaled(a: np.ndarray, f: float) -> np.ndarray:
    """a × f, where a factor like 1e-9 divides by 1e9 (exact for numbers like 7005000000 → 7.005)."""
    if f == 1.0:
        return a
    if f < 1.0 and abs((inv := 1.0 / f) - round(inv)) < 1e-6 * inv:
        return a / round(inv)
    return a * f


@dataclass
class Table:
    """Numbers of a plot: values over traces × points. `x` is the points' coordinate (one array,
    or one per trace when x is a value), `t` the traces' (a series axis, a map's vertical axis)
    or None for one trace. Make one with `lbd.plot.table`; write it with `to_csv`."""

    x: Any
    x_col: Column
    values: List[Tuple[Column, Rows]]
    t: Optional[np.ndarray] = None
    t_col: Optional[Column] = None
    comments: List[str] = field(default_factory=list)
    kind: str = "curve"
    points: Optional[np.ndarray] = None          # the points kept (a zoomed range), None: all
    traces: Optional[np.ndarray] = None          # the traces kept, None: all

    # -- shape

    @property
    def ragged(self) -> bool:
        return isinstance(self.x, (list, tuple))

    def _traces(self) -> np.ndarray:
        n = self.values[0][1].shape[0] if self.values else 0
        return np.arange(n) if self.traces is None else np.asarray(self.traces, dtype=int)

    def _points(self, j: int) -> np.ndarray:
        """The points kept for trace j (indices)."""
        if self.points is not None:
            return np.asarray(self.points, dtype=int)
        return np.arange(len(self.x[j]) if self.ragged else len(self.x))

    def columns(self) -> List[Column]:
        return ([self.t_col] if self.t is not None else []) + [self.x_col] + [c for c, _ in self.values]

    def check_matrix(self) -> None:
        """Raise ValueError when the table can't be written as a matrix, saying why."""
        if self.t is None:
            raise ValueError("a table (matrix) needs two axes: these numbers have one; save them as rows")
        if len(self.values) != 1:
            raise ValueError(f"a table (matrix) holds one value, not {len(self.values)}; save them as rows, or "
                             "show one value")
        if self.ragged:
            raise ValueError("a table (matrix) needs one horizontal axis for every trace; here x is a value with "
                             "its own numbers per trace: save them as rows")

    # -- size

    def estimate(self, layout: str = "rows") -> Dict[str, int]:
        """About how big the file will be: {"bytes", "rows", "columns"} (rows without the comment
        lines). Worked out from a sample of the numbers, without reading them all."""
        _check(layout, LAYOUTS, "layout")
        traces = self._traces()
        if self.ragged:
            npoints = sum(len(self._points(int(j))) for j in traces)
        else:
            npoints = len(self._points(0)) * len(traces)
        if layout == "matrix":
            self.check_matrix()
            rows, cols = len(traces) + 1, (len(self._points(0)) if len(traces) else 0) + 1
        else:
            rows, cols = npoints, len(self.columns())
        sample = self._sample_text(layout)
        per_number = (len(sample) / max(sample.count(",") + sample.count("\n"), 1)) if sample else 8
        header = sum(len(c) + 3 for c in self.header_lines(layout))
        return {"bytes": int(header + rows * cols * per_number), "rows": int(rows), "columns": int(cols)}

    def _sample_text(self, layout: str) -> str:
        """Lines as written for a few points of a few traces."""
        traces = self._traces()
        if not len(traces):
            return ""
        picks = sorted(set(int(traces[k]) for k in np.linspace(0, len(traces) - 1, min(len(traces), 5)).astype(int)))
        out = []
        for j in picks:
            keep = self._points(j)[:400]
            if not keep.size:
                continue
            if layout == "matrix":
                out.append(_line(self._read(0, j, keep)[0]))
            else:
                out.append(self._rows_text(j, keep, drop_missing=False))
        return "\n".join(out)

    # -- reading

    def _read(self, k: int, j: int, keep: np.ndarray) -> np.ndarray:
        """Value k at trace j, points `keep` (sorted indices): read as one block, then taken."""
        if not keep.size:
            return np.empty((1, 0))
        rows = self.values[k][1]
        i0, i1 = int(keep[0]), int(keep[-1]) + 1
        return rows.block(j, j + 1, i0, i1)[:, keep - i0]

    def _rows_text(self, j: int, keep: np.ndarray, drop_missing: bool = True) -> str:
        x = np.asarray(self.x[j] if self.ragged else self.x, dtype=float)[keep]
        cols = ([np.full(keep.size, float(self.t[j]))] if self.t is not None else []) + [x]
        vals = [self._read(k, j, keep)[0] for k in range(len(self.values))]
        block = np.column_stack(cols + vals)
        if drop_missing and vals:
            block = block[~np.all(np.isnan(np.column_stack(vals)), axis=1)]
        return _lines(block)

    # -- the file

    def header_lines(self, layout: str = "rows") -> List[str]:
        """The comment lines (without '# '): the column names first, then where the numbers come from."""
        cols = self.columns()
        if layout == "matrix":
            (vc, _), t = self.values[0], self.t_col
            first = [f"table: rows = {t.heading()}, columns = {self.x_col.heading()}, cells = {vc.heading()}",
                     "the first row holds the columns' coordinates, the first column the rows'; the corner is nan"]
        else:
            first = [",".join(c.name for c in cols)]
        return first + self.comments + ["columns: " + "; ".join(c.heading() for c in cols)]

    def to_csv(self, path: Any, layout: str = "rows", rows_are: str = "t",
               progress: Optional[Callable[[float], None]] = None) -> Path:
        """Write the table as a CSV file. `layout`: "rows" (one data point per row: the
        coordinates, then each value) or "matrix" (2-D only: the first row holds x, the first
        column t; `rows_are="x"` turns it the other way). The file is written next to `path` as
        `<name>.part` and renamed when complete; an existing file is replaced. `progress`
        (fraction done) may raise to stop: the part written is removed."""
        _check(layout, LAYOUTS, "layout")
        _check(rows_are, ("t", "x"), "rows_are")
        if layout == "matrix":
            self.check_matrix()
        path = Path(path)
        part = path.with_name(path.name + ".part")
        try:
            with open(part, "w", encoding="utf-8", newline="\n") as f:
                for line in self.header_lines(layout):
                    f.write("# " + line.replace("\n", " ") + "\n")
                if layout == "matrix":
                    self._write_matrix(f, rows_are, progress)
                else:
                    self._write_rows(f, progress)
            os.replace(part, path)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
        return path

    def _write_rows(self, f, progress) -> None:
        traces = self._traces()
        for n, j in enumerate(traces):
            keep = self._points(int(j))
            step = max(1, BLOCK_NUMBERS // max(len(self.values), 1))
            for a in range(0, keep.size, step):
                text = self._rows_text(int(j), keep[a:a + step])
                if text:
                    f.write(text + "\n")
                if progress is not None:
                    progress((n + (a + step) / max(keep.size, 1)) / len(traces))
            if progress is not None:
                progress((n + 1) / len(traces))

    def _write_matrix(self, f, rows_are: str, progress) -> None:
        traces, keep = self._traces(), self._points(0)
        x = np.asarray(self.x, dtype=float)[keep]
        t = np.asarray(self.t, dtype=float)[traces]
        rows = self.values[0][1]
        if rows_are == "t":
            f.write(_line(np.r_[np.nan, x]) + "\n")
            for n, j in enumerate(traces):
                f.write(_line(np.r_[t[n], self._read(0, int(j), keep)[0]]) + "\n")
                if progress is not None:
                    progress((n + 1) / len(traces))
            return
        f.write(_line(np.r_[np.nan, t]) + "\n")
        step = max(1, BLOCK_NUMBERS // max(len(traces), 1))   # columns read at a time, all traces
        j0, j1 = (int(traces.min()), int(traces.max()) + 1) if traces.size else (0, 0)
        for a in range(0, keep.size, step):
            part = keep[a:a + step]
            block = rows.block(j0, j1, int(part[0]), int(part[-1]) + 1)[traces - j0][:, part - part[0]]
            f.write(_lines(np.column_stack([x[a:a + step], block.T])) + "\n")
            if progress is not None:
                progress(min(1.0, (a + step) / keep.size))


# ---- numbers as text ---------------------------------------------------------------


def _line(a: np.ndarray) -> str:
    return _WHOLE.sub(r"\1", ",".join(map(repr, np.asarray(a, dtype=float).tolist())))


def _lines(block: np.ndarray) -> str:
    """Rows of numbers: full precision (the shortest text that reads back the same), whole
    numbers without '.0', nan for a missing number."""
    text = "\n".join(",".join(map(repr, row)) for row in np.asarray(block, dtype=float).tolist())
    return _WHOLE.sub(r"\1", text)


def _check(v: Any, choices: Sequence[str], what: str) -> None:
    if v not in choices:
        raise ValueError(f"{what} must be one of {list(choices)}, not {v!r}")


def prefixed(unit: str, factor: float) -> str:
    """The unit with the SI prefix that `factor` (shown per stored) stands for: 1e-9, 'Hz' → 'GHz'."""
    if not unit or factor == 1.0:
        return unit
    exp = -round(float(np.log10(factor)))
    for p, e in PREFIXES.items():
        if e == exp and len(p) == 1:
            return p + unit
    return unit


# ---- from a plot -------------------------------------------------------------------


def table(data, kind: Optional[str] = None, values: Any = None, *, numbers: str = "shown",
          xlim: Optional[Tuple[float, float]] = None, ylim: Optional[Tuple[float, float]] = None,
          units: str = "stored", style: Any = None, file_style: bool = True, **spec: Any) -> Table:
    """The numbers a curve plot or heat map shows, as a table (write it with `Table.to_csv`).

    **Use it when** you want the numbers of the viewer's plot (complex mode applied, the series
    and slices chosen) in a file for another program, or as plain arrays. The arguments are those
    of [`plot`][lbd.plot.plot]; the numbers are what it draws.

    Parameters
    ----------
    data : lbd.Dataset or path
        As for `plot`.
    kind : {"curve", "heatmap"}, optional
        As for `plot` (scatter plots aren't tables).
    values : str or list of str, optional
        As for `plot`.
    numbers : {"shown", "stored", "both"}
        "shown": as plotted (complex mode applied); "stored": the file's own numbers (a complex
        value as two columns `name_re`, `name_im`); "both": each shown column followed by the
        stored ones (`name_stored`, or `name_re`, `name_im`).
    xlim, ylim : (low, high), optional
        Keep only the points with x (and, for a heat map, the rows with y) in this range, in
        stored units (Hz, not GHz).
    units : {"stored", "shown"}
        "stored": numbers in the file's units (Hz); "shown": with the plot's unit prefixes (GHz).
    style, file_style, **spec
        As for `plot` (the style matters only for the prefixes of `units="shown"`).

    Returns
    -------
    Table
        `to_csv(path, layout="rows" | "matrix")` writes it; `estimate()` says how big that is.

    Examples
    --------
    >>> t = lp.table("sweep.lbd", "curve", "S21", complex="db", series="power")
    >>> t.to_csv("sweep.csv")
    """
    from . import api

    unknown = set(spec) - api.SPEC_KEYS
    if unknown:
        raise TypeError(f"unknown plot setting(s) {sorted(unknown)}; allowed: {sorted(api.SPEC_KEYS)}")
    full: Dict[str, Any] = dict(spec)
    if kind:
        full["kind"] = kind
    if values is not None:
        full["values"] = [values] if isinstance(values, str) else list(values)
    if isinstance(data, (str, os.PathLike)):
        import warnings

        header = lbd.info(data)
        with warnings.catch_warnings():                  # checked again below, on the loaded data
            warnings.simplefilter("ignore", _r.RenderWarning)
            resolved = _r.resolve_spec(header, full)
        d = lbd.load(data, values=_r.needed_values(header, resolved))
    elif isinstance(data, lbd.Dataset):
        d = data
    else:
        raise TypeError(f"data must be an lbd.Dataset or a path to an .lbd file, not {type(data).__name__}")
    d = _r.flat(d)
    resolved = _r.resolve_spec(d, full)
    if resolved["kind"] not in ("curve", "heatmap"):
        raise _r.RenderError(f"a table is made of curves or a heat map, not a {resolved['kind']} plot")
    s = api._style_for(d, style, file_style)
    prepare = _r.prepare_curves if resolved["kind"] == "curve" else _r.prepare_map
    import matplotlib

    with matplotlib.rc_context(s.to_rcparams()):
        model = prepare(d, resolved, s)
    return from_model(d, resolved, model, numbers=numbers, xlim=xlim, ylim=ylim, units=units)


def from_model(d, spec: Dict[str, Any], model: Any, *, numbers: str = "shown",
               xlim: Optional[Tuple[float, float]] = None, ylim: Optional[Tuple[float, float]] = None,
               units: str = "stored", traces: Optional[Sequence[int]] = None) -> Table:
    """The table of a prepared plot (render.prepare_curves / prepare_map; LBD Viewer passes its
    own): the numbers are read from the data (complex mode applied), the model gives the units'
    prefixes for `units="shown"`. `traces`: only these traces (series positions, a map's rows)."""
    _check(numbers, NUMBERS, "numbers")
    _check(units, UNITS, "units")
    shown = units == "shown"
    mode = spec["complex"]

    def columns(name: str, cols: str, rows: Optional[str], f: float) -> List[Tuple[Column, Rows]]:
        v = d.values[name]
        _, label, unit = _r.apply_complex(np.ones(1, dtype=v.dtype), v.label, v.unit, mode)
        return _value_columns(name, label, prefixed(unit, f), ValueRows(v, cols, rows, spec["index"], mode=mode, scale=f),
                              v, numbers, lambda part: ValueRows(v, cols, rows, spec["index"], part))

    if isinstance(model, _r.MapModel):
        xa, ya = d.axes[spec["x"]], d.axes[spec["y"]]
        x_raw, t_raw = np.asarray(xa.data, dtype=float), np.asarray(ya.data, dtype=float)
        fx, ft, fz = (model.xf, model.yf, model.zf) if shown else (1.0, 1.0, 1.0)
        out = Table(x=scaled(x_raw, fx), x_col=Column(spec["x"], xa.label, prefixed(xa.unit, fx)),
                    values=columns(spec["values"][0], spec["x"], spec["y"], fz),
                    t=scaled(t_raw, ft), t_col=Column(spec["y"], ya.label, prefixed(ya.unit, ft)), kind="heatmap")
        out.points = _inside(x_raw, xlim)
        out.traces = _inside(t_raw, ylim)
        if traces is not None:
            out.traces = np.intersect1d(np.arange(t_raw.size) if out.traces is None else out.traces,
                                        np.asarray(list(traces), dtype=int))
    else:
        series, along = spec.get("series"), spec.get("along", spec["x"])
        x_is_value = spec["x"] in d.values
        xa = d.values[spec["x"]] if x_is_value else d.axes[spec["x"]]
        fx, fy = (model.xf, model.yf) if shown else (1.0, 1.0)
        if getattr(model, "units_apart", None):         # two units (LBD Viewer): each value in its own
            fy = 1.0
        if x_is_value:                                   # its own x for each trace
            xv = np.asarray(_r._take(xa, [along] + ([series] if series else []), spec["index"]), dtype=float)
            x: Any = [scaled(c, fx) for c in (xv.T if series else xv[None, :])]
        else:
            x_raw = np.asarray(xa.data, dtype=float)
            x = scaled(x_raw, fx)
        cols = [c for name in spec["values"] for c in columns(name, along, series, fy)]
        t = t_col = None
        if series:
            sa = d.axes[series]
            t, t_col = np.asarray(sa.data, dtype=float), Column(series, sa.label, sa.unit)
        out = Table(x=x, x_col=Column(spec["x"], xa.label, prefixed(xa.unit, fx)), values=cols, t=t, t_col=t_col,
                    kind="curve")
        if not x_is_value:
            out.points = _inside(x_raw, xlim)
        elif xlim is not None:
            raise ValueError("a range of x can't be kept when x is a value (each trace has its own x); "
                             "save all points")
        if traces is not None:
            out.traces = np.asarray(sorted(set(int(k) for k in traces)), dtype=int)
    out.comments = _comments(d, spec, numbers, shown)
    return out


def _value_columns(name: str, label: str, unit: str, shown_rows: Rows, v, numbers: str,
                   stored: Callable[[Optional[str]], Rows]) -> List[Tuple[Column, Rows]]:
    out: List[Tuple[Column, Rows]] = []
    if numbers in ("shown", "both"):
        out.append((Column(name, label, unit), shown_rows))
    if numbers in ("stored", "both"):
        out += stored_columns(name, v, numbers == "both", stored)
    return out


def stored_columns(name: str, v, beside: bool, stored: Callable[[Optional[str]], Rows]) -> List[Tuple[Column, Rows]]:
    """The stored numbers of value `v`: complex as `name_re`, `name_im`; else `name` (or
    `name_stored` when `beside` the shown column of the same name)."""
    if np.issubdtype(v.dtype, np.complexfloating):
        return [(Column(f"{name}_re", f"Re {v.label}", v.unit), stored("re")),
                (Column(f"{name}_im", f"Im {v.label}", v.unit), stored("im"))]
    return [(Column(f"{name}_stored" if beside else name, f"{v.label} (stored)", v.unit), stored(None))]


def _inside(coords: np.ndarray, lim: Optional[Tuple[float, float]]) -> Optional[np.ndarray]:
    if lim is None:
        return None
    lo, hi = sorted(float(v) for v in lim)
    with np.errstate(invalid="ignore"):
        return np.flatnonzero((coords >= lo) & (coords <= hi))


def _comments(d, spec: Dict[str, Any], numbers: str, shown_units: bool) -> List[str]:
    path = getattr(d, "path", None)
    name = Path(path).name if path else (d.title or "dataset in memory")
    out = [f"LBD export: {name}, {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}, LBD {lbd.__version__}"]
    if path and str(path).lower().endswith(".writing"):
        out.append("still being measured: these are the points written so far")
    cx = [n for n in spec["values"] if np.issubdtype(d.values[n].dtype, np.complexfloating)]
    if cx and numbers != "stored":
        out.append(f"complex mode: {spec['complex']} (for {', '.join(cx)})")
    out.append({"shown": "numbers as shown", "stored": "the stored numbers",
                "both": "numbers as shown, each followed by the stored ones"}[numbers]
               + ("; units as on screen" if shown_units else "; stored units"))
    fixed = [f"{s['label'] or s['axis']} = {s.get('text') or _r._fmt(s['value'])}{(' ' + s['unit']) if s['unit'] and not s.get('text') else ''}"
             for s in spec.get("slices", [])]
    if fixed:
        out.append("fixed: " + ", ".join(fixed))
    return out
