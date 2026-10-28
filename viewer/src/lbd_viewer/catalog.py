"""LBD's own database (the "catalog"): what LBD remembers about data files, kept on this computer.

Data files hold data, metadata and their figure's settings. Everything else LBD remembers about
a file lives here and never in the file: for now the Explore view of each file (what was plotted,
the chosen traces, colour map, scales, limits and zoom), later the file index, tags and stars.

- One SQLite file, `catalog.sqlite`, in LBD's local data folder (`catalog_dir`): never a roaming
  or synced folder, as SQLite files must not be synced while open. Rebuildable: losing it loses
  only remembered views.
- A database that can't be read is moved aside (`catalog.broken-<time>.sqlite`) and a new one is
  started; `problem` then says so, once, for the user.
- Several browser pages may save the same file's view: the last save wins (it is view state only).
- The schema has a version (`PRAGMA user_version`); later versions add tables and migrate.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
KEEP_VIEWS = 5000          # remembered Explore views; the oldest beyond this are forgotten


def catalog_dir(settings_dir: Path) -> Path:
    r"""Where the database lives: LBD's local data folder (`%LOCALAPPDATA%\lbd`, `~/.local/share/lbd`,
    `~/Library/Application Support/lbd`), which never roams with a Windows profile. When the
    settings were moved on purpose (LBD_CONFIG_DIR, tests), it stays next to them."""
    import platformdirs

    if Path(settings_dir) != Path(platformdirs.user_config_dir("lbd", appauthor=False, roaming=True)):
        return Path(settings_dir)
    return Path(platformdirs.user_data_dir("lbd", appauthor=False, roaming=False))


class Catalog:
    def __init__(self, directory: Path, keep: int = KEEP_VIEWS):
        self.path = Path(directory) / "catalog.sqlite"
        self.keep = keep
        self.problem: Optional[str] = None        # set when a broken database was replaced
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None

    # -- connection

    def _connect(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            db = self._open()
        except sqlite3.DatabaseError as e:
            broken = self.path.with_name(f"catalog.broken-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")
            self.path.replace(broken)
            self.problem = (f"LBD's database ({self.path}) couldn't be read ({e}), so the Explore views it "
                            f"remembered were reset. The old file was kept as {broken}.")
            db = self._open()
        self._db = db
        return db

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            self._prepare(db)
        except sqlite3.DatabaseError:
            db.close()                                   # so the file can be moved aside (Windows)
            raise
        return db

    @staticmethod
    def _prepare(db: sqlite3.Connection) -> None:
        db.execute("PRAGMA journal_mode=WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(f"it was made by a newer LBD (schema {version}, this LBD reads {SCHEMA_VERSION})")
        db.execute("""CREATE TABLE IF NOT EXISTS explore_views (
                          path TEXT PRIMARY KEY,
                          structure TEXT NOT NULL,
                          state TEXT NOT NULL,
                          updated REAL NOT NULL)""")
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # -- remembered Explore views

    def view(self, path: str) -> Optional[Dict[str, Any]]:
        """{"structure": ..., "state": ...} remembered for a file, or None."""
        with self._lock:
            row = self._connect().execute("SELECT structure, state FROM explore_views WHERE path = ?",
                                          (path,)).fetchone()
        if row is None:
            return None
        return {"structure": json.loads(row[0]), "state": json.loads(row[1])}

    def remember(self, path: str, structure: Dict[str, Any], state: Dict[str, Any]) -> None:
        with self._lock:
            db = self._connect()
            db.execute("INSERT INTO explore_views (path, structure, state, updated) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(path) DO UPDATE SET structure = excluded.structure, state = excluded.state, "
                       "updated = excluded.updated",
                       (path, json.dumps(structure), json.dumps(state), time.time()))
            db.execute("DELETE FROM explore_views WHERE path NOT IN "
                       "(SELECT path FROM explore_views ORDER BY updated DESC, rowid DESC LIMIT ?)", (self.keep,))

    def forget(self, path: str) -> None:
        with self._lock:
            self._connect().execute("DELETE FROM explore_views WHERE path = ?", (path,))

    def renamed(self, old: str, new: str) -> None:
        """A file was renamed or moved by LBD: its remembered view follows it."""
        with self._lock:
            db = self._connect()
            db.execute("DELETE FROM explore_views WHERE path = ?", (new,))
            db.execute("UPDATE explore_views SET path = ? WHERE path = ?", (new, old))


def structure(header) -> Dict[str, Any]:
    """A file's shape, to tell whether a remembered view still fits it: its axes (name, length)
    and values (name, axes, type)."""
    return {"axes": {n: int(len(a.data)) for n, a in header.axes.items()},
            "values": {n: {"axes": list(v.axes), "dtype": str(v.dtype)} for n, v in header.values.items()}}


def misfit(remembered: Dict[str, Any], now: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    """Why a remembered view no longer fits the file (an axis or value it uses is gone or changed),
    or None. Longer or shorter axes still fit (data added; positions beyond the end are dropped
    when shown)."""
    spec = state.get("spec") or {}
    used_values = list(spec.get("values") or [])
    if spec.get("x") in now["values"] or spec.get("x") in remembered.get("values", {}):
        used_values.append(spec["x"])
    for name in used_values:
        if name not in now["values"]:
            return f"the value '{name}' is gone"
        old = remembered.get("values", {}).get(name)
        if old and old["axes"] != now["values"][name]["axes"]:
            return f"the value '{name}' now has the axes {now['values'][name]['axes']}"
    for key in ("x", "y", "series"):
        name = spec.get(key)
        if name and name != "none" and name not in now["axes"] and name not in now["values"]:
            return f"the axis '{name}' is gone"
    return None
