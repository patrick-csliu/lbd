"""A scatter plot in an Explore session: markers, or above `DENSITY_ABOVE` points the number of
points in each pixel, counted again for each view so that zooming stays sharp.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from lbd.plot import scatter as sc
from lbd.plot import tables
from lbd.plot.render import position_text

from . import Interaction


class Scatter(Interaction):
    name = kind = "scatter"
    model = sc.ScatterModel
    cursor_types = ("cross",)

    def __init__(self, session: Any):
        super().__init__(session)
        self.image: Any = None        # the density picture; None: markers
        self.bar: Any = None          # its "Points per pixel" colour bar

    def _points(self) -> int:
        return sum(x.size for x, _, _ in self.s.model.series)

    def setup(self) -> None:
        s = self.s
        if self._points() > sc.DENSITY_ABOVE:
            self.image, self.bar = sc.draw_scatter(s.fig, s.ax, s.model, s.data, s.spec, s.style,
                                                   image=np.zeros((2, 2, 4)))
        else:
            sc.draw_scatter(s.fig, s.ax, s.model, s.data, s.spec, s.style)
        s.ax.set_aspect("auto")                          # equal axes: `frame` widens the view itself

    def lay_out(self) -> None:
        s = self.s
        if s.bare:                                       # only the data: no colour bar beside it
            for extra in s.fig.axes[1:]:
                extra.remove()
        s._lay_out()

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        s = self.s
        m = s.model
        xlog, ylog = s.ax.get_xscale() == "log", s.ax.get_yscale() == "log"
        x = s._padded(s._range([p[0] for p in m.series], xlog), xlog)
        y = s._padded(s._range([p[1] for p in m.series], ylog), ylog)
        if m.ylim and None not in m.ylim and not ylog:
            y = tuple(m.ylim)
        return x, y

    def _equal(self) -> bool:
        ax = self.s.ax
        return self.s.model.equal and ax.get_xscale() == ax.get_yscale() == "linear"

    def frame(self, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> None:
        """Equal axes: the same units per pixel both ways, by widening the view asked for, so that
        all of it is seen."""
        if self._equal():
            box = self.s.ax.get_window_extent()
            per = max((xlim[1] - xlim[0]) / box.width, (ylim[1] - ylim[0]) / box.height)
            mid_x, mid_y = sum(xlim) / 2, sum(ylim) / 2
            xlim = (mid_x - per * box.width / 2, mid_x + per * box.width / 2)
            ylim = (mid_y - per * box.height / 2, mid_y + per * box.height / 2)
        super().frame(xlim, ylim)

    def shown_limits(self, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> Tuple[Any, Any]:
        ax = self.s.ax
        return (tuple(ax.get_xlim()), tuple(ax.get_ylim())) if self._equal() else (xlim, ylim)

    def picture(self, pxe: np.ndarray, pye: np.ndarray, stat: str, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        s = self.s
        if self.image is None:
            return "every point shown", False
        scales = (s.ax.get_xscale(), s.ax.get_yscale())
        found = sc.density(s.model, (pxe[0], pxe[-1]), (pye[0], pye[-1]), w, h, scales, s.style.figure.axes.colors)
        self.image.set_data(sc.density_image(s.model, found))
        if self.bar is not None and s.model.cvals is None:
            self.bar.set_clim(1, max(int(found.total.max()), 2))
        return found.note, True

    def _nearest(self, x: float, y: float, view: Dict[str, Any], size: Sequence[int]) -> Optional[Tuple[int, int]]:
        """(series, point) of the point in view nearest (x, y) in pixels: in the numbers, not the
        picture, so it is found above the limit too."""
        from ..reading import nearest_point

        xlo, xhi = sorted(view["xlim"])
        ylo, yhi = sorted(view["ylim"])
        best: Optional[Tuple[float, int, int]] = None
        for k, (xs, ys, _) in enumerate(self.s.model.series):
            with np.errstate(invalid="ignore"):
                seen = np.flatnonzero((xs >= xlo) & (xs <= xhi) & (ys >= ylo) & (ys <= yhi))
            i = nearest_point(xs[seen], ys[seen], x, y, view, size)
            if i is None:
                continue
            i = int(seen[i])
            far = self._pixels_away(xs[i], ys[i], x, y, view, size)
            if best is None or far < best[0]:
                best = (far, k, i)
        return None if best is None else (best[1], best[2])

    @staticmethod
    def _pixels_away(px: float, py: float, x: float, y: float, view: Dict[str, Any], size: Sequence[int]) -> float:
        from ..reading import _pixels

        a = [_pixels(np.array([v, c], dtype=float), lim, view.get(scale, "linear"), n)
             for v, c, lim, scale, n in ((px, x, view["xlim"], "xscale", size[0]), (py, y, view["ylim"], "yscale", size[1]))]
        return float((a[0][0] - a[0][1]) ** 2 + (a[1][0] - a[1][1]) ** 2)

    def _colour_item(self, k: int, i: int) -> Optional[Dict[str, Any]]:
        s = self.s
        m = s.model
        c = s.spec.get("color")
        if m.groups is not None:
            step = int(m.index[k][c][i])
            axis = s.data.axes[c]
            return {"role": "series", "name": c, "label": axis.label or c, "unit": axis.unit, "index": step,
                    "value": float(np.asarray(axis.data, dtype=float)[step]), "text": position_text(axis, step)}
        if m.cvals is None:
            return None
        v = float(m.cvals[i])
        return {"role": "z", "name": c, "label": m.c_text[0], "unit": m.c_text[1],
                "value": v / m.cf if np.isfinite(v) else None}

    def read(self, cursor: Dict[str, Any], kind: str, geo: Any) -> Optional[Dict[str, Any]]:
        from ..reading import _check_point, _num

        s = self.s
        m = s.model
        x, y = _check_point(cursor)
        xlim, ylim, w, h, scales = geo
        view = {"xlim": xlim, "ylim": ylim, "xscale": scales[0], "yscale": scales[1]}
        found = self._nearest(x, y, view, (w, h))
        if found is None:
            return None
        k, i = found
        xs, ys, label = m.series[k]
        px, py = float(xs[i]), float(ys[i])
        items = [{"role": "x", "name": m.x_text[0], "label": m.x_text[0], "unit": m.x_text[1], "value": _num(px / m.xf)},
                 {"role": "y", "name": m.y_text[0], "label": label if len(m.series) > 1 else m.y_text[0], "unit": m.y_text[1],
                  "value": _num(py / m.yf)}]
        colour = self._colour_item(k, i)
        if colour is not None:
            items.append(colour)
        free = bool(cursor.get("free"))
        return {"x": x if free else px, "y": y if free else py, "free": free, "items": items,
                "index": {a: int(m.index[k][a][i]) for a in s.data.values[s.spec["values"][k]].axes}}

    def room(self, cursor: Dict[str, Any]) -> List[Tuple[int, int]]:
        return [(0, 0), (0, 0)]                          # no next point between scattered points

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> tables.Table:
        """The points shown: x, each value, the colour, each point's stored index."""
        s = self.s
        m = s.model
        x = m.series[0][0] / m.xf
        same = [p for p in m.series if p[0].size == x.size]
        columns: List[Tuple[tables.Column, tables.Rows]] = []
        for n, (_, y, label) in enumerate(same):
            name = s.spec["values"][n]
            columns.append((tables.Column(name, label, m.y_text[1]), tables.Rows(y / m.yf)))
        if m.cvals is not None:
            columns.append((tables.Column("colour", m.c_text[0], m.c_text[1]), tables.Rows(m.cvals / m.cf)))
        for axis in s.data.values[s.spec["values"][0]].axes:
            columns.append((tables.Column(f"index_{axis}", f"Stored index of {axis}"), tables.Rows(m.index[0][axis].astype(float))))
        t = tables.Table(x=x, x_col=tables.Column("x", m.x_text[0], m.x_text[1]), values=columns)
        if view is not None:
            ys = m.series[0][1]
            (xlo, xhi), (ylo, yhi) = sorted(view["xlim"]), sorted(view["ylim"])
            xs = m.series[0][0]
            t.points = np.flatnonzero((xs >= xlo) & (xs <= xhi) & (ys >= ylo) & (ys <= yhi))
        t.comments = tables._comments(s.data, s.spec, "shown", False)
        return t

    def has_positive(self, which: str) -> bool:
        k = 0 if which == "horizontal" else 1
        with np.errstate(invalid="ignore"):
            return any(bool(np.any(np.isfinite(p[k]) & (p[k] > 0))) for p in self.s.model.series)

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        s = self.s
        series = s.model.series
        notes: List[str] = []
        ok = [np.isfinite(x) & np.isfinite(y) for x, y, _ in series]
        empty = None if any(o.any() for o in ok) else s._why_empty("point")
        for k, which, name in ((0, s.ax.get_xscale(), "horizontal"), (1, s.ax.get_yscale(), "vertical")):
            with np.errstate(invalid="ignore"):
                n = sum(int(((p[k] <= 0) & o).sum()) for p, o in zip(series, ok)) if which == "log" else 0
            if n:
                notes.append(f"{n} point{'s' * (n != 1)} ≤ 0 aren't shown on the log {name} axis.")
        return notes, empty

    def meta(self) -> Dict[str, Any]:
        return {"equal": True} if self._equal() else {}


INTERACTION = Scatter
