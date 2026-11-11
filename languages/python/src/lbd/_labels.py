"""Labels of a data file (spec §1.9): a star, a project, users, tags and a comment.

They are stored in the file's `/labels` group, so they travel with the file when it is copied or
moved. LBD Viewer's Library shows and edits the same labels. `written` records when they were
set, so the Library can tell which is newer: the labels in the file or its own label file.

A label is text; a nested label uses `/` between its parts ("Qubit A/Device 3"). Spaces around
the slashes are removed, and no part may be empty.
"""

from __future__ import annotations

import json
from collections.abc import MutableSet
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Mapping, Optional

import h5py
import numpy as np

KEYS = ("star", "project", "users", "tags", "comment")


def now() -> str:
    """A label time: UTC with milliseconds, e.g. '2026-11-11T09:30:00.125Z' (texts sort as times;
    the same text as LBD Viewer's label file uses)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean(label: Any, what: str) -> str:
    """A label as stored: the parts of a nested label without spaces around the slashes."""
    from .io import LBDError

    if not isinstance(label, str):
        raise TypeError(f"{what}: a label must be text, not {type(label).__name__} ({label!r})")
    parts = [p.strip() for p in label.split("/")]
    if not all(parts):
        raise LBDError(f"{what}: {label!r} is empty or has an empty part; write labels like 'Qubit A/Device 3'")
    return "/".join(parts)


class LabelSet(MutableSet):
    """The tags (or users) of a file: a set of labels, kept sorted (ignoring case).

    Use it like a Python set: `d.labels.tags.add("calibration")`, `.discard(...)`,
    `"calibration" in d.labels.tags`, `list(d.labels.tags)`.
    """

    def __init__(self, owner: "Labels", what: str, items: Iterable[Any] = ()):
        self._owner, self._what = owner, what
        self._items: List[str] = []
        for x in _labels_list(items, what):
            if x not in self._items:
                self._items.append(x)
        self._items.sort(key=str.lower)

    def __contains__(self, label: object) -> bool:
        return isinstance(label, str) and label in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def add(self, label: str) -> None:
        label = clean(label, self._what)
        if label not in self._items:
            self._items.append(label)
            self._items.sort(key=str.lower)
        self._owner._touch()

    def discard(self, label: str) -> None:
        label = clean(label, self._what)
        if label in self._items:
            self._items.remove(label)
        self._owner._touch()

    def update(self, labels: Iterable[str]) -> None:
        """Add several labels."""
        for x in _labels_list(labels, self._what):
            self.add(x)

    def __repr__(self) -> str:
        return repr(self._items)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (LabelSet, set, frozenset, list, tuple)):
            return sorted(self._items) == sorted(other)
        return NotImplemented

    __hash__ = None   # type: ignore[assignment]  # mutable


def _labels_list(items: Any, what: str) -> List[str]:
    if isinstance(items, str):
        raise TypeError(f"{what}: give a list of labels, e.g. [{items!r}], not one text")
    try:
        return [clean(x, what) for x in items]
    except TypeError as e:
        if "label must be text" in str(e):
            raise
        raise TypeError(f"{what}: give a list of labels, not {type(items).__name__}") from None


class Labels:
    """A file's labels: `star`, `project`, `users`, `tags` and `comment`.

    `d.labels` of every [`Dataset`][lbd.Dataset] (and [`Writer`][lbd.Writer]) is one. Set them
    one by one or all at once; each is checked at once, so a mistake shows before measuring:

    >>> d.labels.star = True
    >>> d.labels.project = "Cooldown 7"
    >>> d.labels.tags.add("calibration")
    >>> d.labels = {"project": "Cooldown 7", "tags": ["calibration"], "users": ["Ana"]}

    Attributes
    ----------
    star : bool
        Starred in LBD Viewer's Library.
    project : str or None
        The file's project; a nested one uses `/` ("Chip 3/Cooldown 7").
    users, tags : LabelSet
        Sets of labels (who measured it; free tags).
    comment : str
        Free text.
    written : str or None
        When the labels were last set (UTC, e.g. `"2026-11-11T09:30:00.125Z"`); None if they
        were never set. Changed by every change above.
    """

    def __init__(self, star: bool = False, project: Optional[str] = None, users: Iterable[str] = (),
                 tags: Iterable[str] = (), comment: str = ""):
        self._ready = False
        self.written: Optional[str] = None
        self.star = star
        self.project = project
        self.users = users
        self.tags = tags
        self.comment = comment
        self._ready = True
        self.written = now() if self else None

    @classmethod
    def of(cls, value: Any, what: str = "labels") -> "Labels":
        """`value` as Labels: a Labels (copied), a dict with the keys star, project, users, tags,
        comment, or None (no labels)."""
        from .io import LBDError

        if value is None:
            return cls()
        if isinstance(value, Labels):
            out = cls(value.star, value.project, value.users, value.tags, value.comment)
            out.written = value.written
            return out
        if not isinstance(value, Mapping):
            raise TypeError(f"{what} must be a dict like {{'tags': ['calibration'], 'star': True}} "
                            f"or lbd.Labels, not {type(value).__name__}")
        unknown = sorted(set(value) - set(KEYS))
        if unknown:
            raise LBDError(f"{what}: unknown key(s) {unknown}; the labels are {', '.join(KEYS)}")
        return cls(**value)

    def _touch(self) -> None:
        if getattr(self, "_ready", False):
            self.written = now()

    @property
    def star(self) -> bool:
        return self._star

    @star.setter
    def star(self, value: Any) -> None:
        if not isinstance(value, (bool, np.bool_)):
            raise TypeError(f"labels.star must be True or False, not {value!r}")
        self._star = bool(value)
        self._touch()

    @property
    def project(self) -> Optional[str]:
        return self._project

    @project.setter
    def project(self, value: Any) -> None:
        self._project = None if value is None or value == "" else clean(value, "labels.project")
        self._touch()

    @property
    def users(self) -> LabelSet:
        return self._users

    @users.setter
    def users(self, value: Iterable[str]) -> None:
        self._users = LabelSet(self, "labels.users", value)
        self._touch()

    @property
    def tags(self) -> LabelSet:
        return self._tags

    @tags.setter
    def tags(self, value: Iterable[str]) -> None:
        self._tags = LabelSet(self, "labels.tags", value)
        self._touch()

    @property
    def comment(self) -> str:
        return self._comment

    @comment.setter
    def comment(self, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"labels.comment must be text, not {type(value).__name__}")
        self._comment = value
        self._touch()

    def as_dict(self) -> dict:
        """The labels as a plain dict (lists for users and tags)."""
        return {"star": self.star, "project": self.project, "users": list(self.users),
                "tags": list(self.tags), "comment": self.comment}

    def __bool__(self) -> bool:
        """Whether any label is set."""
        return bool(self.star or self.project or self.comment or len(self.users) or len(self.tags))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Labels):
            return self.as_dict() == other.as_dict()
        if isinstance(other, Mapping):
            try:
                return self == Labels.of(other)
            except (TypeError, ValueError):
                return False
        return NotImplemented

    __hash__ = None   # type: ignore[assignment]  # mutable

    def __repr__(self) -> str:
        parts = [f"{k}={v!r}" for k, v in self.as_dict().items() if v]
        return f"Labels({', '.join(parts)})"


# ---- in the file ---------------------------------------------------------------------------------

def write(f: h5py.File, labels: Labels) -> None:
    """Write `/labels` (replacing it). Nothing is written for labels never set; labels that were
    set and then all removed are written empty, with their time, so that the removal counts."""
    if "labels" in f:
        del f["labels"]
    if not labels and labels.written is None:
        return
    g = f.create_group("labels")
    g.attrs["star"] = np.int8(1 if labels.star else 0)
    if labels.project:
        g.attrs["project"] = labels.project
    g.attrs["users"] = json.dumps(list(labels.users), ensure_ascii=False)
    g.attrs["tags"] = json.dumps(list(labels.tags), ensure_ascii=False)
    g.attrs["comment"] = labels.comment
    g.attrs["written"] = labels.written or now()


def read(g: Any, path: Path) -> Labels:
    """`/labels` as Labels. A part that can't be read is left out with a warning; reading goes on."""
    from .io import LBDWarning, _attr_str, _warn

    out = Labels()
    out._ready = False
    if not isinstance(g, h5py.Group):
        _warn(f"{path.name}: /labels is not a group; reading the file without its labels", LBDWarning)
        out._ready = True
        return out

    def part(key: str, action: Any) -> None:
        if key not in g.attrs:
            return
        try:
            action()
        except (TypeError, ValueError) as e:
            _warn(f"{path.name}: the label '{key}' can't be read ({e}); reading the file without it", LBDWarning)

    def star() -> None:
        raw = g.attrs["star"]
        if np.ndim(raw) != 0 or np.asarray(raw).dtype.kind not in "iub" or int(raw) not in (0, 1):
            raise ValueError(f"expected 0 or 1, got {raw!r}")
        out.star = bool(int(raw))

    def listed(key: str) -> Any:
        def action() -> None:
            text = _attr_str(g, key, "", path)
            items = json.loads(text)
            if not isinstance(items, list):
                raise ValueError("expected a JSON list of labels")
            setattr(out, key, items)
        return action

    part("star", star)
    part("project", lambda: setattr(out, "project", _attr_str(g, "project", "", path) or None))
    part("users", listed("users"))
    part("tags", listed("tags"))
    part("comment", lambda: setattr(out, "comment", _attr_str(g, "comment", "", path)))
    written = _attr_str(g, "written", "", path) if "written" in g.attrs else ""
    out._ready = True
    out.written = written or None
    return out
