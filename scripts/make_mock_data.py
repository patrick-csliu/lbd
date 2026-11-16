"""Make a folder of mock data to try LBD Viewer with: a Library with labels, files for Explore's
panels, large files, the examples, and (optionally) a measurement being written.

    uv run python scripts/make_mock_data.py FOLDER                 # about 300 files, with labels
    uv run python scripts/make_mock_data.py FOLDER --files 2000    # a larger Library
    uv run python scripts/make_mock_data.py FOLDER --small --no-labels   # quick: no large files
    uv run python scripts/make_mock_data.py FOLDER --many-labels  # hundreds of users and tags
    uv run python scripts/make_mock_data.py FOLDER --live          # also a file being written (runs on)
    uv run python scripts/make_mock_data.py FOLDER --healthy       # only healthy files: to play around with

FOLDER gets:

- `Lab library/`: the mock Library (viewer/tests/mock_library.py): `Lab data/` sorted by date and
  `Shared/` sorted by project; measurements of several kinds over two years in several time zones;
  a damaged file, an untitled one, single numbers only, a measurement just before midnight; with
  labels (not with --no-labels): stars, projects nested 1-3 levels, users in groups, flat and
  nested tags, comments, labels kept without a file, copies (identical and in conflict), files
  without an id, a missing file and a sync tool's conflict copy of a labels file.
- `Panels/`: files for Explore's panels (viewer/tests/mock_values.py): several values, 3-D maps,
  values over different axes, I/Q readout, data points with a shape, variable sweeps, uneven grids.
- `Large/` (not with --small): the four engine tests (viewer/tests/mock_large.py), about 214 MB:
  a curve of 1 000 000 points, 1000 traces x 10 000 points, a 4001 x 4001 map, and a small map
  with uneven x.
- `Examples/`: the example files, written by examples/make_examples.py.
- `Live/` (--live): a measurement being written slowly (viewer/tests/mock_live.py, in the
  background; it prints how to stop it) and one that stopped before finishing (mock_live.py
  --stopped).

With --healthy, nothing is broken or in conflict, to show the tool or play around with it: no damaged
file, no copies or copies in conflict, no files without an id, no missing file, no sync conflict copy
of a labels file, and (with --live) no measurement that stopped before finishing. The labels, the
examples, the panel files and (without --small) the large files stay.

Everything is made with fixed random seeds: the same files every time. FOLDER must be empty or
not exist yet. Open it in the viewer with scripts/dev_viewer.py FOLDER (see docs/developers/
mock-data.md).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "viewer" / "tests"))   # the mock modules, which the tests use too


def make(folder: Path, files: int = 300, with_labels: bool = True, small: bool = False,
         live: bool = False, live_seconds: int = 600, many_labels: bool = False,
         healthy: bool = False) -> Dict[str, object]:
    """Write the mock data into `folder` (empty or new). Returns what was made: the open folders
    to add to the viewer, counts, and the live writer's process (or None). `healthy`: none of the
    broken or problem cases (18.5)."""
    import mock_library
    import mock_values

    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"{folder} isn't empty: give an empty or new folder (the mock data is written into it)")
    folder.mkdir(parents=True, exist_ok=True)
    library = folder / "Lab library"
    written = mock_library.write_library(library, files, healthy=healthy)
    special = (mock_library.add_labels(library, keep_in=folder, many=many_labels, healthy=healthy)
               if with_labels else {})   # FOLDER is the open folder
    panels = mock_values.write_all(folder / "Panels", small=small)
    large: List[Path] = []
    if not small:                                   # --small leaves them out, so the tests stay quick
        import mock_large
        large = mock_large.write_all(folder / "Large")
    _write_examples(folder / "Examples")
    writer: Optional[subprocess.Popen] = None
    if live:
        (folder / "Live").mkdir()
        writer = subprocess.Popen([sys.executable, str(REPO / "viewer" / "tests" / "mock_live.py"), str(folder / "Live"),
                                   "--seconds", str(live_seconds), *([] if healthy else ["--stopped"])],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"roots": [str(folder)], "library": {k: len(v) for k, v in written.items()}, "special": special,
            "panels": len(panels), "large": len(large), "writer": writer, "healthy": healthy}


def _write_examples(out: Path) -> None:
    """examples/make_examples.py into `out`, quietly."""
    import contextlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("make_examples", REPO / "examples" / "make_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)                                # type: ignore[union-attr]
    with contextlib.redirect_stdout(io.StringIO()):
        module.main(out)


def report(folder: Path, made: Dict[str, object]) -> List[str]:
    lines = [f"Mock data in {folder}:"]
    for where, n in made["library"].items():                                   # type: ignore[union-attr]
        lines.append(f"  Lab library/{where}: {n} files")
    if made["special"]:
        lines.append("  with labels, copies, a conflict, files without an id and a missing file")
    elif made.get("healthy"):
        lines.append("  healthy: nothing broken or in conflict")
    lines.append(f"  Panels: {made['panels']} files; Examples: the example files (examples/make_examples.py)")
    if made["large"]:
        lines.append(f"  Large: {made['large']} large files (the engine tests)")
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
    ap.add_argument("--many-labels", action="store_true", help="hundreds of users and tags, and very long names (long lists)")
    ap.add_argument("--small", action="store_true", help="the panel files with few points, and no large files (quick)")
    ap.add_argument("--live", action="store_true", help="also a measurement being written, in the background")
    ap.add_argument("--live-seconds", type=int, default=600, help="how long the live measurement runs (default 600)")
    ap.add_argument("--healthy", action="store_true",
                    help="only healthy files, to play around with: no damaged file, copies, conflicts, files "
                         "without an id, missing file or stopped measurement")
    a = ap.parse_args(argv)
    made = make(a.folder, a.files, not a.no_labels, a.small, a.live, a.live_seconds, a.many_labels, a.healthy)
    print("\n".join(report(a.folder, made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
