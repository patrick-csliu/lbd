"""A data file's version: what tells LBD that the file changed (plan 17).

The version is the file's modification time and size. Every part of the viewer that keeps
something drawn or read from a file keys it by the version: the pages' check for changed files,
the memory cache, Explore's sessions, Save view's "changed since you opened it", the previews
and the Library's index.

When LBD itself writes only labels into a file (label_writer.py), the data and the saved view
are unchanged, so nothing of that should be read or drawn again. `label_written` records the
new version as the same content as the one before, and `content` gives the version before the
label write as long as the file stays as LBD left it. Any other change (a script's
`lbd.set_labels`, a new measurement) gives a new version as before. The records live in memory
only: after a restart every cache starts fresh anyway.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional, Tuple

_lock = threading.Lock()
_same: Dict[str, Tuple[str, str]] = {}      # file → (version on disk after LBD's label write, content version)


def _key(path: "os.PathLike[str] | str") -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def raw(st: os.stat_result) -> str:
    """The version on disk: modification time and size."""
    return f"{st.st_mtime_ns}-{st.st_size}"


def content(path: "os.PathLike[str] | str", st: Optional[os.stat_result] = None) -> str:
    """The file's version, unchanged by LBD's own label writes. Raises OSError if it is gone."""
    on_disk = raw(st if st is not None else os.stat(path))
    with _lock:
        same = _same.get(_key(path))
    return same[1] if same is not None and same[0] == on_disk else on_disk


def label_written(path: "os.PathLike[str] | str", before: str, after: str) -> None:
    """LBD changed only the labels of `path`: the file on disk went from version `before` to
    `after` (both raw), and its content version stays what it was before."""
    with _lock:
        same = _same.get(_key(path))
        was = same[1] if same is not None and same[0] == before else before
        _same[_key(path)] = (after, was)


def forget(path: "os.PathLike[str] | str") -> None:
    with _lock:
        _same.pop(_key(path), None)
