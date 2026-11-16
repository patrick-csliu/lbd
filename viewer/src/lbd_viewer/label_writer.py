"""Labels written into the data files (plan 17).

An edit of a file's labels goes to the folder's label file at once (labels.py); about 2 s after
the last edit the labels are written into the data file too (`/labels`, spec §1.9), so they go
wherever the file is copied or moved. Several edits in a row become one write. Anything waiting
is written before the viewer closes.

Which files are written. After every look at the label files (library_labels.apply) the
Library knows, for each file, the labels it shows, when they were last changed and on which
computer, and the labels the data file holds. A file is written when the labels differ, and

- the newest change was made on **this** computer: two viewers on one synced folder never
  both write a file (a sync tool could make conflict copies of it). Labels changed on another
  computer are written there.
- the file is not being written (`.writing`): it gets the labels when it is finished, because
  the check after the finish finds it out of date. Labels a script set while measuring keep
  their own time, so an edit made in the Library meanwhile is newer and wins.

The same check writes labels set before plan 17 (only in the label files) into their files, a
few at a time. A file that can't be written now (read-only, open in another program, a cloud
file that can't be downloaded) keeps its reason in `problems`, shown in the Library, and is tried
again at a later check. The data file's version stays the same for the rest of the viewer
(versions.py): nothing open on it is read or drawn again.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from . import files, labels, versions

if TYPE_CHECKING:
    from .library import LibraryIndex

WRITE_AFTER = 2.0       # seconds after the last edit of a file's labels
RETRY_AFTER = 30.0      # a file that couldn't be written is tried again no sooner than this
PER_CHECK = 50          # files newly found out of date queued per check (labels set before plan 17)
CLOSE_WAIT = 10.0       # at most this long to write what is waiting when the viewer closes
log = logging.getLogger("lbd_viewer")


def _signature(want: Dict[str, Any], written: str) -> Tuple:
    return (bool(want.get("star")), want.get("project") or None, tuple(sorted(want.get("users") or [])),
            tuple(sorted(want.get("tags") or [])), want.get("comment") or "", written)


class LabelWriter:
    """Writes the Library's labels into the data files; see the module's description."""

    def __init__(self, ix: "LibraryIndex", method: Callable[[], str], clock: Callable[[], float] = time.monotonic,
                 host: Callable[[], str] = labels.computer):
        self.ix, self.method, self.clock, self.host = ix, method, clock, host
        self._cond = threading.Condition()
        self._due: Dict[str, Tuple[float, Tuple]] = {}        # path -> (when to write, what)
        self._failed: Dict[str, float] = {}                     # path -> when it may be tried again
        self._done: Dict[str, Tuple[Optional[str], Tuple]] = {}  # path -> (version, what) found up to date
        self.problems: Dict[str, str] = {}                      # path -> why its labels aren't in it yet
        self._thread: Optional[threading.Thread] = None
        self._stop = False

    # ---- what is out of date ----------------------------------------------------------------

    def check(self) -> None:
        """Queue every file whose data file lacks the labels this computer gave it (called after
        each look at the label files)."""
        state: Dict[str, Dict[str, Any]] = getattr(self.ix, "label_state", {}) or {}
        now, me, added = self.clock(), self.host(), 0
        with self._cond:
            for path in [p for p in self._due if p not in state]:
                del self._due[path]
            for path in [p for p in self.problems if p not in state]:
                del self.problems[path]
            for path, s in state.items():
                if not self._out_of_date(path, s, me):
                    self._due.pop(path, None)
                    self.problems.pop(path, None)
                    continue
                what = _signature(s["want"], s["written"])
                if self._done.get(path) == (s.get("version"), what):
                    continue                                    # looked at this version already: it had them
                if self._failed.get(path, 0) > now:
                    continue
                queued = self._due.get(path)
                if queued is None:
                    if added >= PER_CHECK:
                        continue                                # the next check takes more
                    added += 1
                    self._due[path] = (now + WRITE_AFTER, what)
                elif queued[1] != what:                         # edited again: the write waits again
                    self._due[path] = (now + WRITE_AFTER, what)
            self._cond.notify_all()

    @staticmethod
    def _out_of_date(path: str, s: Dict[str, Any], me: str) -> bool:
        if path.lower().endswith(".writing") or s.get("want") is None or not s.get("written"):
            return False
        if s.get("by") != me:                                   # changed on another computer: written there
            return False
        held = s.get("file")
        if held and (held.get("written") or "") > s["written"]:
            return False                                        # the file is newer: the Library takes its labels
        return not labels.same_labels(s["want"], held or {})

    def pending(self, path: str) -> bool:
        with self._cond:
            return path in self._due

    # ---- writing ---------------------------------------------------------------------------------

    def run_due(self, everything: bool = False) -> int:
        """Write the files that are due (`everything`: all queued, now). Returns how many were written."""
        written = 0
        while True:
            with self._cond:
                now = self.clock()
                ready = [p for p, (when, _) in self._due.items() if everything or when <= now]
                if not ready:
                    return written
                path = min(ready, key=lambda p: self._due[p][0])
                del self._due[path]
            written += self._write(path)

    def _write(self, path: str) -> int:
        import lbd
        from lbd.io import _apply_labels, _check_editable

        s = (getattr(self.ix, "label_state", {}) or {}).get(path)
        if s is None or not self._out_of_date(path, s, self.host()):
            return 0
        p = Path(path)
        what = _signature(s["want"], s["written"])
        try:
            held = lbd.labels(p)                               # the file as it is now
            if held is not None and (labels.same_labels(s["want"], held.as_dict())
                                     or (held.written or "") > s["written"]):
                self._done[path] = (s.get("version"), what)
                return 0
            w = s["want"]
            want = lbd.Labels(star=bool(w.get("star")), project=w.get("project") or None, users=w.get("users") or [],
                              tags=w.get("tags") or [], comment=w.get("comment") or "")
            want.written = s["written"]                       # the time they were set, not now
            before_raw = versions.raw(p.stat())
            before = versions.content(p)

            def change(f) -> None:
                _check_editable(f, p)
                _apply_labels(f, want, p)
            files.edit_data_file(p, change, self.method(), expect=before)
            versions.label_written(p, before_raw, versions.raw(p.stat()))
        except Exception as e:                                  # noqa: BLE001 - kept and shown, tried again later
            reason = str(e) or type(e).__name__
            with self._cond:
                self.problems[path] = reason
                self._failed[path] = self.clock() + RETRY_AFTER
            log.info("labels not written into %s: %s", path, reason)
            return 0
        with self._cond:
            self.problems.pop(path, None)
            self._failed.pop(path, None)
        try:
            self.ix.refresh(path)                              # the index sees the labels in the file
        except Exception as e:                                  # noqa: BLE001 - only the listing waits
            log.info("the Library couldn't read %s again after writing its labels: %s", path, e)
        return 1

    # ---- the thread --------------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="lbd-label-writer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stop:
                    return
                now = self.clock()
                nxt = min((when for when, _ in self._due.values()), default=None)
                retry = bool(self._failed)
                if nxt is None or nxt > now:
                    self._cond.wait(min(nxt - now, 1.0) if nxt is not None else 5.0 if retry else None)
                    if not retry or self._stop:
                        continue
            if retry:
                self.check()                                    # files that failed: their time may have come
            try:
                self.run_due()
            except Exception as e:                              # noqa: BLE001 - a bug: logged, the thread goes on
                log.exception("writing labels into data files failed: %s", e)

    def close(self) -> None:
        """Write everything waiting (for at most CLOSE_WAIT seconds), then stop."""
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None
        deadline = time.monotonic() + CLOSE_WAIT
        while time.monotonic() < deadline:
            with self._cond:
                if not self._due:
                    return
                path = next(iter(self._due))
                del self._due[path]
            self._write(path)
        with self._cond:
            left = list(self._due)
        if left:
            log.warning("labels not yet written into %d data file(s) when the viewer closed; they are written "
                        "at its next start: %s", len(left), ", ".join(left[:5]))
