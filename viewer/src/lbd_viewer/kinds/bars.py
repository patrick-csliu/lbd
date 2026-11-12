"""Bars in an Explore session: a click reads a bar, a horizontal cursor is a level to compare them with."""

import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lbd.plot import bars, render as rnd
from lbd.plot.tables import Column, Rows, Table

from .shape_ops import ShapeOps


class Bars(ShapeOps):
    name = kind = "bars"
    model = bars.BarsModel
    cursor_types = ("cross", "horizontal")
    syncs = False          # groups are positions, not an axis to share with a curve

    def setup(self) -> None:
        s = self.s
        s.eq_legend = []
        with warnings.catch_warnings():                  # said when the model was made
            warnings.simplefilter("ignore", rnd.RenderWarning)
            bars.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style)

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        s, m = self.s, self.s.model
        if s.ax.get_yscale() != "log":
            return m.limits
        return m.limits[0], s._padded(s._range([m.bottom + m.z], True), True)

    def picture(self, pxe, pye, stat, draft, w, h) -> Tuple[str, bool]:
        return "every bar shown", False

    def values(self) -> np.ndarray:
        z = self.s.model.z
        return z[np.isfinite(z)]

    # -- reading

    def _bar(self, x: float, y: float, step: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """(bar in its group, group): under (x, y), or the nearest in the group nearest x."""
        m = self.s.model
        count, groups = m.z.shape
        g = int(np.clip(round(x), 0, groups - 1))
        if m.stacked:
            ends = np.sort(np.stack([m.bottom[:, g], m.bottom[:, g] + m.z[:, g]]), axis=0)
            away = np.maximum(np.maximum(ends[0] - y, y - ends[1]), 0)
        else:
            away = np.abs(m.left[:, g] + m.width / 2 - x)
        away = np.where(np.isfinite(m.z[:, g]), away, np.inf)
        if not np.isfinite(away).any():
            return None
        k = int(np.argmin(away))
        if m.stacked:                                    # left and right: the groups; up and down: the bars
            return int(np.clip(k + step[1], 0, count - 1)), int(np.clip(g + step[0], 0, groups - 1))
        flat = int(np.clip(g * count + k + step[0], 0, groups * count - 1))
        return flat % count, flat // count

    def _read_bar(self, k: int, g: int) -> Dict[str, Any]:
        from .. import reading

        s, m = self.s, self.s.model
        b = m.bars
        bottom, height = float(m.bottom[k, g]), float(m.z[k, g])
        left = float(m.left[k, g])
        axis = s.spec.get("x")
        items = [reading._axis_item(s, "x", axis, g) if axis else {"role": "x", "name": "bar", "label": "Bar", "unit": "",
                                                                   "index": g, "value": None, "text": b.groups[g]}]
        if axis and items[0]["text"] is None:
            items[0]["text"] = b.groups[g]
        if b.names[k]:
            items.append({"role": "series", "name": b.columns[k], "label": "Bar", "unit": "", "value": None, "text": b.names[k]})
        items.append({"role": "z", "name": b.columns[k], "label": str(b.bar_labels[k, g]), "unit": str(b.bar_units[k, g]),
                      "value": reading._num(b.raw[k, g])})
        out = {"x": left + m.width / 2, "y": bottom + height / 2, "free": False, "items": items, "at": [g, k],
               "index": {}, "cell": [left, min(bottom, bottom + height), left + m.width, max(bottom, bottom + height)]}
        if axis:
            out["index"][axis] = g
        if s.spec.get("series") and len(b.names) == len(s.data.axes[s.spec["series"]].data):
            out["index"][s.spec["series"]] = k
        if s.ops_result is not None and s.ops_result.applied:
            first = s.raw_model.bars
            out["stored"] = {"label": str(first.bar_labels[k, g]), "unit": str(first.bar_units[k, g]),
                             "value": reading._num(first.raw[k, g])}
        return out

    def read(self, cursor, kind, geo) -> Optional[Dict[str, Any]]:
        from .. import reading

        x, y = reading._check_point(cursor)
        if kind == "horizontal":
            return self._level(x, y)
        step = cursor.get("step") or [0, 0]
        found = self._bar(x, y, (int(step[0]), int(step[1])))
        return None if found is None else self._read_bar(*found)

    def _level(self, x: float, y: float) -> Dict[str, Any]:
        """A level across the bars, read on each vertical axis."""
        from .. import reading

        b = self.s.model.bars
        items = [{"role": "y", "name": "level", "label": b.labels[0], "unit": b.units[0], "value": reading._num(y / b.factors[0])}]
        if len(b.units) == 2:
            items.append({"role": "z", "name": "level", "label": b.labels[1], "unit": b.units[1],
                          "value": reading._num(y / b.right_scale / b.factors[1])})
        return {"x": x, "y": y, "free": False, "items": items, "index": {}}

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        s = self.s
        x, y = s.ax.transData.inverted().transform([(px, s.fig.bbox.height - py)])[0]
        (x0, x1), (y0, y1) = s.ax.get_xlim(), s.ax.get_ylim()
        found = self._bar(x, y, (0, 0)) if x0 <= x <= x1 and y0 <= y <= y1 else None
        if found is None:
            return None
        out = self._read_bar(*found)
        pxs, pys = s._to_px(np.array(out["cell"][0::2]), np.array(out["cell"][1::2]))
        return {**out, "kind": "bar", "rect": [float(pxs.min()), float(pys.min()), float(np.ptp(pxs)), float(np.ptp(pys))]}

    # -- Save as CSV

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> Table:
        s, m = self.s, self.s.model
        shown = self._columns(m.bars)
        stored = self._stored()
        names: Dict[str, Any] = {}
        for column, rows in {"shown": shown, "stored": stored, "both": shown + stored}[numbers]:
            names.setdefault(column.name, (column, rows))     # the same numbers shown and stored: once
        if not s.spec.get("x"):
            return self._one_row(m.bars, numbers)
        xa = s.data.axes[s.spec["x"]]
        comments = ([f"{xa.label or xa.name}: " + ", ".join(f"{k} = {t}" for k, t in enumerate(xa.elements))]
                    if xa.elements is not None else [])
        if s.spec.get("all"):                            # one bar stands for many numbers (16.48)
            stat = bars.STATS[(s.spec.get("options") or {}).get("stat", "mean")][0].lower()
            whole = ", ".join(s.data.axes[a].label or a for a in s.spec["all"])
            comments.append(f"Each bar: the {stat} of all {whole} (empty points left out)")
        t = Table(x=np.asarray(xa.data, dtype=float), x_col=Column(xa.name, xa.label, xa.unit), values=list(names.values()),
                  comments=comments, kind="bars")
        if view is not None:
            t.points = np.flatnonzero((view["xlim"][0] <= m.x) & (m.x <= view["xlim"][1]))
        return t

    @staticmethod
    def _columns(b: "bars.BarSet") -> List[Tuple[Column, Rows]]:
        return [(Column(b.columns[k], str(b.bar_labels[k, 0]), str(b.bar_units[k, 0])), Rows(b.raw[k]))
                for k in range(len(b.columns))]

    def _stored(self) -> List[Tuple[Column, Rows]]:
        s = self.s
        if not any(s.data.values[n].dtype.startswith("complex") for n in s.spec["values"]):
            return self._columns(s.raw_model.bars)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", rnd.RenderWarning)
            return self._columns(bars.read_bars(s.data, {**s.spec, "complex": "re_im"}, s.style))

    def _one_row(self, b: "bars.BarSet", numbers: str) -> Table:
        """Single numbers: a column each, as each has its own unit."""
        s = self.s
        values = []
        for k in range(len(b.columns)):
            for g, name in enumerate(s.spec["values"]):
                if np.isfinite(b.raw[k, g]):
                    part = b.columns[k].removeprefix("value")
                    values.append((Column(f"{name}{part}", str(b.bar_labels[k, g]), str(b.bar_units[k, g])),
                                   Rows(np.array([b.raw[k, g]]))))
        return Table(x=np.zeros(1), x_col=Column("row"), values=values, kind="bars")

    # -- operations

    def why_no_operations(self) -> Optional[str]:
        if len(self.s.base_model.bars.units) > 1:
            return "operations need one unit: show values of one unit here"
        return None

    def grid(self) -> Any:
        from .. import operations as ops_mod

        s, b = self.s, self.s.base_model.bars
        axis = s.data.axes[s.spec["x"]] if s.spec.get("x") else None
        x = np.arange(len(b.groups), dtype=float) if axis is None else np.asarray(axis.data, dtype=float)
        return ops_mod.Grid(a=np.array(b.raw), x=x, t=np.arange(float(len(b.columns))), kind="heatmap",
                            value=ops_mod.Quantity(b.labels[0], b.units[0]),
                            xq=ops_mod.Quantity(axis.label or axis.name if axis is not None else "Bar",
                                                axis.unit if axis is not None else ""),
                            tq=ops_mod.Quantity("Bars in a group"))

    def after(self, grid: Any, shown: Any, label: str) -> Any:
        return bars.operated(self.s.base_model, grid.a, shown.value_factor, shown.value_unit, grid.value.label, label,
                             self.s.style)


INTERACTION = Bars
