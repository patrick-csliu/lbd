"""Open a test viewer on mock data, with settings of its own (your real settings and presets are
never touched).

    uv run python scripts/dev_viewer.py                    # mock data in a scratch folder, then the viewer
    uv run python scripts/dev_viewer.py --build            # build the web UI first (npm ci when needed)
    uv run python scripts/dev_viewer.py FOLDER             # a folder you have (e.g. made by make_mock_data.py)
    uv run python scripts/dev_viewer.py --files 2000 --live

The viewer runs in development mode (lbd-view --dev): http://127.0.0.1:8765/?token=dev (or
--port), it never stops by itself (Ctrl+C stops it), and the Vite dev server can forward to it
(cd viewer/web && npm run dev, for live UI editing). Its settings and its "running viewer" record
are in a scratch folder (LBD_CONFIG_DIR, LBD_RUNTIME_DIR), printed at the start; --keep-settings
FOLDER uses one you keep between runs. Without FOLDER, the mock data is made with
scripts/make_mock_data.py in a new scratch folder (see docs/developers/mock-data.md).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "viewer" / "web"
STATIC = REPO / "viewer" / "src" / "lbd_viewer" / "static" / "index.html"


def build_ui() -> None:
    """npm ci (when node_modules is missing) and npm run build in viewer/web."""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if not (WEB / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=WEB, check=True)
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path, help="the folder to open (default: new mock data)")
    ap.add_argument("--build", action="store_true", help="build the web UI first")
    ap.add_argument("--files", type=int, default=300, help="new mock data: about how many Library files (default 300)")
    ap.add_argument("--no-labels", action="store_true", help="new mock data: without labels")
    ap.add_argument("--live", action="store_true", help="new mock data: also a measurement being written")
    ap.add_argument("--port", type=int, default=8765, help="the port (default 8765, as lbd-view --dev)")
    ap.add_argument("--no-browser", action="store_true", help="print the address instead of opening a browser")
    ap.add_argument("--keep-settings", type=Path, help="a settings folder kept between runs (default: a new scratch one)")
    a = ap.parse_args(argv)

    if a.build:
        build_ui()
    elif not STATIC.is_file():
        print("The web UI isn't built yet: run again with --build (or: cd viewer/web && npm ci && npm run build)",
              file=sys.stderr)
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="lbd-dev-viewer-"))
    folder = a.folder
    if folder is None:
        sys.path.insert(0, str(REPO / "scripts"))
        import make_mock_data

        folder = scratch / "Mock data"
        made = make_mock_data.make(folder, a.files, not a.no_labels, small=False, live=a.live)
        print("\n".join(make_mock_data.report(folder, made)[:-2]))
    elif not folder.is_dir():
        print(f"{folder} isn't a folder", file=sys.stderr)
        return 2
    settings = a.keep_settings or scratch / "settings"
    env = {**os.environ, "LBD_CONFIG_DIR": str(settings), "LBD_RUNTIME_DIR": str(scratch / "runtime")}
    print(f"Settings (not your real ones): {settings}")
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
