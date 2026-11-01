"""Maps and curves bigger than the memory available (plan 6d, B): summarised once, kept on disk.

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

Curves (`BigCurves`: the traces of one value along a sorted axis, each a `BigTrace`) work the
same way: their pyramid (each trace's min and max over blocks of 2, 4, 8, … points,
`lbd.plot.reduce.curve_levels`) is made reading stretches of points, and a view reads about four
blocks per pixel column, or the points in view when zoomed in.

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
from lbd.plot.reduce import CurvePyramid, MapPyramid, ReduceError, curve_levels, map_levels

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

    # -- its summary (SummaryCache)

    def key_parts(self) -> List[Any]:
        return ["map", self.value.name, self.y, self.x, sorted(self.index.items()), self.mode]

    def what(self) -> str:
        return f"summarising {self.value.name} ({self.shape[0]:,} × {self.shape[1]:,} cells)"

    def build(self, f: h5py.File, budget: int, progress: Callable[[float], None]) -> None:
        """Make the summary into the open file `f` (reading the map strip by strip)."""
        ny, nx = self.shape

        def store(k, r0, *arrays):
            # kept smaller than made: sums as float32 (a mean to 7 digits), counts as 16 bits
            # while a block can't have more cells than that
            vmax, vmin, vsum, count = arrays
            arrays = (vmax, vmin, vsum.astype(np.float32), count.astype(np.uint16 if 4 ** k < 1 << 16 else np.int32))
            g = f.require_group(f"L{k}")
            for name, a in zip(("max", "min", "sum", "count"), arrays):
                if name not in g:
                    n = (-(-ny // 2 ** k), -(-nx // 2 ** k))
                    g.create_dataset(name, shape=n, dtype=a.dtype, chunks=(min(n[0], 64), min(n[1], 1024)))
                g[name][r0:r0 + a.shape[0]] = a

        def load(k, r0, r1):
            g = f[f"L{k}"]                               # sums and counts as made, to add them up
            return (g["max"][r0:r1], g["min"][r0:r1], g["sum"][r0:r1].astype(float), g["count"][r0:r1].astype(np.int32))

        try:
            top = map_levels(self.rows, self.shape, store, load, budget, progress=progress)
        except ReduceError as e:
            raise _explore_error(str(e)) from None
        if top == 0:
            raise _explore_error("this map is small enough to show without a summary")
        g = f[f"L{top}"]
        vmax, vmin = g["max"][...], g["min"][...]
        if np.isfinite(vmax).any():
            lo, hi = float(np.nanmin(vmin)), float(np.nanmax(vmax))
        else:                                            # no cell has a number
            lo = hi = np.nan
        f.attrs.update(kind="map", levels=top, lo=lo, hi=hi)

    def attach(self, f: h5py.File) -> None:
        """Use the summary in the open file `f` (KeyError: not a summary of a map)."""
        if f.attrs["kind"] != "map":
            raise KeyError("not a map's summary")
        top = int(f.attrs["levels"])
        self.pyramid_levels = [tuple(f[f"L{k}/{n}"] for n in ("max", "min", "sum", "count")) for k in range(1, top + 1)]
        self._span = (float(f.attrs["lo"]), float(f.attrs["hi"]))
        self._file = f

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


class BigCurves:
    """Curves too big to read whole: the traces of one value along the axis `along` (sorted,
    increasing), one per position of the axis `series` (or one), as drawn (complex mode applied,
    times `factor`). `trace(k)` stands for one of them; `read(traces, points)` reads a part."""

    def __init__(self, value: Any, along: str, series: Optional[str], index: Dict[str, int], mode: str,
                 factor: float = 1.0):
        self.value, self.along, self.series, self.index, self.mode = value, along, series, dict(index), mode
        self.factor = float(factor)
        self.points = value.shape[value.axes.index(along)]
        self.traces = value.shape[value.axes.index(series)] if series else 1
        self.pyramid_levels: Optional[List[Tuple[Any, Any]]] = None     # (lo, hi) per level, set by attach
        self._ranges: Optional[np.ndarray] = None                      # (traces, 2): each one's lowest, highest
        self._file: Optional[h5py.File] = None

    def __mul__(self, f: float) -> "BigCurves":
        out = BigCurves(self.value, self.along, self.series, self.index, self.mode, self.factor * f)
        out.pyramid_levels, out._ranges, out._file = self.pyramid_levels, self._ranges, self._file
        return out

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def trace(self, k: int) -> "BigTrace":
        return BigTrace(self, k)

    def range(self, traces: Optional[Sequence[int]] = None) -> Tuple[float, float]:
        """The lowest and highest number of these traces (default all), exact (NaN when none)."""
        if self._ranges is None:
            return np.nan, np.nan
        r = self._ranges if traces is None else self._ranges[list(traces)]
        if not np.isfinite(r).any():
            return np.nan, np.nan
        return float(np.nanmin(r[:, 0])) * self.factor, float(np.nanmax(r[:, 1])) * self.factor

    def read(self, traces: Any, points: slice, scaled: bool = True) -> np.ndarray:
        """Traces (a slice or a list, increasing) × points (a slice), as drawn: (traces, points)."""
        k = list(range(self.traces)[traces]) if isinstance(traces, slice) else [int(t) for t in traces]
        n = len(k) * max(points.stop - points.start, 0)
        if n * BYTES_PER_CELL > max(memory.shared().memory.room(), MIN_BUDGET):
            raise _explore_error(f"this needs {n:,} points of the curves read at once, more than the memory "
                                 "available; zoom in, or choose fewer traces")
        v = self.value
        rows = slice(k[0], k[-1] + 1) if k else slice(0, 0)
        idx = tuple(points if a == self.along else rows if a == self.series else self.index.get(a, 0) for a in v.axes)
        data = v.data
        if not scaled and isinstance(data, memory.Cached):  # stretches for the summary: read once, not kept
            data = data._data
        raw = np.asarray(data[idx] if hasattr(data, "_source") else np.asarray(data)[idx])
        if not self.series:
            raw = raw[None, :]
        elif v.axes.index(self.along) < v.axes.index(self.series):
            raw = raw.T                                  # traces × points
        if len(k) != rows.stop - rows.start:             # a list with gaps: the box, then those traces
            raw = raw[[t - rows.start for t in k]]
        with warnings.catch_warnings():                  # said once, when the summary was made
            warnings.simplefilter("ignore", rnd.RenderWarning)
            y, _, _ = rnd.apply_complex(raw, "", "", self.mode, axis=1)
        y = np.asarray(y, dtype=float)
        return y * self.factor if scaled else y

    # -- its summary (SummaryCache)

    def key_parts(self) -> List[Any]:
        return ["curves", self.value.name, self.along, self.series, sorted(self.index.items()), self.mode]

    def what(self) -> str:
        return (f"summarising {self.value.name} ({self.traces:,} trace{'s' * (self.traces != 1)} of "
                f"{self.points:,} points)")

    def build(self, f: h5py.File, budget: int, progress: Callable[[float], None]) -> None:
        """Make the summary into the open file `f` (reading stretches of points of every trace)."""
        def store(k, b0, lo, hi):
            g = f.require_group(f"C{k}")
            for name, a in (("lo", lo), ("hi", hi)):
                if name not in g:
                    n = (self.traces, -(-self.points // 2 ** (k + 1)))
                    g.create_dataset(name, shape=n, dtype=np.float32, chunks=(min(n[0], 16), min(n[1], 4096)))
                g[name][:, b0:b0 + a.shape[1]] = a

        def load(k, b0, b1):
            g = f[f"C{k}"]
            return g["lo"][:, b0:b1].astype(float), g["hi"][:, b0:b1].astype(float)

        try:
            top = curve_levels(lambda i0, i1: self.read(slice(None), slice(i0, i1), scaled=False), self.points,
                               store, load, self.traces, budget, progress=progress)
        except ReduceError as e:
            raise _explore_error(str(e)) from None
        if top == 0:
            raise _explore_error("these curves are small enough to show without a summary")
        g = f[f"C{top - 1}"]
        with warnings.catch_warnings():                  # a trace without numbers: NaN, as meant
            warnings.simplefilter("ignore", RuntimeWarning)
            ranges = np.stack([np.nanmin(g["lo"][...], axis=1), np.nanmax(g["hi"][...], axis=1)], axis=1)
        f.create_dataset("ranges", data=ranges)
        f.attrs.update(kind="curves", levels=top)

    def attach(self, f: h5py.File) -> None:
        """Use the summary in the open file `f` (KeyError: not a summary of curves)."""
        if f.attrs["kind"] != "curves":
            raise KeyError("not the summary of curves")
        top = int(f.attrs["levels"])
        self.pyramid_levels = [(f[f"C{k}/lo"], f[f"C{k}/hi"]) for k in range(top)]
        self._ranges = f["ranges"][...]
        self._file = f


class BigTrace:
    """One trace of BigCurves: `t[i]`, `t[a:b]`, `t[index list]` read only that part of the
    file; `np.asarray(t)` is refused; `t * f` is the same trace scaled."""

    ndim = 1
    dtype = np.dtype(float)

    def __init__(self, curves: BigCurves, k: int):
        self.curves, self.k = curves, k
        self.shape = (curves.points,)
        self.size = curves.points

    def __len__(self) -> int:
        return self.curves.points

    def __mul__(self, f: float) -> "BigTrace":
        return BigTrace(self.curves * f, self.k)

    __rmul__ = __mul__

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        c = self.curves
        raise _explore_error(
            f"these curves have {c.traces:,} × {c.points:,} points, more than the memory available; they are shown "
            "from their summary, and this needs a whole trace at once. Turn operations off, or read the file "
            "in a script with lbd.open")

    def range(self) -> Tuple[float, float]:
        return self.curves.range([self.k])

    def __getitem__(self, key: Any) -> Any:
        n = self.curves.points
        if isinstance(key, (int, np.integer)):
            i = int(key) + n if key < 0 else int(key)
            if not 0 <= i < n:
                raise IndexError(f"index {int(key)} is out of bounds for {n} points")
            return float(self.curves.read([self.k], slice(i, i + 1))[0, 0])
        if isinstance(key, slice):
            start, stop, step = key.indices(n)
            if step == 1:
                return self.curves.read([self.k], slice(start, max(start, stop)))[0] if stop > start else np.empty(0)
            key = np.arange(start, stop, step)
        idx = np.asarray(key).astype(np.int64)
        if not idx.size:
            return np.empty(idx.shape)
        idx = np.where(idx < 0, idx + n, idx)
        lo, hi = int(idx.min()), int(idx.max()) + 1
        return self.curves.read([self.k], slice(lo, hi))[0][idx - lo]


def curve_pyramid(curves: BigCurves, x: np.ndarray) -> CurvePyramid:
    """The pyramid of summarised curves (x: the axis in plot units, increasing)."""
    if curves.pyramid_levels is None:
        raise _explore_error("these curves have no summary yet")
    f = curves.factor
    return CurvePyramid.from_levels(x, _AllTraces(curves),
                                    [(_Scaled(lo, f), _Scaled(hi, f)) for lo, hi in curves.pyramid_levels])


class _AllTraces:
    """BigCurves seen as an array (traces, points), read through `[:, i0:i1]`."""

    def __init__(self, curves: BigCurves):
        self.curves = curves
        self.shape = (curves.traces, curves.points)

    def __getitem__(self, key: Tuple[slice, slice]) -> np.ndarray:
        rows, points = key
        return self.curves.read(rows, points)


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
    def key(path: Any, version: str, big: Any) -> str:
        text = json.dumps([str(Path(path).resolve()), version] + big.key_parts())
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def summarise(self, path: Any, version: str, big: Any) -> Any:
        """`big` (BigMap or BigCurves) with its summary: found on disk, or made now (reading the
        file part by part; progress in `jobs[path]`, "cancelled" if cancelled)."""
        key = self.key(path, version, big)
        with self._lock:
            making = self._making.setdefault(key, threading.Lock())
        with making:                                     # another tab making the same one: wait for it
            if not self._open(key, big):
                self._make(key, str(path), big)
                if not self._open(key, big):
                    raise _explore_error("the summary was removed while it was made; open the file again")
        return big

    def _open(self, key: str, big: Any) -> bool:
        """Attach the summary `key` to `big` (kept open while it is shown); False if there is none."""
        p = self.folder / f"{key}.h5"
        if not p.exists():
            return False
        f = None
        try:
            f = h5py.File(p, "r")
            big.attach(f)
        except (OSError, KeyError) as e:                # a damaged or old entry: made again
            if f is not None:
                f.close()
            self._remove(p)
            if p.exists():
                raise _explore_error(f"the summary {p} can't be read ({e}) or removed; delete it, "
                                     "or empty the summaries in Settings") from None
            return False
        try:
            os.utime(p)                                  # recently used: kept longest
        except OSError:
            pass
        return True

    def _make(self, key: str, path: str, big: Any) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        part = self.folder / f"{key}.part"
        job = Job(path, big.what())
        with self._lock:
            self.jobs[path] = job
        said: List[str] = []
        try:
            with h5py.File(part, "w") as f, warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", rnd.RenderWarning)
                big.build(f, max(memory.shared().memory.room() // 2, MIN_BUDGET), job.step)
                said = sorted({str(w.message) for w in caught if issubclass(w.category, rnd.RenderWarning)})
            os.replace(part, self.folder / f"{key}.h5")
        except Cancelled:
            self._remove(part)
            raise _explore_error("summarising this large data was cancelled") from None
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
