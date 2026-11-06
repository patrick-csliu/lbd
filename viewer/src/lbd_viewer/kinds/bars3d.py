"""3D bars in an Explore session: the page turns the picture, the server draws each angle.

There is no cursor and no zoom box on a 3D plot: `pick` reads the bar under a click, and `turn` sets
the angle of the next picture. The rest (labels, Save as CSV, operations) is Matrix's, on the same grid.
"""

import math
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from mpl_toolkits.mplot3d import proj3d

from lbd.plot import bars3d, render as rnd

from .matrix import Matrix


OVERLAP_PX = 3.0           # tops this close to the nearest count as overlapping: the viewer's nearest wins


class Bars3d(Matrix):
    name = kind = "bars3d"
    model = bars3d.Bars3dModel
    cursor_types: Tuple[str, ...] = ()

    def setup(self) -> None:
        s = self.s
        s.eq_legend = []
        with warnings.catch_warnings():                  # said once, by `notes`
            warnings.simplefilter("ignore", rnd.RenderWarning)
            bars3d.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style)
        self.angle = {"elev": s.model.elev, "azim": s.model.azim, "zoom": s.model.zoom}

    def lay_out(self) -> None:
        """Once, as the plot doesn't move while turning."""
        s = self.s
        if s.bare:
            self._bare_out()
            return
        s.fig.set_layout_engine("constrained")
        s.fig.canvas.draw()
        s.fig.set_layout_engine("none")

    def _bare_out(self) -> None:
        s, m = self.s, self.s.model
        for ax in list(s.fig.axes):
            if ax not in m.axes:
                ax.remove()                              # the colour bar
        s.fig.set_layout_engine("none")
        for k, ax in enumerate(m.axes):
            ax.set_axis_off()
            ax.set_position([k / len(m.axes), 0, 1 / len(m.axes), 1])

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        m = self.s.model
        return (-0.5, len(m.x) - 0.5), (-0.5, len(m.y) - 0.5)

    def frame(self, xlim, ylim) -> None:
        pass                                             # the view of a 3D plot is its angle

    def turn(self, angle: Dict[str, Any]) -> None:
        """The angle of the next picture: {elev, azim, zoom}, each optional. A wrong one says which."""
        from ..explore import ExploreError

        new = dict(self.angle)
        for key, low, high in (("elev", -90.0, 90.0), ("azim", -math.inf, math.inf), ("zoom", 0.5, 3.0)):
            if key not in angle:
                continue
            v = angle[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ExploreError(f"the angle's {key} must be a number, not {v!r}")
            if not low <= v <= high:
                raise ExploreError(f"the angle's {key} must be from {low:g} to {high:g}, not {v:g}")
            new[key] = float(v)
        new["azim"] = (new["azim"] + 180.0) % 360.0 - 180.0
        self.angle = new

    def picture(self, pxe, pye, stat, draft, w, h) -> Tuple[str, bool]:
        s, m = self.s, self.s.model
        bars3d.set_angle(s.fig, self.angle["elev"], self.angle["azim"], self.angle["zoom"])
        bars3d.set_draft(m, draft)
        return f"{len(m.y)} × {len(m.x)} bars", False

    def meta(self) -> Dict[str, Any]:
        return {"angle": dict(self.angle)}

    def read(self, cursor, kind, geo) -> Optional[Dict[str, Any]]:
        return None                                      # no cursors in 3D: `pick` reads a bar

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        """The bar whose top is nearest the pixel, read from the stored numbers. Where tops overlap
        on screen, the one nearest the viewer."""
        from ..explore import PICK_RADIUS_PX

        s, m = self.s, self.s.model
        height = s.fig.bbox.height
        found: List[Tuple[float, float, int, int, int, float, float]] = []
        x, y = np.meshgrid(m.x, m.y)
        for k, (ax, panel) in enumerate(zip(m.axes, m.panels)):
            ok = np.isfinite(panel.height)
            tx, ty, depth = proj3d.proj_transform(x[ok], y[ok], panel.height[ok], ax.get_proj())
            at = ax.transData.transform(np.column_stack([tx, ty]))
            away = np.hypot(at[:, 0] - px, height - at[:, 1] - py)
            rows, columns = np.nonzero(ok)
            for n in np.flatnonzero(away <= 3 * PICK_RADIUS_PX):
                found.append((float(depth[n]), float(away[n]), k, int(rows[n]), int(columns[n]),
                              float(at[n, 0]), float(height - at[n, 1])))
        if not found:
            return None
        nearest = min(f[1] for f in found)
        _, _, k, row, column, x_px, y_px = min(f for f in found if f[1] <= nearest + OVERLAP_PX)
        g, panel = m.grid, m.panels[k]
        return {"kind": "bar3d", "row": g.row_labels[row], "column": g.col_labels[column], "panel": panel.title,
                "index": {g.row_axis: row, g.col_axis: column}, "value": float(panel.raw[row, column]), "unit": g.raw_unit,
                "label": f"{panel.title} {g.label}" if panel.title else g.label, "at": [x_px, y_px],
                "row_label": s.data.axes[g.row_axis].label, "column_label": s.data.axes[g.col_axis].label}

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> Any:
        return super().table(numbers, None)              # no zoomed range: the whole grid

    def after(self, grid: Any, shown: Any, label: str) -> Any:
        return bars3d.operated(self.s.base_model, grid.a, shown.value_factor, shown.value_unit, grid.value.label, label)


INTERACTION = Bars3d
