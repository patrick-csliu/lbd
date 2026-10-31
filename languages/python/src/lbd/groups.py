"""Axis groups (format 2.0, spec §1.8): sweeps whose inner points depend on the outer ones.

A group lists its measured points level by level. Level k is the group's k-th axis: one entry
per point of its first k axes, holding the k-th coordinate (`Axis.data`) and, below level 1,
the index of the point it belongs to in the level above (`Axis.parent`). Only measured points
exist.

This module finds points by their coordinates (`Lookup`), plans the group part of a write
(`plan_points`), grows arrays without copying them at every point (`grown`), and reads values
on groups: `coords`, `rows`, `to_dense`.
"""

from __future__ import annotations

import bisect
from array import array
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from .io import Axis, Group, LBDError, Value, _warn

if TYPE_CHECKING:
    from .io import Dataset

NEAR = 1e-9                  # coordinates closer than this × their scale (range or size) are "near-equal"
DENSE_LIMIT = 10 ** 8        # to_dense refuses rectangles of more cells (limit=None: no limit)


# ---- dimensions --------------------------------------------------------------


def dimensions(d: "Dataset", names: Sequence[str], where: str) -> List[Tuple[str, ...]]:
    """A value's dimensions from its axis names: a fixed axis is one dimension; consecutive
    axes of one group, starting at its first, are one dimension (a level); a group's name
    means all its axes."""
    dims: List[Tuple[str, ...]] = []
    seen: set = set()
    i = 0
    while i < len(names):
        name = names[i]
        if name in d.groups:
            g = d.groups[name]
            if not g.order:
                raise LBDError(f"{where}: group '{name}' has no axes yet; add them with add_axis(..., group='{name}')")
            dim = tuple(g.order)
            i += 1
        elif name in d.axes and d.axes[name].group is not None:
            g = d.groups[d.axes[name].group]
            if name != g.order[0]:
                k = g.order.index(name)
                raise LBDError(f"{where}: '{name}' is an inner axis of group '{g.name}' (order {g.order}); a value "
                               f"lies on an outer part of a group: give {g.order[:k + 1]}, not '{name}' alone")
            k = 1
            while i + k < len(names) and k < len(g.order) and names[i + k] == g.order[k]:
                k += 1
            if i + k < len(names) and names[i + k] in g.order:
                raise LBDError(f"{where}: the axes of group '{g.name}' must be given in its order {g.order}, "
                               f"consecutive and starting at '{g.order[0]}'; got {list(names)}")
            dim = tuple(g.order[:k])
            i += k
        else:
            if name not in d.axes:
                raise LBDError(f"{where}: axis '{name}' does not exist; add it with add_axis first")
            dim = (name,)
            i += 1
        owner = d.axes[dim[0]].group or dim[0]
        if owner in seen:
            raise LBDError(f"{where}: {'group' if d.axes[dim[0]].group else 'axis'} '{owner}' appears more than once "
                           f"in {list(names)}")
        seen.add(owner)
        dims.append(dim)
    return dims


def dim_length(d: "Dataset", dim: Tuple[str, ...]) -> int:
    """A dimension's length: its axis's points, or its level's (the last axis of the level)."""
    return len(d.axes[dim[-1]].data)


def is_group_dim(d: "Dataset", dim: Tuple[str, ...]) -> bool:
    return d.axes[dim[0]].group is not None


def ancestors(d: "Dataset", dim: Tuple[str, ...]) -> List[np.ndarray]:
    """For each point of the level `dim` ends at, the index of its point at every level of
    `dim` (outer first; the last is 0 … n−1)."""
    idx = np.arange(dim_length(d, dim))
    out = [idx]
    for m in range(len(dim) - 1, 0, -1):
        idx = np.asarray(d.axes[dim[m]].parent)[idx]
        out.insert(0, idx)
    return out


# ---- growing arrays ----------------------------------------------------------


def grown(d: "Dataset", key: Any, arr: np.ndarray, axis: int, k: int, fill: Any,
          dtype: Any = None) -> np.ndarray:
    """`arr` with `k` more entries along `axis`, holding `fill`. Arrays that grow point by point
    are views of a buffer with room (kept in `d._room`), so a point costs no copy of the whole."""
    dtype = np.dtype(dtype) if dtype is not None else arr.dtype
    dtype = np.result_type(arr.dtype, dtype)
    shape = list(arr.shape)
    old = shape[axis]
    shape[axis] += k
    buf = d._room.get(key)
    fits = (buf is not None and buf.dtype == dtype and buf.ndim == arr.ndim and arr.base is buf
            and all(b >= n for b, n in zip(buf.shape, shape)))
    if not fits:
        cap = list(shape)
        cap[axis] = max(int(shape[axis] * 1.5), shape[axis] + 16)
        buf = np.empty(cap, dtype=dtype)
        buf[tuple(slice(0, n) for n in arr.shape)] = arr
        d._room[key] = buf
    out = buf[tuple(slice(0, n) for n in shape)]
    new = [slice(None)] * len(shape)
    new[axis] = slice(old, old + k)
    out[tuple(new)] = fill
    return out


def fill_for(dtype: str) -> Any:
    """What a point not measured holds: NaN, or 0 (with a `measured` mask) for integers and booleans."""
    if dtype.startswith("complex"):
        return complex(np.nan, np.nan)
    return np.nan if dtype.startswith("float") else 0


# ---- finding points by their coordinates ---------------------------------------


class Lookup:
    """The points of one level, found by (parent, coordinate). Per parent: its points'
    coordinates sorted, with their indices (compact arrays, searched by bisection); this also
    gives each new point's neighbours, for the near-equal warning."""

    def __init__(self, ax: Axis):
        data = np.asarray(ax.data, dtype=float)
        parents = np.full(data.size, -1, dtype=np.int64) if ax.parent is None else np.asarray(ax.parent, dtype=np.int64)
        self.n = data.size
        self.by_parent: Dict[int, Tuple[array, array]] = {}
        self.lo = float(data.min()) if data.size else np.inf
        self.hi = float(data.max()) if data.size else -np.inf
        if data.size:
            order = np.lexsort((data, parents))
            p_sorted = parents[order]
            cuts = np.flatnonzero(np.diff(p_sorted)) + 1
            for chunk in np.split(order, cuts):
                self.by_parent[int(parents[chunk[0]])] = (array("d", data[chunk].tolist()),
                                                          array("q", chunk.tolist()))

    def find(self, parent: int, c: float) -> Optional[int]:
        entry = self.by_parent.get(parent)
        if entry is None:
            return None
        coords, idx = entry
        i = bisect.bisect_left(coords, c)
        if i < len(coords) and coords[i] == c:
            return idx[i]
        return None

    def add(self, parent: int, c: float, index: int) -> Optional[float]:
        """Record a new point; returns a neighbour it is near-equal to (or None)."""
        coords, idx = self.by_parent.setdefault(parent, (array("d"), array("q")))
        i = bisect.bisect_left(coords, c)
        self.lo, self.hi = min(self.lo, c), max(self.hi, c)
        scale = max(self.hi - self.lo, abs(self.lo), abs(self.hi))
        near = None
        for j in (i - 1, i):
            if 0 <= j < len(coords) and coords[j] != c and abs(coords[j] - c) <= NEAR * scale:
                near = coords[j]
        coords.insert(i, c)
        idx.insert(i, index)
        self.n += 1
        return near


def lookup(d: "Dataset", name: str) -> Lookup:
    ax = d.axes[name]
    lk = d._lookups.get(name)
    if lk is None or lk.n != len(ax.data):          # new, or the level was changed by hand
        lk = Lookup(ax)
        d._lookups[name] = lk
    return lk


# ---- planning the group part of a write ------------------------------------------


def _coordinates(name: str, x: Any) -> np.ndarray:
    arr = np.asarray(x)
    if arr.dtype.kind not in "iuf" or arr.ndim > 1:
        raise LBDError(f"write: '{name}' is an axis of a group: give its coordinate (a number) or a 1-D array of "
                       f"them, not {x!r}")
    if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
        raise LBDError(f"write: '{name}' got NaN or inf; coordinates must be finite numbers")
    return arr


def plan_points(d: "Dataset", given: Dict[str, Any], parent: Any) -> Dict[str, Dict[str, Any]]:
    """The points a write names in each group: found by their coordinates, or new. Nothing is
    changed; returns per group the point index (int, or an array for several points), the
    deepest level given, and the new points per level, outer first."""
    by_group: Dict[str, List[str]] = {}
    for a in given:
        by_group.setdefault(d.axes[a].group, []).append(a)
    if parent is not None and len(by_group) != 1:
        raise LBDError("write: parent= names a point of one group; give the axes of that group (and only one group) "
                       f"with it, got {sorted(by_group) or 'no group axis'}")
    plans: Dict[str, Dict[str, Any]] = {}
    for gname, names in by_group.items():
        g = d.groups[gname]
        ks = sorted(g.order.index(a) for a in names)
        start, end = ks[0], ks[-1]
        if ks != list(range(start, end + 1)):
            missing = [a for a in g.order[start:end + 1] if a not in names]
            raise LBDError(f"write: group '{gname}' (order {g.order}) needs its axes one after the other; "
                           f"{missing} missing")
        if parent is None and start > 0:
            raise LBDError(f"write: '{g.order[start]}' means something only under {g.order[:start]}: give "
                           f"{', '.join(g.order[:start])} too, or the outer point with parent=")
        if parent is not None and start == 0:
            raise LBDError(f"write: parent= names a point of the level above '{g.order[0]}', which is the first axis "
                           f"of group '{gname}'; leave parent= out")
        coords = [_coordinates(a, given[a]) for a in g.order[start:end + 1]]
        lens = {c.size for c in coords if c.ndim == 1}
        par = None
        if parent is not None:
            par = np.asarray(parent)
            if par.dtype.kind not in "iu" or par.ndim > 1:
                raise LBDError(f"write: parent= takes the index (or a 1-D array of indices) that write returned, "
                               f"not {parent!r}")
            n_above = len(d.axes[g.order[start - 1]].data)
            if par.size and (par.min() < 0 or par.max() >= n_above):
                raise LBDError(f"write: parent={parent!r} is not a point of '{g.order[start - 1]}' (it has {n_above}: "
                               f"0 … {n_above - 1})")
            if par.ndim == 1:
                lens.add(par.size)
        if len(lens) > 1:
            raise LBDError(f"write: the coordinates given for group '{gname}' have different lengths {sorted(lens)}")
        many = bool(lens)
        n = lens.pop() if many else 1
        cols = [np.broadcast_to(c, (n,)).tolist() for c in coords]
        pars = [-1] * n if par is None else np.broadcast_to(par, (n,)).tolist()
        new: List[Tuple[str, List[Any], List[int]]] = [(a, [], []) for a in g.order[start:end + 1]]
        pending: Dict[Tuple[int, int, Any], int] = {}
        result = []
        for i in range(n):
            p = pars[i]
            for m, a in enumerate(g.order[start:end + 1]):
                c = cols[m][i]
                key = (m, p, c)
                idx = pending.get(key)
                if idx is None:
                    idx = lookup(d, a).find(p, c)
                if idx is None:
                    idx = len(d.axes[a].data) + len(new[m][1])
                    new[m][1].append(c)
                    new[m][2].append(p)
                    pending[key] = idx
                p = idx
            result.append(p)
        plans[gname] = {
            "depth": g.order[end], "index": np.array(result, dtype=np.int64) if many else result[0],
            "n": n if many else None,
            "new": [(a, cs, ps) for a, cs, ps in new if cs],
        }
    if sum(p["n"] is not None for p in plans.values()) > 1:
        raise LBDError("write: give several points of one group at a time (one point of each other group)")
    return plans


# ---- reading values on groups ------------------------------------------------------


def coords(d: "Dataset", v: Value) -> Dict[str, np.ndarray]:
    """One array per axis of `v`, along its dimension of `v.data`: a fixed axis's coordinates;
    for a level of a group, each point's coordinate on every axis down to it."""
    out: Dict[str, np.ndarray] = {}
    for dim in v.dims:
        if not is_group_dim(d, dim):
            out[dim[0]] = np.array(d.axes[dim[0]].data)
            continue
        for a, ix in zip(dim, ancestors(d, dim)):
            out[a] = np.asarray(d.axes[a].data)[ix]
    return {a: out[a] for a in v.axes}


def rows(d: "Dataset", v: Value, by: str) -> Iterator[Tuple[Any, "Dataset"]]:
    """One row per point of `by`'s level (or per position of a fixed axis `by`): the key is
    the coordinate(s) down to `by`, the row an lbd.Dataset with what lies inside it."""
    pos = next((i for i, dim in enumerate(v.dims) if by in dim), None)
    if pos is None:
        raise LBDError(f"rows: '{v.name}' doesn't lie on '{by}' (its axes: {v.axes})")
    dim = v.dims[pos]
    if not is_group_dim(d, dim):
        ax = d.axes[by]
        for i in range(len(ax.data)):
            yield np.asarray(ax.data)[i].item(), part(d, v, pos, ("index", i))
        return
    j = dim.index(by)
    if j == len(dim) - 1:                     # by the innermost level: a row per point
        chain = ancestors(d, dim)
        cols = [np.asarray(d.axes[a].data)[ix] for a, ix in zip(dim, chain)]
        for p in range(dim_length(d, dim)):
            key = tuple(c[p].item() for c in cols)
            yield (key[0] if len(key) == 1 else key), part(d, v, pos, ("point", p))
        return
    anc = ancestors(d, dim)[j]                # each point's point on by's level
    outer = dim[:j + 1]
    key_cols = [np.asarray(d.axes[a].data)[ix] for a, ix in zip(outer, ancestors(d, outer))]
    n_by = dim_length(d, outer)
    order = np.argsort(anc, kind="stable")
    counts = np.bincount(anc, minlength=n_by)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
    in_place = bool(np.all(order == np.arange(order.size)))    # rows stored one after the other
    for p in range(n_by):
        s, n = int(starts[p]), int(counts[p])
        pts = slice(s, s + n) if in_place else np.sort(order[s:s + n])
        key = tuple(c[p].item() for c in key_cols)
        yield (key[0] if len(key) == 1 else key), part(d, v, pos, ("under", j, p, pts))


def part(d: "Dataset", v: Value, pos: int, sel: Tuple) -> "Dataset":
    """A new dataset with the part of `v` that `sel` picks along dimension `pos` (everything
    along the others): `("index", i)` of a fixed axis, `("point", p)` of a level, or
    `("under", j, p, pts)`: the points under point p of level j. Its arrays are copies."""
    from .io import Dataset

    nd = Dataset(d.title)
    index: List[Any] = []
    dims: List[Tuple[str, ...]] = []
    for i, dim in enumerate(v.dims):
        if i != pos:
            _copy_dim(d, nd, dim)
            index.append(slice(None))
            dims.append(dim)
            continue
        kind = sel[0]
        if kind in ("index", "point"):
            index.append(sel[1])
            continue
        _, j, p, pts = sel
        rest = dim[j + 1:]
        if len(rest) == 1:                    # what is inside is one axis: an ordinary axis
            src = d.axes[rest[0]]
            nd.axes[rest[0]] = Axis(rest[0], np.array(np.asarray(src.data)[pts]), unit=src.unit, label=src.label)
            index.append(pts)
        else:                                 # still a group: its levels below point p
            g = d.groups[d.axes[dim[0]].group]
            nd.groups[g.name] = Group(g.name, list(rest))
            keep_above = None
            for m in range(j + 1, len(dim)):
                anc = ancestors(d, dim[:m + 1])[j]
                keep = np.flatnonzero(anc == p)
                src = d.axes[dim[m]]
                parent = None if keep_above is None else \
                    np.searchsorted(keep_above, np.asarray(src.parent)[keep]).astype(np.int64)
                nd.axes[dim[m]] = Axis(dim[m], np.array(np.asarray(src.data)[keep]), unit=src.unit, label=src.label,
                                       group=g.name, parent=parent)
                keep_above = keep
            index.append(keep_above)
        dims.append(rest)
    data = np.array(v._read(tuple(index)))
    measured = None if v.measured is None else np.array(np.asarray(v.measured)[tuple(index)])
    _add(nd, v, data, dims, measured)
    return nd


def _copy_dim(d: "Dataset", nd: "Dataset", dim: Tuple[str, ...]) -> None:
    if is_group_dim(d, dim):
        g = d.groups[d.axes[dim[0]].group]
        nd.groups.setdefault(g.name, Group(g.name, list(dim)))
    for a in dim:
        src = d.axes[a]
        nd.axes[a] = Axis(a, np.array(src.data), unit=src.unit, label=src.label, elements=src.elements,
                          group=src.group, parent=None if src.parent is None else np.array(src.parent))


def _add(nd: "Dataset", v: Value, data: np.ndarray, dims: List[Tuple[str, ...]],
         measured: Optional[np.ndarray]) -> Value:
    axes = [a for dim in dims for a in dim]
    w = Value(v.name, data, axes, unit=v.unit, label=v.label, shape=data.shape, dtype=v.dtype, dims=list(dims),
              point_shape=tuple(v.point_shape), elements=list(v.elements), measured=measured)
    w._point = list(v._point)
    w._owner = nd
    nd.values[v.name] = w
    return w


def _ticks(c: np.ndarray, name: str, round_: Optional[int], rtol: Optional[float],
           atol: Optional[float]) -> Tuple[np.ndarray, np.ndarray]:
    """An axis's ticks (sorted) from its points' coordinates, and each point's tick."""
    if round_ is not None:
        c = np.round(c, round_)
    u, inv = np.unique(c, return_inverse=True)
    inv = inv.reshape(-1)
    if rtol is not None or atol is not None:
        r, a = rtol or 0.0, atol or 0.0
        cluster = np.empty(u.size, dtype=np.int64)
        first, k = None, -1
        for i, x in enumerate(u.tolist()):
            if first is None or abs(x - first) > a + r * abs(first):
                first, k = x, k + 1
            cluster[i] = k
        ticks = np.array([u[cluster == m].mean() for m in range(k + 1)]) if u.size else u
        return ticks, cluster[inv]
    if round_ is None and u.dtype.kind == "f" and u.size > 1:
        scale = max(u[-1] - u[0], abs(u[0]), abs(u[-1]))
        close = np.flatnonzero(np.diff(u) <= NEAR * scale)
        if close.size:
            pairs = ", ".join(f"{u[i]!r} and {u[i + 1]!r}" for i in close[:3])
            _warn(f"to_dense: '{name}' has coordinates that differ only by rounding ({pairs}"
                  f"{' …' if close.size > 3 else ''}): they become separate ticks. Merge them with round= "
                  "(decimals) or rtol= / atol= (as np.isclose)")
    return u, inv


def to_dense(d: "Dataset", v: Value, round: Optional[int] = None, rtol: Optional[float] = None,
             atol: Optional[float] = None, limit: Optional[int] = DENSE_LIMIT) -> "Dataset":
    """`v` placed in a rectangle (an lbd.Dataset with fixed axes only): each axis's ticks are the
    sorted distinct coordinates of `v`'s points; cells not measured hold NaN (0 / False with a
    `measured` mask for integers and booleans). A copy; it doesn't interpolate."""
    from .io import Dataset

    if round is not None and (rtol is not None or atol is not None):
        raise LBDError("to_dense: give round= or rtol= / atol=, not both")
    for what, x in (("rtol", rtol), ("atol", atol)):
        if x is not None and not (isinstance(x, (int, float)) and x >= 0):
            raise LBDError(f"to_dense: {what}= must be a number ≥ 0, not {x!r}")
    if round is not None and not isinstance(round, (int, np.integer)):
        raise LBDError(f"to_dense: round= takes a number of decimals (an int), not {round!r}")
    ticks: Dict[str, np.ndarray] = {}
    places: List[Optional[List[np.ndarray]]] = []
    for dim in v.dims:
        if not is_group_dim(d, dim):
            ticks[dim[0]] = np.array(d.axes[dim[0]].data)
            places.append(None)
            continue
        where = []
        for a, ix in zip(dim, ancestors(d, dim)):
            t, inv = _ticks(np.asarray(d.axes[a].data)[ix], a, round, rtol, atol)
            ticks[a] = t
            where.append(inv)
        places.append(where)
    shape = tuple(len(ticks[a]) for a in v.axes) + tuple(v.point_shape)
    cells = int(np.prod(shape, dtype=np.float64))
    itemsize = np.dtype("uint8" if v.dtype == "bool" else v.dtype).itemsize
    if limit is not None and cells > limit:
        raise LBDError(f"to_dense: '{v.name}' as a rectangle {shape} has {cells:,} cells "
                       f"({cells * itemsize / 1e9:.2f} GB), more than limit={limit:,}. Read it row by row with "
                       "rows(by=...), or give limit=None to make it anyway")
    data = np.asarray(v._read(()))
    is_float = v.dtype.startswith(("float", "complex"))
    mask = None if is_float else (np.ones(data.shape, dtype=bool) if v.measured is None else np.asarray(v.measured))
    out, out_mask = data, mask
    axis = 0
    for dim, where in zip(v.dims, places):
        if where is None:
            axis += 1
            continue
        sizes = tuple(len(ticks[a]) for a in dim)
        flat = np.ravel_multi_index(tuple(where), sizes) if where[0].size else np.zeros(0, dtype=np.int64)
        u, counts = np.unique(flat, return_counts=True)
        if np.any(counts > 1):
            cell = np.unravel_index(int(u[np.argmax(counts > 1)]), sizes)
            at = ", ".join(f"{a}={ticks[a][c]!r}" for a, c in zip(dim, cell))
            raise LBDError(f"to_dense: two points of '{v.name}' fall into one cell ({at}): merging must not drop a "
                           "result. Use a smaller round= / rtol= / atol=")
        out = _scatter(out, axis, where, sizes, fill_for(v.dtype))
        if out_mask is not None:
            out_mask = _scatter(out_mask, axis, where, sizes, False)
        axis += len(dim)
    if out is data:
        out = np.array(data)
        out_mask = None if out_mask is None else np.array(out_mask)
    nd = Dataset(d.title)
    for a in v.axes:
        src = d.axes[a]
        nd.axes[a] = Axis(a, ticks[a], unit=src.unit, label=src.label,
                          elements=src.elements if src.group is None else None)
    measured = None if out_mask is None or bool(out_mask.all()) else out_mask
    _add(nd, v, out, [(a,) for a in v.axes], measured)
    return nd


def _scatter(arr: np.ndarray, axis: int, where: List[np.ndarray], sizes: Tuple[int, ...], fill: Any) -> np.ndarray:
    """Spread `arr`'s points along `axis` into the cells `where` of `sizes` (new dimensions)."""
    moved = np.moveaxis(arr, axis, 0)
    out = np.full(sizes + moved.shape[1:], fill, dtype=arr.dtype)
    out[tuple(where)] = moved
    return np.moveaxis(out, list(range(len(sizes))), [axis + k for k in range(len(sizes))])
