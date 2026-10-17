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
