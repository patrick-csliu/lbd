"""Writing while measuring: `lbd.Writer` (spec §7, "Files being written").

The Writer writes `name.lbd.writing` in HDF5's single-writer / multiple-reader (SWMR) mode, so
LBD readers can show the data while it is measured, and holds the **guard**: an exclusive lock on
one byte at offset 2^40 of the file, for as long as it writes. The lock disappears with the
process, so `writing_status` tells "measuring" (held) from "stopped" (a crash or a script that
ended without closing; `recover` turns such a file into an `.lbd` file). At the finish the file
is closed and renamed to `name.lbd`.

Measurements are put in with the same calls as `lbd.Dataset` (`add_axis`, `add_value`, `write`);
`write` only checks and collects, and a background thread writes what was collected every
`flush_every` seconds, forcing it to disk every `force_every` seconds.
"""

from __future__ import annotations

import atexit
import contextlib
import datetime as _dt
import os
import struct
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union

import h5py
import numpy as np

from .io import (
    WRITING_SUFFIX,
    Axis,
    Dataset,
    LBDError,
    Value,
    __version__,
    _created_text,
    _normalize_dtype,
    _plot_json,
    _style_json,
    _check_style_name,
    _check_text,
    _matplotlib_version,
    _version_needed,
    _warn,
    _write_meta,
    load,
    new_uuid7,
)

PathLike = Union[str, os.PathLike]

GUARD_OFFSET = 2 ** 40      # the guard's byte: far beyond any data, so no read is ever blocked
FINISH_WAIT = 10.0          # seconds the finish waits for a program holding the file (Windows)

_OWN: Dict[str, "Writer"] = {}      # files written by this process (POSIX locks don't see their own)


# ---- the guard lock --------------------------------------------------------


def _take_guard(path: Path) -> int:
    """Lock the guard byte on a handle of our own; returns it (closing it releases the lock)."""
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, GUARD_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.fcntl(fd, _SETLK, _flock(fcntl.F_WRLCK))
    except OSError:
        os.close(fd)
        raise
    return fd


def _guard_held(path: Path) -> bool:
    """Does another process (or a Writer in this one) hold the guard of `path`?"""
    if str(path.resolve()) in _OWN:
        return True
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except PermissionError:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, GUARD_OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            os.lseek(fd, GUARD_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False
        import fcntl

        answer = fcntl.fcntl(fd, _GETLK, _flock(fcntl.F_WRLCK))
        return _flock_type(answer) != fcntl.F_UNLCK
    finally:
        os.close(fd)


if sys.platform != "win32":
    import fcntl as _fcntl

    # Linux: locks of an open file description (not released when this process closes another
    # handle of the file, e.g. a reader's); other systems: classic POSIX record locks.
    _SETLK = getattr(_fcntl, "F_OFD_SETLK", _fcntl.F_SETLK)
    _GETLK = getattr(_fcntl, "F_OFD_GETLK", _fcntl.F_GETLK)
    _FLOCK = "@hhqqi4x" if sys.platform.startswith("linux") else "@qqihh"

    def _flock(kind: int) -> bytes:
        if sys.platform.startswith("linux"):
            return struct.pack(_FLOCK, kind, os.SEEK_SET, GUARD_OFFSET, 1, 0)
        return struct.pack(_FLOCK, GUARD_OFFSET, 1, 0, kind, os.SEEK_SET)

    def _flock_type(raw: bytes) -> int:
        fields = struct.unpack(_FLOCK, raw)
        return fields[0] if sys.platform.startswith("linux") else fields[3]


def _own_writer(path: Path) -> Optional["Writer"]:
    """The Writer of this process writing `path`, if any."""
    try:
        return _OWN.get(str(Path(path).resolve()))
    except OSError:
        return None


def _who_has_open(path: Path) -> str:
    """The programs that have `path` open, as text ("" if unknown)."""
    try:
        if sys.platform == "win32":
            return _restart_manager(path)
        out = subprocess.run(["lsof", "-Fc", str(path)], capture_output=True, text=True, timeout=5).stdout
        return ", ".join(sorted({line[1:] for line in out.splitlines() if line.startswith("c")}))
    except Exception:          # only for a better message; never fails the caller
        return ""


def _restart_manager(path: Path) -> str:
    """Windows Restart Manager: what Explorer uses for "the file is open in …"."""
    import ctypes
    from ctypes import wintypes

    rm = ctypes.WinDLL("rstrtmgr")

    class UniqueProcess(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [("Process", UniqueProcess), ("strAppName", ctypes.c_wchar * 256),
                    ("strServiceShortName", ctypes.c_wchar * 64), ("ApplicationType", ctypes.c_int),
                    ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD),
                    ("bRestartable", wintypes.BOOL)]

    session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
    if rm.RmStartSession(ctypes.byref(session), 0, key):
        return ""
    try:
        files = (ctypes.c_wchar_p * 1)(str(path))
        rm.RmRegisterResources(session, 1, files, 0, None, 0, None)
        needed, count, reason = wintypes.UINT(), wintypes.UINT(0), wintypes.DWORD()
        rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        infos = (ProcessInfo * max(needed.value, 1))()
        count = wintypes.UINT(needed.value)
        if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reason)):
            return ""
        return ", ".join(f"{infos[i].strAppName} (process {infos[i].Process.dwProcessId})"
                         for i in range(count.value) if infos[i].Process.dwProcessId != os.getpid())
    finally:
        rm.RmEndSession(session)


def _on_network_share(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    text = str(path.resolve())
    if text.startswith("\\\\"):
        return True
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(text[:3]) == 4      # DRIVE_REMOTE


def _free_name(path: Path) -> Path:
    """`path`, or `name (2).lbd`, `name (3).lbd` … if it is taken."""
    if not path.exists():
        return path
    k = 2
    while True:
        other = path.with_name(f"{path.stem} ({k}){path.suffix}")
        if not other.exists():
            return other
        k += 1


def _writing_path(path: PathLike) -> Path:
    path = Path(path)
    if path.name.lower().endswith(WRITING_SUFFIX):
        return path
    if path.suffix.lower() == ".lbd":
        return path.with_name(path.name + WRITING_SUFFIX)
    raise LBDError(f"{path.name} is not a file being written (name.lbd{WRITING_SUFFIX})")


# ---- status and recovery ---------------------------------------------------


def writing_status(path: PathLike) -> str:
    """Is a file being written still measuring?

    Parameters
    ----------
    path : str or path-like
        The `name.lbd.writing` file (or `name.lbd`, meaning its `.writing` file).

    Returns
    -------
    str
        `"measuring"`: its writer holds the guard lock; `"stopped"`: it doesn't (it crashed, or
        the script ended or was stopped before finishing) — [`recover`][lbd.recover] makes it an
        `.lbd` file. Only programs on this computer are seen: a file measured on another
        computer and synced here is always `"stopped"`.

    Raises
    ------
    FileNotFoundError
        There is no such `.writing` file.

    Examples
    --------
    >>> lbd.writing_status("rabi.lbd.writing")
    'measuring'
    """
    p = _writing_path(path)
    if not p.exists():
        raise FileNotFoundError(f"no file being written: {p}")
    return "measuring" if _guard_held(p) else "stopped"


def recover(path: PathLike) -> Path:
    """Make a stopped `.writing` file into an `.lbd` file with everything it holds.

    A Writer that stopped before finishing (a crash, a script ended without `close`) leaves
    `name.lbd.writing`; this copies what was written into `name.lbd` (or `name (2).lbd` … if
    that is taken), checks the copy, and removes the `.writing` file. Points never measured stay
    `NaN` (or masked, for integers and booleans). The file keeps its id.

    Parameters
    ----------
    path : str or path-like
        The `name.lbd.writing` file.

    Returns
    -------
    pathlib.Path
        The `.lbd` file made.

    Raises
    ------
    LBDError
        Its writer is still measuring.
    FileNotFoundError
        There is no such file.

    Examples
    --------
    >>> lbd.recover("rabi.lbd.writing")
    WindowsPath('rabi.lbd')
    """
    import warnings

    from .io import LBDWarning

    src = _writing_path(path)
    if writing_status(src) == "measuring":
        raise LBDError(f"{src.name} is still being written (its writer holds it); recover it only after "
                       "the measurement stopped")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*still being written", category=LBDWarning)
        d = load(src)
    target = _free_name(src.with_name(src.name[: -len(WRITING_SUFFIX)]))
    d.path = target                          # the same measurement: keep its id
    d.save(target)
    check = load(target)
    if check.id != d.id or {k: v.shape for k, v in check.values.items()} != {k: v.shape for k, v in d.values.items()}:
        raise LBDError(f"recovering {src.name}: the copy {target.name} doesn't match; {src.name} is kept")
    _remove(src)
    return target


def _remove(path: Path) -> None:
    deadline = time.monotonic() + FINISH_WAIT
    while True:
        try:
            path.unlink()
            return
        except PermissionError as e:
            if time.monotonic() > deadline:
                who = _who_has_open(path)
                raise PermissionError(f"can't remove {path}: {who or 'another program'} keeps it open") from e
            time.sleep(0.1)


# ---- the Writer --------------------------------------------------------------


class Writer:
    """Write a file while measuring: readers see the data as it comes, and a crash loses at
    most the last moments.

    Build it like an [`lbd.Dataset`][lbd.Dataset] (`add_axis`, `add_value` without data,
    `meta`), then [`write`][lbd.Writer.write] each point, trace or map as it is measured. It
    writes `name.lbd.writing`; at the finish (`close`, or leaving the `with` block) the file
    becomes `name.lbd`. Saving a whole dataset at the end with `Dataset.save` stays the simple
    way when nobody needs to look while it is measured.

    Parameters
    ----------
    path : str or path-like
        The finished file's name, ending in `.lbd`. Neither it nor `path.writing` may exist.
    title, description : str, optional
        As for `Dataset`; may be changed until the finish.
    created : str or datetime, optional
        When the measurement started; default: the first `write`.
    flush_every : float, optional
        Seconds between writes to the file (readers see new data this often). Default 0.5.
    force_every : float, optional
        Seconds between forcing the written data to the disk (for a power cut). Default 2.

    Attributes
    ----------
    path : pathlib.Path
        The finished file's name.
    writing_path : pathlib.Path
        The file while written: `path` + `.writing`.
    title, description, meta, plot, style, style_name
        As for `Dataset`; written at the finish.

    Raises
    ------
    LBDError
        `path` doesn't end in `.lbd`.
    FileExistsError
        `path` or its `.writing` file exists.

    Warns
    -----
    LBDWarning
        The folder is on a network share: live writing there is not tested yet.

    Examples
    --------
    >>> with lbd.Writer("sweep.lbd", title="Resonator power sweep") as w:
    ...     w.add_axis("power", p, unit="dBm")
    ...     w.add_axis("freq", f, unit="Hz")
    ...     w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    ...     for i in range(len(p)):
    ...         w.write(power=i, S21=vna.trace(p[i]))
    """

    def __init__(self, path: PathLike, title: str = "", description: str = "", created: Any = None,
                 flush_every: float = 0.5, force_every: float = 2.0):
        path = Path(path)
        if path.suffix.lower() != ".lbd":
            raise LBDError(f"{path.name}: lbd.Writer writes .lbd files; give a name ending in .lbd")
        self.path = path
        self.writing_path = path.with_name(path.name + WRITING_SUFFIX)
        for p in (path, self.writing_path):
            if p.exists():
                raise FileExistsError(f"{p} exists; lbd.Writer never replaces a file — choose another name")
        if not (flush_every > 0 and force_every > 0):
            raise LBDError("flush_every and force_every must be positive numbers of seconds")
        if _on_network_share(path.parent if path.parent.exists() else Path.cwd()):
            _warn(f"{path.parent} is on a network share; writing while measuring is not tested there yet. "
                  "Measure into a local folder if you see problems.")
        self._d = Dataset(title, description, created)
        self._d._placeholders = set()
        self.flush_every = float(flush_every)
        self.force_every = float(force_every)
        self._file: Optional[h5py.File] = None
        self._guard: Optional[int] = None
        self._pending: List[tuple] = []
        self._lock = threading.Lock()        # guards _pending
        self._io = threading.Lock()          # one user of the HDF5 file at a time
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[BaseException] = None
        self._last_force = 0.0
        self._state = "new"                  # new → writing → finished | stopped

    # ---- description, as Dataset ---------------------------------------

    title = property(lambda self: self._d.title, lambda self, v: setattr(self._d, "title", v))
    description = property(lambda self: self._d.description, lambda self, v: setattr(self._d, "description", v))
    meta = property(lambda self: self._d.meta, lambda self, v: setattr(self._d, "meta", v))
    plot = property(lambda self: self._d.plot, lambda self, v: setattr(self._d, "plot", v))
    style = property(lambda self: self._d.style, lambda self, v: setattr(self._d, "style", v))
    style_name = property(lambda self: self._d.style_name, lambda self, v: setattr(self._d, "style_name", v))

    @property
    def axes(self) -> Dict[str, Axis]:
        return self._d.axes

    @property
    def values(self) -> Dict[str, Value]:
        return self._d.values

    @property
    def id(self) -> Optional[str]:
        """The measurement's id, given when the file is created (the first `write`)."""
        return self._d.id

    def add_axis(self, name: str, data: Any = None, unit: str = "", label: Optional[str] = None,
                 elements: Optional[Sequence[str]] = None, grows: bool = False) -> Axis:
        """As [`Dataset.add_axis`][lbd.Dataset.add_axis]; before the first `write`."""
        self._before_start("add_axis")
        return self._d.add_axis(name, data, unit=unit, label=label, elements=elements, grows=grows)

    def add_value(self, name: str, data: Any = None, axes: Union[str, Sequence[str], None] = None,
                  unit: str = "", label: Optional[str] = None, dtype: str = "auto",
                  shape: Optional[Sequence[int]] = None, elements: Optional[Sequence[Any]] = None) -> Value:
        """As [`Dataset.add_value`][lbd.Dataset.add_value]; before the first `write`. Without
        data the value is filled by `write`; with data it is written whole at the start."""
        self._before_start("add_value")
        return self._d.add_value(name, data, axes=axes, unit=unit, label=label, dtype=dtype,
                                 shape=shape, elements=elements)

    def _before_start(self, what: str) -> None:
        if self._state != "new":
            raise LBDError(f"{what}: give every axis and value before the first write "
                           "(a file being written can't get new ones)")

    # ---- writing --------------------------------------------------------

    def start(self) -> None:
        """Create the `.writing` file now (the first `write` does it otherwise)."""
        if self._state != "new":
            return
        d = self._d
        if not d.values:
            raise LBDError("add at least one value before writing")
        d._check_complete(live=True)
        if d.created is None:
            d.created = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        d.new_id()
        d.writer = f"python lbd {__version__}"
        try:
            # the HDF5 1.10 format (SWMR needs it): readable by every HDF5 since, unlike "latest";
            # HDF5's own locking off: the guard locks it
            f = h5py.File(self.writing_path, "w-", libver=("v110", "v110"), locking=False)
        except FileExistsError:
            raise FileExistsError(f"{self.writing_path} exists; lbd.Writer never replaces a file") from None
        try:
            self._guard = _take_guard(self.writing_path)   # at once: from now on it reads "measuring"
            self._create(f)
            f.swmr_mode = True
        except BaseException:
            f.close()
            if self._guard is not None:
                os.close(self._guard)
                self._guard = None
            self.writing_path.unlink()
            raise
        self._file = f
        self._state = "writing"
        _OWN[str(self.writing_path.resolve())] = self
        _open_writers.add(self)
        self._last_force = time.monotonic()
        self._thread = threading.Thread(target=self._run, name=f"lbd.Writer {self.path.name}", daemon=True)
        self._thread.start()

    def _create(self, f: h5py.File) -> None:
        d = self._d
        f.attrs["lbd_format"] = "LBD"
        d.lbd_version = _version_needed(d)
        f.attrs["lbd_version"] = d.lbd_version
        f.attrs["title"] = d.title
        f.attrs["description"] = d.description
        f.attrs["created"] = _created_text(d.created)
        f.attrs["writer"] = d.writer
        f.attrs["id"] = d.id
        g_axes = f.create_group("axes")
        for a in d.axes.values():
            if a.grows:
                ds = g_axes.create_dataset(a.name, shape=(0,), maxshape=(None,), dtype="f8", chunks=(1024,))
            else:
                ds = g_axes.create_dataset(a.name, data=_normalize_dtype(np.asarray(a.data), a.name))
            ds.attrs["unit"] = a.unit
            ds.attrs["label"] = a.label
            if a.elements is not None:
                ds.attrs.create("elements", np.array(a.elements, dtype=object), dtype=h5py.string_dtype("utf-8"))
            if a.role is not None:
                ds.attrs["role"] = a.role
        g_values = f.create_group("values")
        g_measured = None
        for v in d.values.values():
            grows = bool(v.axes) and d.axes[v.axes[0]].grows
            is_bool = v.dtype == "bool"
            store = "uint8" if is_bool else v.dtype
            placeholder = v.name in d._placeholders
            fill = complex(np.nan, np.nan) if store.startswith("complex") else np.nan if store.startswith("float") else 0
            if grows:
                ds = g_values.create_dataset(v.name, shape=v.data.shape, maxshape=(None,) + v.data.shape[1:],
                                             dtype=store, fillvalue=fill, chunks=_chunks(v.data.shape[1:]))
            elif placeholder:
                ds = g_values.create_dataset(v.name, shape=v.data.shape, dtype=store, fillvalue=fill,
                                             chunks=True if v.data.ndim else None)
            else:
                data = _normalize_dtype(np.asarray(v.data), v.name)
                ds = g_values.create_dataset(v.name, data=data.astype(np.uint8) if is_bool else data)
            ds.attrs["unit"] = v.unit
            ds.attrs["label"] = v.label
            ds.attrs["axes"] = ",".join(v.axes)
            if is_bool:
                ds.attrs["lbd_bool"] = np.int64(1)
            if v.measured is not None and placeholder:
                g_measured = g_measured or f.create_group("measured")
                if grows:
                    g_measured.create_dataset(v.name, shape=v.data.shape, maxshape=(None,) + v.data.shape[1:],
                                              dtype="u1", fillvalue=0, chunks=_chunks(v.data.shape[1:]))
                else:
                    g_measured.create_dataset(v.name, shape=v.data.shape, dtype="u1", fillvalue=0,
                                              chunks=True if v.data.ndim else None)
            elif v.measured is not None:
                v.measured = None                # given whole: everything measured
        _write_meta(f.create_group("meta"), d.meta, "meta")

    def write(self, names: Optional[Mapping[str, Any]] = None, **more: Any) -> None:
        """Put measured data in its place: as [`Dataset.write`][lbd.Dataset.write].

        It returns at once: the data is written to the file by a background thread within
        `flush_every` seconds (or at [`flush`][lbd.Writer.flush] / the finish).

        Raises
        ------
        LBDError
            As `Dataset.write`; also when writing to the file failed earlier (e.g. the disk is
            full: what was written before stays in the `.writing` file), or after the finish.
        """
        self._raise_error()
        if self._state == "new":
            self.start()
        if self._state != "writing":
            raise LBDError(f"{self.path.name}: the Writer is closed; nothing more can be written")
        plan = self._d._plan_write(names, more)
        items: List[tuple] = []
        if plan["grow"] is not None:
            g, coords = plan["grow"]
            ax = self._d.axes[g]
            ax.data = np.concatenate([ax.data, np.atleast_1d(coords).astype(float)])
            items.append(("grow", g, np.atleast_1d(coords).astype(float), len(ax.data)))
        for name, index, arr in plan["puts"]:
            store = "uint8" if self._d.values[name].dtype == "bool" else self._d.values[name].dtype
            items.append(("put", name, index, np.array(arr, dtype=store)))   # a copy: the caller may reuse its buffer
        with self._lock:
            self._pending.extend(items)

    def flush(self) -> None:
        """Write everything collected so far to the file now (readers see it)."""
        self._raise_error()
        if self._state == "writing":
            self._write_pending()
            self._raise_error()

    @contextlib.contextmanager
    def _reading(self) -> Iterator[Optional[h5py.File]]:
        """The open file, with everything written so far, for `lbd.load` in this process."""
        self._write_pending()
        with self._io:
            yield self._file

    def _run(self) -> None:
        while not self._stop.wait(self.flush_every):
            self._write_pending()
            if self._error is not None:
                return

    def _write_pending(self) -> None:
        with self._io:
            if self._file is None or self._error is not None:
                return
            with self._lock:
                items, self._pending = self._pending, []
            try:
                if items:
                    self._apply(items)
                    self._file.flush()
                if time.monotonic() - self._last_force >= self.force_every and self._guard is not None:
                    os.fsync(self._guard)
                    self._last_force = time.monotonic()
            except BaseException as e:      # raised in the user's thread at the next call
                self._error = e

    def _apply(self, items: List[tuple]) -> None:
        f = self._file
        d = self._d
        for item in items:
            if item[0] == "grow":
                _, g, coords, n = item
                for v in d.values.values():           # values first: readers cut to the shortest
                    if v.axes and v.axes[0] == g:
                        f["values"][v.name].resize(n, axis=0)
                        if "measured" in f and v.name in f["measured"]:
                            f["measured"][v.name].resize(n, axis=0)
                ds = f["axes"][g]
                ds.resize(n, axis=0)
                ds[n - coords.size:] = coords
            else:
                _, name, index, arr = item
                ds = f["values"][name]
                ds[index] = arr
                if "measured" in f and name in f["measured"]:
                    f["measured"][name][index] = 1

    def _raise_error(self) -> None:
        if self._error is not None:
            e = self._error
            raise LBDError(f"writing {self.writing_path.name} failed: {e}. What was written before is in "
                           f"{self.writing_path}; lbd.recover makes it an .lbd file once this Writer is closed") from e

    # ---- the finish ---------------------------------------------------

    def close(self, stopped: bool = False) -> Path:
        """Finish: write what is left, close the file and rename it to `path`.

        Parameters
        ----------
        stopped : bool, optional
            The measurement was stopped on purpose before every point was measured: the file
            is finished the same way (the points not measured stay `NaN`, or masked), without
            the warning that an integer or boolean value was not measured everywhere.

        Returns
        -------
        pathlib.Path
            The finished file: `path`, or `name (2).lbd` if `path` was made meanwhile (with a
            warning).

        Raises
        ------
        LBDError
            Writing to the file failed (what was written is in the `.writing` file).
        PermissionError
            Another program kept the file open for 10 s, so it couldn't be renamed: the message
            names the program; the complete file is the `.writing` file (`lbd.recover`).
        """
        if self._state == "new":
            self.start()
        if self._state != "writing":
            return self.path
        description = self._finished_description()      # bad metadata: still writing, nothing lost
        self._end_thread()
        self._write_pending()
        if self._error is not None:
            self._abandon()
            self._raise_error()
        self._file.close()
        self._file = None
        try:
            missing = self._finish_description(*description)
        except BaseException:
            self._release()
            self._state = "stopped"
            raise
        self._release()
        if missing and not stopped:
            _warn(f"{self.path.name}: {', '.join(missing)} not measured everywhere; the points not measured are "
                  "marked in the file (close(stopped=True) says the measurement was stopped on purpose)")
        target = _free_name(self.path)
        if target != self.path:
            _warn(f"{self.path.name} was made by someone else while measuring; the measurement is saved as "
                  f"{target.name}")
        deadline = time.monotonic() + FINISH_WAIT
        while True:
            try:
                os.rename(self.writing_path, target)
                break
            except PermissionError as e:
                if time.monotonic() > deadline:
                    who = _who_has_open(self.writing_path)
                    raise PermissionError(
                        f"the measurement is complete, but {who or 'another program'} kept {self.writing_path.name} "
                        f"open for {FINISH_WAIT:g} s, so it couldn't be renamed to {target.name}. Close it there, "
                        f"then rename it yourself or use lbd.recover({str(self.writing_path)!r})") from e
                time.sleep(0.1)
        self._state = "finished"
        self.path = target
        return target

    def _finished_description(self) -> tuple:
        """The saved view as text, after checking it and the metadata (raises if they can't be
        stored)."""
        d = self._d
        _check_text(d.title, "title")
        _check_text(d.description, "description")
        with h5py.File(f"lbd-meta-check-{id(self)}", "w", driver="core", backing_store=False) as scratch:
            _write_meta(scratch.create_group("meta"), d.meta, "meta")
        return (None if d.plot is None else _plot_json(d.plot, "plot"),
                None if d.style is None else _style_json(d.style, "style"),
                None if d.style_name is None else _check_style_name(d.style_name))

    def _finish_description(self, plot_json: Optional[str], style_json: Optional[str],
                            style_name: Optional[str]) -> List[str]:
        """What SWMR can't change while writing: the description, metadata, saved view; and the
        masks of values measured completely. Returns the values not measured everywhere."""
        d = self._d
        missing: List[str] = []
        with h5py.File(self.writing_path, "r+", locking=False) as f:
            f.attrs["title"] = d.title
            f.attrs["description"] = d.description
            del f["meta"]
            _write_meta(f.create_group("meta"), d.meta, "meta")
            if plot_json is not None or style_json is not None or style_name is not None:
                g = f.create_group("plot")
                for key, val in (("spec", plot_json), ("style", style_json), ("style_name", style_name)):
                    if val is not None:
                        g.attrs[key] = val
                mpl = _matplotlib_version()
                if mpl:
                    g.attrs["matplotlib"] = mpl
            if "measured" in f:
                for name in list(f["measured"]):
                    if np.all(f["measured"][name][()]):
                        del f["measured"][name]
                    else:
                        missing.append(name)
                if not len(f["measured"]):
                    del f["measured"]
        return missing

    def _end_thread(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _release(self) -> None:
        if self._guard is not None:
            os.close(self._guard)
            self._guard = None
        _OWN.pop(str(self.writing_path.resolve()), None)
        _open_writers.discard(self)

    def _abandon(self) -> None:
        """Stop without finishing: what was written stays in the `.writing` file ("stopped")."""
        if self._state != "writing":
            return
        self._end_thread()
        try:
            self._write_pending()
            if self._file is not None:
                self._file.close()
        finally:
            self._file = None
            self._release()
            self._state = "stopped"

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, kind, error, tb) -> None:
        if kind is None:
            self.close()
            return
        try:
            self._abandon()
        except Exception as e:                    # the original error goes on; say what else happened
            _warn(f"{self.writing_path.name}: after {kind.__name__}, writing what was measured failed too: {e}")
        if self._state == "stopped" and self.writing_path.exists():
            _warn(f"the measurement stopped with {kind.__name__}; what was measured is in {self.writing_path.name} "
                  f"(lbd.recover makes it an .lbd file)")

    def __repr__(self) -> str:
        return f"<lbd.Writer {self.writing_path if self._state == 'writing' else self.path} ({self._state})>"


def _chunks(rest: tuple) -> tuple:
    """Chunks along a growing axis: about 64 kB, at least one row."""
    row = int(np.prod(rest)) if rest else 1
    return (max(1, 8192 // max(row, 1)),) + tuple(rest)


_open_writers: "weakref.WeakSet[Writer]" = weakref.WeakSet()


@atexit.register
def _stop_open_writers() -> None:
    for w in list(_open_writers):
        try:
            w._abandon()
            _warn(f"{w.writing_path.name} was not closed before Python ended; what was measured is in it "
                  "(lbd.recover makes it an .lbd file)")
        except Exception:
            pass


