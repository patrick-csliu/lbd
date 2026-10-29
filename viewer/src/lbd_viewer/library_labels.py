"""Labels in the Library (plan 8b): which file each sidecar entry belongs to, labels shared by
copies, files followed when renamed or moved, and the actions that change labels or identities.

The sidecars (labels.py) are the original; the index (library.py) keeps a copy of each file's
labels for listing, filtering and searching. `apply` works that copy out again after a scan:

- An entry with an `id` belongs to the files with that id: in its own folder first; identical
  copies elsewhere share it (their sidecars' entries are merged for showing, and an edit is
  written to all of them). Copies in conflict (same id, different contents) don't share: each
  keeps its own folder's entry until the user resolves it.
- An entry whose file is gone is followed: by id (moved to another open folder), or for a file
  without id by the file system's file ID (renamed or moved on the same drive, seen by the
  scan), then by its `created` time when exactly one unlabelled file has it. The entry is moved
  to the sidecar of the file's new folder. Otherwise it is listed as missing until the user
  points it to a file or discards it.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import h5py

from . import labels

if TYPE_CHECKING:
    from .library import LibraryIndex

LABEL_KEYS = ("star", "project", "users", "tags", "comment")


def _rows(ix: "LibraryIndex") -> List[Dict[str, Any]]:
    with ix._lock:
        cur = ix._connect().execute("SELECT path, name, id, created, conflict, version, fsid FROM files")
        return [dict(zip(("path", "name", "id", "created", "conflict", "version", "fsid"), r)) for r in cur]


def _folders(ix: "LibraryIndex", rows: List[Dict[str, Any]]) -> List[str]:
    """Folders whose sidecar matters: those with data files, and those that had labels before."""
    out = {str(Path(r["path"]).parent) for r in rows}
    with ix._lock:
        out |= {f for (f,) in ix._connect().execute("SELECT folder FROM sidecars")}
    return sorted(out)


def apply(ix: "LibraryIndex", renames: Optional[Dict[str, str]] = None) -> List[str]:
    """Work out every file's labels from the sidecars again (after a scan or an edit); follow
    renamed or moved files. Returns notes for the user."""
    notes: List[str] = []
    renames = renames or {}
    rows = _rows(ix)
    by_path = {r["path"]: r for r in rows}
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if r["id"]:
            by_id.setdefault(r["id"], []).append(r)
    docs: Dict[str, Dict[str, Any]] = {}
    for folder in _folders(ix, rows):
        if (Path(folder) / labels.SIDECAR).exists():
            docs[folder] = labels.read(Path(folder), notes)
    shown: Dict[str, Dict[str, Any]] = {}                  # path -> the labels shown for it
    accepted: Dict[str, List[str]] = {}                    # id -> versions the user said are the same
    missing: List[Dict[str, Any]] = []
    moves: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []   # (from folder, entry, to row)
    labelled = set()

    def give(row, e):
        old = shown.get(row["path"])
        shown[row["path"]] = labels.merge(old, e) if old else e
        labelled.add(row["path"])

    for folder, doc in docs.items():
        for e in doc.get("files", []):
            if e.get("id"):
                here = [r for r in by_id.get(e["id"], []) if str(Path(r["path"]).parent) == folder]
                everywhere = by_id.get(e["id"], [])
                if e.get("accepted"):
                    accepted.setdefault(e["id"], []).extend(e["accepted"])
                if here:
                    for r in here:
                        give(r, e)
                    for r in everywhere:                   # identical copies elsewhere share it
                        if r not in here and not r["conflict"]:
                            give(r, e)
                elif everywhere:                           # moved to another open folder
                    moves.append((folder, e, everywhere[0]))
                else:
                    missing.append({"folder": folder, **_brief(e)})
            else:
                path = str(Path(folder) / e.get("name", ""))
                path = renames.get(path, path)              # renamed / moved on the same drive
                r = by_path.get(path)
                if r is None and e.get("created"):          # moved further: by its date, if unique
                    same = [x for x in rows if x["created"] == e["created"] and x["path"] not in labelled]
                    r = same[0] if len(same) == 1 else None
                if r is None:
                    missing.append({"folder": folder, **_brief(e)})
                elif str(Path(r["path"]).parent) == folder and r["name"] == e.get("name"):
                    give(r, e)
                else:
                    moves.append((folder, e, r))
    for frm, e, row in moves:
        notes += _move(frm, e, row, ix)
        give(row, e)
    _store(ix, rows, shown, accepted)
    ix.missing = missing
    with ix._lock:
        db = ix._connect()
        db.execute("BEGIN")
        db.execute("DELETE FROM sidecars")
        db.executemany("INSERT INTO sidecars (folder) VALUES (?)", [(f,) for f in docs])
        db.execute("COMMIT")
    return notes


def _brief(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e.get(k) for k in ("id", "name", "created", *LABEL_KEYS)}


def _move(frm: str, e: Dict[str, Any], row: Dict[str, Any], ix: "LibraryIndex") -> List[str]:
    """An entry follows its file to its new name or folder (both sidecars updated)."""
    to = str(Path(row["path"]).parent)
    moved = dict(e, name=row["name"], id=row["id"] or e.get("id"))
    notes = []
    if to != frm:
        notes += labels.update(Path(frm), lambda d: d.__setitem__("files", [x for x in d["files"] if x is not e and
                                                                            not _same_entry(x, e)]), ix.trash)
    def put(d):
        old = labels.find(d, moved.get("id"), moved["name"]) or (next((x for x in d["files"] if _same_entry(x, e)), None))
        if old is not None:
            d["files"].remove(old)
            merged = labels.merge(old, moved)
            merged["name"], merged["id"] = moved["name"], moved.get("id")   # where the file is now
            d["files"].append(merged)
        else:
            d["files"].append(moved)
    notes += labels.update(Path(to), put, ix.trash)
    return notes


def _same_entry(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a.get("id") or None, a.get("name")) == (b.get("id") or None, b.get("name"))


def _store(ix: "LibraryIndex", rows, shown, accepted) -> None:
    """The labels shown for each file into the index (and accepted conflicts cleared)."""
    out = []
    for r in rows:
        e = shown.get(r["path"]) or {}
        users, tags = e.get("users") or [], e.get("tags") or []
        text = " ".join([e.get("project") or "", *users, *tags, e.get("comment") or ""]).lower()
        out.append((1 if e.get("star") else 0, e.get("project"), _joined(users), _joined(tags),
                    e.get("comment") or "", text, r["path"]))
    with ix._lock:
        db = ix._connect()
        db.execute("BEGIN")
        db.executemany("UPDATE files SET star = ?, project = ?, users = ?, tags = ?, comment = ?, label_text = ? "
                       "WHERE path = ?", out)
        for ident, versions in accepted.items():           # "they are the same measurement"
            members = [r for r in rows if r["id"] == ident]
            if members and all(r["version"] in versions for r in members):
                db.execute("UPDATE files SET conflict = 0 WHERE id = ?", (ident,))
        db.execute("COMMIT")


def _joined(items: List[str]) -> str:
    """Labels stored for matching: one per line, with a line break on both ends."""
    return "\n" + "\n".join(items) + "\n" if items else ""


# ---- edits ------------------------------------------------------------------------------------

def _row(ix: "LibraryIndex", path: str) -> Dict[str, Any]:
    p = str(Path(path).resolve())
    with ix._lock:
        r = ix._connect().execute("SELECT path, name, id, created, conflict, version FROM files WHERE path = ?",
                                  (p,)).fetchone()
    if r is None:
        raise labels.LabelsError(f"{Path(path).name} isn't in the Library's list (yet); wait a moment and try again")
    return dict(zip(("path", "name", "id", "created", "conflict", "version"), r))


def set_labels(ix: "LibraryIndex", paths: List[str], changes: Dict[str, Any]) -> List[str]:
    """Change the labels of these files (and of their identical copies in the open folders)."""
    labels.apply(labels.new_entry(None, "", None), changes)   # a mistyped label stops here, before any write
    notes: List[str] = []
    targets: Dict[str, List[Dict[str, Any]]] = {}
    for path in paths:
        r = _row(ix, path)
        group = [r]
        if r["id"] and not r["conflict"]:
            with ix._lock:
                group += [dict(zip(("path", "name", "id", "created", "conflict", "version"), x)) for x in
                          ix._connect().execute("SELECT path, name, id, created, conflict, version FROM files "
                                                "WHERE id = ? AND path != ?", (r["id"], r["path"]))]
        for g in group:
            targets.setdefault(str(Path(g["path"]).parent), []).append(g)
    for folder, rows in targets.items():
        def change(doc, rows=rows):
            for r in rows:
                e = labels.find(doc, r["id"], r["name"])
                if e is None:
                    e = labels.new_entry(r["id"], r["name"], r["created"])
                    doc["files"].append(e)
                labels.apply(e, changes)
        try:
            notes += labels.update(Path(folder), change, ix.trash)
        except labels.LabelsError as err:
            notes.append(str(err))
    notes += apply(ix)
    ix.generation += 1
    return notes


def _write_id(path: str, version: str, new: str, parent: Optional[str]) -> None:
    """Write an id into an existing data file — only after the user asked; refused when the file
    changed since it was shown or another program has it open."""
    p = Path(path)
    st = p.stat()
    if f"{st.st_mtime_ns}-{st.st_size}" != version:
        raise labels.LabelsError(f"{p.name} changed since it was shown; nothing was written. Look at it again "
                                 "and repeat if still wanted.")
    try:
        with h5py.File(p, "r+") as f:
            f.attrs["id"] = new
            if parent:
                f.attrs["parent_id"] = parent
    except OSError as e:
        raise labels.LabelsError(f"{p.name} couldn't be changed ({e}); it may be open in another program. "
                                 "Close it there and try again. Nothing was written.") from None


def new_measurement(ix: "LibraryIndex", path: str) -> List[str]:
    """Make this file a separate measurement: a new id written into it (the old one as its
    parent_id); its labels are kept and no longer follow the other copies."""
    from lbd.io import new_uuid7

    r = _row(ix, path)
    new = new_uuid7()
    _write_id(r["path"], r["version"], new, r["id"])
    folder = Path(r["path"]).parent
    with ix._lock:                                          # another copy in this folder shares its entry
        shared = ix._connect().execute("SELECT COUNT(*) FROM files WHERE id = ? AND path != ? AND path LIKE ?",
                                       (r["id"], r["path"], str(folder) + os.sep + "%")).fetchone()[0]

    def change(doc):
        e = labels.find(doc, r["id"], r["name"])
        if e is not None and r["id"]:
            mine = dict(json.loads(json.dumps(e)), id=new, name=r["name"], accepted=[])
            if not shared:
                doc["files"].remove(e)
            doc["files"].append(mine)
    notes = labels.update(folder, change, ix.trash)
    ix.refresh(r["path"])
    return notes + apply(ix)


def same_measurement(ix: "LibraryIndex", path: str) -> List[str]:
    """The user says the files sharing this id are the same measurement though they differ:
    remembered (with their current versions) in their sidecars; their labels follow each other
    again. A later change to one of them brings the question back."""
    r = _row(ix, path)
    with ix._lock:
        members = ix._connect().execute("SELECT path, name, version FROM files WHERE id = ?", (r["id"],)).fetchall()
    versions = [v for _, _, v in members]
    notes: List[str] = []
    for folder in {str(Path(p).parent) for p, _, _ in members}:
        def change(doc, folder=folder):
            names = [n for p, n, _ in members if str(Path(p).parent) == folder]
            e = labels.find(doc, r["id"], names[0])
            if e is None:
                e = labels.new_entry(r["id"], names[0], r["created"])
                doc["files"].append(e)
            e["accepted"] = versions
        notes += labels.update(Path(folder), change, ix.trash)
    ix.compare_same_ids()
    return notes + apply(ix)


def duplicate(ix: "LibraryIndex", path: str, with_labels: bool = True) -> Tuple[str, List[str]]:
    """Copy a file as a new measurement next to it ("name (copy).lbd", never replacing a file):
    the copy gets a new id (the original's as parent_id); the original is not touched."""
    from lbd.io import new_uuid7

    r = _row(ix, path)
    src = Path(r["path"])
    k = 1
    while True:
        target = src.with_name(f"{src.stem} (copy{'' if k == 1 else f' {k}'}){src.suffix}")
        try:
            with open(target, "xb") as out, open(src, "rb") as inp:      # exclusive: never replaces
                shutil.copyfileobj(inp, out)
            break
        except FileExistsError:
            k += 1
    new = new_uuid7()
    with h5py.File(target, "r+") as f:
        f.attrs["id"] = new
        if r["id"]:
            f.attrs["parent_id"] = r["id"]
    notes: List[str] = []
    if with_labels:
        def change(doc):
            e = labels.find(doc, r["id"], r["name"])
            if e is not None:
                doc["files"].append(dict(json.loads(json.dumps(e)), id=new, name=target.name, accepted=[]))
        notes += labels.update(src.parent, change, ix.trash)
    ix.refresh(str(target))
    return str(target), notes + apply(ix)


def give_ids(ix: "LibraryIndex", paths: List[str]) -> List[str]:
    """Write an id into files that have none (asked by the user); their labels follow."""
    from lbd.io import new_uuid7

    notes: List[str] = []
    for path in paths:
        r = _row(ix, path)
        if r["id"]:
            continue
        new = new_uuid7()
        _write_id(r["path"], r["version"], new, None)
        def change(doc, r=r, new=new):
            e = labels.find(doc, None, r["name"])
            if e is not None:
                e["id"] = new
        notes += labels.update(Path(r["path"]).parent, change, ix.trash)
        ix.refresh(r["path"])
    return notes + apply(ix)


def renamed(ix: "LibraryIndex", old: str, new: str) -> List[str]:
    """A file renamed by LBD: its entry follows (same folder)."""
    old_p, new_p = Path(old), Path(new)
    def change(doc):
        for e in doc["files"]:
            if e.get("name") == old_p.name:
                e["name"] = new_p.name
    if (old_p.parent / labels.SIDECAR).exists():
        return labels.update(old_p.parent, change, ix.trash)
    return []


def trashed(ix: "LibraryIndex", path: str, ident: Optional[str]) -> List[str]:
    """A file moved to the Recycle Bin by LBD: its entry in its folder goes too."""
    p = Path(path)
    if not (p.parent / labels.SIDECAR).exists():
        return []
    return labels.update(p.parent, lambda doc: doc.__setitem__(
        "files", [e for e in doc["files"] if not ((ident and e.get("id") == ident) or (not e.get("id") and e.get("name") == p.name))]),
        ix.trash)


def resolve_missing(ix: "LibraryIndex", entry: Dict[str, Any], path: Optional[str]) -> List[str]:
    """A missing entry pointed to a file (it moves there), or discarded (path None)."""
    frm = entry["folder"]
    def gone(doc):
        doc["files"] = [e for e in doc["files"] if not ((entry.get("id") and e.get("id") == entry["id"]) or
                                                        (not entry.get("id") and e.get("name") == entry.get("name")))]
    notes: List[str] = []
    if path is None:
        notes += labels.update(Path(frm), gone, ix.trash)
        return notes + apply(ix)
    r = _row(ix, path)
    with open(Path(frm) / labels.SIDECAR, encoding="utf-8") as f:
        doc = json.load(f)
    e = next((x for x in doc["files"] if (entry.get("id") and x.get("id") == entry["id"]) or
              (not entry.get("id") and x.get("name") == entry.get("name"))), None)
    if e is None:
        raise labels.LabelsError("those labels are gone already (changed elsewhere); nothing was done")
    notes += _move(frm, e, r, ix)
    return notes + apply(ix)
