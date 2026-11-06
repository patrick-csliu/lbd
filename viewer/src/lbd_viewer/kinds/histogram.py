"""A histogram in an Explore session. The counts are the expensive part, and depend only on which
numbers are shown: they are kept by `key_of`, so another vertical axis or drawing style needs no
recount.
"""

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from lbd.plot import histogram as hist

from . import Interaction

KEEP = 32                 # results kept (least recently used dropped)
NUMBER_SETTINGS = ("ops", "ops_on", "equations", "select")     # the view settings that change the numbers
SPEC_NUMBERS = ("values", "complex", "color", "all", "index")

_lock = threading.Lock()
_results: "OrderedDict[str, hist.Counted]" = OrderedDict()


def key_of(s: Any, settings: Dict[str, Any]) -> str:
    """What the counts depend on: path, version, which numbers, the bins, what is done to them."""
    spec = {k: s.spec.get(k) for k in SPEC_NUMBERS}
    shown = {k: settings.get(k) for k in NUMBER_SETTINGS}
    return json.dumps([str(Path(s.path).resolve()), s.version, spec, s.spec["options"]["bins"], shown],
                      sort_keys=True, default=str)


def _keep(key: str, counted: hist.Counted) -> None:
    with _lock:
        _results[key] = counted
        _results.move_to_end(key)
        while len(_results) > KEEP:
            _results.popitem(last=False)


def counts_of(s: Any, settings: Dict[str, Any]) -> hist.Counted:
    key = key_of(s, settings)
    with _lock:
        counted = _results.get(key)
        if counted is not None:
            _results.move_to_end(key)
            return counted
    counted = hist.count(s.data, s.spec)
    _keep(key, counted)
    return counted


def forget() -> None:
    """Drop every kept count (tests)."""
    with _lock:
        _results.clear()


class Histogram(Interaction):
    name = kind = "histogram"
    model = hist.HistModel
    cursor_types = ("vertical",)
    operations = "before"         # on the numbers, before they are counted
    log_x = False

    def __init__(self, session: Any):
        super().__init__(session)
        self.drawn: List[Any] = []
        self.showing: Optional[Tuple[int, bool]] = None      # the model and scale the artists show

    @classmethod
    def prepare(cls, s: Any) -> hist.HistModel:
        settings = getattr(s, "settings", None) or {}
        return hist.prepare(s.data, s.spec, s.style, big=counts_of(s, settings))

    def setup(self) -> None:
        s = self.s
        self.drawn = hist.draw(s.fig, s.ax, s.model, s.data, s.spec, s.style, quiet=True)
        self.showing = (id(s.model), s.ax.get_yscale() == "log")

    def _log(self) -> bool:
        return self.s.ax.get_yscale() == "log"

    def limits(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        edges = self.s.model.edges
        return (float(edges[0]), float(edges[-1])), hist.y_limits(self.s.model, self._log())

    def picture(self, pxe: np.ndarray, pye: np.ndarray, stat: str, draft: bool, w: int, h: int) -> Tuple[str, bool]:
        m = self.s.model
        now = (id(m), self._log())
        if now != self.showing:
            hist.update_series(self.drawn, m, now[1])
            self.showing = now
        total = sum(int(s.counts.sum()) for s in m.series)
        return f"{total:,} numbers in {m.edges.size - 1:,} bins", False

    def has_positive(self, which: str) -> bool:
        return which == "horizontal" or any(s.counts.any() for s in self.s.model.series)

    def hidden(self) -> Tuple[List[str], Optional[str]]:
        m = self.s.model
        empty = None if any(s.counts.any() for s in m.series) else self.s._why_empty("number")
        return hist.notes_of(m), empty


INTERACTION = Histogram
