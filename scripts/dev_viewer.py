"""Open a test viewer on mock data, with settings of its own (your real settings and presets are
never touched).

    uv run python scripts/dev_viewer.py                    # mock data in a scratch folder, then the viewer
    uv run python scripts/dev_viewer.py --build            # build the web UI and the docs first
    uv run python scripts/dev_viewer.py FOLDER             # a folder you have (e.g. made by make_mock_data.py)
    uv run python scripts/dev_viewer.py --files 2000 --live

The viewer runs in development mode (lbd-view --dev): http://127.0.0.1:8765/?token=dev (or
--port), it never stops by itself (Ctrl+C stops it), and the Vite dev server can forward to it
(cd viewer/web && npm run dev, for live UI editing). Its settings and its "running viewer" record
are in a scratch folder (LBD_CONFIG_DIR, LBD_RUNTIME_DIR), printed at the start; --keep-settings
FOLDER uses one you keep between runs. Without FOLDER, the mock data is made with
scripts/make_mock_data.py in the scratch folder (see docs/developers/mock-data.md).

--build builds the web UI (npm ci when needed) and the docs (mkdocs build --strict into site/,
which Help shows when the viewer runs from source). Without it, a line says when the docs are
newer than site/.

The scratch folder is deleted when the viewer stops (Ctrl+C too). Each holds a marker with the
PID of the dev_viewer.py that made it; at start, older scratch folders whose dev_viewer.py no
longer runs are deleted too. A --keep-settings folder and a FOLDER you name are never deleted.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import psutil

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "viewer" / "web"
STATIC = REPO / "viewer" / "src" / "lbd_viewer" / "static" / "index.html"
SITE_INDEX = REPO / "site" / "index.html"
# What the docs site is built from (mkdocs.yml includes spec/ and CHANGELOG.md by snippets).
DOCS_SOURCES = [REPO / "docs", REPO / "mkdocs.yml", REPO / "spec", REPO / "CHANGELOG.md"]

SCRATCH_ROOT = Path(tempfile.gettempdir())   # where the scratch folders are made
SCRATCH_PREFIX = "lbd-dev-viewer-"
MARKER = "dev_viewer.pid"                     # in each scratch folder: the PID of the script that made it
FRESH_SECONDS = 60                            # a folder this young without a marker may be one just being made


# --- Building ----------------------------------------------------------------------------------

def build_ui() -> int:
    """npm ci (when node_modules is missing) and npm run build in viewer/web. Returns 0 or the error code."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if not (WEB / "node_modules").is_dir():
        code = subprocess.call([npm, "ci"], cwd=WEB)
        if code:
            print(f"npm ci failed (exit code {code}): see its output above.", file=sys.stderr)
            return code
    code = subprocess.call([npm, "run", "build"], cwd=WEB)
    if code:
        print(f"The web UI build failed (exit code {code}): see its output above.", file=sys.stderr)
    return code


def build_docs() -> int:
    """mkdocs build --strict into site/, as CI does. Returns 0 or the error code."""
    if importlib.util.find_spec("mkdocs") is None:
        print("mkdocs isn't installed in this environment: run `uv sync --all-packages --group docs`, "
              "then again with --build.", file=sys.stderr)
        return 2
    print("Building the docs (mkdocs build --strict)...")
    code = subprocess.call([sys.executable, "-m", "mkdocs", "build", "--strict", "--quiet"], cwd=REPO)
    if code:
        print(f"The docs build failed (exit code {code}): see its output above.", file=sys.stderr)
    return code


def newest_mtime(paths: Iterable[Path]) -> float:
    """The latest change time of any file in `paths` (files, or folders searched through); 0 if none."""
    newest = 0.0
    for p in paths:
        files = p.rglob("*") if p.is_dir() else [p]
        for f in files:
            if f.is_file():
                newest = max(newest, f.stat().st_mtime)
    return newest


def docs_out_of_date(site_index: Path = SITE_INDEX, sources: Iterable[Path] = DOCS_SOURCES) -> Optional[str]:
    """A line to print when the built docs (Help) are missing or older than their sources, else None."""
    if not site_index.is_file():
        return ("Help isn't built (no site/ folder): `dev_viewer.py --build` builds it "
                "(or: uv run mkdocs build --strict).")
    if newest_mtime(sources) > site_index.stat().st_mtime:
        return ("Help is older than the docs (docs/, mkdocs.yml, spec/ or CHANGELOG.md changed since site/ "
                "was built): `dev_viewer.py --build` updates it.")
    return None


# --- Scratch folders ---------------------------------------------------------------------------

def make_scratch(root: Path) -> Path:
    """A new scratch folder, with a marker holding this process's PID (written at once)."""
    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=root))
    (scratch / MARKER).write_text(str(os.getpid()), encoding="utf-8")
    return scratch


def marker_pid(folder: Path) -> Optional[int]:
    """The PID in a scratch folder's marker; None when there is no marker or it can't be read."""
    try:
        return int((folder / MARKER).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def remove_folder(folder: Path, tries: int = 5) -> bool:
    """Delete a folder, retrying briefly (on Windows a just-stopped viewer may still hold a file)."""
    for i in range(tries):
        try:
            shutil.rmtree(folder)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if i < tries - 1:
                time.sleep(0.2 * (i + 1))
    return False


def old_scratch_folders(root: Path, keep: Iterable[Path] = (),
                        pid_alive: Callable[[int], bool] = psutil.pid_exists,
                        now: Optional[float] = None) -> List[Path]:
    """The scratch folders under `root` that may be deleted: made by this script (name prefix), and
    whose dev_viewer.py no longer runs (marker PID not alive) or that have no readable marker.
    Never a folder in `keep` (or holding one of them), and never one without a marker made in the
    last minute (its dev_viewer.py may be writing the marker right now)."""
    now = time.time() if now is None else now
    keep = [Path(k).resolve() for k in keep]
    found = []
    for d in sorted(root.glob(SCRATCH_PREFIX + "*")):
        if not d.is_dir():
            continue
        r = d.resolve()
        if any(k == r or r in k.parents for k in keep):
            continue                                       # a folder the user named
        pid = marker_pid(d)
        if pid is not None and pid_alive(pid):
            continue                                       # its dev_viewer.py still runs
        if pid is None and now - d.stat().st_mtime < FRESH_SECONDS:
            continue                                       # perhaps just made, marker not yet written
        found.append(d)
    return found


def remove_old_scratch(root: Path, keep: Iterable[Path] = (),
                       pid_alive: Callable[[int], bool] = psutil.pid_exists) -> List[Path]:
    """Delete old_scratch_folders(), saying which couldn't be deleted. Returns the deleted ones."""
    removed = []
    for d in old_scratch_folders(root, keep, pid_alive):
        if remove_folder(d):
            removed.append(d)
        else:
            print(f"Couldn't delete the old scratch folder {d} (a file in it is open?); "
                  "the next start tries again.", file=sys.stderr)
    return removed


# --- Main --------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path, help="the folder to open (default: new mock data)")
    ap.add_argument("--build", action="store_true", help="build the web UI and the docs first")
    ap.add_argument("--files", type=int, default=300, help="new mock data: about how many Library files (default 300)")
    ap.add_argument("--no-labels", action="store_true", help="new mock data: without labels")
    ap.add_argument("--many-labels", action="store_true", help="new mock data: hundreds of users and tags (long lists)")
    ap.add_argument("--live", action="store_true", help="new mock data: also a measurement being written")
    ap.add_argument("--port", type=int, default=8765, help="the port (default 8765, as lbd-view --dev)")
    ap.add_argument("--no-browser", action="store_true", help="print the address instead of opening a browser")
    ap.add_argument("--keep-settings", type=Path, help="a settings folder kept between runs (default: a new scratch one)")
    a = ap.parse_args(argv)

    if a.build:
        code = build_ui() or build_docs()
        if code:
            return code
    elif not STATIC.is_file():
        print("The web UI isn't built yet: run again with --build (or: cd viewer/web && npm ci && npm run build)",
              file=sys.stderr)
        return 2
    else:
        note = docs_out_of_date()
        if note:
            print(note)

    keep = [p for p in (a.folder, a.keep_settings) if p is not None]
    removed = remove_old_scratch(SCRATCH_ROOT, keep)
    if removed:
        print(f"Deleted {len(removed)} old scratch folder(s) of dev_viewer.py runs that have stopped.")

    scratch = make_scratch(SCRATCH_ROOT)
    try:
        return run_viewer(a, scratch)
    finally:
        if not remove_folder(scratch):
            print(f"Couldn't delete the scratch folder {scratch} (a file in it is open?); "
                  "the next start deletes it.", file=sys.stderr)


def run_viewer(a: argparse.Namespace, scratch: Path) -> int:
    """Make the mock data (when no folder is named) and run the viewer until it stops."""
    folder = a.folder
    if folder is None:
        sys.path.insert(0, str(REPO / "scripts"))
        import make_mock_data

        folder = scratch / "Mock data"
        made = make_mock_data.make(folder, a.files, not a.no_labels, small=False, live=a.live, many_labels=a.many_labels)
        print("\n".join(make_mock_data.report(folder, made)[:-2]))
    elif not folder.is_dir():
        print(f"{folder} isn't a folder", file=sys.stderr)
        return 2
    settings = a.keep_settings or scratch / "settings"
    env = {**os.environ, "LBD_CONFIG_DIR": str(settings), "LBD_RUNTIME_DIR": str(scratch / "runtime")}
    print(f"Settings (not your real ones): {settings}")
    print(f"Scratch folder (deleted when the viewer stops): {scratch}")
    print(f"The viewer: http://127.0.0.1:{a.port}/?token=dev   (Ctrl+C stops it)")
    cmd = [sys.executable, "-m", "lbd_viewer", "--dev", "--new", "--port", str(a.port), str(folder.resolve())]
    if a.no_browser:
        cmd.append("--no-browser")
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
