"""Reduce large data to what a screen can show, without losing what matters (the Explore view).

A screen pixel shows one colour. When a map has more cells than the plot has pixels, or a curve
more points than pixel columns, each pixel stands for several stored numbers and something must
choose between them. Drawing programs choose silently (usually an average, which can hide a
single hot cell). Here the choice is made on purpose and reported:

- maps (`MapPyramid`): the max, min or mean of the cells under each pixel. A pyramid of blocks of
  2x2, 4x4, ... cells, made once, keeps this fast at every zoom; max and min stay exact (the max
  of maxima is the max).
- curves (`curve_minmax`): the smallest and largest value in each pixel column, so a spike of one
  point stays visible.

Zoomed in, when cells are bigger than pixels, nothing is reduced: each pixel shows the cell under
its centre. Values read off the screen (clicks, cursors) must come from the full data, not from
these pictures.

A map bigger than memory (plan 6d) gets its pyramid built part by part (`map_levels`: strips of
rows read one at a time) and kept on disk; `MapPyramid.from_levels` reads from it, and from the
file itself when zoomed in, only the part in view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

STATS = ("max", "min", "mean")


class ReduceError(ValueError):
    """The data can't be reduced as asked (e.g. a map axis that isn't monotonic)."""


def cell_edges(centres: np.ndarray) -> np.ndarray:
    """Cell edges for cell centres: halfway between neighbours, the outer cells mirrored.

    The same edges matplotlib's pcolormesh(shading="nearest") uses, so the Explore view and the
    figure put every cell in the same place."""
    c = np.asarray(centres, dtype=float)
    if c.size == 1:
        return np.array([c[0] - 0.5, c[0] + 0.5])
    mid = (c[:-1] + c[1:]) / 2
    return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])


@dataclass
class Raster:
    """A map reduced to the pixels of a plot area: `image` has one value per pixel (rows bottom to
    top, NaN where no cell is), `level` the pyramid level used (blocks of 2**level cells a side),
    and `cells_per_pixel` how many stored cells one pixel stands for along x and y (below 1:
    zoomed in, every cell shown)."""

    image: np.ndarray
    level: int
    cells_per_pixel: Tuple[float, float]
    stat: str

    @property
    def reduced(self) -> bool:
        return max(self.cells_per_pixel) > 1

    def note(self) -> str:
        cx, cy = self.cells_per_pixel
        if not self.reduced:
            return "every cell shown"
        return f"{self.stat} of {max(cx, 1):.3g}×{max(cy, 1):.3g} cells per pixel"


class _Level:
    def __init__(self, vmax, vmin, vsum, count, xe, ye):
        self.max, self.min, self.sum, self.count, self.xe, self.ye = vmax, vmin, vsum, count, xe, ye


def _halve(a: np.ndarray, fill, ufunc) -> np.ndarray:
    """Combine 2x2 blocks with `ufunc` (odd sizes padded with `fill`)."""
    ny, nx = a.shape
    if ny % 2 or nx % 2:
        a = np.pad(a, ((0, ny % 2), (0, nx % 2)), constant_values=fill)
    a = a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2)
    return ufunc.reduce(ufunc.reduce(a, axis=3), axis=1)


def _monotonic(edges: np.ndarray, what: str) -> bool:
    """True when increasing, False when decreasing; anything else can't be drawn as a map."""
    d = np.diff(edges)
    if np.all(d > 0):
        return True
    if np.all(d < 0):
        return False
    raise ReduceError(f"the map's {what} axis is not sorted (its values go up and down); "
                      "the Explore view needs sorted axes to place the cells")


class MapPyramid:
    """A map's cells, and blocks of 2x2, 4x4, ... of them, for fast reduction to any view.

    `z` has rows along y and columns along x; `x_edges` / `y_edges` are the cell edges (see
    cell_edges), increasing or decreasing. Missing cells are NaN and are left out of every block.
    """

    def __init__(self, z: np.ndarray, x_edges: np.ndarray, y_edges: np.ndarray, smallest: int = 64):
        z = np.asarray(z, dtype=float)
        xe, ye = np.asarray(x_edges, dtype=float), np.asarray(y_edges, dtype=float)
        if z.shape != (len(ye) - 1, len(xe) - 1):
            raise ReduceError(f"a map of {z.shape[0]}×{z.shape[1]} cells needs {z.shape[1] + 1} x edges and "
                              f"{z.shape[0] + 1} y edges, not {len(xe)} and {len(ye)}")
        if not _monotonic(xe, "horizontal"):          # stored in increasing order from here on
            xe, z = xe[::-1], z[:, ::-1]
        if not _monotonic(ye, "vertical"):
            ye, z = ye[::-1], z[::-1, :]
        self.shape = z.shape
        # Level 0 is the map itself; its sum and count are made per view, from the visible part only.
        self.levels: List[_Level] = [_Level(z, z, None, None, xe, ye)]
        vmax, vmin = z, z
        vsum, count = np.nan_to_num(z), np.isfinite(z).astype(np.int32)
        while max(vmax.shape) > smallest:
            step = 2 ** len(self.levels)
            vmax = _halve(vmax, np.nan, np.fmax).astype(np.float32)
            vmin = _halve(vmin, np.nan, np.fmin).astype(np.float32)
            vsum = _halve(vsum, 0.0, np.add)
            count = _halve(count, 0, np.add)
            ny, nx = vmax.shape
            self.levels.append(_Level(vmax, vmin, vsum, count,
                                      xe[np.minimum(np.arange(nx + 1) * step, len(xe) - 1)],
                                      ye[np.minimum(np.arange(ny + 1) * step, len(ye) - 1)]))

    @classmethod
    def from_levels(cls, z: Any, x_edges: np.ndarray, y_edges: np.ndarray, levels: Sequence[Sequence[Any]]) -> "MapPyramid":
        """A pyramid read when needed: `z` (the map) and every level's arrays give `[rows, cols]`
        (two slices) as numpy arrays, e.g. HDF5 datasets; `levels[k]` = (max, min, sum, count) of
        level k + 1 in the map's own order, as made by `map_levels`. A view reads only what it
        shows: about two blocks per pixel each way."""
        xe, ye = np.asarray(x_edges, dtype=float), np.asarray(y_edges, dtype=float)
        if tuple(z.shape) != (len(ye) - 1, len(xe) - 1):
            raise ReduceError(f"a map of {z.shape[0]}×{z.shape[1]} cells needs {z.shape[1] + 1} x edges and "
                              f"{z.shape[0] + 1} y edges, not {len(xe)} and {len(ye)}")
        fx, fy = not _monotonic(xe, "horizontal"), not _monotonic(ye, "vertical")

        def seen(a: Any) -> Any:                         # stored in increasing order from here on
            return _Flipped(a, fx, fy) if fx or fy else a

        def order(e: np.ndarray, flip: bool) -> np.ndarray:
            return e[::-1] if flip else e

        self = cls.__new__(cls)
        self.shape = tuple(z.shape)
        self.levels = [_Level(seen(z), seen(z), None, None, order(xe, fx), order(ye, fy))]
        for k, (vmax, vmin, vsum, count) in enumerate(levels, start=1):
            ny, nx = vmax.shape
            step = 2 ** k
            lxe = xe[np.minimum(np.arange(nx + 1) * step, len(xe) - 1)]
            lye = ye[np.minimum(np.arange(ny + 1) * step, len(ye) - 1)]
            self.levels.append(_Level(seen(vmax), seen(vmin), seen(vsum), seen(count), order(lxe, fx), order(lye, fy)))
        return self

    def raster(self, px_x_edges: Sequence[float], px_y_edges: Sequence[float], stat: str = "max") -> Raster:
        """The map as seen through a plot area whose pixel boundaries are at these data values
        (W+1 x edges left to right, H+1 y edges bottom to top, both increasing).

        Each pixel gets the `stat` of the cells it covers; a pixel smaller than a cell gets the
        cell under its centre. Blocks from the pyramid are used where a pixel covers many cells.
        """
        if stat not in STATS:
            raise ReduceError(f"unknown reduction {stat!r}; use one of {', '.join(STATS)}")
        pxe, pye = np.asarray(px_x_edges, dtype=float), np.asarray(px_y_edges, dtype=float)
        if len(pxe) < 2 or len(pye) < 2 or np.any(np.diff(pxe) <= 0) or np.any(np.diff(pye) <= 0):
            raise ReduceError("pixel edges must be increasing, at least one pixel each way")
        full = self.levels[0]
        cx = _cells_in(full.xe, pxe[0], pxe[-1]) / (len(pxe) - 1)
        cy = _cells_in(full.ye, pye[0], pye[-1]) / (len(pye) - 1)
        level = int(np.clip(np.floor(np.log2(max(min(cx, cy), 1))), 0, len(self.levels) - 1))
        lv = self.levels[level]
        x0, x1, xa, xb = _ranges(lv.xe, pxe)
        y0, y1, ya, yb = _ranges(lv.ye, pye)
        image = np.full((len(pye) - 1, len(pxe) - 1), np.nan)
        if x0 > x1 or y0 > y1:                          # the view shows none of the map
            return Raster(image, level, (cx, cy), stat)
        rows, cols = slice(y0, y1 + 1), slice(x0, x1 + 1)
        if stat == "mean":
            if lv.sum is None:                           # level 0: from the visible cells
                part = lv.max[rows, cols]
                vsum, count = np.nan_to_num(part), np.isfinite(part).astype(np.int32)
            else:
                vsum, count = lv.sum[rows, cols], lv.count[rows, cols]
            s = _reduce2d(vsum, np.add, 0.0, xa - x0, xb - x0, ya - y0, yb - y0)
            n = _reduce2d(count, np.add, 0, xa - x0, xb - x0, ya - y0, yb - y0)
            with np.errstate(invalid="ignore", divide="ignore"):
                image = np.where(n > 0, s / np.maximum(n, 1), np.nan)
        else:
            src = (lv.max if stat == "max" else lv.min)[rows, cols].astype(float)
            image = _reduce2d(src, np.fmax if stat == "max" else np.fmin, np.nan,
                              xa - x0, xb - x0, ya - y0, yb - y0)
        empty = (xa < 0)[None, :] | (ya < 0)[:, None]
        image[empty] = np.nan
        return Raster(image, level, (cx, cy), stat)


class _Flipped:
    """A 2-D array-like seen with its columns (fx) and/or rows (fy) reversed; takes [rows, cols]
    as two slices (what MapPyramid.raster asks)."""

    def __init__(self, a: Any, fx: bool, fy: bool):
        self.a, self.fx, self.fy = a, fx, fy
        self.shape = tuple(a.shape)

    def __getitem__(self, key: Tuple[slice, slice]) -> np.ndarray:
        rows, cols = key
        r = _flip_slice(rows, self.shape[0]) if self.fy else rows
        c = _flip_slice(cols, self.shape[1]) if self.fx else cols
        part = np.asarray(self.a[r, c])
        return part[::-1 if self.fy else 1, ::-1 if self.fx else 1]


def _flip_slice(s: slice, n: int) -> slice:
    start, stop, step = s.indices(n)
    if step != 1:
        raise ReduceError("a flipped map takes ranges of rows and columns")
    stop = max(start, stop)
    return slice(n - stop, n - start)


def map_levels(read_rows: Callable[[int, int], np.ndarray], shape: Tuple[int, int],
               store: Callable[[int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray], None],
               load: Callable[[int, int, int], Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
               budget: int, smallest: int = 64, progress: Optional[Callable[[float], None]] = None) -> int:
    """Make levels 1, 2, … of a map's pyramid (as MapPyramid does) without holding the map:
    strips of rows are read one at a time, each made into its part of as many levels as fit.

    `read_rows(r0, r1)`: rows r0 … r1-1 of the map (as drawn: NaN for missing cells).
    `store(level, r0, max, min, sum, count)`: keep these rows of a level, from row r0.
    `load(level, r0, r1)`: rows of a level stored before, as (max, min, sum, count): the next
    levels are made from it when the first strips couldn't hold them all.
    `budget`: bytes a strip and its work may take. `progress(fraction)` is called after each
    strip of the map (it may raise to stop). Returns the number of levels made."""
    ny, nx = shape
    sizes = [(ny, nx)]
    while max(sizes[-1]) > smallest:
        h, w = sizes[-1]
        sizes.append(((h + 1) // 2, (w + 1) // 2))
    top = len(sizes) - 1
    done = 0
    while done < top:
        h, w = sizes[done]
        per_row = w * 40                               # the strip as float, its four sums, temporaries
        most = max(int(np.log2(max(budget // per_row, 1))), 0)
        if most < 1:
            raise ReduceError(f"two rows of {w} cells don't fit in the memory available; "
                              "free some memory or set a larger maximum in Settings")
        last = min(done + most, top)
        rows = 2 ** (last - done)
        for r0 in range(0, h, rows):
            r1 = min(r0 + rows, h)
            if done == 0:
                z = np.asarray(read_rows(r0, r1), dtype=float)
                vmax = vmin = z
                vsum, count = np.nan_to_num(z), np.isfinite(z).astype(np.int32)
            else:
                vmax, vmin, vsum, count = load(done, r0, r1)
            for k in range(done + 1, last + 1):
                vmax = _halve(vmax, np.nan, np.fmax).astype(np.float32)
                vmin = _halve(vmin, np.nan, np.fmin).astype(np.float32)
                vsum = _halve(vsum, 0.0, np.add)
                count = _halve(count, 0, np.add)
                store(k, r0 >> (k - done), vmax, vmin, vsum, count)
            if done == 0 and progress is not None:
                progress(r1 / h)
        done = last
    return top


def _cells_in(edges: np.ndarray, lo: float, hi: float) -> float:
    """How many cells (fractionally) lie between lo and hi."""
    idx = np.interp([lo, hi], edges, np.arange(len(edges)), left=0, right=len(edges) - 1)
    return float(idx[1] - idx[0])


def _ranges(edges: np.ndarray, pix: np.ndarray):
    """For each pixel (between consecutive `pix` values): the first and last cell it shows.

    A pixel narrower than the cells there shows the one cell under its centre; a wider pixel shows
    every cell it overlaps. Pixels outside the map get -1. Also returns the overall first and last
    cell used (first > last when none)."""
    n = len(edges) - 1
    lo, hi = pix[:-1], pix[1:]
    centre = np.searchsorted(edges, (lo + hi) / 2, side="right") - 1
    first = np.searchsorted(edges, lo, side="right") - 1
    last = np.searchsorted(edges, hi, side="left") - 1
    first, last = np.clip(first, 0, n - 1), np.clip(last, 0, n - 1)
    # A pixel narrower than the cell under its centre shows that cell (so cell borders stay sharp
    # when zoomed in); a wider one shows every cell it overlaps.
    c = np.clip(centre, 0, n - 1)
    narrow = (hi - lo) < (edges[c + 1] - edges[c])
    a = np.where(narrow, centre, first)
    b = np.where(narrow, centre, last)
    outside = (hi <= edges[0]) | (lo >= edges[-1]) | (narrow & ((centre < 0) | (centre >= n)))
    a, b = np.where(outside, -1, a), np.where(outside, -1, b)
    used = a >= 0
    if not used.any():
        return 1, 0, a, b
    return int(a[used].min()), int(b[used].max()), a, b


def _reduce1d(arr: np.ndarray, ufunc, fill, a: np.ndarray, b: np.ndarray, axis: int) -> np.ndarray:
    """ufunc over arr[a[k] : b[k]+1] along `axis`, for every pixel k (-1: no cell; those results
    are discarded by the caller).

    Pixels come in order, so the ranges only overlap where two pixels share the cell on their
    border: pixel k is the segment from a[k] up to the next pixel's first cell, plus its last
    cell b[k] when the next pixel starts there too."""
    n = arr.shape[axis]
    out = np.full(_shape_with(arr.shape, axis, len(a)), fill, dtype=np.result_type(arr, type(fill)))
    used = np.flatnonzero(a >= 0)        # the pixels over the map: one run (the map is one piece)
    if not used.size:
        return out
    starts, ends = a[used], b[used]
    segments = ufunc.reduceat(arr, starts, axis=axis)
    nxt = np.append(starts[1:], n)
    # The last cell is the next pixel's first. (When both pixels start at the same cell, reduceat
    # already returned just that cell.)
    shared = (ends >= nxt) & (nxt > starts)
    if shared.any():
        extra = np.take(arr, np.minimum(ends, n - 1), axis=axis)
        mask = _expand(shared, arr.ndim, axis)
        segments = np.where(mask, ufunc(segments, extra), segments)
    # Rare, with uneven cells: the next pixel shows only the cell under its centre and skips a
    # narrow cell, which the segment would wrongly include. Those pixels are done one by one.
    for k in np.flatnonzero(nxt > ends + 1):
        part = np.take(arr, np.arange(starts[k], ends[k] + 1), axis=axis)
        idx = [slice(None)] * arr.ndim
        idx[axis] = k
        segments[tuple(idx)] = ufunc.reduce(part, axis=axis)
    idx = [slice(None)] * arr.ndim
    idx[axis] = used
    out[tuple(idx)] = segments
    return out


def _shape_with(shape, axis, size):
    s = list(shape)
    s[axis] = size
    return tuple(s)


def _expand(v: np.ndarray, ndim: int, axis: int) -> np.ndarray:
    s = [1] * ndim
    s[axis] = len(v)
    return v.reshape(s)


def _reduce2d(arr, ufunc, fill, xa, xb, ya, yb) -> np.ndarray:
    cols = _reduce1d(arr, ufunc, fill, xa, xb, axis=1)
    return _reduce1d(cols, ufunc, fill, ya, yb, axis=0)


def curve_minmax(x: np.ndarray, ys: Sequence[np.ndarray], px_x_edges: Sequence[float],
                 pass_through: float = 2.0) -> Tuple[List[Tuple[np.ndarray, np.ndarray]], bool]:
    """Curves reduced to the pixel columns of a plot area (W+1 increasing x edges).

    Returns one (x, y) per curve and whether anything was reduced. Each pixel column with more
    than one point keeps its smallest and largest value (drawn at the column's centre), so spikes
    stay; a column with only missing points breaks the line, as the gap does. When a curve has at
    most `pass_through` points per column in view, its stored points in view (and one beyond each
    side) are returned unchanged. `x` must be sorted (increasing or decreasing).
    """
    x = np.asarray(x, dtype=float)
    pxe = np.asarray(px_x_edges, dtype=float)
    w = len(pxe) - 1
    if x.size > 1 and not (np.all(np.diff(x) >= 0) or np.all(np.diff(x) <= 0)):
        return [(x, np.asarray(y, dtype=float)) for y in ys], False     # unsorted x: drawn as stored
    flip = x.size > 1 and x[0] > x[-1]
    xs = x[::-1] if flip else x
    i0 = max(int(np.searchsorted(xs, pxe[0], side="left")) - 1, 0)
    i1 = min(int(np.searchsorted(xs, pxe[-1], side="right")) + 1, xs.size)
    out, reduced = [], False
    if i1 - i0 <= pass_through * w:
        for y in ys:
            yv = np.asarray(y, dtype=float)
            yv = yv[::-1] if flip else yv
            out.append((xs[i0:i1], yv[i0:i1]))
        return out, False
    xv = xs[i0:i1]
    col = np.clip(np.searchsorted(pxe, xv, side="right") - 1, -1, w)
    starts = np.flatnonzero(np.r_[True, col[1:] != col[:-1]])
    ids = col[starts]
    centres = np.where((ids >= 0) & (ids < w), (pxe[np.clip(ids, 0, w - 1)] + pxe[np.clip(ids + 1, 0, w)]) / 2,
                       xv[starts])                     # the points just outside keep their own x
    xx = np.repeat(centres, 2)
    # all curves at once (one row each): one reduceat instead of one per curve
    yv = np.stack([np.asarray(y, dtype=float) for y in ys])
    yv = (yv[:, ::-1] if flip else yv)[:, i0:i1]
    lo = np.fmin.reduceat(yv, starts, axis=1)
    hi = np.fmax.reduceat(yv, starts, axis=1)
    yy = np.empty((len(ys), 2 * len(starts)))
    yy[:, 0::2], yy[:, 1::2] = lo, hi
    out = [(xx, row) for row in yy]
    return out, len(out) > 0


def nearest_point(x: np.ndarray, ys: Sequence[np.ndarray], to_px, click: Tuple[float, float],
                  max_px: float = 12.0) -> Optional[Tuple[int, int]]:
    """The stored point nearest to a click, in screen pixels: (curve, index), or None when no
    point is within `max_px`. `to_px(x, y)` maps data to pixels (arrays in, (px, py) out)."""
    x = np.asarray(x, dtype=float)
    best, best_d = None, max_px ** 2
    for k, y in enumerate(ys):
        px, py = to_px(x, np.asarray(y, dtype=float))
        d = (px - click[0]) ** 2 + (py - click[1]) ** 2
        d = np.where(np.isfinite(d), d, np.inf)
        i = int(np.argmin(d))
        if d[i] < best_d:
            best, best_d = (k, i), float(d[i])
    return best


def thin_in_order(x: np.ndarray, y: np.ndarray, n_out: int) -> Tuple[np.ndarray, np.ndarray]:
    """A curve whose x isn't sorted (e.g. one value against another), cut to about `n_out` points
    in stored order: each block of consecutive points keeps its lowest and highest y, in the order
    they were stored. For drawing only; picks read the full data."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = y.size
    block = max(1, -(-2 * n // max(n_out, 2)))         # ceil(n / (n_out / 2))
    if block == 1:
        return x, y
    pad = (-n) % block
    yp = np.concatenate([y, np.full(pad, np.nan)]).reshape(-1, block)
    ok = np.isfinite(yp).any(axis=1)
    lo = np.where(ok, np.nanargmin(np.where(np.isfinite(yp), yp, np.inf), axis=1), 0)
    hi = np.where(ok, np.nanargmax(np.where(np.isfinite(yp), yp, -np.inf), axis=1), 0)
    first, second = np.minimum(lo, hi), np.maximum(lo, hi)
    starts = np.arange(yp.shape[0]) * block
    idx = np.stack([starts + first, starts + second], axis=1).ravel()
    idx = idx[np.repeat(ok, 2)]
    return x[idx], y[idx]


class CurvePyramid:
    """Curves that share one sorted x, with the min and max of blocks of 2, 4, 8, ... points made
    once, so reducing a view to pixel columns reads about two blocks per column instead of every
    point (curve_minmax on 1000 curves of 10 000 points: ~50 ms; from the pyramid: a few ms).

    `x` increasing (n,), `ys` (curves, n). Blocks never mix points of different columns by more
    than a block, and a block is at most half a pixel column wide, so peaks stay in their column
    or the next (as with MapPyramid); zoomed in, the stored points are used as they are."""

    def __init__(self, x: np.ndarray, ys: np.ndarray, smallest: int = 256):
        x = np.asarray(x, dtype=float)
        y = np.atleast_2d(np.asarray(ys, dtype=float))
        self.x, self.y = x, y
        self.levels: List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []   # x0, x1, lo, hi
        x0, x1, lo, hi = x, x, y, y
        while x0.size > smallest:
            n = x0.size // 2 * 2                          # an odd last point stays a block of its own
            x0 = np.concatenate([x0[:n:2], x0[n:]])
            x1 = np.concatenate([x1[1:n:2], x1[n:]])
            lo = np.concatenate([np.fmin(lo[:, :n:2], lo[:, 1:n:2]), lo[:, n:]], axis=1)
            hi = np.concatenate([np.fmax(hi[:, :n:2], hi[:, 1:n:2]), hi[:, n:]], axis=1)
            self.levels.append((x0, x1, lo, hi))

    def spans(self, px_x_edges: Sequence[float]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """For each curve and pixel column: its lowest and highest value there, (curves, columns)
        each (NaN where it has none); None when zoomed in so far that the stored points should be
        drawn instead (see minmax)."""
        pxe = np.asarray(px_x_edges, dtype=float)
        w = len(pxe) - 1
        found = self._blocks(pxe)
        if found is None:
            return None
        cols, lo_c, hi_c = found
        lo = np.full((lo_c.shape[0], w), np.nan)
        hi = np.full((lo_c.shape[0], w), np.nan)
        inside = (cols >= 0) & (cols < w)
        lo[:, cols[inside]], hi[:, cols[inside]] = lo_c[:, inside], hi_c[:, inside]
        return lo, hi

    def _blocks(self, pxe: np.ndarray):
        """The pyramid level for these pixel columns: (column of each group, min, max), or None."""
        w = len(pxe) - 1
        visible = int(np.searchsorted(self.x, pxe[-1], side="right") - np.searchsorted(self.x, pxe[0], side="left"))
        level = None
        for i in range(len(self.levels)):
            if visible / 2 ** (i + 1) >= 2 * w:
                level = i
        if level is None:
            return None
        x0, x1, lo, hi = self.levels[level]
        mid = (x0 + x1) / 2
        i0 = max(int(np.searchsorted(mid, pxe[0], side="left")) - 1, 0)
        i1 = min(int(np.searchsorted(mid, pxe[-1], side="right")) + 1, mid.size)
        col = np.clip(np.searchsorted(pxe, mid[i0:i1], side="right") - 1, -1, w)
        starts = np.flatnonzero(np.r_[True, col[1:] != col[:-1]])
        return col[starts], np.fmin.reduceat(lo[:, i0:i1], starts, axis=1), np.fmax.reduceat(hi[:, i0:i1], starts, axis=1)

    def minmax(self, px_x_edges: Sequence[float]) -> Tuple[List[Tuple[np.ndarray, np.ndarray]], bool]:
        """As curve_minmax(x, ys, px_x_edges), from the coarsest level with at least two blocks per
        pixel column in view."""
        pxe = np.asarray(px_x_edges, dtype=float)
        w = len(pxe) - 1
        visible = int(np.searchsorted(self.x, pxe[-1], side="right") - np.searchsorted(self.x, pxe[0], side="left"))
        level = None
        for i, (x0, x1, lo, hi) in enumerate(self.levels):
            if visible / 2 ** (i + 1) >= 2 * w:
                level = i
        if level is None:
            return curve_minmax(self.x, list(self.y), pxe)
        x0, x1, lo, hi = self.levels[level]
        mid = (x0 + x1) / 2                               # a block belongs to the column of its middle
        i0 = max(int(np.searchsorted(mid, pxe[0], side="left")) - 1, 0)
        i1 = min(int(np.searchsorted(mid, pxe[-1], side="right")) + 1, mid.size)
        col = np.clip(np.searchsorted(pxe, mid[i0:i1], side="right") - 1, -1, w)
        starts = np.flatnonzero(np.r_[True, col[1:] != col[:-1]])
        ids = col[starts]
        centres = np.where((ids >= 0) & (ids < w), (pxe[np.clip(ids, 0, w - 1)] + pxe[np.clip(ids + 1, 0, w)]) / 2,
                           mid[i0:i1][starts])
        xx = np.repeat(centres, 2)
        lo_c = np.fmin.reduceat(lo[:, i0:i1], starts, axis=1)
        hi_c = np.fmax.reduceat(hi[:, i0:i1], starts, axis=1)
        yy = np.empty((lo.shape[0], 2 * len(starts)))
        yy[:, 0::2], yy[:, 1::2] = lo_c, hi_c
        return [(xx, row) for row in yy], True
