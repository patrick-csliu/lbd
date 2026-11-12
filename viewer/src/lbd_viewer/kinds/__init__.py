"""What a plot type does in an Explore session: one `Interaction` per type, one file each.

`ExploreSession` keeps the figure, the locks and the picture; it asks `session.view` (an
Interaction) for everything that depends on the type. A new type fills `kinds/<name>.py` and ends it
with `INTERACTION = TheClass`; a file with `INTERACTION = None` adds nothing. This module needs no
edit for a new type.
"""

from typing import Any, Dict, List, Optional, Tuple, Type

import numpy as np

from lbd.plot import kinds as plot_kinds


class Interaction:
    """The default answers. `name`: the spec's kind; `kind`: what the session and the page call it
    (a variable-sweep map is a kind of "heatmap"). `model`: the model class that picks this class."""

    name = ""
    kind = ""
    model: Optional[type] = None
    cursor_types: Tuple[str, ...] = ("cross", "vertical", "horizontal")
    # False: not available; True: all; "shape": those that keep the shape (ShapeOps); "points": on a
    # scatter plot's points; "before": the type runs them. Which ones: operations.OFFERED (16.50)
    operations: Any = False
    no_operations = "Operations aren't available on this plot"
    strips: Optional[str] = None  # None, "cuts" or "histograms"
    syncs = True                  # False: a panel without x and y to share (`meta.sync` is empty)
    log_x = True                  # False: the horizontal axis stays linear

    def __init__(self, session: Any):
        self.s = session
        self.line_options: Dict[str, Any] = {}    # every, at_line, limit: what reading.cursors was asked

    @classmethod
    def prepare(cls, s: Any) -> Any:
        """The model for session `s`, after `set_spec` (curves and maps have their own path)."""
        return plot_kinds.KINDS[s.base_kind].prepare(s.data, s.spec, s.style)

    def make_axes(self) -> Any:
        kind = plot_kinds.KINDS.get(self.kind or self.name)
        return kind.make_axes(self.s.fig, self.s.model) if kind else self.s.fig.add_subplot()

    def setup(self) -> None:
        """The artists for `s.model`, after `fig.clear()`."""
        raise NotImplementedError

    def lay_out(self) -> None:
        self.s._lay_out()

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """The whole data: x and y limits."""
        raise NotImplementedError

    def equal(self) -> bool:
        """Equal axes asked for (`options.equal`, 16.32) and both scales linear."""
        ax = self.s.ax
        return bool((self.s.spec.get("options") or {}).get("equal")) and ax.get_xscale() == ax.get_yscale() == "linear"

    def frame(self, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> None:
        """Show this view on the axes. Equal axes: one stored unit is as long both ways, by
        widening the view asked for around its middle, so that all of it is seen (the widening is
        never sent back: the page keeps the view it asked for, 16.49)."""
        if self.equal():
            xlim, ylim = equal_view(xlim, ylim, self.s.ax.get_window_extent(),
                                    getattr(self.s.model, "xf", 1.0), getattr(self.s.model, "yf", 1.0))
        self.s.ax.set_xlim(*xlim)
        self.s.ax.set_ylim(*ylim)
        self.s._plain_tick_numbers()

    def shown_limits(self, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> Tuple[Any, Any]:
        """The view really shown, after `frame` (equal axes may have widened it)."""
        ax = self.s.ax
        return (tuple(ax.get_xlim()), tuple(ax.get_ylim())) if self.equal() else (xlim, ylim)

    def apply(self, settings: Dict[str, Any], chosen: Optional[set], clim: Any) -> None:
        """View settings, on the artists."""

    def picture(self, pxe: np.ndarray, pye: np.ndarray, stat: str, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        """Bring the artists up to date for these pixel edges: (the note, whether it is reduced)."""
        raise NotImplementedError

    def read(self, cursor: Dict[str, Any], kind: str, geo: Any) -> Optional[Dict[str, Any]]:
        """One cursor's answer."""
        return None

    def read_all(self, cursors: List[Any], kind: str, geo: Any) -> Dict[str, Any]:
        """Added to the whole cursors answer."""
        return {}

    def room(self, cursor: Dict[str, Any]) -> Optional[List[Tuple[int, int]]]:
        """How far a cursor can step down and up, along x and along y (None: as on curves and maps)."""
        return None

    def pick(self, px: float, py: float) -> Optional[Dict[str, Any]]:
        return None

    def find(self, what: str, xlim: Any, ylim: Any, trace: Optional[int]) -> Dict[str, Any]:
        """Max, Min, Peak."""
        from ..explore import ExploreError

        raise ExploreError("searching isn't available on this plot")

    def cuts(self, cursor: Dict[str, Any], kind: str, geo: Any) -> Optional[Dict[str, Any]]:
        """The row and column through a cursor; None: this plot has no cuts."""
        return None

    def values(self) -> np.ndarray:
        """The finite numbers shown: for the contrast and the colour range."""
        return np.empty(0)

    def table(self, numbers: str, view: Optional[Dict[str, Any]]) -> Any:
        """Save as CSV."""
        from .. import export

        return export.grid_table(self.s, numbers, view)

    def has_positive(self, which: str) -> bool:
        """Whether a log scale on this axis ("horizontal", "vertical") can show anything."""
        return True

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        """Notes the page keeps on screen, and why nothing is shown when nothing can be."""
        return [], None

    def ops_info(self) -> Dict[str, Any]:
        """A type with `operations = "before"`: what the page shows about its operations."""
        raise NotImplementedError

    def notes(self) -> List[str]:
        """Notes for the user, added to the frame's."""
        return []

    def meta(self) -> Dict[str, Any]:
        """Added to the frame's `meta`."""
        return {"equal": True} if self.equal() else {}


def equal_view(xlim: Tuple[float, float], ylim: Tuple[float, float], box: Any, xf: float = 1.0,
               yf: float = 1.0) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """The view (plot units) widened so that one stored unit has as many pixels both ways, all of
    the asked view inside it; `box`: the axes in pixels; `xf`, `yf`: plot units per stored unit
    (a prefix shown on an axis doesn't change the shape)."""
    per = max((xlim[1] - xlim[0]) / xf / box.width, (ylim[1] - ylim[0]) / yf / box.height)  # stored units per pixel
    mid_x, mid_y = sum(xlim) / 2, sum(ylim) / 2
    half_x, half_y = per * xf * box.width / 2, per * yf * box.height / 2
    return (mid_x - half_x, mid_x + half_x), (mid_y - half_y, mid_y + half_y)


def _classes() -> List[Type[Interaction]]:
    # (plain imports, so a packaged app has them)
    from . import bars, bars3d, curve, groupmap, heatmap, histogram, matrix, scatter

    modules = (curve, heatmap, groupmap, matrix, bars, bars3d, histogram, scatter)
    return [m.INTERACTION for m in modules if m.INTERACTION is not None]


def interactions() -> Dict[str, Type[Interaction]]:
    return {c.name: c for c in _classes()}


def for_session(s: Any) -> Interaction:
    """The class for what the session shows: by its model's type, else by the spec's kind."""
    classes = _classes()
    for c in classes:
        if c.model is not None and isinstance(s.model, c.model):
            return c(s)
    for c in classes:
        if c.name == s.spec["kind"]:
            return c(s)
    raise KeyError(s.spec["kind"])
