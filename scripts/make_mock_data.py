"""Make a folder of mock data to try LBD Viewer with: a Library with labels, files for Explore's
panels, the examples, and (optionally) a measurement being written.

    uv run python scripts/make_mock_data.py FOLDER                 # about 300 files, with labels
    uv run python scripts/make_mock_data.py FOLDER --files 2000    # a larger Library
    uv run python scripts/make_mock_data.py FOLDER --small --no-labels
    uv run python scripts/make_mock_data.py FOLDER --live          # also a file being written (runs on)

FOLDER gets:

- `Lab library/`: the mock Library (viewer/tests/mock_library.py): `Lab data/` sorted by date and
  `Shared/` sorted by project; measurements of several kinds over two years in several time zones;
  a damaged file, an untitled one, single numbers only, a measurement just before midnight; with
  labels (not with --no-labels): stars, projects nested 1-3 levels, users in groups, flat and
  nested tags, comments, labels kept without a file, copies (identical and in conflict), files
  without an id, a missing file and a sync tool's conflict copy of a labels file.
- `Panels/`: files for Explore's panels (viewer/tests/mock_values.py): several values, 3-D maps,
  values over different axes, I/Q readout, data points with a shape, variable sweeps.
- `Examples/`: the repository's examples (examples/data).
- `Live/` (--live): a measurement being written slowly (viewer/tests/mock_live.py, in the
  background; it prints how to stop it) and one that stopped before finishing.

Everything is made with fixed random seeds: the same files every time. FOLDER must be empty or
not exist yet. Open it in the viewer with scripts/dev_viewer.py FOLDER (see docs/developers/
mock-data.md).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "viewer" / "tests"))   # the mock modules, which the tests use too


def make(folder: Path, files: int = 300, with_labels: bool = True, small: bool = False,
         live: bool = False, live_seconds: int = 600) -> Dict[str, object]:
    """Write the mock data into `folder` (empty or new). Returns what was made: the open folders
    to add to the viewer, counts, and the live writer's process (or None)."""
    import mock_library
    import mock_values

    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"{folder} isn't empty: give an empty or new folder (the mock data is written into it)")
    folder.mkdir(parents=True, exist_ok=True)
    library = folder / "Lab library"
    written = mock_library.write_library(library, files)
    special = mock_library.add_labels(library, keep_in=folder) if with_labels else {}   # FOLDER is the open folder
    panels = mock_values.write_all(folder / "Panels", small=small)
    shutil.copytree(REPO / "examples" / "data", folder / "Examples")
    writer: Optional[subprocess.Popen] = None
    if live:
        (folder / "Live").mkdir()
        writer = subprocess.Popen([sys.executable, str(REPO / "viewer" / "tests" / "mock_live.py"), str(folder / "Live"),
                                   "--seconds", str(live_seconds)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"roots": [str(folder)], "library": {k: len(v) for k, v in written.items()}, "special": special,
            "panels": len(panels), "writer": writer}


def report(folder: Path, made: Dict[str, object]) -> List[str]:
    lines = [f"Mock data in {folder}:"]
    for where, n in made["library"].items():                                   # type: ignore[union-attr]
        lines.append(f"  Lab library/{where}: {n} files")
    if made["special"]:
        lines.append("  with labels, copies, a conflict, files without an id and a missing file")
    lines.append(f"  Panels: {made['panels']} files; Examples: the repository's examples")
    if made["writer"] is not None:
        lines.append(f"  Live: a measurement being written (process {made['writer'].pid}; it stops by itself, "  # type: ignore[union-attr]
                     "or stop it with Ctrl+C here / kill that process)")
    lines.append("Open it in a test viewer:")
    lines.append(f'  uv run python scripts/dev_viewer.py "{folder}"')
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="where to write (empty or new)")
    ap.add_argument("--files", type=int, default=300, help="about how many files the Library gets (default 300)")
    ap.add_argument("--no-labels", action="store_true", help="no labels, copies or missing files")
    ap.add_argument("--small", action="store_true", help="the panel files with few points (quick)")
    ap.add_argument("--live", action="store_true", help="also a measurement being written, in the background")
    ap.add_argument("--live-seconds", type=int, default=600, help="how long the live measurement runs (default 600)")
    a = ap.parse_args(argv)
    made = make(a.folder, a.files, not a.no_labels, a.small, a.live, a.live_seconds)
    print("\n".join(report(a.folder, made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
