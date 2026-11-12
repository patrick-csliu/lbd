"""Labels of data files (plan 8b): a star, a project, users, tags and a comment, kept in a small
sidecar file in each folder, `.lbd-library.json`, next to the files it describes. Since plan 17
the data files hold their labels too (`/labels`, spec §1.9), written shortly after each edit
(label_writer.py); the sidecar stays the record of every change, for merging and history. The
format is defined in docs/developers/library-sidecar.md.

- Each file's entry is found by the file's id (format 1.1), else by its name and `created`.
- Every field, and every single tag and user, records when it was last set or removed and on
  which computer (`changed`), so two edits are merged item by item: the newer one wins, a
  removal is remembered too (a removed tag doesn't come back), an exact tie keeps both values
  (with a note), and a value that lost is kept in the entry's `history`. Nothing is lost
  silently, even when two computers' clocks disagree.
- Writing never overwrites another writer's change: a lock file (`.lbd-library.lock`, made
  exclusively, kept fresh while its writer works) keeps two LBD programs on one computer apart; just before the sidecar is
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
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SIDECAR = ".lbd-library.json"
LOCK = ".lbd-library.lock"
FORMAT, VERSION = "lbd-library", 1
SCALARS = ("star", "project", "comment")
LISTS = ("users", "tags")
KINDS = ("project", "users", "tags")   # the labels that can be kept without a file (`labels`)
OWN_KEYS = ("format", "version", "files", "labels", "read_only")   # anything else a newer writer added is kept
LOCK_STALE = 10.0                      # a lock unchanged this long (watched here) was left behind (a crash)
LOCK_WAIT = 15.0                       # how long a writer waits for another one
LOCK_REFRESH = 2.0                     # how often a working writer touches its lock file


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


def has_labels(e: Dict[str, Any]) -> bool:
    return bool(e.get("star") or e.get("project") or e.get("comment") or e.get("users") or e.get("tags"))


def is_empty(e: Dict[str, Any]) -> bool:
    """No label, nothing decided about the file and no change recorded (the entry can go). An
    entry whose labels were all removed stays, with the times of the removals: they are newer
    than the labels an older copy of the data file may still hold (plan 17)."""
    return not (has_labels(e) or e.get("accepted") or last_change(e)[0])


def last_change(e: Dict[str, Any]) -> Tuple[str, str]:
    """(time, computer) of the newest change recorded in an entry; ("", "") if none."""
    best = ("", "")
    changed = e.get("changed") or {}
    for key in SCALARS:
        m = changed.get(key)
        if m and m[0] > best[0]:
            best = (m[0], m[1] if len(m) > 1 else "")
    for key in LISTS:
        for m in (changed.get(key) or {}).values():
            if m and m[0] > best[0]:
                best = (m[0], m[1] if len(m) > 1 else "")
    return best


def same_labels(e: Dict[str, Any], file_labels: Dict[str, Any]) -> bool:
    """Whether an entry shows the same labels as a data file holds (`/labels`, as lbd reads it)."""
    return (bool(e.get("star")) == bool(file_labels.get("star")) and (e.get("project") or None) == (file_labels.get("project") or None)
            and (e.get("comment") or "") == (file_labels.get("comment") or "")
            and sorted(e.get("users") or []) == sorted(file_labels.get("users") or [])
            and sorted(e.get("tags") or []) == sorted(file_labels.get("tags") or []))


FROM_FILE = "the data file"     # the computer recorded for labels taken from a data file


def file_changes(e: Optional[Dict[str, Any]], file_labels: Dict[str, Any]) -> Dict[str, Any]:
    """What a data file's labels change in an entry: each field, tag and user of the file counts
    as set at the file's `written` time, so it wins where the entry has no newer change of its
    own (a script's labels, or another viewer's edit this one hasn't seen); a newer edit in the
    Library, also a removal, wins over the file. Empty: nothing to take."""
    when = file_labels.get("written") or ""
    if not when:
        return {}
    e = e or new_entry(None, "", None)
    changed = e.get("changed") or {}
    out: Dict[str, Any] = {}
    wanted = {"star": bool(file_labels.get("star")), "project": file_labels.get("project") or None,
              "comment": file_labels.get("comment") or ""}
    for key in SCALARS:
        mine = (changed.get(key) or [""])[0]
        if mine < when and (e.get(key) or ({"star": False, "comment": ""}.get(key))) != wanted[key]:
            out[key] = wanted[key]
    for key in LISTS:
        marks = changed.get(key) or {}
        held = file_labels.get(key) or []
        add = [x for x in held if x not in (e.get(key) or []) and (marks.get(x) or [""])[0] < when]
        remove = [x for x in (e.get(key) or []) if x not in held and (marks.get(x) or [""])[0] < when]
        if add:
            out[f"add_{key}"] = add
        if remove:
            out[f"remove_{key}"] = remove
    return out


def take_from_file(e: Dict[str, Any], file_labels: Dict[str, Any]) -> bool:
    """The entry takes what is newer in the data file's labels (`file_changes`), recorded at the
    file's `written` time; the values it had before are kept in its history. Returns whether
    anything changed."""
    changes = file_changes(e, file_labels)
    if not changes:
        return False
    when = file_labels["written"]
    before = {k: copy.deepcopy(e.get(k)) for k in (*SCALARS, *LISTS)}
    apply(e, changes, when=when, by=FROM_FILE)
    history = e.setdefault("history", [])
    history.append({"field": "labels", "value": before, "changed": [when, FROM_FILE],
                    "note": "changed by newer labels in the data file"})
    del history[:-50]
    return True


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


# ---- labels kept without a file (a new project before its first measurement) ------------------

def kept(doc: Dict[str, Any]) -> Dict[str, List[str]]:
    """The labels the folder keeps although no file needs to have them, per kind."""
    marks = doc.get("labels") or {}
    return {k: sorted((label for label, m in (marks.get(k) or {}).items() if m and m[-1]), key=str.lower) for k in KINDS}


def keep(doc: Dict[str, Any], kind: str, label: str, on: bool = True,
         when: Optional[str] = None, by: Optional[str] = None) -> str:
    """Keep (or stop keeping) a label in the folder; recorded like a tag (newer wins on a merge)."""
    if kind not in KINDS:
        raise LabelsError(f"unknown kind of label {kind!r}; use one of {', '.join(KINDS)}")
    label = _clean(label)
    doc.setdefault("labels", {}).setdefault(kind, {})[label] = [when or now(), by or computer(), bool(on)]
    return label


def _merge_kept(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind in KINDS:
        ma, mb = (a.get("labels") or {}).get(kind) or {}, (b.get("labels") or {}).get(kind) or {}
        merged = {}
        for label in set(ma) | set(mb):
            ra, rb = ma.get(label), mb.get(label)
            merged[label] = rb if rb and (not ra or rb[0] > ra[0]) else ra
        if merged:
            out[kind] = merged
    return out


def _under(label: str, top: str) -> bool:
    """`label` is `top` or nested inside it ("Qubit A/Device 3" is under "Qubit A")."""
    return label == top or label.startswith(top + "/")


def renamed_label(label: str, old: str, new: str) -> str:
    """`label` with its `old` part replaced by `new` ("Qubit A/Device 3", "Qubit A" → "Qubit B")."""
    return new + label[len(old):]


def relabel(e: Dict[str, Any], kind: str, old: str, new: Optional[str],
            when: Optional[str] = None, by: Optional[str] = None) -> bool:
    """In one file's entry: `old` and every label under it become `new/…` (None: removed). Each
    change is recorded as an edit would be. Returns whether the entry changed."""
    when, by = when or now(), by or computer()
    if kind == "project":
        p = e.get("project")
        if not p or not _under(p, old):
            return False
        apply(e, {"project": renamed_label(p, old, new) if new else None}, when, by)
        return True
    hit = [x for x in e.get(kind, []) if _under(x, old)]
    if not hit:
        return False
    changes: Dict[str, Any] = {f"remove_{kind}": hit}
    if new:
        changes[f"add_{kind}"] = [renamed_label(x, old, new) for x in hit]
    apply(e, changes, when, by)
    return True


def merge_docs(a: Dict[str, Any], b: Dict[str, Any], notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Two sidecars of one folder as one (entries matched by id, else by name; kept labels by
    label, the newer decision wins; keys of a newer format kept)."""
    out = {**{k: v for k, v in b.items() if k not in OWN_KEYS}, **{k: v for k, v in a.items() if k not in OWN_KEYS},
           "format": FORMAT, "version": VERSION, "files": []}
    marks = _merge_kept(a, b)
    if marks:
        out["labels"] = marks
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


class _Lock:
    """The folder's lock file, held by this writer. While held, a small thread touches the file
    every LOCK_REFRESH seconds, so a writer that works long (a slow or busy computer) never looks
    like one that stopped. It holds this writer's text ("computer pid token"); release removes the
    file only if it still holds that text, so a lock another writer has taken meanwhile stays."""

    def __init__(self, path: Path, text: str):
        self.path, self.text = path, text
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._keep_fresh, name="labels-lock", daemon=True)
        self._thread.start()

    def _mine(self) -> bool:
        try:
            return self.path.read_text(encoding="utf-8") == self.text
        except (OSError, ValueError):
            return False

    def _keep_fresh(self) -> None:
        while not self._stop.wait(LOCK_REFRESH):
            try:
                if self._mine():
                    os.utime(self.path)
            except OSError:
                pass                                   # tried again in a moment

    def release(self) -> None:
        from .files import _while_in_use

        self._stop.set()
        self._thread.join()
        if self._mine():
            try:
                _while_in_use(self.path.unlink, wait=2.0)   # a waiter may be looking at it (Windows)
            except OSError:
                pass                                   # stays; it counts as left behind after LOCK_STALE


def _lock(folder: Path) -> _Lock:
    """Take the folder's lock, waiting up to LOCK_WAIT for another writer. A lock counts as left
    behind (a writer that crashed) only when its file's time hasn't changed for LOCK_STALE seconds
    of this computer's clock while we watch: a working writer refreshes it, and the file's time is
    only compared with itself, so a clock difference between computers (shared folder) doesn't
    matter."""
    lock = Path(folder) / LOCK
    text = f"{computer()} {os.getpid()} {uuid.uuid4().hex[:8]}"
    deadline = time.monotonic() + LOCK_WAIT
    seen: Optional[Tuple[int, int]] = None            # the lock file's (mtime, size) as last seen
    since = 0.0                                        # ... unchanged since then (this computer's clock)
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, text.encode())
            os.close(fd)
            return _Lock(lock, text)
        except FileExistsError:
            try:
                st = lock.stat()
                if seen != (st.st_mtime_ns, st.st_size):
                    seen, since = (st.st_mtime_ns, st.st_size), time.monotonic()
                elif time.monotonic() - since > LOCK_STALE:
                    _remove_left_behind(lock, seen)
                    seen = None
                    continue
            except FileNotFoundError:
                continue
            except PermissionError:                    # being removed by its writer (see below)
                pass
            if time.monotonic() > deadline:
                raise LabelsError(f"The labels in {folder} were not changed: another LBD program was changing "
                                  f"them and didn't finish within {LOCK_WAIT:.0f} s. Try again in a moment.") from None
            time.sleep(0.02)
        except PermissionError:
            # On Windows a lock file another writer has just removed stays "delete pending" for a
            # moment, and making it again is denied as if the folder were read-only. So only a
            # denial that lasts means the folder can't be written to.
            if time.monotonic() > deadline:
                raise LabelsError(f"The labels in {folder} were not changed: the folder is read-only (or not "
                                  "yours to change); copy the files to a folder you can write to.") from None
            time.sleep(0.02)


def _remove_left_behind(lock: Path, seen: Tuple[int, int]) -> None:
    """Remove a lock left behind, if it is still the one watched (not one just made by another writer)."""
    try:
        st = lock.stat()
        if (st.st_mtime_ns, st.st_size) == seen:
            lock.unlink()
    except (FileNotFoundError, PermissionError):
        pass


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
        # what this version doesn't know (written by a newer LBD of the same format version) is kept
        doc = {**{k: v for k, v in doc.items() if k not in OWN_KEYS}, "format": FORMAT, "version": VERSION,
               "files": doc["files"], **({"labels": doc["labels"]} if doc.get("labels") else {})}
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
        lock.release()


def _write(p: Path, doc: Dict[str, Any]) -> None:
    from .files import _while_in_use

    if not doc["files"] and not any(kept(doc).values()):    # nothing left to keep: no file
        if p.exists():
            _while_in_use(lambda: p.unlink())
        return
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        _while_in_use(lambda: os.replace(tmp, p))
    except PermissionError:
        raise LabelsError(f"The labels in {p.parent} were not changed: the folder is read-only (or not yours "
                          "to change); copy the files to a folder you can write to.") from None
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
