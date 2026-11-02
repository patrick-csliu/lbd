"""The Library's index of data files (plan 8a): every .lbd file under the open folders, with
what the Library lists, filters and searches by, kept on this computer.

- One SQLite file, `library.sqlite`, next to LBD's database (`catalog_dir`). It is a cache: it
  holds nothing that isn't in the files, so deleting it costs only the time to read the files
  again. One that can't be read (or was made by a newer LBD) is deleted and built again.
- A background thread walks the open folders: a file is read again only when its version (size
  and modification time) changed. While the Library is shown it checks every few seconds,
  otherwise every minute, and at once when woken (a folder added or removed, a setting changed).
- With "read headers" off (the setting for cloud storage, where opening a file downloads it),
  only what the disk tells is stored (name, size, dates); a file's header is read when it is
  asked for (`file`).
- Files are only read, never written or locked; one that can't be read stays listed, with the
  reason.
- Files with the same id (format 1.1: the measurement's identity) are compared after each scan:
  **copies** (the same size and modification time, or else the same content hash, read only for
  such pairs) or a **conflict** (they differ: one was changed after copying, or an id was copied
  by hand). Nothing is decided for the user; `same_id` says what differs.
- Labels (star, project, users, tags, comment) come from the folders' sidecars (labels.py); the
  index keeps a copy per file for listing, filtering and searching, worked out again whenever
  files or sidecars change (library_labels.py), which also follows renamed and moved files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import scan

SCHEMA_VERSION = 3
LIBRARY_FILE = "library.sqlite"
# How often the open folders are checked: while the Library is shown, and otherwise.
ACTIVE_EVERY, IDLE_EVERY, ACTIVE_FOR = 3.0, 60.0, 30.0
SORTS = {
    "name": "COALESCE(NULLIF(title, ''), name) COLLATE NOCASE",
    "date": "sort_time",
    "sweep": "points",
    "values": "value_names COLLATE NOCASE",
    "folder": "folder COLLATE NOCASE",
    "size": "size",
    "file": "name COLLATE NOCASE",
    "modified": "mtime",
}
ROW_FIELDS = ["path", "root", "folder", "name", "size", "mtime", "read", "title", "description", "created",
              "day", "date_from_file", "sweep", "points", "value_names", "error", "id", "parent_id",
              "copies", "conflict", "star", "project", "users", "tags", "comment"]
LABEL_SORTS = {"star": "star", "project": "project COLLATE NOCASE", "users": "users COLLATE NOCASE",
               "tags": "tags COLLATE NOCASE", "comment": "comment COLLATE NOCASE", "copies": "copies"}
log = logging.getLogger("lbd_viewer")


def _version(st: os.stat_result) -> str:
    return f"{st.st_mtime_ns}-{st.st_size}"


def parse_created(text: Optional[str]) -> Optional[Tuple[float, str]]:
    """(UTC timestamp, day "YYYY-MM-DD" in the file's own time zone) of a `created` text, or
    None when it is missing or not a date and time with an offset."""
    if not text:
        return None
    t = text.strip()
    try:
        when = datetime.fromisoformat(t[:-1] + "+00:00" if t.endswith(("Z", "z")) else t)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return when.timestamp(), when.date().isoformat()


def _flatten(meta: Any, prefix: str = "") -> Iterable[str]:
    """Keys and values of nested metadata as words to search (large arrays left out)."""
    if isinstance(meta, dict):
        for k, v in meta.items():
            yield str(k)
            yield from _flatten(v, f"{prefix}{k}.")
    elif isinstance(meta, list):
        for v in meta[:50]:
            yield from _flatten(v, prefix)
    elif meta is not None and not isinstance(meta, dict):
        yield str(meta)


def row_from_summary(path: Path, root: str, st: os.stat_result, summary: Dict[str, Any]) -> Dict[str, Any]:
    """A row of the index from a file's header summary (server.file_summary)."""
    row = _stat_row(path, root, st)
    created = parse_created(summary.get("created"))
    if created:
        row["sort_time"], row["day"], row["date_from_file"] = created[0], created[1], 0
    # the sweep: axes with more than one point that values lie on; not a data point's axes (format
    # 1.2); a group's points count once, as many as its most points a value lies on (format 2.0)
    used = [a for a in summary["axes"] if a.get("role") != "point" and any(a["name"] in v["axes"] for v in summary["values"])]
    swept = [a for a in used if a["length"] > 1 and not a.get("group")]
    groups = {}
    for a in used:
        if a.get("group"):
            groups[a["group"]] = max(groups.get(a["group"], 0), a["length"])
    parts = [str(a["length"]) for a in swept] + [f"{n} (variable)" for n in groups.values()]
    points = math.prod([a["length"] for a in swept] + list(groups.values())) if parts else 0
    sweep = "×".join(parts)
    if groups and len(parts) == 1:
        sweep = f"{next(iter(groups.values()))} points (variable)"
    values = summary["values"]
    words = [summary.get("title") or "", path.name, summary.get("description") or ""]
    for item in summary["axes"] + values:
        words += [item["name"], item.get("label") or "", item.get("unit") or ""]
    words += list(_flatten(summary.get("meta") or {}))
    row.update({
        "read": 1, "title": summary.get("title") or "", "description": summary.get("description") or "",
        "id": summary.get("id"), "parent_id": summary.get("parent_id"),
        "created": summary.get("created"), "writer": summary.get("writer"), "lbd_version": summary.get("lbd_version"),
        "sweep": sweep, "points": points,
        "value_names": ", ".join(v["name"] for v in values),
        "searchable": "\n".join(w for w in words if w).lower(),
        "summary": json.dumps(summary),
    })
    return row


def _stat_row(path: Path, root: str, st: os.stat_result, error: Optional[str] = None) -> Dict[str, Any]:
    """A row from what the disk tells: name, size, dates (the date from the file's time)."""
    rel = os.path.relpath(path.parent, root)
    local = datetime.fromtimestamp(st.st_mtime).astimezone()
    return {
        "path": str(path), "root": root, "folder": "" if rel == "." else rel.replace(os.sep, "/"), "name": path.name,
        "version": _version(st), "size": st.st_size, "mtime": st.st_mtime, "read": 0, "title": "", "description": "",
        "created": None, "sort_time": st.st_mtime, "day": local.date().isoformat(), "date_from_file": 1,
        "writer": None, "lbd_version": None, "sweep": "", "points": 0, "value_names": "",
        "searchable": path.name.lower(), "summary": None, "error": error, "seen": time.time(),
        "id": None, "parent_id": None, "fsid": f"{st.st_dev}:{st.st_ino}", "hash": None, "copies": 0, "conflict": 0,
    }


def outermost(roots: Iterable[str]) -> List[str]:
    """The roots, without those inside another (a folder opened twice is indexed once)."""
    resolved = sorted({str(Path(r).resolve()) for r in roots}, key=len)
    out: List[str] = []
    for r in resolved:
        if not any(os.path.normcase(r).startswith(os.path.normcase(o).rstrip("\\/") + os.sep) or
                   os.path.normcase(r) == os.path.normcase(o) for o in out):
            out.append(r)
    return out


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class LibraryIndex:
    def __init__(self, directory: Path, roots: Callable[[], List[str]], read_headers: Callable[[], bool],
                 summarize: Optional[Callable[[Path], Dict[str, Any]]] = None):
        self.path = Path(directory) / LIBRARY_FILE
        self.roots, self.read_headers = roots, read_headers
        self._summarize = summarize
        self._db: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()           # the connection
        self._scanning = threading.Lock()        # one scan at a time
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        self.last_request = 0.0                  # when the Library last asked (it is shown)
        self.generation = 0                      # changes whenever the index does
        self.status: Dict[str, Any] = {"indexing": False, "done": 0, "total": 0, "errors": [], "scans": 0}
        self.missing: List[Dict[str, Any]] = []          # labels whose file can't be found
        self.notes: List[str] = []                       # about labels, for the page (told once)
        self._sidecar_state: Optional[Dict[str, Optional[str]]] = None

    def trash(self, path: Path) -> None:
        """Move a file (a merged sync conflict copy) to the Recycle Bin."""
        from .files import trash

        trash(path)

    # -- the database

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._db = self._open()
            except sqlite3.DatabaseError as e:      # a cache: start again
                log.warning("the Library index %s couldn't be read (%s); it is built again", self.path, e)
                for p in (self.path, self.path.with_name(self.path.name + "-wal"), self.path.with_name(self.path.name + "-shm")):
                    p.unlink(missing_ok=True)
                self._db = self._open()
        return self._db

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION and version != 0:
                raise sqlite3.DatabaseError(f"made by another LBD (schema {version}, this one uses {SCHEMA_VERSION})")
            db.execute("""CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, root TEXT NOT NULL, folder TEXT NOT NULL, name TEXT NOT NULL,
                version TEXT NOT NULL, size INTEGER, mtime REAL, read INTEGER NOT NULL,
                title TEXT, description TEXT, created TEXT, sort_time REAL, day TEXT, date_from_file INTEGER,
                writer TEXT, lbd_version TEXT, sweep TEXT, points INTEGER, value_names TEXT,
                searchable TEXT, summary TEXT, error TEXT, seen REAL,
                id TEXT, parent_id TEXT, fsid TEXT, hash TEXT, copies INTEGER DEFAULT 0, conflict INTEGER DEFAULT 0,
                star INTEGER DEFAULT 0, project TEXT, users TEXT DEFAULT '', tags TEXT DEFAULT '',
                comment TEXT DEFAULT '', label_text TEXT DEFAULT '')""")
            db.execute("CREATE TABLE IF NOT EXISTS sidecars (folder TEXT PRIMARY KEY)")
            db.execute("CREATE INDEX IF NOT EXISTS files_id ON files (id)")
            db.execute("CREATE INDEX IF NOT EXISTS files_root ON files (root)")
            db.execute("CREATE INDEX IF NOT EXISTS files_day ON files (day)")
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.DatabaseError:
            db.close()
            raise
        return db

    def close(self) -> None:
        self.stop()
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # -- reading files

    def _summary(self, path: Path) -> Dict[str, Any]:
        if self._summarize is not None:
            return self._summarize(path)
        import lbd

        from .server import file_summary, quiet_writing   # the same summary as /api/file
        with quiet_writing():                     # a file being written: its status is shown instead
            return file_summary(lbd.info(path))

    def _read(self, path: Path, root: str, st: os.stat_result) -> Dict[str, Any]:
        try:
            return row_from_summary(path, root, st, self._summary(path))
        except Exception as e:                     # damaged, not LBD, newer format, …: listed, with why
            row = _stat_row(path, root, st, error=str(e) or type(e).__name__)
            row["read"] = 1                        # tried: read again only when the file changes
            return row

    def _write(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        with self._lock:
            db = self._connect()
            db.execute("BEGIN")
            db.executemany(f"INSERT OR REPLACE INTO files ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           [[r[c] for c in cols] for r in rows])
            db.execute("COMMIT")

    # -- indexing

    def scan(self) -> bool:
        """Bring the index up to date with the open folders now; True when anything changed."""
        with self._scanning:
            roots = outermost(self.roots())
            read = bool(self.read_headers())
            errors: List[Dict[str, str]] = []
            found: List[Tuple[Path, str, os.stat_result]] = []
            for root in roots:
                for p in scan.walk_files(Path(root), errors):
                    if not scan.is_lbd(p.name):
                        continue
                    try:
                        found.append((p, root, p.stat()))
                    except OSError as e:
                        errors.append({"path": str(p), "error": e.strerror or str(e)})
            with self._lock:
                known = {r[0]: (r[1], r[2], r[3], r[4]) for r in
                         self._connect().execute("SELECT path, version, read, root, fsid FROM files")}
            todo = [(p, root, st) for p, root, st in found
                    if (k := known.get(str(p))) is None or k[0] != _version(st) or k[2] != root
                    or (read and not k[1])]
            self.status.update({"indexing": bool(todo), "done": 0, "total": len(todo), "errors": errors})
            batch: List[Dict[str, Any]] = []
            for i, (p, root, st) in enumerate(todo):
                batch.append(self._read(p, root, st) if read else _stat_row(p, root, st))
                if len(batch) >= 100:
                    self._write(batch)
                    batch = []
                    self.generation += 1
                self.status["done"] = i + 1
            self._write(batch)
            gone = set(known) - {str(p) for p, _, _ in found}
            # renamed or moved on the same drive: the file system's id is the same
            new_by_fsid = {f"{st.st_dev}:{st.st_ino}": str(p) for p, _, st in found if str(p) not in known}
            renames = {g: new_by_fsid[known[g][3]] for g in gone if known[g][3] in new_by_fsid}
            if gone:
                with self._lock:
                    db = self._connect()
                    db.execute("BEGIN")
                    db.executemany("DELETE FROM files WHERE path = ?", [(g,) for g in gone])
                    db.execute("COMMIT")
            changed = bool(todo or gone)
            if changed:
                self._compare_same_ids()
            sidecars = self._sidecars([p for p, _, _ in found])
            if changed or sidecars != self._sidecar_state:
                from . import library_labels

                try:
                    self.notes += library_labels.apply(self, renames)
                except Exception as e:                   # labels must never stop the list
                    log.exception("Library: labels couldn't be worked out")
                    self.notes.append(f"The Library's labels couldn't be worked out ({e}); the details are in the log.")
                self._sidecar_state = self._sidecars([p for p, _, _ in found])
                changed = True
            if changed:
                self.generation += 1
            self.status.update({"indexing": False, "scans": self.status["scans"] + 1})
            return changed

    def _sidecars(self, files: List[Path]) -> Dict[str, Optional[str]]:
        """The version of the label file of every folder with data files (or labels before)."""
        from .labels import SIDECAR

        folders = {str(p.parent) for p in files}
        with self._lock:
            folders |= {f for (f,) in self._connect().execute("SELECT folder FROM sidecars")}
        out = {}
        for f in folders:
            try:
                st = os.stat(os.path.join(f, SIDECAR))
                out[f] = _version(st)
            except OSError:
                out[f] = None
            for name in _listdir(f):                       # sync conflict copies count as changes
                if name.lower().startswith(".lbd-library") and name != SIDECAR and ".broken-" not in name:
                    out[f] = (out[f] or "") + "+" + name
        return out

    def refresh(self, path: str) -> None:
        """Read one file again now (LBD itself just changed it), then compare same ids."""
        p = Path(path).resolve()
        st = p.stat()
        with self._lock:
            r = self._connect().execute("SELECT root FROM files WHERE path = ?", (str(p),)).fetchone()
        root = r[0] if r else next((o for o in outermost(self.roots())
                                    if str(p).lower().startswith(o.lower().rstrip("\\/") + os.sep)), str(p.parent))
        self._write([self._read(p, root, st)])
        self._compare_same_ids()
        self.generation += 1

    def compare_same_ids(self) -> None:
        self._compare_same_ids()
        self.generation += 1

    def _compare_same_ids(self) -> None:
        """Copies or conflict, for every id that more than one file has (after a scan)."""
        with self._lock:
            db = self._connect()
            groups: Dict[str, List[Tuple[str, str, int, Optional[str]]]] = {}
            for path, ident, version, size, h in db.execute(
                    "SELECT path, id, version, size, hash FROM files WHERE id IN "
                    "(SELECT id FROM files WHERE id IS NOT NULL GROUP BY id HAVING COUNT(*) > 1)"):
                groups.setdefault(ident, []).append((path, version, size, h))
        verdicts: Dict[str, Tuple[int, int]] = {}
        for ident, members in groups.items():
            first = members[0]
            same = True
            for m in members[1:]:
                if m[1] == first[1]:                       # same size and modification time
                    continue
                if m[2] != first[2]:                       # another size: not the same content
                    same = False
                    break
                if self._hash(first) != self._hash(m):    # same size, other time: compare contents
                    same = False
                    break
            for path, *_ in members:
                verdicts[path] = (len(members) - 1, 0 if same else 1)
        with self._lock:
            db = self._connect()
            db.execute("BEGIN")
            db.execute("UPDATE files SET copies = 0, conflict = 0 WHERE copies != 0 OR conflict != 0")
            db.executemany("UPDATE files SET copies = ?, conflict = ? WHERE path = ?",
                           [(c, k, p) for p, (c, k) in verdicts.items()])
            db.execute("COMMIT")

    def _hash(self, member: Tuple[str, str, int, Optional[str]]) -> Optional[str]:
        """A file's content hash (SHA-256), read once per version and kept in the index."""
        path, version, _, known = member
        if known:
            return known
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
        except OSError:
            return None
        digest = h.hexdigest()
        with self._lock:
            self._connect().execute("UPDATE files SET hash = ? WHERE path = ? AND version = ?", (digest, path, version))
        return digest

    def same_id(self, path: str) -> Dict[str, Any]:
        """The other files with this file's id, whether they are copies or a conflict, and what
        differs between this file and each other one (from the headers; "the data itself" when
        only the contents differ)."""
        self.last_request = time.monotonic()
        p = str(Path(path).resolve())
        with self._lock:
            db = self._connect()
            me = db.execute("SELECT id, summary, conflict, size, mtime FROM files WHERE path = ?", (p,)).fetchone()
            if not me or not me[0]:
                return {"id": None, "others": [], "conflict": False}
            others = db.execute("SELECT path, summary, size, mtime, version FROM files WHERE id = ? AND path != ?",
                                (me[0], p)).fetchall()
        mine = json.loads(me[1]) if me[1] else {}
        out = []
        for path_o, summary_o, size_o, mtime_o, _ in others:
            theirs = json.loads(summary_o) if summary_o else {}
            out.append({"path": path_o, "size": size_o, "mtime": mtime_o, "title": theirs.get("title"),
                        "differs": differences(mine, theirs) if me[2] else [],
                        "newer": mtime_o > me[4]})
        return {"id": me[0], "conflict": bool(me[2]), "size": me[3], "mtime": me[4], "others": out}

    def start(self) -> None:
        """Keep the index up to date in the background (once; later calls do nothing)."""
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="library-index", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def wake(self) -> None:
        """Check the folders now (a folder added or removed, a setting changed)."""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop:
            try:
                self.scan()
            except Exception:                      # never stop indexing; the log has the details
                log.exception("Library index: a scan failed")
            active = time.monotonic() - self.last_request < ACTIVE_FOR
            self._wake.wait(ACTIVE_EVERY if active else IDLE_EVERY)
            self._wake.clear()

    # -- what the Library asks

    def _where(self, folder: Optional[str], q: str, date: str, project: str = "", tags: Iterable[str] = (),
               users: Iterable[str] = (), starred: bool = False, conflicts: bool = False) -> Tuple[str, List[Any]]:
        clauses, args = [], []
        if project:                                        # this project and the ones inside it
            clauses.append("(project = ? OR project LIKE ? ESCAPE '\\')")
            args += [project, _like(project + "/")[1:]]
        for key, chosen in (("tags", list(tags)), ("users", list(users))):
            if chosen:                                     # any of them (OR), each with its sub-labels
                ors = []
                for label in chosen:
                    ors.append(f"({key} LIKE ? ESCAPE '\\' OR {key} LIKE ? ESCAPE '\\')")
                    args += [_like("\n" + label + "\n"), _like("\n" + label + "/")]
                clauses.append("(" + " OR ".join(ors) + ")")
        if starred:
            clauses.append("star = 1")
        if conflicts:
            clauses.append("conflict = 1")
        if folder:
            f = str(Path(folder).resolve())
            clauses.append("(path LIKE ? ESCAPE '\\')")
            args.append(_like(f.rstrip("\\/") + os.sep)[1:])
        if date:
            clauses.append("day LIKE ?")
            args.append(date + "%")
        for word in q.lower().split():
            clauses.append("(searchable || ' ' || label_text) LIKE ? ESCAPE '\\'")
            args.append(_like(word))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args

    def list(self, folder: Optional[str] = None, q: str = "", date: str = "", sort: str = "date",
             order: str = "desc", offset: int = 0, limit: int = 200, project: str = "",
             tags: Iterable[str] = (), users: Iterable[str] = (), starred: bool = False,
             conflicts: bool = False) -> Dict[str, Any]:
        """One page of the files under `folder` (None: every open folder) matching the search
        words (all of them) and the date ("2026", "2026-03" or "2026-03-14"), sorted."""
        self.last_request = time.monotonic()
        sorts = {**SORTS, **LABEL_SORTS}
        if sort not in sorts:
            raise ValueError(f"sort must be one of {', '.join(sorts)}, not {sort!r}")
        direction = "DESC" if order == "desc" else "ASC"
        where, args = self._where(folder, q, date, project, tags, users, starred, conflicts)
        with self._lock:
            db = self._connect()
            total = db.execute(f"SELECT COUNT(*) FROM files{where}", args).fetchone()[0]
            cur = db.execute(f"SELECT {', '.join(ROW_FIELDS)} FROM files{where} "
                             f"ORDER BY {sorts[sort]} {direction}, path LIMIT ? OFFSET ?",
                             args + [max(1, min(limit, 1000)), max(0, offset)])
            rows = [dict(zip(ROW_FIELDS, r)) for r in cur]
        for r in rows:
            r["writing"] = writing_status(r["path"])
            r["users"] = [u for u in (r["users"] or "").split("\n") if u]
            r["tags"] = [t for t in (r["tags"] or "").split("\n") if t]
            r["star"] = bool(r["star"])
        return {"rows": rows, "total": total, "generation": self.generation}

    def facets(self, folder: Optional[str] = None, q: str = "", date: str = "") -> Dict[str, Any]:
        """The date tree (year → month → day, with counts) of the files under `folder` matching
        the search, the folder tree of every open folder with the number of files below each, and
        the number of files in all of them (`total`: a folder opened inside another counts once)."""
        self.last_request = time.monotonic()
        where, args = self._where(folder, q, "")
        with self._lock:
            db = self._connect()
            days = db.execute(f"SELECT day, COUNT(*) FROM files{where} GROUP BY day", args).fetchall()
            folders = db.execute("SELECT root, folder, COUNT(*) FROM files GROUP BY root, folder").fetchall()
            total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            conflicts = db.execute(f"SELECT COUNT(*) FROM files{where}{' AND' if where else ' WHERE'} conflict = 1",
                                   args).fetchone()[0]
            lw, la = self._where(folder, q, date)
            labelled = db.execute(f"SELECT project, users, tags, star FROM files{lw}", la).fetchall()
        dates: Dict[str, Dict[str, Dict[str, int]]] = {}
        for day, n in days:
            if day:
                y, m, d = day.split("-")
                dates.setdefault(y, {}).setdefault(m, {})[d] = n
        trees = {"projects": {}, "users": {}, "tags": {}}
        starred = 0
        for project, users, tags, star in labelled:
            starred += 1 if star else 0
            if project:
                _count(trees["projects"], project)
            for u in (users or "").split("\n"):
                if u:
                    _count(trees["users"], u)
            for t in (tags or "").split("\n"):
                if t:
                    _count(trees["tags"], t)
        return {"dates": dates, "folders": self._folder_tree(folders), "total": total, "conflicts": conflicts,
                "projects": _label_tree(trees["projects"]), "users": _label_tree(trees["users"]),
                "tags": _label_tree(trees["tags"]), "starred": starred, "missing": len(self.missing),
                "generation": self.generation}

    def _folder_tree(self, counts: List[Tuple[str, str, int]]) -> List[Dict[str, Any]]:
        trees = []
        indexed = outermost(self.roots())
        for root in [str(Path(r).resolve()) for r in self.roots()]:
            node = {"path": root, "name": Path(root).name or root, "count": 0, "children": []}
            trees.append(node)
            base = next((o for o in indexed if os.path.normcase(root) == os.path.normcase(o)
                         or os.path.normcase(root).startswith(os.path.normcase(o).rstrip("\\/") + os.sep)), root)
            inner = os.path.relpath(root, base).replace(os.sep, "/") if base != root else ""
            for r, folder, n in counts:
                if os.path.normcase(r) != os.path.normcase(base):
                    continue
                rel = folder if not inner else (folder[len(inner) + 1:] if folder.startswith(inner + "/") else
                                                "" if folder == inner else None)
                if rel is None:
                    continue
                node["count"] += n
                cur = node
                for part in [p for p in rel.split("/") if p]:
                    child = next((c for c in cur["children"] if c["name"] == part), None)
                    if child is None:
                        child = {"path": str(Path(cur["path"]) / part), "name": part, "count": 0, "children": []}
                        cur["children"].append(child)
                    child["count"] += n
                    cur = child
            _sort_tree(node)
        return trees

    def versions(self) -> Dict[str, str]:
        """Every indexed file's version (size and modification time), by path: what the
        previews (previews.py) are drawn for."""
        with self._lock:
            return dict(self._connect().execute("SELECT path, version FROM files"))

    def identity(self, path: str) -> Tuple[Optional[str], bool, int]:
        """A file's id as indexed, whether it is in a conflict (same id, other content), and
        how many other indexed files have that id."""
        p = str(Path(path).resolve())
        with self._lock:
            db = self._connect()
            r = db.execute("SELECT id, conflict FROM files WHERE path = ?", (p,)).fetchone()
            if not r or not r[0]:
                return None, False, 0
            n = db.execute("SELECT COUNT(*) FROM files WHERE id = ? AND path != ?", (r[0], p)).fetchone()[0]
        return r[0], bool(r[1]), n

    def file(self, path: str) -> Dict[str, Any]:
        """A file's summary (as /api/file gives it), from the index; read now when it isn't there
        yet, is out of date, or wasn't read (headers off). Raises FileNotFoundError or the
        reading error."""
        self.last_request = time.monotonic()
        p = Path(path).resolve()
        st = p.stat()
        with self._lock:
            r = self._connect().execute("SELECT version, summary, root FROM files WHERE path = ?", (str(p),)).fetchone()
        if r and r[0] == _version(st) and r[1]:
            return {**json.loads(r[1]), "writing": writing_status(str(p))}   # the status now, not when read
        summary = self._summary(p)                 # raises: the page shows why
        root = r[2] if r else next((o for o in outermost(self.roots())
                                    if str(p).lower().startswith(o.lower().rstrip("\\/") + os.sep)), str(p.parent))
        self._write([row_from_summary(p, root, st, summary)])
        self.generation += 1
        return summary


def writing_status(path: str) -> Optional[str]:
    """For a file being written (name.lbd.writing): "measuring" (here), "elsewhere" (on another
    computer, synced here), "silent" (no sign from that computer lately) or "stopped" (live.py);
    else None."""
    if not scan.is_writing(path):
        return None
    from . import live

    try:
        state = live.shared().status(path)["state"]
    except OSError:                              # gone meanwhile (finished: renamed)
        return None
    return None if state == "gone" else state


def _listdir(folder: str) -> List[str]:
    try:
        return os.listdir(folder)
    except OSError:
        return []


def _count(tree: Dict[str, Any], label: str) -> None:
    """Count a nested label (a/b/c) in a tree of {part: {"n": count, "c": children}}."""
    node = tree
    for part in label.split("/"):
        child = node.setdefault(part, {"n": 0, "c": {}})
        child["n"] += 1
        node = child["c"]


def _label_tree(tree: Dict[str, Any], prefix: str = "") -> List[Dict[str, Any]]:
    """[{label, name, count, children}] sorted by name: what the filter boxes show."""
    out = []
    for name in sorted(tree, key=str.lower):
        label = f"{prefix}{name}"
        out.append({"label": label, "name": name, "count": tree[name]["n"],
                    "children": _label_tree(tree[name]["c"], label + "/")})
    return out


def differences(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """What differs between two files' header summaries, in words for the page; "the data itself"
    when the headers agree (the contents differ)."""
    out = []
    for key, word in (("title", "title"), ("description", "description"), ("created", "date (created)")):
        if (a.get(key) or "") != (b.get(key) or ""):
            out.append(word)
    if set((a.get("meta") or {})) != set((b.get("meta") or {})) or (a.get("meta") or {}) != (b.get("meta") or {}):
        out.append("metadata")
    shape = lambda s: sorted((v["name"], tuple(v["shape"])) for v in s.get("values", []))   # noqa: E731
    if shape(a) != shape(b):
        out.append("values or their sizes")
    axes = lambda s: sorted((x["name"], x["length"], x.get("min"), x.get("max")) for x in s.get("axes", []))   # noqa: E731
    if axes(a) != axes(b):
        out.append("axes")
    return out or ["the data itself"]


def _sort_tree(node: Dict[str, Any]) -> None:
    node["children"].sort(key=lambda c: c["name"].lower())
    for c in node["children"]:
        _sort_tree(c)
