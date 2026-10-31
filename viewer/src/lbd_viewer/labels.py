"""Labels of data files (plan 8b): a star, a project, users, tags and a comment, kept in a small
sidecar file in each folder, `.lbd-library.json`, next to the files it describes. Data files are
never written for a label. The format is defined in docs/developers/library-sidecar.md.

- Each file's entry is found by the file's id (format 1.1), else by its name and `created`.
- Every field, and every single tag and user, records when it was last set or removed and on
  which computer (`changed`), so two edits are merged item by item: the newer one wins, a
  removal is remembered too (a removed tag doesn't come back), an exact tie keeps both values
  (with a note), and a value that lost is kept in the entry's `history`. Nothing is lost
  silently, even when two computers' clocks disagree.
- Writing never overwrites another writer's change: a lock file (`.lbd-library.lock`, made
  exclusively) keeps two LBD programs on one computer apart; just before the sidecar is
  replaced it is read again, and a change made meanwhile (another computer, through sync) is
  merged first. Sync tools' conflict copies (`.lbd-library_<computer>_<date>_Conflict.json`,
  "… (conflicted copy) …", …) are merged in and then moved to the Recycle Bin.
- A sidecar written by a newer LBD is read but not written; a damaged one is set aside
  (`.lbd-library.broken-<time>.json`) and a new one started. Both say so.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SIDECAR = ".lbd-library.json"
LOCK = ".lbd-library.lock"
FORMAT, VERSION = "lbd-library", 1
SCALARS = ("star", "project", "comment")
LISTS = ("users", "tags")
LOCK_STALE = 10.0                      # a lock older than this was left behind (a crash)
LOCK_WAIT = 3.0                        # how long a writer waits for another one


class LabelsError(Exception):
    """Labels can't be read or written; the message says why and what to do."""


def computer() -> str:
    return socket.gethostname() or "this computer"


def now() -> str:
    """A change time: UTC, milliseconds, so texts sort as times."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---- entries ---------------------------------------------------------------------------------

def new_entry(ident: Optional[str], name: str, created: Optional[str]) -> Dict[str, Any]:
    return {"id": ident, "name": name, "created": created, "star": False, "project": None, "comment": "",
            "users": [], "tags": [], "changed": {"users": {}, "tags": {}}, "history": []}


def is_empty(e: Dict[str, Any]) -> bool:
    """No label left and nothing decided about the file (the entry can go)."""
    return not (e.get("star") or e.get("project") or e.get("comment") or e.get("users") or e.get("tags")
                or e.get("accepted"))


def _clean(label: str) -> str:
    """A label as stored: parts of a nested label without spaces around the slashes."""
    parts = [p.strip() for p in str(label).split("/")]
    if not all(parts):
        raise LabelsError(f"'{label}' has an empty part; write labels like 'Qubit A/Device 3'")
    return "/".join(parts)


def apply(e: Dict[str, Any], changes: Dict[str, Any], when: Optional[str] = None, by: Optional[str] = None) -> None:
    """Change an entry: star (bool), project (text or None), comment (text), add_/remove_tags,
    add_/remove_users (lists). Each change is recorded with its time and computer."""
    when, by = when or now(), by or computer()
    changed = e.setdefault("changed", {"users": {}, "tags": {}})
    for key in SCALARS:
        if key in changes:
            value = changes[key]
            if key == "star":
                value = bool(value)
            elif key == "project":
                value = _clean(value) if value else None
            else:
                value = str(value or "")
            if e.get(key) != value:
                e[key] = value
                changed[key] = [when, by]
    for key in LISTS:
        marks = changed.setdefault(key, {})
        for label in changes.get(f"add_{key}", []) or []:
            label = _clean(label)
            if label not in e[key]:
                e[key].append(label)
            marks[label] = [when, by, True]
        for label in changes.get(f"remove_{key}", []) or []:
            label = _clean(label)
            if label in e[key]:
                e[key].remove(label)
            marks[label] = [when, by, False]
        e[key].sort(key=str.lower)


def merge(a: Dict[str, Any], b: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Two versions of one file's labels as one: per field, per tag and per user the newer change
    wins (a field never changed counts as oldest); an exact tie with different values keeps
    `a`'s and notes it; every value that lost is added to `history`."""
    out = copy.deepcopy(a)
    ca, cb = a.get("changed", {}), b.get("changed", {})
    changed = out.setdefault("changed", {"users": {}, "tags": {}})
    history = out.setdefault("history", [])
    for key in SCALARS:
        ta, tb = (ca.get(key) or ["", ""]), (cb.get(key) or ["", ""])
        va, vb = a.get(key), b.get(key)
        if va == vb:
            if tb[0] > ta[0]:
                changed[key] = tb
            continue
        if tb[0] > ta[0]:
            out[key] = vb
            changed[key] = tb
            history.append({"field": key, "value": va, "changed": ta})
        else:
            history.append({"field": key, "value": vb, "changed": tb})
            if tb[0] == ta[0] and notes is not None:
                notes.append(f"{a.get('name')}: {key} was changed at the same moment on two computers; "
                             f"kept {va!r} (the other value, {vb!r}, is in its history)")
    for key in LISTS:
        ma, mb = ca.get(key, {}), cb.get(key, {})
        marks = changed.setdefault(key, {})
        labels = set(a.get(key, [])) | set(b.get(key, [])) | set(ma) | set(mb)
        result = []
        for label in labels:
            ra, rb = ma.get(label), mb.get(label)
            on_a, on_b = label in a.get(key, []), label in b.get(key, [])
            if rb and (not ra or rb[0] > ra[0]):
                marks[label], on = rb, on_b
            elif ra:
                marks[label], on = ra, on_a
            else:
                on = on_a or on_b                      # no record on either side (written by hand)
            if on:
                result.append(label)
        out[key] = sorted(result, key=str.lower)
    for h in b.get("history", []):
        if h not in history:
            history.append(h)
    del history[:-50]                                  # the latest 50 are enough to look back
    for key in ("id", "name", "created"):
        out[key] = out.get(key) or b.get(key)
    accepted = sorted(set(a.get("accepted") or []) | set(b.get("accepted") or []))
    if accepted:                                       # "the same measurement", decided on either side
        out["accepted"] = accepted
    return out


def merge_docs(a: Dict[str, Any], b: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Two sidecars of one folder as one (entries matched by id, else by name)."""
    out = {"format": FORMAT, "version": VERSION, "files": []}
    def key(e):
        return ("id", e["id"]) if e.get("id") else ("name", e.get("name"))
    index: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    for e in a.get("files", []):
        index[key(e)] = copy.deepcopy(e)
    for e in b.get("files", []):
        k = key(e)
        index[k] = merge(index[k], e, notes) if k in index else copy.deepcopy(e)
    out["files"] = [e for e in index.values() if not is_empty(e)]
    return out


# ---- the file --------------------------------------------------------------------------------

def _version(p: Path) -> Optional[str]:
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    return f"{st.st_mtime_ns}-{st.st_size}"


def read(folder: Path, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """The folder's labels (an empty document when there is no sidecar). A damaged sidecar is set
    aside and an empty one used, with a note; one of a newer version gets "read_only": True."""
    p = Path(folder) / SIDECAR
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"format": FORMAT, "version": VERSION, "files": []}
    try:
        doc = json.loads(text)
        if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("files"), list):
            raise ValueError("not an LBD label file")
    except ValueError as e:
        aside = p.with_name(f".lbd-library.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            p.replace(aside)
        except OSError:
            raise LabelsError(f"the labels in {p} can't be read ({e}) and the file couldn't be set aside; "
                              "fix or remove it") from None
        if notes is not None:
            notes.append(f"The labels file {p} couldn't be read ({e}); it was kept as {aside.name} and "
                         "the labels of that folder start afresh.")
        return {"format": FORMAT, "version": VERSION, "files": []}
    if not isinstance(doc.get("version"), int) or doc["version"] > VERSION:
        doc["read_only"] = True
        if notes is not None:
            notes.append(f"The labels in {p} were written by a newer LBD (version {doc.get('version')}); "
                         "they are shown but can't be changed here. Update LBD to change them.")
    return doc


def conflict_copies(folder: Path) -> List[Path]:
    """Sync tools' copies of the sidecar made when two computers changed it while apart."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        low = n.lower()
        if low.startswith(".lbd-library") and low.endswith(".json") and n != SIDECAR and ".broken-" not in low:
            out.append(Path(folder) / n)
    return sorted(out)


def _lock(folder: Path) -> Path:
    lock = Path(folder) / LOCK
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{computer()} {os.getpid()}".encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE:
                    lock.unlink()                      # left behind by a writer that stopped
                    continue
            except FileNotFoundError:
                continue
            except PermissionError:                    # being removed by its writer (see below)
                pass
            if time.monotonic() > deadline:
                raise LabelsError(f"the labels of {folder} are being changed by another LBD program; "
                                  "try again in a moment") from None
            time.sleep(0.02)
        except PermissionError:
            # On Windows a lock file another writer has just removed stays "delete pending" for a
            # moment, and making it again is denied as if the folder were read-only. So only a
            # denial that lasts means the folder can't be written to.
            if time.monotonic() > deadline:
                raise LabelsError(f"labels can't be saved in {folder}: the folder is read-only (or not "
                                  "yours to change); copy the files to a folder you can write to") from None
            time.sleep(0.02)


def update(folder: Path, change: Callable[[Dict[str, Any]], None],
           trash: Optional[Callable[[Path], None]] = None) -> List[str]:
    """Change the folder's labels: `change` edits the document in place. Never overwrites a change
    made meanwhile by another program or computer (merged first). Returns notes for the user."""
    folder = Path(folder)
    notes: List[str] = []
    lock = _lock(folder)
    try:
        p = folder / SIDECAR
        before = _version(p)
        doc = read(folder, notes)
        if doc.get("read_only"):
            raise LabelsError(notes[-1])
        copies = conflict_copies(folder)
        for c in copies:                               # two computers' changes while apart
            try:
                doc = merge_docs(doc, json.loads(c.read_text(encoding="utf-8")), notes)
            except (OSError, ValueError):
                notes.append(f"{c.name} looks like a copy of the labels made by a sync tool but can't be "
                             "read; it was left as it is.")
                copies.remove(c)
        change(doc)
        if _version(p) != before:                      # changed while we worked: merge, don't overwrite
            doc = merge_docs(read(folder, notes), doc, notes)
        doc["files"] = [e for e in doc["files"] if not is_empty(e)]
        doc = {"format": FORMAT, "version": VERSION, "files": doc["files"]}
        _write(p, doc)
        for c in copies:
            try:
                (trash or (lambda q: q.unlink()))(c)
                notes.append(f"Labels changed on two computers at once ({c.name}) were merged; the copy "
                             "was moved to the Recycle Bin.")
            except OSError as e:
                notes.append(f"Labels in {c.name} were merged, but it couldn't be removed ({e}).")
        return notes
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _write(p: Path, doc: Dict[str, Any]) -> None:
    from .files import _while_in_use

    if not doc["files"]:
        if p.exists():
            _while_in_use(lambda: p.unlink())
        return
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        _while_in_use(lambda: os.replace(tmp, p))
    except PermissionError:
        raise LabelsError(f"labels can't be saved in {p.parent}: the folder is read-only (or not yours "
                          "to change); copy the files to a folder you can write to") from None
    finally:
        if tmp.exists():
            tmp.unlink()


def find(doc: Dict[str, Any], ident: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    """A file's entry: by id, else (a file without id) by name."""
    for e in doc.get("files", []):
        if ident and e.get("id") == ident:
            return e
    if not ident:
        for e in doc.get("files", []):
            if not e.get("id") and e.get("name") == name:
                return e
    return None
