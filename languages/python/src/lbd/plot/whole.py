"""A whole file as CSV: every point of one group of values.

A file can hold values on different axes, e.g. axes A, B, C with u(A), v(A, B) and t(C). A table
holds one **group**: the values lying on the same axes. Mixing them would give a table of mostly
empty cells, so each group is a table of its own: a column per axis, then per value, a row per
data point, for any number of axes. Unlike `tables.Table` (what a plot shows) it needs no plot:

>>> for g in lp.groups("sweep.lbd"):
...     print(g.label, g.rows)
>>> lp.table("sweep.lbd", group="S21").to_csv("sweep_S21.csv")

Complex values are two columns (`S21_re`, `S21_im`); a data point with several numbers (a vector,
a matrix) a column each; a level of an axis group (a variable sweep) gives each point its
coordinates. Single numbers and the file's metadata go into the comments. The numbers are the
stored ones, read and written block by block, so a file bigger than memory can be saved.
"""

from __future__ import annotations

import datetime as _dt
import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

import lbd
from lbd import groups as _groups

from . import tables as _t

SAMPLE_ROWS = 400                # rows looked at to estimate the size of a number


@dataclass
class Group:
    """Values lying on the same axes: what one CSV of a whole file holds."""

    key: str                     # the first value's name: `table(d, group=key)`
    values: List[str]
    axes: List[str]
    rows: int                    # data points
    columns: int

    @property
    def label(self) -> str:
        """For example "S21, S11 (power, freq)"."""
        return f"{', '.join(self.values)} ({', '.join(self.axes)})"


def _number_columns(v) -> List[Tuple[_t.Column, Tuple[Tuple[int, ...], Optional[str]]]]:
    """The columns of a value: each with where it is in a data point and "re" / "im" / None."""
    shape = tuple(v.point_shape)
    out = []
    for at in np.ndindex(*shape) if shape else [()]:
        names = [(v.elements[k][i] if k < len(v.elements) and v.elements[k] else str(i)) for k, i in enumerate(at)]
        name = "_".join([v.name] + [n.replace(" ", "_") for n in names])
        label = (v.label or v.name) + (f" [{', '.join(names)}]" if names else "")
        if np.issubdtype(np.dtype(v.dtype), np.complexfloating):
            out.append((_t.Column(f"{name}_re", f"Re {label}", v.unit), (at, "re")))
            out.append((_t.Column(f"{name}_im", f"Im {label}", v.unit), (at, "im")))
        else:
            out.append((_t.Column(name, label, v.unit), (at, None)))
    return out


def _grouped(d) -> List[List[str]]:
    """The names of the values with a sweep, by the axes they lie on, in the file's order."""
    found: Dict[str, List[str]] = {}
    for name, v in d.values.items():
        if v.dims:
            found.setdefault(json.dumps([list(dim) for dim in v.dims]), []).append(name)
    return list(found.values())


def groups(data: Any) -> List[Group]:
    """The groups of values of a file, each what one CSV holds (see the module's text).

    Parameters
    ----------
    data : lbd.Dataset or path
        A dataset, or a file (only its structure is read).

    Returns
    -------
    list of Group
        Each with `key` (for `table(data, group=key)`), `values`, `axes`, `rows`, `columns`, `label`.
    """
    d = lbd.info(data) if isinstance(data, (str, os.PathLike)) else data
    out = []
    for names in _grouped(d):
        v = d.values[names[0]]
        lengths = [_groups.dim_length(d, dim) for dim in v.dims]
        cols = sum(len(_number_columns(d.values[n])) for n in names)
        out.append(Group(names[0], names, list(v.axes), int(np.prod(lengths)), len(v.axes) + cols))
    return out


class FileTable:
    """One group of a file's values, as a table: a column per axis, then per number of a data
    point, a row per data point. `to_csv` and `estimate` as `tables.Table`."""

    def __init__(self, d: Any, key: str, close: bool = False):
        found = [names for names in _grouped(d) if key in names]
        if not found:
            known = ", ".join(g.key for g in groups(d)) or "none"
            raise ValueError(f"no group of values with '{key}' in this file (groups: {known}); "
                             "a single number has no table: it is in the comments")
        self.d, self.names, self._close = d, found[0], close
        self.first = d.values[self.names[0]]
        self.dims = list(self.first.dims)
        self.lengths = [_groups.dim_length(d, dim) for dim in self.dims]
        coords = _groups.coords(d, self.first)
        self.axes = [(a, np.asarray(coords[a], dtype=float), k) for k, dim in enumerate(self.dims) for a in dim]
        self.axis_columns = [_t.Column(a, d.axes[a].label, d.axes[a].unit) for a, _, _ in self.axes]
        self.value_columns = [(d.values[n], col, where) for n in self.names for col, where in _number_columns(d.values[n])]
        self.comments = self._comments()

    # -- what it holds

    def columns(self) -> List[_t.Column]:
        return self.axis_columns + [c for _, c, _ in self.value_columns]

    def _comments(self) -> List[str]:
        d = self.d
        path = getattr(d, "path", None)
        name = Path(path).name if path else (d.title or "dataset in memory")
        out = [f"LBD export: {name}, {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}, LBD {lbd.__version__}"]
        out += _t.identity(d)
        if path and str(path).lower().endswith(".writing"):
            out.append("still being measured: these are the points written so far")
        out.append(f"the whole file, as stored: {', '.join(self.names)} over {', '.join(self.first.axes)}; stored units")
        others = [n for g in _grouped(d) for n in g if n not in self.names]
        if others:
            out.append("in other tables (other axes): " + ", ".join(others))
        for a, _, _ in self.axes:
            if d.axes[a].elements:
                out.append(f"{a}: " + ", ".join(f"{i} = {e}" for i, e in enumerate(d.axes[a].elements)))
        for n, v in d.values.items():
            if not v.dims and not v.point_shape:
                out.append(f"{n} = {np.asarray(v._read(())).item()}" + (f" {v.unit}" if v.unit else ""))
        if d.meta:
            out.append("meta: " + json.dumps(d.meta, ensure_ascii=False, default=str)[:20000])
        return out

    def header_lines(self, layout: str = "rows") -> List[str]:
        if layout == "matrix":
            return self._grid().header_lines("matrix")
        cols = self.columns()
        return [",".join(c.name for c in cols)] + self.comments + ["columns: " + "; ".join(c.heading() for c in cols)]

    # -- reading, block by block

    def _blocks(self, rows: int) -> Iterator[Tuple[Tuple, int, int, int]]:
        """(the positions of the outer dimensions, dimension `s`, from, to): the dimensions after
        `s` are whole, about `rows` rows at a time."""
        n, size, s = self.lengths, 1, len(self.lengths) - 1
        while s > 0 and size * n[s] <= rows:
            size *= n[s]
            s -= 1
        step = max(1, rows // size)
        for outer in itertools.product(*[range(k) for k in n[:s]]):
            for a in range(0, n[s], step):
                yield outer, s, a, min(a + step, n[s])

    def _block(self, outer: Tuple, s: int, a: int, b: int) -> np.ndarray:
        """Rows of numbers: the coordinates, then the values."""
        ranges = [np.array([i]) for i in outer] + [np.arange(a, b)] + [np.arange(k) for k in self.lengths[s + 1:]]
        grid = np.meshgrid(*ranges, indexing="ij")
        cols = [c[grid[k].ravel()] for _, c, k in self.axes]
        read: Dict[str, np.ndarray] = {}
        sel = tuple(outer) + (slice(a, b),) + (slice(None),) * (len(self.lengths) - s - 1)
        points = int(np.prod([len(r) for r in ranges]))
        for v, _, (at, part) in self.value_columns:
            if v.name not in read:
                read[v.name] = np.asarray(v._read(sel)).reshape((points,) + tuple(v.point_shape))
            x = read[v.name][(slice(None),) + at]
            cols.append(x.real if part == "re" else x.imag if part == "im" else x)
        return np.column_stack([np.asarray(c, dtype=float) for c in cols])

    # -- a table (matrix), for two plain axes

    def _grid(self) -> _t.Table:
        if len(self.dims) != 2 or any(len(dim) != 1 for dim in self.dims):
            raise ValueError(f"a table (matrix) needs two axes: this group has {len(self.first.axes)}; "
                             "save it as one data point per row")
        if len(self.value_columns) != 1:
            raise ValueError(f"a table (matrix) holds one number per cell, not {len(self.value_columns)}; "
                             "save it as one data point per row")
        v, col, (_, part) = self.value_columns[0]
        (a, t, _), (b, x, _) = self.axes
        out = _t.Table(x=x, x_col=self.axis_columns[1], values=[(col, _t.ValueRows(v, b, a, {}, part))],
                       t=t, t_col=self.axis_columns[0], kind="heatmap")
        out.comments = self.comments
        return out

    def check_matrix(self) -> None:
        self._grid().check_matrix()

    # -- size and the file

    def estimate(self, layout: str = "rows") -> Dict[str, int]:
        """About how big the file will be: {"bytes", "rows", "columns"}, from the first rows."""
        if layout == "matrix":
            return self._grid().estimate("matrix")
        rows, cols = int(np.prod(self.lengths)), len(self.columns())
        first = next(self._blocks(SAMPLE_ROWS), None)
        sample = _t._lines(self._block(*first)[:SAMPLE_ROWS]) if first and rows else ""
        per_number = (len(sample) / max(sample.count(",") + sample.count("\n") + 1, 1)) if sample else 8
        header = sum(len(c) + 3 for c in self.header_lines())
        return {"bytes": int(header + rows * cols * per_number), "rows": rows, "columns": cols}

    def to_csv(self, path: Any, layout: str = "rows", rows_are: str = "t",
               progress: Optional[Callable[[float], None]] = None) -> Path:
        """Write the table, as `tables.Table.to_csv` (`<name>.part`, renamed when complete).
        `layout` "rows", or "matrix" for two plain axes."""
        try:
            if layout == "matrix":
                return self._grid().to_csv(path, "matrix", rows_are, progress)
            path = Path(path)
            part = path.with_name(path.name + ".part")
            try:
                with open(part, "w", encoding="utf-8", newline="\n") as f:
                    for line in self.header_lines():
                        f.write("# " + line.replace("\n", " ") + "\n")
                    self._write_rows(f, progress)
                os.replace(part, path)
            except BaseException:
                try:
                    part.unlink()
                except OSError:
                    pass
                raise
            return path
        finally:
            self.close()

    def _write_rows(self, f, progress) -> None:
        total, done = max(int(np.prod(self.lengths)), 1), 0
        step = max(1, _t.BLOCK_NUMBERS // max(len(self.columns()), 1))
        n_axes = len(self.axes)
        for where in self._blocks(step):
            block = self._block(*where)
            done += block.shape[0]
            # a data point not measured (every value empty) has no row, as in `tables.Table`
            block = block[~np.all(np.isnan(block[:, n_axes:]), axis=1)]
            if block.size:
                f.write(_t._lines(block) + "\n")
            if progress is not None:
                progress(done / total)

    def close(self) -> None:
        """A table made from a path holds the file open until it is written."""
        if self._close:
            self.d.close()
            self._close = False


def file_table(data: Any, group: Any) -> FileTable:
    """`group` of `data` (a dataset, or a path, read block by block) as a table. `group`: a Group,
    or the name of one of its values."""
    key = group.key if isinstance(group, Group) else group
    if isinstance(data, (str, os.PathLike)):
        d = lbd.open(data)
        try:
            return FileTable(d, key, close=True)
        except BaseException:
            d.close()
            raise
    if isinstance(data, lbd.Dataset):
        return FileTable(data, key)
    raise TypeError(f"data must be an lbd.Dataset or a path to an .lbd file, not {type(data).__name__}")


__all__: Sequence[str] = ["FileTable", "Group", "file_table", "groups"]
