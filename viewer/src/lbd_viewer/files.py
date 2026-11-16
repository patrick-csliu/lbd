"""File actions of the folder panel: show in the file manager, rename, move to the trash.

Rename and trash only act on files the panel shows (data, style and image files), never on
folders. Trash never falls back to deleting permanently: if the system has no trash for that
file, it is an error.

On Windows a file can't be renamed or deleted while any program has it open, even for a moment:
the viewer itself drawing it in another page, an antivirus scan, Explorer's preview. So both
retry for a few seconds (`IN_USE_WAIT`) before reporting that the file is in use.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import send2trash
from lbd.plot.style import STYLE_SUFFIX

from . import scan
from .sdk import open_folder


class FileActionError(ValueError):
    """A rename or trash request that can't be done (wrong name, wrong kind of file, ...)."""


class NameTakenError(FileActionError):
    """Another file already has the new name."""


IN_USE_WAIT = 3.0      # seconds to wait for a file another program has open (Windows)


def _in_use(e: BaseException) -> bool:
    """Windows' "the file is open in another program" (sharing violation, or access denied while
    it is being read)."""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32)


def _while_in_use(action: Callable[[], None], wait: float = None) -> None:
    """Run `action`; while it fails because the file is open elsewhere, try again for a while."""
    deadline = time.monotonic() + (IN_USE_WAIT if wait is None else wait)
    while True:
        try:
            return action()
        except OSError as e:
            if not _in_use(e) or time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def show_in_file_manager(path: Path) -> None:
    """Open the system file manager with `path` selected (a folder is opened itself)."""
    if path.is_dir():
        open_folder(str(path))
    elif os.name == "nt":
        # explorer wants the quotes after the comma; Windows paths can't contain '"'.
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif shutil.which("dbus-send"):
        # The freedesktop file manager interface (Nautilus, Dolphin, Nemo, ...) selects the file.
        result = subprocess.run(
            ["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
             "--type=method_call", "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems", f"array:string:{path.as_uri()}", "string:"],
            capture_output=True, timeout=5)
        if result.returncode != 0:
            open_folder(str(path.parent))
    else:
        open_folder(str(path.parent))


def extension(name: str) -> str:
    """The part of a file name that rename keeps: '.lbd.json' for style files, else the suffix."""
    if name.lower().endswith(STYLE_SUFFIX):
        return name[-len(STYLE_SUFFIX):]
    return Path(name).suffix


def check_shown_file(path: Path) -> None:
    """Rename and trash only work on existing files that the folder panel shows."""
    if path.is_dir():
        raise FileActionError(f"{path.name} is a folder; only data, style and image files can be renamed or moved to the trash")
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    if scan.file_type(path.name) is None:
        raise FileActionError(f"{path.name} is not a data, style or image file")


def rename(path: Path, name: str) -> Path:
    """Rename a file inside its folder, keeping its extension. Returns the new path."""
    check_shown_file(path)
    name = name.strip()
    if not name or "/" in name or "\\" in name:
        raise FileActionError("enter a file name without '/' or '\\'")
    old_ext = extension(path.name)
    if extension(name).lower() != old_ext.lower() or len(name) <= len(old_ext):
        raise FileActionError(f"the new name must end in {old_ext} (the file type can't change)")
    target = path.with_name(name)
    if target.exists() and not _same_file(target, path):
        raise NameTakenError(f"{name} already exists in this folder")
    try:
        _while_in_use(lambda: path.rename(target))
    except OSError as e:
        why = "it is open in another program; close it there and try again" if _in_use(e) else (e.strerror or e)
        raise FileActionError(f"couldn't rename {path.name} to {name}: {why}") from e
    return target


def trash(path: Path) -> None:
    """Move a file to the Recycle Bin (Windows) or Trash. Never deletes it permanently."""
    check_shown_file(path)
    try:
        _while_in_use(lambda: send2trash.send2trash(str(path)))
    except Exception as e:  # send2trash raises OSError or its TrashPermissionError
        why = "it is open in another program; close it there and try again" if _in_use(e) else e
        raise OSError(f"couldn't move {path.name} to the trash, so it was not deleted: {why}") from e


def _same_file(a: Path, b: Path) -> bool:
    """True for the same file, e.g. a rename that only changes upper/lower case on Windows."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


# ---- editing a finished data file (plan 16.19 / 17) -------------------------------------------

EDIT_METHODS = ("in_place", "copy_and_swap")
COPY_MARGIN = 64 * 2**20     # room left free on the disk beyond the copy, in bytes


class DataEditError(ValueError):
    """An edit of a data file that wasn't made; the message says why and what to do. Nothing
    was changed."""


def edit_data_file(path: Path, change: Callable[["h5py.File"], None], method: str = "in_place",
                   expect: "str | None" = None, progress: "Callable[[float], None] | None" = None) -> None:
    """Change a finished data file: `change(f)` gets it open for writing (h5py).

    `method` is the Settings choice for every edit of a finished data file (ids, Save view,
    labels): "in_place" writes into the file (about 10 ms at any size; a hard kill at that moment
    was harmless in tests, a power cut isn't covered), "copy_and_swap" writes a complete copy and
    puts it in the file's place (survives a power cut; needs room for the copy; about 1 s per GB,
    reported to `progress` as 0 … 1). `expect`: the version the user saw (versions.content); a
    file changed since is refused. A file being written is refused.
    """
    import h5py

    from . import versions

    path = Path(path)
    if path.name.lower().endswith(".writing"):
        raise DataEditError(f"{path.name} is being written; it can be changed when it is finished")
    if method not in EDIT_METHODS:
        raise DataEditError(f"unknown way to edit data files {method!r}; use one of {', '.join(EDIT_METHODS)}")
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    if expect is not None and versions.content(path) != expect:
        raise DataEditError(f"{path.name} changed since it was shown; nothing was written. Look at it again "
                            "and repeat if still wanted.")
    if method == "in_place":
        def write() -> None:
            with h5py.File(path, "r+") as f:
                change(f)
        try:
            _while_in_use(write)
        except OSError as e:
            raise DataEditError(f"{path.name} couldn't be changed ({e}); it may be open in another program. "
                                "Close it there and try again. Nothing was written.") from None
        return

    size = path.stat().st_size
    free = shutil.disk_usage(path.parent).free
    if free < size + COPY_MARGIN:
        raise DataEditError(
            f"{path.name} wasn't changed: copy and swap needs room for a copy ({_gb(size + COPY_MARGIN)}), but the "
            f"disk has {_gb(free)} free. Free some room, or choose Settings → Library → Edit data files: in place.")
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(path, "rb") as src, open(tmp, "xb") as out:
            done = 0
            while block := src.read(8 * 2**20):
                out.write(block)
                done += len(block)
                if progress is not None:
                    progress(done / max(size, 1))
            out.flush()
            os.fsync(out.fileno())
        with h5py.File(tmp, "r+") as f:
            change(f)
        import lbd

        lbd.info(tmp)                          # the copy is a readable LBD file before it replaces the original
        try:
            _while_in_use(lambda: os.replace(tmp, path))
        except OSError as e:
            raise DataEditError(f"{path.name} couldn't be replaced by its changed copy ({e}); it may be open in "
                                "another program. Close it there and try again. Nothing was changed.") from None
    finally:
        if tmp.exists():
            tmp.unlink()


def _gb(n: int) -> str:
    return f"{n / 2**30:.2f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"
