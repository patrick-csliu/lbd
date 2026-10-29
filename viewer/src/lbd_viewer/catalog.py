"""LBD's own database (the "catalog"): what LBD remembers about data files, kept on this computer.

Data files hold data, metadata and their figure's settings. Everything else LBD remembers about
a file lives here and never in the file: the Explore view of each file (what was plotted, the
chosen traces, colour map, scales, limits and zoom) and the Library preview a user chose for a
file in Explore (plan 8c: only the picture, never how it was made; it can't be drawn again, so
it lives here and not in the preview cache).

- One SQLite file, `catalog.sqlite`, in LBD's local data folder (`catalog_dir`): never a roaming
  or synced folder, as SQLite files must not be synced while open. Rebuildable: losing it loses
  only remembered views.
- A database that can't be read is moved aside (`catalog.broken-<time>.sqlite`) and a new one is
  started; `problem` then says so, once, for the user.
- Several browser pages may save the same file's view: the last save wins (it is view state only).
- The schema has a version (`PRAGMA user_version`); later versions add tables and migrate
  (1 → 2: the chosen previews' table; the remembered views are kept).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = 2
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
        # key: "id:<the file's id>" (identical copies share it) or "path:<path>" (files without an
        # id, or copies that differ); version: the file's (size, mtime) when it was chosen
        db.execute("""CREATE TABLE IF NOT EXISTS chosen_previews (
                          key TEXT PRIMARY KEY,
                          path TEXT NOT NULL,
                          picture BLOB NOT NULL,
                          chosen_at REAL NOT NULL,
                          version TEXT NOT NULL)""")
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
            db.execute("DELETE FROM chosen_previews WHERE key = ?", ("path:" + new,))
            db.execute("UPDATE chosen_previews SET key = ?, path = ? WHERE key = ?", ("path:" + new, new, "path:" + old))
            db.execute("UPDATE chosen_previews SET path = ? WHERE path = ?", (new, old))

    # -- previews chosen in Explore (plan 8c)

    def choose_preview(self, key: str, path: str, picture: bytes, version: str) -> float:
        """Keep the picture a user chose as a file's Library preview; returns when (time.time())."""
        now = time.time()
        with self._lock:
            self._connect().execute(
                "INSERT INTO chosen_previews (key, path, picture, chosen_at, version) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET path = excluded.path, picture = excluded.picture, "
                "chosen_at = excluded.chosen_at, version = excluded.version",
                (key, path, picture, now, version))
        return now

    def chosen_preview(self, keys) -> Optional[Dict[str, Any]]:
        """The chosen preview under the first of these keys that has one: {key, path, picture,
        chosen_at, version}, or None."""
        with self._lock:
            db = self._connect()
            for key in keys:
                row = db.execute("SELECT key, path, picture, chosen_at, version FROM chosen_previews WHERE key = ?",
                                 (key,)).fetchone()
                if row is not None:
                    return dict(zip(("key", "path", "picture", "chosen_at", "version"), row))
        return None

    def forget_preview(self, keys) -> int:
        """Forget the chosen previews under these keys; returns how many there were."""
        with self._lock:
            db = self._connect()
            return sum(db.execute("DELETE FROM chosen_previews WHERE key = ?", (k,)).rowcount for k in keys)


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


# The remembered Explore view's shape. Version 2 (plan 4) holds panels; a record without a
# version is one plot (LBD 1.3.0-dev before panels) and is read as one panel.
STATE_VERSION = 2
PANEL_DEFAULTS: Dict[str, Any] = {"active": 0, "layout": "side", "sync": {"x": True, "y": False, "sliders": True}}


def upgrade(state: Dict[str, Any]) -> Dict[str, Any]:
    """A remembered view in the newest shape: an older record becomes one panel (nothing in it is
    lost); missing keys get their defaults."""
    if "version" not in state:
        state = {"version": STATE_VERSION, "panels": [state]}
    out = {**PANEL_DEFAULTS, **state}
    out["sync"] = {**PANEL_DEFAULTS["sync"], **(state.get("sync") or {})}
    return out


def fitting(remembered: Dict[str, Any], now: Dict[str, Any], state: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The remembered view (upgraded) with only the panels that still fit the file, and a note
    naming the ones left out; (None, why) when none fits."""
    state = upgrade(state)
    kept, why = [], []
    for k, panel in enumerate(state["panels"]):
        reason = misfit(remembered, now, panel)
        if reason:
            why.append(f"panel {k + 1}: {reason}")
        else:
            kept.append(k)
    if not kept:
        return None, "; ".join(why) or "it has no panels"
    active = kept.index(state["active"]) if state["active"] in kept else 0
    state = {**state, "panels": [state["panels"][k] for k in kept], "active": active}
    return state, ("; ".join(why) if why else None)
