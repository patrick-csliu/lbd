"""A map of a variable sweep in an Explore session (lbd.plot.groupmap): for the user it is a Map.

The picture is made per view, from the stored points. A cursor sits on a stored point, found in
pixels, and reads that point's own coordinates. Only a map with rows has cuts.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lbd.plot import groupmap
from lbd.plot import render as rnd, tables

from . import Interaction


class GroupMap(Interaction):
    name = "groupmap"
    kind = "heatmap"
    model = groupmap.GroupMapModel
    operations = False
    no_operations = "Operations aren't available on a variable sweep's map yet"

    def __init__(self, session: Any):
        super().__init__(session)
        self._cells: Optional[List[Any]] = None
        self._cells_of: Any = None

    @property
    def strips(self) -> Optional[str]:
        return "cuts" if self.s.model.cells == "rows" else None

    def setup(self):
        s = self.s
        m = s.model
        s.style_fixed = m.norm.vmin is not None or m.norm.vmax is not None
        m.norm.autoscale_None(np.ma.masked_invalid(m.z))
        s.image = rnd.draw_map(s.fig, s.ax, m, s.data, s.spec, s.style, image=np.full((2, 2), np.nan))
        (x0, x1), (y0, y1) = groupmap.bounds(m)
        s.x_edges, s.y_edges = np.array([x0, x1]), np.array([y0, y1])
        s.full = ((x0, x1), (y0, y1))

    def limits(self):
        return self.s._map_limits()

    def apply(self, settings, chosen, clim):
        self.s._apply_colours(settings, clim)

    def picture(self, pxe, pye, stat, draft, w, h):
        s = self.s
        s.image.set_data(groupmap.raster(s.model, pxe, pye))
        if s.model.z.size > w * h:
            return "more points than pixels: each pixel shows one point", True
        return "every point shown", False

    def values(self):
        z = self.s.model.z
        return z[np.isfinite(z)]

    def table(self, numbers, view):
        """Every point as a row: its coordinates and its number, in the stored units."""
        s, m = self.s, self.s.model
        keep = np.arange(m.z.size)
        if view is not None:
            (x0, x1), (y0, y1) = sorted(view["xlim"]), sorted(view["ylim"])
            keep = np.flatnonzero((m.x >= x0) & (m.x <= x1) & (m.y >= y0) & (m.y <= y1))
        src = s.data._unflat
        ax, ay = src.axes[s.spec["x"]], src.axes[s.spec["y"]]
        v = s.data.values[s.spec["values"][0]]
        return tables.Table(
            x=m.x[keep] / m.xf, x_col=tables.Column(ax.name, ax.label, ax.unit),
            values=[(tables.Column(ay.name, ay.label, ay.unit), tables.Rows(m.y[keep] / m.yf)),
                    (tables.Column(v.name, v.label, v.unit), tables.Rows(m.z[keep] / m.zf))],
            comments=[*tables.identity(s.data), "a variable sweep: one row per stored point"])

    # -- reading values

    def _view(self, geo: Any) -> Tuple[Dict[str, Any], Tuple[int, int]]:
        xlim, ylim, w, h, (xscale, yscale) = geo
        return {"xlim": xlim, "ylim": ylim, "xscale": xscale, "yscale": yscale}, (w, h)

    def _rows(self) -> List[Any]:
        if self._cells is None or self._cells_of is not self.s.model:
            self._cells, self._cells_of = groupmap.row_cells(self.s.model), self.s.model
        return self._cells

    def _order(self) -> Tuple[np.ndarray, List[np.ndarray]]:
        """The rows from low to high, and each one's points along it."""
        m = self.s.model
        along = m.x if m.rows_on == "y" else m.y
        order = np.argsort(m.row_at, kind="stable")
        return order, [(lambda sel: sel[np.argsort(along[sel], kind="stable")])(np.flatnonzero(m.row == r)) for r in order]

    def _step(self, i: int, step: Any) -> int:
        """`step` [along x, along y] in stored points: along a row, or to the next row's nearest."""
        m = self.s.model
        if m.cells != "rows":
            for n, v in zip(step, (m.x, m.y)):
                if n:
                    order = np.argsort(v, kind="stable")
                    at = int(np.flatnonzero(order == i)[0])
                    i = int(order[int(np.clip(at + int(n), 0, order.size - 1))])
            return i
        along, across = (step[0], step[1]) if m.rows_on == "y" else (step[1], step[0])
        rows, points = self._order()
        where = int(np.flatnonzero(rows == m.row[i])[0])
        if along:
            line = points[where]
            at = int(np.flatnonzero(line == i)[0])
            i = int(line[int(np.clip(at + int(along), 0, line.size - 1))])
        if across:
            pos = m.x if m.rows_on == "y" else m.y
            target = points[int(np.clip(where + int(across), 0, len(points) - 1))]
            i = int(target[int(np.argmin(np.abs(pos[target] - pos[i])))])
        return i

    def _nearest(self, cursor: Dict[str, Any], geo: Any) -> Optional[int]:
        from .. import reading

        m = self.s.model
        x, y = reading._check_point(cursor)
        view, size = self._view(geo)
        i = reading.nearest_point(m.x, m.y, x, y, view, size)
        if i is None:
            return None
        return self._step(i, cursor["step"]) if any(cursor.get("step") or []) else i

    def _axis(self, role: str, name: str, plot_value: float, factor: float, point: int) -> Dict[str, Any]:
        a = self.s.data._unflat.axes[name]
        return {"role": role, "name": name, "label": a.label or name, "unit": a.unit, "index": int(point),
                "value": float(plot_value / factor), "text": None}

    def _box(self, i: int) -> Optional[List[float]]:
        """The cell of point i, on a map with rows."""
        m = self.s.model
        if m.cells != "rows":
            return None
        rows, _ = self._order()
        (lo, hi), edges, _z = self._rows()[int(np.flatnonzero(rows == m.row[i])[0])]
        along = m.x[i] if m.rows_on == "y" else m.y[i]
        k = int(np.clip(np.searchsorted(edges, along, side="right") - 1, 0, edges.size - 2))
        a, b = float(edges[k]), float(edges[k + 1])
        return [a, float(lo), b, float(hi)] if m.rows_on == "y" else [float(lo), a, float(hi), b]

    def read(self, cursor, kind, geo):
        from .. import reading

        s, m = self.s, self.s.model
        i = self._nearest(cursor, geo)
        if i is None:
            return None
        x, y = reading._check_point(cursor)
        free = bool(cursor.get("free")) and not any(cursor.get("step") or [])
        point = int(m.point[i])
        items = [self._axis("x", s.spec["x"], m.x[i], m.xf, point), self._axis("y", s.spec["y"], m.y[i], m.yf, point),
                 reading._value_item(s, "z", s.spec["values"][0], m.z[i])]
        out = {"x": x if free or kind == "horizontal" else float(m.x[i]),
               "y": y if free or kind == "vertical" else float(m.y[i]), "free": free, "items": items,
               "index": {s.spec["x"]: point}, "at": [i, int(m.row[i])]}
        box = self._box(i)
        if box:
            out["cell"] = box
        return out

    def pick(self, px, py):
        s, m = self.s, self.s.model
        xd, yd = s.ax.transData.inverted().transform([(px, s.fig.bbox.height - py)])[0]
        from .. import reading

        w, h = s._plot_area()[2:]
        geo = (s.ax.get_xlim(), s.ax.get_ylim(), w, h, (s.ax.get_xscale(), s.ax.get_yscale()))
        view, size = self._view(geo)
        i = reading.nearest_point(m.x, m.y, xd, yd, view, size)
        if i is None:
            return None
        value = None if not np.isfinite(m.z[i]) else float(m.z[i] / m.zf)
        return {"kind": "cell", "index": {s.spec["x"]: int(m.point[i])},
                "value": value, "value_unit": s.data.values[s.spec["values"][0]].unit,
                "shown": {"x": float(m.x[i]), "y": float(m.y[i]), "value": None if value is None else float(m.z[i])}}

    def find(self, what, xlim, ylim, trace):
        from .. import reading
        from ..explore import ExploreError

        m = self.s.model
        x0, x1 = sorted(float(v) for v in xlim)
        y0, y1 = sorted(float(v) for v in ylim)
        sel = np.flatnonzero((m.x >= x0) & (m.x <= x1) & (m.y >= y0) & (m.y <= y1) & np.isfinite(m.z))
        if not sel.size:
            raise ExploreError("no stored values in this range to search")
        i = int(sel[int(np.argmax(reading._score(m.z[sel], what)))])
        return {"x": float(m.x[i]), "y": float(m.y[i])}

    def cuts(self, cursor, kind, geo):
        """Rows only. Along a row: its own stored points. Across the rows: each row's point nearest
        the cursor, with where it really is, because rows have their own positions."""
        from .. import reading

        s, m = self.s, self.s.model
        if m.cells != "rows":
            return None
        xlim, ylim, w, h, (xscale, yscale) = geo
        i = cursor["at"][0]
        rows, points = self._order()
        where = int(np.flatnonzero(rows == m.row[i])[0])
        own = points[where]
        pos = m.x if m.rows_on == "y" else m.y
        nearest = np.array([p[int(np.argmin(np.abs(pos[p] - pos[i])))] for p in points])
        fixed_row, fixed_col = s.spec["y"], s.spec["x"]
        if m.rows_on == "y":
            along = reading._cut(m.x[own], m.z[own], xlim, xscale, w, fixed_row, where)
            across = reading._cut(m.row_at[rows], m.z[nearest], ylim, yscale, h, fixed_col, int(m.point[i]))
            names = ("row", "column")
        else:
            along = reading._cut(m.y[own], m.z[own], ylim, yscale, h, fixed_col, where)
            across = reading._cut(m.row_at[rows], m.z[nearest], xlim, xscale, w, fixed_row, int(m.point[i]))
            names = ("column", "row")
        if len(across["pos"]) == nearest.size:
            across["at"] = [float(v) for v in pos[nearest]]
        out: Dict[str, Any] = {"zf": m.zf}
        cut = {names[0]: along, names[1]: across}
        if kind != "vertical":
            out["row"] = cut["row"]
        if kind != "horizontal":
            out["column"] = cut["column"]
        return out

    def room(self, cursor: Dict[str, Any]) -> List[Tuple[int, int]]:
        """How many stored points a cursor can step down and up: along x, along y."""
        from .. import reading

        m = self.s.model
        x, y = reading._check_point(cursor)
        i = int(np.argmin((m.x - x) ** 2 + (m.y - y) ** 2))
        if m.cells != "rows":
            return [(-int((m.x < m.x[i]).sum()), int((m.x > m.x[i]).sum())),
                    (-int((m.y < m.y[i]).sum()), int((m.y > m.y[i]).sum()))]
        rows, points = self._order()
        where = int(np.flatnonzero(rows == m.row[i])[0])
        at = int(np.flatnonzero(points[where] == i)[0])
        along, across = (-at, points[where].size - 1 - at), (-where, len(points) - 1 - where)
        return [along, across] if m.rows_on == "y" else [across, along]


INTERACTION = GroupMap
