"""A scatter plot in an Explore session: markers, or above `DENSITY_ABOVE` points the number of
points in each pixel, counted again for each view so that zooming stays sharp.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lbd.plot import scatter as sc

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
