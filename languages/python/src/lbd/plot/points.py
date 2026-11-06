"""The points of a value, one by one: for plot types that take points, not a grid.

Axes in `spec["index"]` are fixed there (sliders); every other axis keeps all its points, so a
value can be seen as one list of numbers with each point's coordinates and stored index. On an
axis group the coordinates are the real ones, not the point numbers of the flat view.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

import numpy as np

from lbd import groups

from .render import flat

BLOCK = 2_000_000       # numbers per block of iter_points


@dataclass
class Points:
    """`data`: 1-D, complex kept. `coords`: every kept axis's coordinate of each point (a group's
    outer axes too). `stored`: each point's index on every dimension of the value (flat view's
    names), so that the point can be found again."""

    data: np.ndarray
    coords: Dict[str, np.ndarray]
    stored: Dict[str, np.ndarray]


def _fixed(v: Any, spec: Dict[str, Any]) -> Dict[str, int]:
    whole = spec.get("all") or []
    return {a: int(i) for a, i in (spec.get("index") or {}).items() if a in v.axes and a not in whole}


def _group_coords(d: Any, v: Any) -> Dict[str, Dict[str, np.ndarray]]:
    """For each dimension of `v` on an axis group: every axis's coordinate, per point of it."""
    owner = v._owner
    if owner is None or v.name not in owner.values:
        return {}
    raw = owner.values[v.name]
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for dim in raw.dims:
        if groups.is_group_dim(owner, dim):
            out[dim[-1]] = {a: np.asarray(owner.axes[a].data)[ix] for a, ix in zip(dim, groups.ancestors(owner, dim))}
    return out


def points_of(d: Any, spec: Dict[str, Any], name: str) -> Points:
    """The points of value `name`: the axes in `spec["index"]` fixed, the rest all kept."""
    f = flat(d)
    v = f.values[name]
    index = _fixed(v, spec)
    arr = np.asarray(v._read(tuple(index.get(a, slice(None)) for a in v.axes) if v.axes else ()))
    left = [a for a in v.axes if a not in index]
    grids = np.indices(arr.shape) if arr.ndim else []
    stored = {a: g.ravel() for a, g in zip(left, grids)}
    size = arr.size
    for a, i in index.items():
        stored[a] = np.full(size, i)
    on_groups = _group_coords(f, v)
    coords: Dict[str, np.ndarray] = {}
    for a in left:
        if a in on_groups:
            coords.update({k: c[stored[a]] for k, c in on_groups[a].items()})
        else:
            coords[a] = np.asarray(f.axes[a].data)[stored[a]]
    return Points(arr.ravel(), coords, stored)


def iter_points(d: Any, spec: Dict[str, Any], name: str, block: int = BLOCK) -> Iterator[Tuple[Optional[int], np.ndarray]]:
    """The numbers of value `name`, block by block, never the whole value at once: `(colour_step,
    numbers)`, with the step of the axis `spec["color"]` (None without one). A value read by part
    stays on disk; what is needed comes through `Value._read`."""
    f = flat(d)
    v = f.values[name]
    index = _fixed(v, spec)
    colour = spec.get("color")
    steps: Any = [None]
    if colour in v.axes:
        steps = range(v.shape[v.axes.index(colour)])
        index.pop(colour, None)
    left = [i for i, a in enumerate(v.axes) if a not in index and a != colour]
    for step in steps:
        where: Dict[int, Any] = {i: index[a] for i, a in enumerate(v.axes) if a in index}
        if colour in v.axes:
            where[v.axes.index(colour)] = step
        if not left:
            sel = tuple(where[i] for i in range(len(v.axes)))
            yield step, np.asarray(v._read(sel if v.axes else ())).ravel()
            continue
        # along the first kept dimension, as many positions as fit a block
        lead = left[0]
        per = int(np.prod([v.shape[i] for i in left[1:]], dtype=np.int64)) or 1
        rows = max(block // per, 1)
        for start in range(0, v.shape[lead], rows):
            part = {**where, lead: slice(start, min(start + rows, v.shape[lead]))}
            sel = tuple(part.get(i, slice(None)) for i in range(len(v.axes)))
            yield step, np.asarray(v._read(sel)).ravel()
