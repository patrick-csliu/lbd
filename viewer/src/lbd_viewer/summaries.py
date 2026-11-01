"""Maps bigger than the memory available (plan 6d, B): summarised once, kept on disk.

A map the viewer can't hold (memory.py says how much it may use) is never read whole:

- `BigMap` stands for its numbers (Explore's `model.z`): indexing reads only that part from the
  file — a cell for a click or a cursor, a row or column for a cut, the cells in view when zoomed
  in. Reading it whole is refused with a message (operations, choosing rows).
- Its zoom summary (the map's pyramid: max, min, sum and count of blocks of 2×2, 4×4, … cells,
  `lbd.plot.reduce.map_levels`) is made by reading the file strip by strip, once, and kept in
  `SummaryCache`: one HDF5 file per map in LBD's local data folder (`catalog_dir/summaries/`).
  A view then reads about two blocks per pixel each way from it.
- Making it takes a while for a big file: its progress is shown, and it can be cancelled
  (`Job`, `/api/summaries`). The cache keeps the most recently used summaries up to the size set
  in Settings (20 GB by default), and can be emptied.

A summary is found again by the file, its version (changes when the file is written), the value,
the axes drawn, the slider positions and the complex mode.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import h5py
import numpy as np

from lbd.plot import render as rnd
from lbd.plot.reduce import MapPyramid, ReduceError, map_levels

from . import memory

# What a map, its drawn numbers and an in-memory pyramid take per cell: a map whose cells need more
# than the memory available is summarised instead.
BYTES_PER_CELL = 24
MIN_BUDGET = 16 << 20         # the strips read while summarising take at least this


def _explore_error(message: str) -> Exception:
    from .explore import ExploreError                   # explore imports this module

    return ExploreError(message)


class Cancelled(Exception):
    """Making a summary was cancelled (`Job.cancel`)."""


class Job:
    """A summary being made: how far it is (0 … 1), and a way to cancel it."""

    def __init__(self, path: str, what: str):
        self.path, self.what = path, what
        self.fraction = 0.0
        self.cancelled = False
        self.started = time.monotonic()

    def step(self, fraction: float) -> None:
        if self.cancelled:
            raise Cancelled()
        self.fraction = fraction

    def cancel(self) -> None:
        self.cancelled = True

    def info(self) -> Dict[str, Any]:
        return {"path": self.path, "what": self.what, "fraction": round(self.fraction, 4),
                "seconds": round(time.monotonic() - self.started, 1)}


class BigMap:
    """A map too big to read whole, as drawn (complex mode applied, times `factor`): rows along
    y, columns along x. `m[j, i]`, `m[j, :]`, `m[:, i]`, `m[np.ix_(rows, cols)]` read only that
    part of the file; `np.asarray(m)` is refused. `range()`: its lowest and highest number."""

    ndim = 2
    dtype = np.dtype(float)

    def __init__(self, value: Any, x: str, y: str, index: Dict[str, int], mode: str,
                 factor: float = 1.0, span: Tuple[float, float] = (np.nan, np.nan)):
        self.value, self.x, self.y, self.index, self.mode = value, x, y, dict(index), mode
        self.factor, self._span = float(factor), span
        self.shape = (value.shape[value.axes.index(y)], value.shape[value.axes.index(x)])
        self.pyramid_levels: Optional[List[Tuple[Any, Any, Any, Any]]] = None    # set by SummaryCache
        self._file: Optional[h5py.File] = None                                   # the summary, open

    def __mul__(self, f: float) -> "BigMap":
        out = BigMap(self.value, self.x, self.y, self.index, self.mode, self.factor * f, self._span)
        out.pyramid_levels, out._file = self.pyramid_levels, self._file
        return out

    def close(self) -> None:
        """Let go of the summary's file (a closed view; on Windows it can then be removed)."""
        if self._file is not None:
            self._file.close()
            self._file = None

    __rmul__ = __mul__

    def range(self) -> Tuple[float, float]:
        lo, hi = self._span
        return lo * self.factor, hi * self.factor

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        raise _explore_error(
            f"this map has {self.shape[0]:,} × {self.shape[1]:,} cells, more than the memory available; it is shown "
            "from its summary, and this needs all of it at once. Turn operations and row choices off, or read "
            "the file in a script with lbd.open")

    def rows(self, r0: int, r1: int) -> np.ndarray:
        """Rows r0 … r1-1, all columns, as drawn but not scaled (for making the summary)."""
        return self._read(slice(r0, r1), slice(0, self.shape[1]), scaled=False)

    def __getitem__(self, key: Any) -> Any:
        if not isinstance(key, tuple) or len(key) != 2:
            raise IndexError("a big map takes [rows, columns]")
        boxes, picks = [], []                            # the box read, then what is taken from it
        for k, n in zip(key, self.shape):
            if isinstance(k, (int, np.integer)):
                i = int(k) + n if k < 0 else int(k)
                if not 0 <= i < n:
                    raise IndexError(f"index {int(k)} is out of bounds for {n} cells")
                boxes.append(slice(i, i + 1))
                picks.append(0)
                continue
            if isinstance(k, slice):
                start, stop, step = k.indices(n)
                if step == 1:
                    boxes.append(slice(start, max(start, stop)))
                    picks.append(slice(None))
                    continue
                k = np.arange(start, stop, step)
            idx = np.asarray(k).ravel().astype(np.int64)     # an index list (or np.ix_'s)
            idx = np.where(idx < 0, idx + n, idx)
            if idx.size and (idx.min() < 0 or idx.max() >= n):
                raise IndexError(f"an index is out of bounds for {n} cells")
            lo = int(idx.min()) if idx.size else 0
            boxes.append(slice(lo, int(idx.max()) + 1 if idx.size else lo))
            picks.append(idx - lo)
        part = self._read(*boxes)
        if all(isinstance(p, np.ndarray) for p in picks):        # rows × columns (np.ix_)
            return part[np.ix_(*picks)]
        out = part[picks[0], picks[1]]
        return float(out) if np.ndim(out) == 0 else out

    def _read(self, rows: slice, cols: slice, scaled: bool = True) -> np.ndarray:
        if self.mode in ("phase_unwrap", "phase_deg_unwrap"):     # a phase is unwrapped along the whole row
            whole_cols, keep = slice(0, self.shape[1]), cols
        else:
            whole_cols, keep = cols, None
        n = max(rows.stop - rows.start, 0) * max(whole_cols.stop - whole_cols.start, 0)
        if n * BYTES_PER_CELL > max(memory.shared().memory.room(), MIN_BUDGET):
            raise _explore_error(
                f"this needs {n:,} cells of the map read at once, more than the memory available; zoom in, "
                "or choose a smaller area")
        v = self.value
        idx = tuple(rows if a == self.y else whole_cols if a == self.x else self.index.get(a, 0) for a in v.axes)
        data = v.data
        if not scaled and isinstance(data, memory.Cached):  # strips for the summary: read once, not kept
            data = data._data
        raw = np.asarray(data[idx] if hasattr(data, "_source") else np.asarray(data)[idx])
        if v.axes.index(self.x) < v.axes.index(self.y):
            raw = raw.T
        with warnings.catch_warnings():                 # said once, when the summary was made
            warnings.simplefilter("ignore", rnd.RenderWarning)
            z, _, _ = rnd.apply_complex(raw, "", "", self.mode, axis=1)
        z = np.asarray(z, dtype=float)
        if keep is not None:
            z = z[:, keep]
        return z * self.factor if scaled else z


class _Scaled:
    """An array-like read through `[...]`, times a factor (a summary is kept in stored units)."""

    def __init__(self, a: Any, factor: float):
        self.a, self.factor = a, factor
        self.shape = tuple(a.shape)

    def __getitem__(self, key: Any) -> np.ndarray:
        return np.asarray(self.a[key], dtype=float) * self.factor


def pyramid(big: BigMap, x_edges: np.ndarray, y_edges: np.ndarray) -> MapPyramid:
    """The pyramid of a summarised map, reading its levels from the summary and, zoomed in, the
    cells from the file."""
    if big.pyramid_levels is None:
        raise _explore_error("this map has no summary yet")
    f = big.factor
    # counts read as numbers (a pixel adds up many blocks: more than 16 bits hold)
    levels = [(_Scaled(a, f), _Scaled(b, f), _Scaled(s, f), _Scaled(c, 1.0)) for a, b, s, c in big.pyramid_levels]
    return MapPyramid.from_levels(big, x_edges, y_edges, levels)


def histogram_cells(big: BigMap, most: int = 4_000_000) -> Tuple[np.ndarray, int]:
    """For the contrast histogram of a summarised map: the mean of each block of the finest
    level with at most `most` blocks (scaled), and how many cells they stand for. Approximate."""
    if not big.pyramid_levels:
        raise _explore_error("this map has no summary yet")
    for vmax, vmin, vsum, count in big.pyramid_levels:
        if int(np.prod(vmax.shape)) <= most:
            s, c = np.asarray(vsum[...], dtype=float), np.asarray(count[...])
            ok = c > 0
            return s[ok] / c[ok] * big.factor, int(c.sum())
    raise _explore_error("this map's summary is too large for a histogram")


class SummaryCache:
    """The summaries kept on disk (one HDF5 file each), most recently used kept, up to `limit()`
    bytes; and the summaries being made (`jobs`, by file)."""

    def __init__(self, folder: Path, limit: Callable[[], int]):
        self.folder = Path(folder)
        self.limit = limit
        self.jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._making: Dict[str, threading.Lock] = {}

    # -- finding or making one ---------------------------------------------------------------

    @staticmethod
    def key(path: Any, version: str, big: BigMap) -> str:
        text = json.dumps([str(Path(path).resolve()), version, big.value.name, big.y, big.x,
                           sorted(big.index.items()), big.mode])
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def summarise(self, path: Any, version: str, big: BigMap) -> BigMap:
        """`big` with its summary: found on disk, or made now (reading the file strip by strip;
        progress in `jobs[path]`, `Cancelled` if cancelled)."""
        key = self.key(path, version, big)
        with self._lock:
            making = self._making.setdefault(key, threading.Lock())
        with making:                                     # another tab making the same one: wait for it
            found = self._open(key)
            if found is None:
                self._make(key, str(path), big)
                found = self._open(key)
                if found is None:
                    raise _explore_error("the summary of this map was removed while it was made; open it again")
        f, levels, span = found
        big.pyramid_levels, big._span = levels, span
        big._file = f                                   # kept open while the map is shown
        return big

    def _open(self, key: str):
        p = self.folder / f"{key}.h5"
        if not p.exists():
            return None
        f = None
        try:
            f = h5py.File(p, "r")
            top = int(f.attrs["levels"])
            levels = [tuple(f[f"L{k}/{n}"] for n in ("max", "min", "sum", "count")) for k in range(1, top + 1)]
            span = (float(f.attrs["lo"]), float(f.attrs["hi"]))
        except (OSError, KeyError) as e:                # a damaged or old entry: made again
            if f is not None:
                f.close()
            self._remove(p)
            if p.exists():
                raise _explore_error(f"the summary {p} can't be read ({e}) or removed; delete it, "
                                     "or empty the summaries in Settings") from None
            return None
        try:
            os.utime(p)                                  # recently used: kept longest
        except OSError:
            pass
        return f, levels, span

    def _make(self, key: str, path: str, big: BigMap) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        part = self.folder / f"{key}.part"
        job = Job(path, f"summarising {big.value.name} ({big.shape[0]:,} × {big.shape[1]:,} cells)")
        with self._lock:
            self.jobs[path] = job
        said: List[str] = []
        try:
            with h5py.File(part, "w") as f, warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", rnd.RenderWarning)
                ny, nx = big.shape

                def store(k, r0, *arrays):
                    # kept smaller than made: sums as float32 (a mean to 7 digits), counts as
                    # 16 bits while a block can't have more cells than that
                    vmax, vmin, vsum, count = arrays
                    arrays = (vmax, vmin, vsum.astype(np.float32),
                              count.astype(np.uint16 if 4 ** k < 1 << 16 else np.int32))
                    g = f.require_group(f"L{k}")
                    for name, a in zip(("max", "min", "sum", "count"), arrays):
                        if name not in g:
                            n = (-(-ny // 2 ** k), -(-nx // 2 ** k))
                            g.create_dataset(name, shape=n, dtype=a.dtype, chunks=(min(n[0], 64), min(n[1], 1024)))
                        g[name][r0:r0 + a.shape[0]] = a

                def load(k, r0, r1):
                    g = f[f"L{k}"]                       # sums and counts as made, to add them up
                    return (g["max"][r0:r1], g["min"][r0:r1], g["sum"][r0:r1].astype(float),
                            g["count"][r0:r1].astype(np.int32))

                budget = max(memory.shared().memory.room() // 2, MIN_BUDGET)
                try:
                    top = map_levels(big.rows, big.shape, store, load, budget, progress=job.step)
                except ReduceError as e:
                    raise _explore_error(str(e)) from None
                if top == 0:
                    raise _explore_error("this map is small enough to show without a summary")
                g = f[f"L{top}"]
                vmax, vmin = g["max"][...], g["min"][...]
                if np.isfinite(vmax).any():
                    lo, hi = float(np.nanmin(vmin)), float(np.nanmax(vmax))
                else:                                    # no cell has a number
                    lo = hi = np.nan
                f.attrs.update(levels=top, lo=lo, hi=hi)
                said = sorted({str(w.message) for w in caught if issubclass(w.category, rnd.RenderWarning)})
            os.replace(part, self.folder / f"{key}.h5")
        except Cancelled:
            self._remove(part)
            raise _explore_error("summarising this large map was cancelled") from None
        except BaseException:
            self._remove(part)
            raise
        finally:
            with self._lock:
                if self.jobs.get(path) is job:
                    del self.jobs[path]
        for message in said:                             # each said once, not once per strip
            warnings.warn(message, rnd.RenderWarning)
        self.trim()

    # -- size, trimming, emptying ------------------------------------------------------------

    def entries(self) -> List[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(self.folder.glob("*.h5"), key=lambda p: p.stat().st_mtime)     # oldest first

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.entries())

    def trim(self) -> None:
        """Remove the least recently used summaries while all of them take more than the limit
        (one in use, open in a view, stays)."""
        total = self.size()
        for p in self.entries()[:-1]:
            if total <= self.limit():
                break
            size = p.stat().st_size
            if self._remove(p):
                total -= size

    def empty(self) -> Dict[str, int]:
        """Remove every summary not in use now; returns {"removed": n, "kept": n in use}."""
        removed = kept = 0
        for p in self.entries():
            if self._remove(p):
                removed += 1
            else:
                kept += 1
        return {"removed": removed, "kept": kept}

    @staticmethod
    def _remove(p: Path) -> bool:
        try:
            p.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:                                  # open in a view (Windows): removed another time
            return False

    def progress(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [j.info() for j in self.jobs.values()]

    def cancel(self, path: str) -> bool:
        with self._lock:
            job = self.jobs.get(path)
        if job is None:
            return False
        job.cancel()
        return True


_shared: Dict[str, SummaryCache] = {}


def configure(folder: Path, limit_gb: Callable[[], float]) -> SummaryCache:
    """Set the viewer's summary cache up (server start)."""
    _shared["cache"] = SummaryCache(folder, lambda: int(limit_gb() * memory.GB))
    return _shared["cache"]


def shared() -> SummaryCache:
    if "cache" not in _shared:
        raise RuntimeError("the summary cache isn't set up (summaries.configure)")
    return _shared["cache"]


def too_big(shape: Sequence[int]) -> bool:
    """True when a map of this many cells doesn't fit in the memory available now (a map of at
    most 64 cells each way is its own summary: always shown whole). Outside the viewer's server
    (no summary cache set up: a script, the benchmark) maps are drawn whole, as asked."""
    if max(shape) <= 64 or "cache" not in _shared:
        return False
    return not memory.shared().memory.fits(int(np.prod(shape, dtype=np.int64)) * BYTES_PER_CELL)
