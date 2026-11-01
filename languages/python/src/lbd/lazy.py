"""Reading only what is needed: `lbd.open` and the on-disk array (plan 6d).

`lbd.open(path)` reads a file's structure (header, axes, groups, each value's shape and type)
and gives every value an `OnDisk` array as its `data`: indexing it reads only that part of the
file (`v.data[3]`, `v.data[3, 100:200]`); `np.asarray(v.data)` reads it all. The file stays
open until `close()` (or the end of a `with` block).

`mode="r"` (the default) only reads. `mode="r+"` also writes: `write` puts data into the file at
points that exist, `save()` rewrites the description, metadata and saved view in place, and
`save(other)` copies the file piece by piece (no value is read whole).

A file being written (`.lbd.writing`) is read with sizes as they were at `open`, opening the
file for each read and closing it again (spec §7: readers don't keep it open). LBD Viewer reads
every file that way (`hold=False`), so it never holds one open.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

import h5py
import numpy as np

from .io import (
    WRITING_SUFFIX,
    Dataset,
    LBDError,
    PathLike,
    _attr_str,
    _check_style_name,
    _check_text,
    _matplotlib_version,
    _open,
    _plot_json,
    _read_structure,
    _reading,
    _same_target,
    _style_json,
    _validate_loaded,
    _warn,
    _write_meta,
)

MODES = ("r", "r+")


class _Source:
    """The file an opened dataset reads from: held open, or opened for each read (`hold=False`).
    Reads are serialised (one at a time), so threads can share an opened dataset."""

    def __init__(self, path: Path, mode: str, hold: bool):
        self.path, self.mode = path, mode
        self.writing = path.name.lower().endswith(WRITING_SUFFIX)
        self.hold = hold and not self.writing
        self.lock = threading.RLock()
        self.file: Optional[h5py.File] = None
        self.closed = False
        if self.hold:
            self.file = _open(path, mode)

    def run(self, fn):
        """`fn(file)` with the file open; refused once closed."""
        with self.lock:
            if self.closed:
                raise LBDError(f"{self.path.name} is closed: open it again, or use lbd.load")
            if self.file is not None:
                return fn(self.file)
            with _reading(self.path, self.writing) as f:
                return fn(f)

    def close(self) -> None:
        with self.lock:
            if self.file is not None:
                self.file.close()
                self.file = None
            self.closed = True


class OnDisk:
    """A value's data (or its `measured` mask) in the file: shape and type without reading;
    indexing reads only that part and gives a numpy array (a copy).

    Index with integers, slices, `...`, a list or array of indices, or a boolean array per
    dimension, as numpy. `np.asarray(x)` reads it all.
    """

    def __init__(self, source: _Source, where: str, shape: Tuple[int, ...], dtype: np.dtype, is_bool: bool):
        self._source, self._where = source, where
        self.shape = tuple(int(n) for n in shape)
        self.dtype = np.dtype(bool) if is_bool else np.dtype(dtype)
        self._is_bool = is_bool

    ndim = property(lambda self: len(self.shape))
    size = property(lambda self: int(np.prod(self.shape, dtype=np.int64)))
    nbytes = property(lambda self: self.size * self.dtype.itemsize)

    def __len__(self) -> int:
        if not self.shape:
            raise TypeError("len() of a 0-d value")
        return self.shape[0]

    def __repr__(self) -> str:
        return f"<lbd.OnDisk {self._where} {self.shape} {self.dtype} in {self._source.path.name}>"

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        arr = self[...]
        return arr if dtype is None else arr.astype(dtype, copy=False)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def __getitem__(self, key: Any) -> np.ndarray:
        boxes, picks = _plan(key, self.shape)

        def read(f: h5py.File) -> np.ndarray:
            ds = f[self._where]
            if any(b.stop <= b.start for b in boxes if isinstance(b, slice)):
                shape = [0 if isinstance(b, slice) and b.stop <= b.start else (b.stop - b.start)
                         for b in boxes if isinstance(b, slice)]
                return np.empty(shape, dtype=ds.dtype)
            return np.asarray(ds[tuple(boxes)] if boxes else ds[()])

        arr = self._source.run(read)
        if picks:                                   # steps, index lists, masks: taken from the box
            arr = arr[tuple(picks)]
        if self._is_bool:
            arr = arr.astype(bool)
        return np.array(arr, copy=True) if isinstance(arr, np.ndarray) else np.asarray(arr)

    def __setitem__(self, key: Any, value: Any) -> None:
        if self._source.mode != "r+":
            raise LBDError(f"{self._source.path.name} is opened read-only (mode='r'); open it with mode='r+' "
                           "to write into it, or use lbd.load")
        idx = _simple(key, self.shape)
        arr = np.asarray(value)
        arr = arr.astype(np.uint8) if self._is_bool else arr.astype(self.dtype, copy=False)   # as the value stores it

        def write(f: h5py.File) -> None:
            f[self._where][idx] = arr

        self._source.run(write)

    def _copy_to(self, group: h5py.Group, name: str) -> h5py.Dataset:
        """This dataset copied into another file, inside HDF5 (no value is read whole)."""
        def copy(f: h5py.File) -> h5py.Dataset:
            f.flush()                               # what write changed, on disk before it is copied
            f.copy(f[self._where], group, name=name)
            return group[name]

        return self._source.run(copy)


def _plan(key: Any, shape: Tuple[int, ...]) -> Tuple[List[Any], List[Any]]:
    """A numpy index → (a box to read: an int or a slice per dimension, h5py-style; what to
    take from the box afterwards: steps, index lists, masks), reading as little as possible."""
    if not isinstance(key, tuple):
        key = (key,)
    if not shape:
        if len(key) == 0 or (len(key) == 1 and key[0] is Ellipsis):
            return [], []
        raise IndexError("a 0-d value takes no index (use [()] or [...])")
    if sum(k is Ellipsis for k in key) > 1:
        raise IndexError("an index can only have a single ellipsis ('...')")
    if any(k is Ellipsis for k in key):
        i = next(j for j, k in enumerate(key) if k is Ellipsis)
        key = key[:i] + (slice(None),) * (len(shape) - len(key) + 1) + key[i + 1:]
    if len(key) > len(shape):
        raise IndexError(f"too many indices: {len(key)} for {len(shape)} dimension(s)")
    key = key + (slice(None),) * (len(shape) - len(key))
    boxes: List[Any] = []
    picks: List[Any] = []
    arrays = 0
    for k, n in zip(key, shape):
        if k is None:
            raise IndexError("np.newaxis isn't supported here; read the part, then add the axis")
        if isinstance(k, (int, np.integer)) and not isinstance(k, (bool, np.bool_)):
            i = int(k) + n if k < 0 else int(k)
            if not 0 <= i < n:
                raise IndexError(f"index {int(k)} is out of bounds for a dimension of size {n}")
            boxes.append(i)
            continue
        if isinstance(k, slice):
            start, stop, step = k.indices(n)
            if step > 0:
                lo, hi = start, max(start, stop)
                boxes.append(slice(lo, hi))
                picks.append(slice(None, None, step) if step != 1 else slice(None))
            else:                                   # backwards: read the span forwards, then reverse
                count = len(range(start, stop, step))
                lo = start + step * (count - 1) if count else 0
                boxes.append(slice(lo, lo + (start - lo + 1) if count else lo))
                picks.append(slice(None, None, step) if count else slice(0, 0))
            continue
        arr = np.asarray(k)
        if arr.dtype == bool:
            if arr.shape != (n,):
                raise IndexError(f"a boolean index must match its dimension ({n}), not {arr.shape}")
            arr = np.flatnonzero(arr)
        if arr.dtype.kind not in "iu" or arr.ndim != 1:
            raise IndexError(f"index {k!r}: give integers, slices, '...', or a 1-D list of indices per dimension")
        arr = np.where(arr < 0, arr + n, arr)
        if arr.size and (arr.min() < 0 or arr.max() >= n):
            raise IndexError(f"an index is out of bounds for a dimension of size {n}")
        arrays += 1
        if arrays > 1:
            raise IndexError("give a list of indices for one dimension at a time")
        lo = int(arr.min()) if arr.size else 0
        hi = int(arr.max()) + 1 if arr.size else 0
        boxes.append(slice(lo, hi))
        picks.append(arr - lo)
    # `picks` holds one entry per dimension the box keeps (not the integers), in order
    return boxes, picks if any(not (isinstance(p, slice) and p == slice(None)) for p in picks) else []


def _simple(key: Any, shape: Tuple[int, ...]) -> Tuple[Any, ...]:
    """An index for writing: integers and slices of step 1 (as `write` makes them)."""
    boxes, picks = _plan(key, shape)
    if picks:
        raise IndexError("writing into an opened file takes integers and plain slices")
    return tuple(boxes)


def open(path: PathLike, mode: str = "r", *, hold: bool = True) -> Dataset:   # noqa: A001 - lbd.open
    """Open an `.lbd` file to read only what is needed: the structure now, value data when it
    is indexed.

    Every value's `data` is an `OnDisk` array: `v.data[3]` reads row 3 only, `v.data.shape` reads
    nothing, `np.asarray(v.data)` reads it all. Axes, groups, metadata and the saved view are
    read at once, as by [`load`][lbd.load]; `coords`, `rows` and `to_dense` work as after `load`
    and read only what they need (`rows` one row at a time). Close it with `close()` or a `with`
    block; what was read stays usable.

    Parameters
    ----------
    path : str or path-like
        The file. A file being written (`.lbd.writing`) is read as it was at `open`, and is
        opened for each read and closed again (spec §7).
    mode : {"r", "r+"}, optional
        `"r"` (default): read only; `write` and `save` are refused. `"r+"`: `write` puts data
        into the file at points that exist (no new points or axes), `save()` rewrites the
        description, metadata and saved view in place, and `save(other)` copies the file piece
        by piece.

    Returns
    -------
    Dataset

    Raises
    ------
    LBDError, LBDVersionError, OSError
        As for [`load`][lbd.load]; also an unknown `mode`, or `"r+"` for a file being written.

    Examples
    --------
    >>> with lbd.open("big.lbd") as d:
    ...     row = d.values["S21"].data[3]          # only row 3 is read
    >>> with lbd.open("big.lbd", mode="r+") as d:
    ...     d.write(power=3, S21=trace)            # into the file, at once
    """
    if mode not in MODES:
        raise LBDError(f"mode must be 'r' (read) or 'r+' (read and write), not {mode!r}")
    path = Path(path)
    writing = path.name.lower().endswith(WRITING_SUFFIX)
    if writing and mode != "r":
        raise LBDError(f"{path.name} is being written by a measurement: open it with mode='r'")
    if writing:
        _warn(f"{path.name} is still being written, or its writer stopped before finishing "
              "(lbd.writing_status tells which); reading it as it is now")
    source = _Source(path, mode, hold)
    try:
        def structure(f: h5py.File) -> Dataset:
            d, described = _read_structure(f, path, writing)
            masks = f["measured"] if isinstance(f.get("measured"), h5py.Group) else None
            for name, ds in f["values"].items():
                v = described[name]
                v.data = OnDisk(source, f"values/{name}", v.shape, ds.dtype, v.dtype == "bool")
                if masks is not None and name in masks:
                    if tuple(masks[name].shape[:len(v.shape)]) >= tuple(v.shape):
                        v.measured = OnDisk(source, f"measured/{name}", v.shape, np.uint8, True)
                    else:
                        _warn(f"{path.name}: the measured mask of '{name}' has shape {masks[name].shape}, "
                              f"not {tuple(v.shape)}; it is ignored")
                d.values[name] = v
            return d

        d = source.run(structure)
        _validate_loaded(d, path)
    except BaseException:
        source.close()
        raise
    d._source = source
    return d


def save_in_place(d: Dataset) -> Path:
    """`save()` of a dataset opened with mode="r+": the description, metadata and saved view
    rewritten in the file; the data is already there."""
    source = d._source
    _check_text(d.title, "title")
    _check_text(d.description, "description")
    plot_json = None if d.plot is None else _plot_json(d.plot, "plot")
    style_json = None if d.style is None else _style_json(d.style, "style")
    style_name = None if d.style_name is None else _check_style_name(d.style_name)
    with h5py.File(f"lbd-meta-check-{id(d)}", "w", driver="core", backing_store=False) as scratch:
        _write_meta(scratch.create_group("meta"), d.meta, "meta")      # refused before anything changes

    def rewrite(f: h5py.File) -> None:
        f.attrs["title"] = d.title
        f.attrs["description"] = d.description
        if "meta" in f:
            del f["meta"]
        _write_meta(f.create_group("meta"), d.meta, "meta")
        if "plot" in f:
            del f["plot"]
        if plot_json is not None or style_json is not None or style_name is not None:
            g = f.create_group("plot")
            for key, val in (("spec", plot_json), ("style", style_json), ("style_name", style_name)):
                if val is not None:
                    g.attrs[key] = val
            mpl = _matplotlib_version() or d.matplotlib
            if mpl:
                g.attrs["matplotlib"] = mpl

    source.run(rewrite)
    return source.path


def check_change(d: Dataset, what: str, path: Optional[PathLike] = None) -> bool:
    """Whether a dataset opened with lbd.open may do `what` ("write" or "save"); raises if not.
    Returns True for `save` in place (no path, or the file itself)."""
    source = d._source
    if source.mode != "r+":
        raise LBDError(f"{source.path.name} is opened read-only (mode='r'): {what} is refused. Open it with "
                       "mode='r+' to change it, or use lbd.load")
    if source.closed:
        raise LBDError(f"{source.path.name} is closed: open it again, or use lbd.load")
    return what == "save" and (path is None or _same_target(Path(path), source.path))
