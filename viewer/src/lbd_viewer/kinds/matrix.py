"""Matrix in an Explore session: a click reads a cell, as stored; Save as CSV gives the grid."""

import dataclasses
import warnings
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.colors as mcolors
import numpy as np

from lbd.plot import matrix, render as rnd
from lbd.plot.tables import Column, Rows, Table

from .shape_ops import ShapeOps


class Matrix(ShapeOps):
    name = kind = "matrix"
    model = matrix.MatrixModel
    cursor_types = ("cross",)
    syncs = False          # columns are positions, not an axis to share with a map

    def setup(self) -> None:
        s = self.s
        s.eq_legend = []
        with warnings.catch_warnings():                  # said once, by `notes`
            warnings.simplefilter("ignore", rnd.RenderWarning)
            matrix.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style)

    def lay_out(self) -> None:
        s = self.s
        if s.bare:
            s.ax.set_aspect("auto")
            for artist in [*s.model.artists.get("titles", []), s.model.artists.get("numbers")]:
                if artist is not None:
                    artist.set_visible(False)
        s._lay_out()

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return self.s.model.extent

    def frame(self, xlim, ylim) -> None:
        super().frame(xlim, ylim)
        self.s.ax.apply_aspect()                         # equal cells: the box follows the view

    def picture(self, pxe, pye, stat, draft, w, h) -> Tuple[str, bool]:
        s, m = self.s, self.s.model
        left, right = sorted(s.ax.get_xlim())
        for title in m.artists.get("titles", []):
            title.set_visible(left <= title.get_position()[0] <= right and not s.bare)
        numbers = m.artists.get("numbers")
        if numbers is not None and not numbers.fit():
            return "every cell shown; the cells are too small for their numbers: zoom in", False
        return "every cell shown", False

    def notes(self) -> List[str]:
        return [self.s.model.note] if self.s.model.note else []

    def values(self) -> np.ndarray:
        z = self.s.model.z
        return z[np.isfinite(z)]

    # -- reading

    def _cell(self, x: float, y: float, step: Tuple[int, int] = (0, 0)) -> Tuple[int, int, int]:
        """The row, the column in its block, and the block, nearest (x, y)."""
        m = self.s.model
        rows, columns = m.grid.blocks[0].z.shape
        places = np.concatenate([start + np.arange(columns) for start in m.starts])     # not the gap
        k = int(np.clip(np.argmin(np.abs(places - x)) + step[0], 0, places.size - 1))
        row = int(np.clip(np.argmin(np.abs(m.y - y)) - step[1], 0, rows - 1))
        return row, k % columns, k // columns

    def _read(self, row: int, column: int, block: int) -> Dict[str, Any]:
        from .. import reading

        s, m = self.s, self.s.model
        g = m.grid
        x, y = float(m.starts[block] + column), float(m.y[row])
        b = g.blocks[block]
        label = f"{b.title} {g.label}" if b.title else g.label
        value = {"role": "z", "name": g.value, "label": label, "unit": g.raw_unit, "value": reading._num(b.raw[row, column])}
        out = {"x": x, "y": y, "free": False, "index": {g.col_axis: column, g.row_axis: row}, "at": [column, row],
               "items": [reading._axis_item(s, "y", g.row_axis, row), reading._axis_item(s, "x", g.col_axis, column), value],
               "cell": [x - 0.5, y - 0.5, x + 0.5, y + 0.5]}
        if b.title:
            out["block"] = b.title
        if s.ops_result is not None and s.ops_result.applied:
            first = s.raw_model.grid
            out["stored"] = {"label": first.label, "unit": first.raw_unit,
                             "value": reading._num(first.blocks[block].raw[row, column])}
        return out

    def read(self, cursor, kind, geo) -> Optional[Dict[str, Any]]:
        from .. import reading

        x, y = reading._check_point(cursor)
        step = cursor.get("step") or [0, 0]
        return self._read(*self._cell(x, y, (int(step[0]), int(step[1]))))

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        s = self.s
        x, y = s.ax.transData.inverted().transform([(px, s.fig.bbox.height - py)])[0]
        (x0, x1), (y0, y1) = s.model.extent
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        out = self._read(*self._cell(x, y))
        pxs, pys = s._to_px(np.array(out["cell"][0::2]), np.array(out["cell"][1::2]))
        return {**out, "kind": "cell", "rect": [float(pxs.min()), float(pys.min()), float(np.ptp(pxs)), float(np.ptp(pys))]}

    # -- Save as CSV

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> Table:
        s, m = self.s, self.s.model
        g = m.grid
        xa, ya = s.data.axes[g.col_axis], s.data.axes[g.row_axis]
        shown = [(self._column(g, b.title), Rows(b.raw)) for b in g.blocks]
        stored = self._stored()
        values = {"shown": shown, "stored": stored, "both": shown + stored}[numbers]
        x = np.asarray(xa.data, dtype=float)
        names: Dict[str, Any] = {}
        for column, rows in values:                      # the same numbers shown and stored: once
            names.setdefault(column.name, (column, rows))
        comments = [f"{axis.label or axis.name}: " + ", ".join(f"{k} = {t}" for k, t in enumerate(axis.elements))
                    for axis in (ya, xa) if axis.elements is not None]
        columns = list(names.values())
        if m.sums is not None:                           # one more column, for the rows' sums
            x = np.r_[x, np.nan]
            comments.append("the last column, at nan on the horizontal axis, holds each row's sum")
            columns = [(c, Rows(np.c_[rows.source, m.sums if c.name == g.value and numbers != "stored" else np.nan]))
                       for c, rows in columns]
        t = Table(x=x, x_col=Column(g.col_axis, xa.label, xa.unit),
                  t=np.asarray(ya.data, dtype=float), t_col=Column(g.row_axis, ya.label, ya.unit),
                  values=columns, comments=comments, kind="matrix")
        if view is not None:
            self._keep_view(t, view)
        return t

    @staticmethod
    def _column(g: "matrix.Grid", title: str) -> Column:
        name = f"{g.value}_{title.lower()}" if title else g.value
        return Column(name, f"{title} {g.label}" if title else g.label, g.raw_unit)

    def _stored(self) -> List[Tuple[Column, Rows]]:
        s = self.s
        v, g = s.data.values[s.spec["values"][0]], s.model.grid
        z = rnd._take(v, [g.row_axis, g.col_axis], s.spec["index"])
        if np.iscomplexobj(z):
            return [(Column(f"{v.name}_re", f"Re {v.label}", v.unit), Rows(z.real)),
                    (Column(f"{v.name}_im", f"Im {v.label}", v.unit), Rows(z.imag))]
        return [(Column(v.name, v.label, v.unit), Rows(z))]

    def _keep_view(self, t: Table, view: Dict[str, Any]) -> None:
        m = self.s.model
        columns = m.grid.blocks[0].z.shape[1]
        (xa, xb), (ya, yb) = view["xlim"], view["ylim"]
        places = [start + np.arange(columns) for start in m.starts]
        t.points = np.flatnonzero(np.any([(xa <= p) & (p <= xb) for p in places], axis=0))
        if m.sums is not None and xa <= len(m.x) <= xb:
            t.points = np.r_[t.points, columns]
        t.traces = np.flatnonzero((ya <= m.y) & (m.y <= yb))

    # -- operations

    def why_no_operations(self) -> Optional[str]:
        if len(self.s.base_model.grid.blocks) > 1:
            return "operations need one number per cell: choose another complex mode than Re and Im"
        return None

    def grid(self) -> Any:
        from .. import operations as ops_mod

        s = self.s
        g = s.base_model.grid
        xa, ya = s.data.axes[g.col_axis], s.data.axes[g.row_axis]
        return ops_mod.Grid(a=np.array(g.blocks[0].raw, dtype=float), x=np.asarray(xa.data, dtype=float),
                            t=np.asarray(ya.data, dtype=float), value=ops_mod.Quantity(g.label, g.raw_unit),
                            xq=ops_mod.Quantity(xa.label or xa.name, xa.unit), tq=ops_mod.Quantity(ya.label or ya.name, ya.unit),
                            kind="heatmap")

    def after(self, grid: Any, shown: Any, label: str) -> Any:
        m = self.s.base_model
        factor = shown.value_factor
        z = grid.a * factor
        new = dataclasses.replace(m.grid, blocks=[matrix.GridBlock("", z, grid.a)], label=grid.value.label,
                                  unit=shown.value_unit, raw_unit=grid.value.unit, zf=factor)
        norm = mcolors.Normalize()
        norm.autoscale_None(np.ma.masked_invalid(z))
        sums = None if m.sums is None else np.nansum(grid.a, axis=1)
        return dataclasses.replace(m, grid=new, z=z, zf=factor, norm=norm, range="auto", z_label=label, sums=sums, artists={})


INTERACTION = Matrix
