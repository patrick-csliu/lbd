"""List folders and files for the folder panel: .lbd data, .lbd.json styles and images."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from lbd.plot.style import STYLE_SUFFIX

from .images import is_image

# Folders never worth showing: VCS/tool caches, and Synology/Windows system folders.
SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".ipynb_checkpoints",
    "@eaDir", "#recycle", "#snapshot", "$RECYCLE.BIN", "System Volume Information",
}


def is_lbd(name: str) -> bool:
    return name.lower().endswith(".lbd")


def file_type(name: str) -> Optional[str]:
    """'lbd', 'style', 'image', or None for files the panel doesn't show."""
    low = name.lower()
    if low.endswith(".lbd"):
        return "lbd"
    if low.endswith(STYLE_SUFFIX):
        return "style"
    if is_image(name):
        return "image"
    return None


def _skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def list_dir(path: Path) -> Dict[str, Any]:
    """Direct subfolders and shown files of one folder (lazy tree loading).

    Entries that can't be read (no permission, a broken link) are not dropped silently: they
    are listed under "errors" with the reason, so the folder panel can show them.
    """
    dirs: List[str] = []
    files: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    with os.scandir(path) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not _skip_dir(e.name):
                        dirs.append(e.name)
                elif e.is_file():
                    t = file_type(e.name)
                    if t:
                        st = e.stat()
                        files.append({"name": e.name, "type": t, "size": st.st_size, "mtime": st.st_mtime})
                elif e.is_symlink() and file_type(e.name):
                    errors.append({"name": e.name, "error": "broken link (its target doesn't exist)"})
            except OSError as err:
                errors.append({"name": e.name, "error": err.strerror or str(err)})
    dirs.sort(key=str.lower)
    files.sort(key=lambda f: f["name"].lower())
    listing = {"path": str(path), "dirs": dirs, "files": files, "errors": errors}
    return {**listing, "signature": signature(listing)}


def signature(listing: Dict[str, Any]) -> str:
    """A short text that changes whenever the listing does: a file or folder added, removed or
    renamed, or a file rewritten (size or time). The pages compare it to see that a folder changed
    (watch.ts in the web UI)."""
    text = json.dumps([listing["dirs"], listing["files"], listing["errors"]], sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def walk_files(root: Path, errors: Optional[List[Dict[str, str]]] = None) -> Iterator[Path]:
    """All shown files under `root`, recursively, skipping SKIP_DIRS.

    Folders that can't be read are added to `errors` (if given) instead of being skipped silently.
    """
    def onerror(e: OSError) -> None:
        if errors is not None:
            errors.append({"path": str(e.filename), "error": e.strerror or str(e)})

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        dirnames[:] = sorted((d for d in dirnames if not _skip_dir(d)), key=str.lower)
        for f in sorted(filenames, key=str.lower):
            if file_type(f):
                yield Path(dirpath) / f


def search(root: Path, query: str, limit: int = 500) -> Dict[str, Any]:
    """Files under `root` whose path relative to it contains `query` (case-insensitive).

    "truncated" is true when more than `limit` files match; "errors" lists folders and files
    that couldn't be read, so an incomplete result is visible as such.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    q = query.lower().strip()
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    truncated = False
    for p in walk_files(root, errors):
        rel = os.path.relpath(p, root)
        if q in rel.lower():
            if len(results) >= limit:
                truncated = True
                break
            try:
                st = p.stat()
            except OSError as err:
                errors.append({"path": str(p), "error": err.strerror or str(err)})
                continue
            results.append({"path": str(p), "rel": rel, "type": file_type(p.name), "size": st.st_size,
                            "mtime": st.st_mtime})
    return {"root": str(root), "query": query, "results": results, "truncated": truncated, "errors": errors}
