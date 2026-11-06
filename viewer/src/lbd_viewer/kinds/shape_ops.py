"""Operations on plots of few positions (Matrix, Bars, 3D bars): only those that keep the shape, so
each cell or bar stays where it is, with the same labels."""

import json
from typing import Any, Dict, List, Optional

from . import Interaction

KEEP_SHAPE = ("subtract_mean", "normalize", "derivative", "smooth", "subtract_first", "subtract_previous")
NOT_APPLIED = "not applied (an operation above can't apply)"


class ShapeOps(Interaction):
    operations = "shape"

    def grid(self) -> Any:
        """The numbers shown, as an `operations.Grid` in stored units."""
        raise NotImplementedError

    def after(self, grid: Any, shown: Any, label: str) -> Any:
        """The model that draws an operated grid."""
        raise NotImplementedError

    def why_no_operations(self) -> Optional[str]:
        """Why this plot can't be operated on now; None: it can."""
        return None

    def apply_ops(self, ops: List[Dict[str, Any]], eqs: Dict[str, str]) -> bool:
        """Run the operations; True when the figure was set up again for another model."""
        from .. import operations as ops_mod
        from ..explore import ExploreError

        s = self.s
        if eqs:
            raise ExploreError("Equations aren't available on this plot")
        key = json.dumps(ops)
        if key == s.ops_key:
            return False
        s.ops_key, s.ops_list = None, ops
        model, result, shown = s.base_model, None, None
        if any(op["on"] for op in ops):
            result = self._run(ops_mod, ops)
            if result.applied:
                factor, unit, label = ops_mod.shown(result.grid.a, result.grid.value,
                                                    s.style.axis_style("y").label.unit_format)
                shown = ops_mod.Shown(factor, unit, False, False)
                model = self.after(result.grid, shown, label)
        s.ops_result, s.ops_shown = result, shown
        s.ops_key = key
        if model is s.model:
            return False
        s.model = model
        s._build()
        return True

    def _run(self, ops_mod: Any, ops: List[Dict[str, Any]]) -> Any:
        """Those before the first one that can't be used here run; that one says why."""
        why = self.why_no_operations()
        if why:
            return ops_mod.Result(None, [why if op["on"] else "off" for op in ops], 0)
        wrong = next((i for i, op in enumerate(ops) if op["on"] and op["op"] not in KEEP_SHAPE), len(ops))
        result = ops_mod.run(self.grid(), ops[:wrong])
        if wrong < len(ops):
            result.notes.append("it changes the shape of the data, so it isn't available on this plot")
            result.notes += [NOT_APPLIED] * (len(ops) - wrong - 1)
        return result
