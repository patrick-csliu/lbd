"""The plot types: one `Kind` each, in a registry, so a new type is one file.

`render.py` registers curve, heatmap and scatter when it is imported, then `load_types()` adds the
types with a file of their own. A file ends with `KIND = Kind(...)`, or `KIND = None` while it has
nothing to offer. This module imports nothing from `render.py`.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


def _plain_axes(fig: Any, model: Any) -> Any:
    return fig.add_subplot()


def _nothing_more(spec: Dict[str, Any]) -> List[str]:
    return []


@dataclass(frozen=True)
class Kind:
    """A plot type.

    `fits(d, value_name)`: None if it can draw that value, otherwise the reason, for the user.
    `d` may be header-only (`lbd.info`), with one axis per dimension (`render.flat`).
    `resolve(d, out, values, pick, spec, index_in, warn_unused, file_spec)`: finishes a resolved
    spec (see `render.resolve_spec`). `prepare(d, spec, style, **kw)` gives the model, and
    `draw(fig, ax, model, d, spec, style)` draws it, on the axes from `make_axes(fig, model)`.
    `applies`: the spec keys it uses, besides those of every type. `needs(spec)`: values to read
    besides `spec["values"]`.
    """

    name: str
    title: str
    fits: Callable[[Any, str], Optional[str]]
    resolve: Callable[..., Dict[str, Any]]
    prepare: Callable[..., Any]
    draw: Callable[..., Any]
    applies: frozenset = frozenset()
    needs: Callable[[Dict[str, Any]], List[str]] = _nothing_more
    make_axes: Callable[[Any, Any], Any] = _plain_axes


KINDS: Dict[str, Kind] = {}


def register(kind: Kind) -> None:
    if kind.name in KINDS:
        raise ValueError(f"the plot type {kind.name!r} is registered twice")
    KINDS[kind.name] = kind


def load_types() -> None:
    """Add the types that have a file of their own. (Plain imports, so a packaged app has them.)"""
    from . import bars, bars3d, histogram, matrix, scatter

    for module in (matrix, bars, bars3d, histogram, scatter):
        if module.KIND is not None:
            register(module.KIND)
