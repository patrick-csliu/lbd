"""The Library's previews (plan 8c): a small picture of a data file, drawn by the Explore engine.

- A preview comes only from Explore. **Automatic**: what Explore opens with the first time,
  worked out from the file's data alone (the file's saved figure view, /plot, is never used):
  one panel per value with axes, up to four, in Explore's grid. **Chosen**: the user pressed
  "Library preview" in Explore; the panels as shown are drawn once and only the picture
  is kept (catalog.py), never how it was made.
- Every preview has one size (4:3, PREVIEW_SIZE CSS pixels at PREVIEW_DPR) and is a WebP
  picture: a fraction of a PNG's size, so thousands of them stay small.
- A preview shows only the data (ExploreSession `bare`): no axes, tick labels, axis labels,
  colour bar or legend; the plot fills its panel. It is a thumbnail of the data, the same for
  every file; the numbers are in the file's details next to it.
- Drawing a panel is an ExploreSession (explore.py) at its share of the picture, so a preview
  uses Explore's reduction (a large map draws in about a second) and looks like Explore.
- Automatic pictures are a cache (`previews.sqlite`, next to the Library index): current while
  the file's version (size, modification time) is the same; a style change doesn't redraw them.
  Deletable: they are drawn again.
- Drawing happens in two worker processes, never in the server's own: matplotlib's render lock
  would make Explore wait while a large file is drawn. One draws what the user is looking at
  now; the other, at lower priority, the rest. The setting (config.py PREVIEW_MODES) says what
  is drawn without being asked: every file ("all"), the rows near the selection ("nearby"), or
  nothing ("off").
"""

from __future__ import annotations

import io
import logging
import multiprocessing
import os
import sqlite3
import sys
import threading
import time
import warnings
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

import lbd
from lbd.plot.render import RenderWarning, flat
from lbd.plot.style import Style

PREVIEW_SIZE = (640, 480)           # drawn as a 640×480 Explore panel (text in proportion), 4:3
PREVIEW_DPR = 2.0                   # 1280×960 pixels: sharp up to 640×480 on a high-density (2×, e.g. 4K) screen
PREVIEW_QUALITY = 80                # WebP quality (0-100); lines and text stay readable
FIRST_PANELS = 4                    # as Explore (ExploreTab.tsx FIRST_PANELS)
BACKGROUND = (255, 255, 255, 255)   # around the panels
CACHE_FILE, CACHE_SCHEMA = "previews.sqlite", 2   # 2: data only (no axes, labels, colour bar), at 2×
REDRAW_EVERY = 30.0                 # a file that keeps changing (being written) is redrawn in the background at most this often
NOW, NEAR, ALL = 0, 1, 2            # priorities: what the user looks at, the rows near it, every file
log = logging.getLogger("lbd_viewer")


class PreviewError(ValueError):
    """A file's preview can't be drawn; the message says why, in words."""


Panel = Dict[str, Any]               # {"spec": {...}, "settings": {...}, "view": {"xlim", "ylim"} | None}


def grid_of(n: int, layout: str = "side") -> Tuple[int, int]:
    """Rows and columns of the panel grid, as Explore (ExploreTab.tsx gridOf)."""
    if n <= 1:
        return (1, 1)
    if n <= 3:
        return (1, n) if layout == "side" else (n, 1)
    if n == 4:
        return (2, 2)
    return (2, 3) if layout == "side" else (3, 2)


def automatic_panels(header: "lbd.Dataset") -> Tuple[List[Panel], Tuple[int, int]]:
    """What Explore opens a file with the first time (ExploreTab.tsx `fresh`), from the data
    only: one panel per value with axes, up to FIRST_PANELS, side by side."""
    header = flat(header)
    names = [name for name, v in header.values.items() if len(v.shape) > 0]
    if not names:
        singles = ", ".join(header.values) or "none"
        raise PreviewError(f"this file has only single numbers ({singles}); there is no plot to preview")
    panels = [{"spec": {"values": [name]}, "settings": {}, "view": None} for name in names[:FIRST_PANELS]]
    return panels, grid_of(len(panels))


def draw(path: Path, panels: Sequence[Panel], grid: Tuple[int, int], style: Style,
         saved_view: bool = False) -> bytes:
    """The picture of these panels (WebP). `saved_view` False (automatic previews): the file's
    saved figure view is ignored. Raises PreviewError with the reason."""
    from PIL import Image

    from .explore import ExploreSession

    rows, cols = grid
    if not panels or len(panels) > rows * cols:
        raise PreviewError(f"{len(panels)} panels don't fit a {rows}×{cols} grid")
    width, height = PREVIEW_SIZE
    px_w, px_h = round(width * PREVIEW_DPR), round(height * PREVIEW_DPR)
    canvas = np.empty((px_h, px_w, 4), dtype=np.uint8)
    canvas[:] = BACKGROUND
    version = ""                                     # sessions are used once: no version needed
    for i, panel in enumerate(panels):
        r, c = divmod(i, cols)
        x0, x1 = c * width // cols, (c + 1) * width // cols
        y0, y1 = r * height // rows, (r + 1) * height // rows
        try:
            # a preview is a picture: the notices about how a plot is drawn (e.g. a variable sweep
            # against its point number) are shown when the file is opened, not on its thumbnail
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RenderWarning)
                s = ExploreSession(Path(path), version, dict(panel.get("spec") or {}), style,
                                   x1 - x0, y1 - y0, PREVIEW_DPR, saved_view=saved_view, summarise=False,
                                   bare=True)
                try:
                    s.apply(panel.get("settings") or {})
                    view = panel.get("view") or {}
                    data, meta = s.render(view.get("xlim"), view.get("ylim"), panel.get("stat", "max"))
                finally:
                    s.close()
        except PreviewError:
            raise
        except Exception as e:                   # unreadable file, unplottable value …: in words
            raise PreviewError(_reason(e)) from e
        picture = np.frombuffer(data, dtype=np.uint8).reshape(meta["height"], meta["width"], 4)
        top, left = round(y0 * PREVIEW_DPR), round(x0 * PREVIEW_DPR)
        h, w = min(picture.shape[0], px_h - top), min(picture.shape[1], px_w - left)
        canvas[top:top + h, left:left + w] = picture[:h, :w]
    buf = io.BytesIO()
    Image.fromarray(canvas[:, :, :3]).save(buf, format="WEBP", quality=PREVIEW_QUALITY, method=4)
    return buf.getvalue()


def draw_automatic(path: Path, style: Style) -> bytes:
    """A file's automatic preview: Explore's first open, from the data only."""
    try:
        header = lbd.info(path)
    except Exception as e:
        raise PreviewError(_reason(e)) from e
    panels, grid = automatic_panels(header)
    return draw(path, panels, grid, style, saved_view=False)


def _reason(e: Exception) -> str:
    text = str(e).strip() or type(e).__name__
    return text[0].upper() + text[1:] if text else text


# ---- the cache of automatic pictures


class PreviewCache:
    """Automatic pictures by path, with the file version they were drawn for (or why the file
    can't be drawn). A cache: one that can't be read is deleted and started again."""

    def __init__(self, directory: Path):
        self.path = Path(directory) / CACHE_FILE
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._db = self._open()
            except sqlite3.DatabaseError as e:
                log.warning("the preview cache %s couldn't be read (%s); it is started again", self.path, e)
                for p in (self.path, self.path.with_name(self.path.name + "-wal"),
                          self.path.with_name(self.path.name + "-shm")):
                    p.unlink(missing_ok=True)
                self._db = self._open()
        return self._db

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, CACHE_SCHEMA):
                raise sqlite3.DatabaseError(f"made by another LBD (schema {version}, this one uses {CACHE_SCHEMA})")
            db.execute("""CREATE TABLE IF NOT EXISTS previews (
                path TEXT PRIMARY KEY, version TEXT NOT NULL, picture BLOB, error TEXT, drawn_at REAL NOT NULL)""")
            db.execute(f"PRAGMA user_version = {CACHE_SCHEMA}")
        except sqlite3.DatabaseError:
            db.close()
            raise
        return db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def get(self, path: str) -> Optional[Dict[str, Any]]:
        """{version, picture, error, drawn_at} or None."""
        with self._lock:
            r = self._connect().execute("SELECT version, picture, error, drawn_at FROM previews WHERE path = ?",
                                        (path,)).fetchone()
        return dict(zip(("version", "picture", "error", "drawn_at"), r)) if r else None

    def put(self, path: str, version: str, picture: Optional[bytes], error: Optional[str]) -> None:
        with self._lock:
            self._connect().execute("INSERT OR REPLACE INTO previews (path, version, picture, error, drawn_at) "
                                    "VALUES (?, ?, ?, ?, ?)", (path, version, picture, error, time.time()))

    def versions(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._connect().execute("SELECT path, version FROM previews"))

    def drop(self, paths: Iterable[str]) -> None:
        with self._lock:
            db = self._connect()
            db.execute("BEGIN")
            db.executemany("DELETE FROM previews WHERE path = ?", [(p,) for p in paths])
            db.execute("COMMIT")

    def renamed(self, old: str, new: str) -> None:
        with self._lock:
            db = self._connect()
            db.execute("DELETE FROM previews WHERE path = ?", (new,))
            db.execute("UPDATE previews SET path = ? WHERE path = ?", (new, old))

    def size(self) -> Tuple[int, int]:
        """How many pictures, and their bytes."""
        with self._lock:
            n, b = self._connect().execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(picture)), 0) FROM previews").fetchone()
        return int(n), int(b)

    def clear(self) -> int:
        """Delete every automatic picture (they are drawn again); returns the bytes freed."""
        _, freed = self.size()
        with self._lock:
            db = self._connect()
            db.execute("DELETE FROM previews")
            db.execute("VACUUM")                       # give the space back to the disk
        return freed


# ---- the worker processes


def _lower_priority() -> None:
    """In the background worker: below normal priority, so the computer stays responsive."""
    try:
        if sys.platform == "win32":
            import ctypes

            BELOW_NORMAL_PRIORITY_CLASS = 0x4000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                    BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception:                                  # only a nicety: drawing works without it
        pass


def work(job: Dict[str, Any]) -> Tuple[Optional[bytes], Optional[str]]:
    """Draw one picture (in a worker): (picture, None) or (None, why it can't be drawn).
    job: {path, style (Style as a dict), panels (None: automatic), grid, saved_view}."""
    style = Style.model_validate(job["style"])
    try:
        if job.get("panels") is None:
            return draw_automatic(Path(job["path"]), style), None
        return draw(Path(job["path"]), job["panels"], tuple(job["grid"]), style, job.get("saved_view", True)), None
    except PreviewError as e:
        return None, str(e)


def file_version(path: str) -> Optional[str]:
    """The file's version as the Library index writes it (library._version), or None if it is gone."""
    from .library import _version

    try:
        return _version(os.stat(path))
    except OSError:
        return None


class Previewer:
    """Draws the automatic previews: what is asked for now first, then the rows near it, then
    (setting "all") every file the Library knows.

    - `files()`: every indexed file's version by path (LibraryIndex.versions); `generation()`
      says when that changed. `mode()`: "all", "nearby" or "off" (config.previews_mode).
      `style()`: the style to draw with, as a dict. `chosen(path)`: True when the file has a
      chosen picture (it isn't drawn automatically).
    - `processes` False (tests): drawn in threads of this process instead of worker processes.
    """

    def __init__(self, cache: PreviewCache, files: Callable[[], Dict[str, str]], generation: Callable[[], int],
                 mode: Callable[[], str], style: Callable[[], Dict[str, Any]],
                 chosen: Callable[[str], bool] = lambda path: False, processes: bool = True):
        self.cache = cache
        self.files, self.generation, self.mode, self.style, self.chosen = files, generation, mode, style, chosen
        self.processes = processes
        self._queue: Dict[str, Tuple[int, float]] = {}      # path -> (priority, not before)
        self._drawing: Set[str] = set()
        self._last_drawn: Dict[str, float] = {}
        self._cond = threading.Condition()
        self._pools: Dict[str, Optional[Executor]] = {"now": None, "background": None}
        self._threads: List[threading.Thread] = []
        self._stop = False
        self._seen: Optional[Tuple[int, str]] = None
        self.status: Dict[str, Any] = {"drawn": 0, "total": 0, "drawing": 0}

    # -- asking

    def answer(self, path: str, now: bool = True) -> Dict[str, Any]:
        """The automatic picture of a file if it is current ({picture} or {error}), else what is
        happening: {state: "drawing"} (asked for: `now` for the selected file, else as a row near
        it, e.g. a picture in view; not when previews are off) or {state: "off"}."""
        if path.lower().endswith(".lbd.writing"):
            return {"state": "writing"}
        version = file_version(path)
        if version is None:
            return {"error": "The file is gone (moved, renamed or deleted)."}
        row = self.cache.get(path)
        if row and row["version"] == version:
            return {"picture": row["picture"], "error": row["error"], "drawn_at": row["drawn_at"]}
        with self._cond:
            busy = path in self._drawing or path in self._queue
        if busy:
            return {"state": "drawing"}
        if self.mode() == "off":
            return {"state": "off"}
        self.want([path], now=now)
        return {"state": "drawing"}

    def want(self, paths: Iterable[str], now: bool) -> None:
        """Draw these files soon: `now` (the selected file, or Show preview: also when previews
        are off) first; otherwise as the rows near the selection (not when previews are off)."""
        if not now and self.mode() == "off":
            return
        priority = NOW if now else NEAR
        with self._cond:
            for p in paths:
                if p.lower().endswith(".lbd.writing"):   # no preview while it is written
                    continue
                version = file_version(p)
                row = self.cache.get(p)
                if version is None or (row and row["version"] == version) or p in self._drawing:
                    continue
                old = self._queue.get(p)
                if old is None or priority < old[0]:     # what the user looks at isn't held back
                    self._queue[p] = (priority, 0.0 if now else self._not_before(p))
            self.status["drawing"] = len(self._queue) + len(self._drawing)
            self._cond.notify_all()
        self.start()

    def draw_now(self, job: Dict[str, Any], timeout: float = 120.0) -> bytes:
        """Draw a picture in the "now" worker and wait for it (a chosen preview). Raises PreviewError."""
        try:
            picture, error = self._run("now", job).result(timeout=timeout)
        except BrokenProcessPool as e:
            self._pools["now"] = None
            raise PreviewError(f"The drawing process stopped ({e or 'it ended unexpectedly'}).") from e
        if error:
            raise PreviewError(error)
        assert picture is not None
        return picture

    def renamed(self, old: str, new: str) -> None:
        self.cache.renamed(old, new)

    def forget(self, path: str) -> None:
        self.cache.drop([path])

    def clear(self) -> int:
        freed = self.cache.clear()
        self._seen = None                             # count (and with "all", queue) again
        self._last_drawn.clear()                      # drawn again at once, not held back
        with self._cond:
            self._cond.notify_all()
        return freed

    # -- the workers

    def start(self) -> None:
        if self._threads or self._stop:
            return
        for lane in ("now", "background"):
            t = threading.Thread(target=self._lane, args=(lane,), name=f"previews-{lane}", daemon=True)
            t.start()
            self._threads.append(t)

    def close(self) -> None:
        self._stop = True
        with self._cond:
            self._cond.notify_all()
        for t in self._threads:
            t.join(timeout=5)
        self._threads = []
        for lane, pool in self._pools.items():
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)
            self._pools[lane] = None
        self.cache.close()

    def _pool(self, lane: str) -> Executor:
        pool = self._pools[lane]
        if pool is None:
            if self.processes:
                pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                                           initializer=_lower_priority if lane == "background" else None)
            else:
                pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"previews-draw-{lane}")
            self._pools[lane] = pool
        return pool

    def _run(self, lane: str, job: Dict[str, Any]) -> "Future[Tuple[Optional[bytes], Optional[str]]]":
        try:
            return self._pool(lane).submit(work, job)
        except BrokenProcessPool:                     # the worker died earlier: a new one
            self._pools[lane] = None
            return self._pool(lane).submit(work, job)

    def _not_before(self, path: str) -> float:
        last = self._last_drawn.get(path)
        return 0.0 if last is None else last + REDRAW_EVERY

    def _next(self, lane: str) -> Optional[str]:
        """The next file for this lane ("now": priority NOW; "background": the others), or None."""
        now = time.monotonic()
        with self._cond:
            ready = [(prio, nb, p) for p, (prio, nb) in self._queue.items()
                     if nb <= now and (prio == NOW) == (lane == "now") and p not in self._drawing]
            if not ready:
                return None
            _, _, path = min(ready)
            del self._queue[path]
            self._drawing.add(path)
            return path

    def _lane(self, lane: str) -> None:
        while not self._stop:
            if lane == "background":
                try:
                    self._refill()
                except Exception:                     # never stop drawing; the log has the details
                    log.exception("Previews: the list of files to draw couldn't be made")
            path = self._next(lane)
            if path is None:
                with self._cond:
                    self._cond.wait(0.5 if lane == "now" else 1.0)
                continue
            try:
                self._draw(lane, path)
            finally:
                with self._cond:
                    self._drawing.discard(path)
                    self.status["drawing"] = len(self._queue) + len(self._drawing)

    def _draw(self, lane: str, path: str) -> None:
        version = file_version(path)
        if version is None:
            return
        try:
            picture, error = self._run(lane, {"path": path, "style": self.style(), "panels": None}).result()
        except BrokenProcessPool as e:               # the file stopped the worker: say so, don't retry
            self._pools[lane] = None
            picture, error = None, f"Drawing this file stopped the drawing process ({e or 'it ended unexpectedly'})."
        except Exception as e:
            log.exception("Previews: %s couldn't be drawn", path)
            picture, error = None, f"The preview couldn't be drawn ({e}); the details are in the log."
        if file_version(path) != version:            # changed while drawing: drawn again a little later
            with self._cond:
                self._queue.setdefault(path, (NEAR, time.monotonic() + REDRAW_EVERY))
            return
        self.cache.put(path, version, picture, error)
        self._last_drawn[path] = time.monotonic()
        self.status["drawn"] = min(self.status["drawn"] + 1, self.status["total"] or self.status["drawn"] + 1)

    def _refill(self) -> None:
        """After the Library's index changed (or the mode did): drop the pictures of files that
        are gone, and with "all", queue every file whose picture isn't current."""
        seen = (self.generation(), self.mode())
        if seen == self._seen:
            return
        self._seen = seen
        mode = seen[1]
        files = self.files()
        cached = self.cache.versions()
        gone = [p for p in cached if p not in files]
        if gone:
            self.cache.drop(gone)
        todo = [p for p, v in files.items() if cached.get(p) != v and not p.lower().endswith(".lbd.writing")]
        self.status.update({"total": len(files), "drawn": len(files) - len(todo)})
        with self._cond:
            if mode == "all":
                for p in todo:
                    if p not in self._queue and p not in self._drawing and not self.chosen(p):
                        self._queue[p] = (ALL, self._not_before(p))
            else:                                     # no longer every file: only what was asked
                for p in [p for p, (prio, _) in self._queue.items() if prio == ALL]:
                    del self._queue[p]
            self.status["drawing"] = len(self._queue) + len(self._drawing)
            self._cond.notify_all()
