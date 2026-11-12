"""How the Library notices new files (plan 16, 16.20), the way other programs do it:

- A full check of every open folder when the viewer starts (library.py).
- Then the system's notifications (the `watchdog` package: ReadDirectoryChangesW on Windows,
  FSEvents on macOS, inotify on Linux), one observer per open folder, its subfolders included.
  A notice says which folder changed; notices are gathered for DEBOUNCE seconds and then only
  those folders are checked (`LibraryIndex.scan(folders=...)`), so a new file appears in about
  a second.
- A slow full check every FULL_EVERY seconds as the safety net: a notice can be lost (the system's
  buffer overflowed, a change made while the computer slept), and that only delays a file until
  the next full check (or **Check folders now**).
- Timed checks alone for a folder on a network drive (NETWORK_EVERY: notices of changes made by
  another computer don't reliably arrive over the network, and a check costs a NAS more) and for
  one whose notifications couldn't start or stopped (FALLBACK_EVERY).

`describe()` says how each folder is watched, for the Library's status line, so a user can see
why a file is slow to appear. Nothing here reads files: it only says which folders to check.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import scan

FULL_EVERY = 7 * 60.0     # the safety net: every open folder checked again
NETWORK_EVERY = 60.0      # a folder on a network drive: timed checks only
FALLBACK_EVERY = 10.0     # a local folder without notifications: timed checks (cheap on a local disk)
DEBOUNCE = 1.0            # notices are gathered this long, then their folders are checked
LOOK_EVERY = 5.0          # how often the observers are looked at (one that stopped: timed checks)
LABEL_FILES = ".lbd-library"   # the folders' label files (labels.py) and their sync conflict copies
# file systems reached over the network (Linux /proc/mounts, macOS `mount`)
NETWORK_FILE_SYSTEMS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "afpfs", "webdav", "davfs", "fuse.davfs2",
                        "sshfs", "fuse.sshfs", "afs", "9p", "ncpfs", "ceph", "fuse.ceph", "glusterfs",
                        "fuse.glusterfs", "lustre", "fuse.rclone"}
log = logging.getLogger("lbd_viewer")


def _same(a: str, b: str) -> bool:
    return os.path.normcase(a.rstrip("\\/")) == os.path.normcase(b.rstrip("\\/"))


def is_inside(path: str, folder: str) -> bool:
    """`path` is `folder` or below it."""
    p, f = os.path.normcase(path), os.path.normcase(folder.rstrip("\\/"))
    return p == f or p.startswith(f + os.sep)


def on_network_drive(path: str) -> bool:
    """The folder is on a network drive (a mapped drive or \\\\server\\share on Windows; an NFS,
    SMB, … mount on macOS and Linux). False when it can't be told."""
    try:
        if sys.platform == "win32":
            if path.startswith(("\\\\", "//")):
                return True
            import ctypes

            drive = os.path.splitdrive(path)[0]
            return bool(drive) and ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4   # DRIVE_REMOTE
        mounts: List[tuple] = []                          # (mount point, file system)
        if sys.platform.startswith("linux"):
            with open("/proc/mounts", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        mounts.append((parts[1].replace("\\040", " "), parts[2]))
        elif sys.platform == "darwin":
            out = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():                 # "//user@nas/share on /Volumes/share (smbfs, …)"
                if " on " in line and " (" in line:
                    point = line.split(" on ", 1)[1].rsplit(" (", 1)
                    mounts.append((point[0], point[1].split(",")[0].strip(" )")))
        best = max((m for m in mounts if is_inside(path, m[0]) or m[0] == "/"), key=lambda m: len(m[0]), default=None)
        return best is not None and best[1].lower() in NETWORK_FILE_SYSTEMS
    except Exception:                                     # noqa: BLE001 - unknown: treated as a local folder
        log.debug("couldn't tell whether %s is on a network drive", path, exc_info=True)
        return False


def _default_observer() -> Any:
    from watchdog.observers import Observer

    return Observer()


class _Watch:
    """One open folder: watched by notifications (`observer`), or timed checks (`every` seconds)."""

    def __init__(self, path: str):
        self.path = path
        self.observer: Any = None
        self.every: Optional[float] = None
        self.reason = ""
        self.due = 0.0                       # timed: when it is checked next
        self.network = False

    def describe(self) -> Dict[str, Any]:
        how = "notifications" if self.observer is not None else "timed"
        return {"path": self.path, "how": how, "every": self.every, "reason": self.reason}


class Watcher:
    """The open folders' notifications and timed checks. `on_notice` is called (from the
    observers' threads) when a folder should be checked: the Library's indexing thread then asks
    `due()` which folders, and `next_time()` how long it may wait."""

    def __init__(self, on_notice: Callable[[], None], make_observer: Callable[[], Any] = _default_observer):
        self.on_notice, self.make_observer = on_notice, make_observer
        self._lock = threading.Lock()
        self._watches: Dict[str, _Watch] = {}
        self._pending: Dict[str, bool] = {}            # folder -> also its subfolders
        self._first_notice: Optional[float] = None
        # a notice is dropped when this returns False (tests: a lost notice)
        self.accept: Callable[[str], bool] = lambda path: True

    # -- the folders

    def update(self, roots: List[str]) -> None:
        """Watch exactly these open folders: start new ones, stop removed ones, try notifications
        again for a local folder where they failed (a drive plugged in again)."""
        now = time.monotonic()
        for path in list(self._watches):
            if not any(_same(path, r) for r in roots):
                self._stop(self._watches.pop(path))
        for root in roots:
            w = self._watches.get(root)
            if w is None:
                w = self._watches[root] = _Watch(root)
                w.network = on_network_drive(root)
            if w.observer is not None or w.network and w.every is not None:
                continue
            if w.network:
                self._timed(w, NETWORK_EVERY, "a network drive: notices of changes made on other computers don't "
                                              "reliably arrive", now)
                continue
            try:
                self._start(w)
            except Exception as e:                       # noqa: BLE001 - timed checks instead, and say why
                if w.every is None:
                    log.warning("the Library can't get notifications for %s (%s); it is checked every %.0f s instead",
                                root, e, FALLBACK_EVERY)
                self._timed(w, FALLBACK_EVERY, f"notifications couldn't start: {e}", now)

    def _start(self, w: _Watch) -> None:
        from watchdog.events import FileSystemEventHandler

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event: Any) -> None:
                watcher._event(w.path, event)

        if not os.path.isdir(w.path):
            raise OSError("the folder can't be found")
        observer = self.make_observer()
        observer.schedule(Handler(), w.path, recursive=True)
        observer.daemon = True
        observer.start()
        w.observer, w.every, w.reason = observer, None, ""

    def _timed(self, w: _Watch, every: float, reason: str, now: float) -> None:
        w.every, w.reason, w.due = every, reason, now + every

    def _stop(self, w: _Watch) -> None:
        if w.observer is not None:
            try:
                w.observer.stop()
                w.observer.join(timeout=2)
            except Exception:                            # noqa: BLE001 - stopping: nothing more to do
                log.debug("stopping the observer of %s failed", w.path, exc_info=True)
            w.observer = None

    def stop(self) -> None:
        for w in self._watches.values():
            self._stop(w)
        self._watches.clear()

    def describe(self) -> List[Dict[str, Any]]:
        """How each open folder is watched: {path, how: "notifications" | "timed", every, reason}."""
        return [w.describe() for w in self._watches.values()]

    # -- notices

    def _event(self, root: str, event: Any) -> None:
        """A notice from the system: which folder to check. Only what the Library lists counts: data
        files, the label files, folders; nothing in folders it skips (.git, @eaDir, …)."""
        kind = event.event_type
        if kind in ("opened", "closed_no_write"):
            return
        paths = [os.fsdecode(event.src_path)]
        if getattr(event, "dest_path", None):
            paths.append(os.fsdecode(event.dest_path))
        wanted: Dict[str, bool] = {}
        for path in paths:
            rel = os.path.relpath(path, root)
            parts = [] if rel == "." else rel.split(os.sep)
            if any(scan._skip_dir(p) for p in parts[:-1]):
                continue
            name = parts[-1] if parts else ""
            listed = scan.is_lbd(name) or name.lower().startswith(LABEL_FILES)
            if event.is_directory:
                if kind != "modified" and parts and not scan._skip_dir(name):
                    wanted[path] = True                  # a folder made, removed or moved: all inside it
            elif listed:
                wanted[os.path.dirname(path)] = wanted.get(os.path.dirname(path), False)
            elif kind in ("deleted", "moved") and parts:
                # a folder removed may be told as a file (it can't be looked at any more)
                wanted[path] = True
        if not wanted or not all(self.accept(p) for p in wanted):
            return
        with self._lock:
            for folder, deep in wanted.items():
                self._pending[folder] = self._pending.get(folder, False) or deep
            if self._first_notice is None:
                self._first_notice = time.monotonic()
        self.on_notice()

    def due(self, now: float) -> Dict[str, bool]:
        """The folders to check now ({folder: also its subfolders}): those notified at least
        DEBOUNCE seconds ago, and the timed ones whose time came. A folder whose observer stopped
        gets timed checks from now on."""
        out: Dict[str, bool] = {}
        for w in list(self._watches.values()):
            if w.observer is not None and not w.observer.is_alive():
                log.warning("the Library's notifications for %s stopped; it is checked every %.0f s instead",
                            w.path, FALLBACK_EVERY)
                self._stop(w)
                self._timed(w, FALLBACK_EVERY, "notifications stopped", now)
                out[w.path] = True
            if w.observer is None and w.every is not None and now >= w.due:
                out[w.path] = True
                w.due = now + w.every
        with self._lock:
            if self._first_notice is not None and now >= self._first_notice + DEBOUNCE:
                for folder, deep in self._pending.items():
                    out[folder] = out.get(folder, False) or deep
                self._pending, self._first_notice = {}, None
        return out

    def checked_all(self, now: float) -> None:
        """A full check just ran: the timed folders were checked too."""
        for w in self._watches.values():
            if w.every is not None:
                w.due = now + w.every

    def next_time(self) -> Optional[float]:
        """When `due()` will have something (monotonic time), or None."""
        times = [w.due for w in self._watches.values() if w.observer is None and w.every is not None]
        with self._lock:
            if self._first_notice is not None:
                times.append(self._first_notice + DEBOUNCE)
        return min(times) if times else None
