"""Build the two release wheels: the `lbd` module and LBD Viewer with its Help and language modules.

    uv run python scripts/build_wheels.py --out DIR [--prebuilt ID=DIR ...]

Mac users (and anyone with Python) install the viewer from these, with `uv tool install`; see
docs/getting-started/install.md. Steps:
  1. check the versions;
  2. build the web UI (npm ci, npm run build);
  3. stage the Help (mkdocs build --strict) and the language modules (packaging/stage_sdk.py,
     with --prebuilt passed on) into viewer/src/lbd_viewer/docs and .../sdk;
  4. uv build both wheels into DIR, and check the viewer wheel contains the UI, Help and modules.
The staged docs/ and sdk/ are always removed again, so running the viewer from source is unaffected.
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_versions import REPO, release_version  # noqa: E402

PACKAGE = REPO / "viewer" / "src" / "lbd_viewer"
STAGED = [PACKAGE / "docs", PACKAGE / "sdk"]
# Files the viewer wheel must contain, so the installed viewer has its UI, Help and modules.
REQUIRED = ["lbd_viewer/static/index.html", "lbd_viewer/docs/index.html", "lbd_viewer/sdk/LICENSE"]


def run(cmd: List[str], cwd: Path = REPO) -> None:
    exe = shutil.which(cmd[0]) or cmd[0]     # npm is npm.cmd on Windows
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run([exe, *cmd[1:]], cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed (exit code {r.returncode})")


def remove_staged() -> None:
    for folder in STAGED:
        shutil.rmtree(folder, ignore_errors=True)


def build(out: Path, prebuilt: List[str]) -> List[Path]:
    version = release_version()
    out.mkdir(parents=True, exist_ok=True)
    remove_staged()   # leftovers of an interrupted run
    try:
        run(["npm", "ci"], REPO / "viewer" / "web")
        run(["npm", "run", "build"], REPO / "viewer" / "web")
        run([sys.executable, "-m", "mkdocs", "build", "--strict", "--quiet", "--site-dir", str(PACKAGE / "docs")])
        run([sys.executable, "packaging/stage_sdk.py", "--dest", str(PACKAGE / "sdk")]
            + (["--prebuilt", *prebuilt] if prebuilt else []))
        for package in ("lbd", "lbd-viewer"):
            run(["uv", "build", "--package", package, "--wheel", "--out-dir", str(out)])
    finally:
        remove_staged()
    wheels = [out / f"lbd-{version}-py3-none-any.whl", out / f"lbd_viewer-{version}-py3-none-any.whl"]
    missing = [w.name for w in wheels if not w.is_file()]
    if missing:
        raise SystemExit(f"not built: {missing}")
    names = set(zipfile.ZipFile(wheels[1]).namelist())
    absent = [n for n in REQUIRED if n not in names]
    if absent:
        raise SystemExit(f"{wheels[1].name} lacks {absent}")
    return wheels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="folder for the two wheels")
    ap.add_argument("--prebuilt", nargs="*", default=[], metavar="ID=DIR",
                    help="passed to packaging/stage_sdk.py, e.g. matlab=<folder with LBD.mltbx>")
    args = ap.parse_args(argv)
    for wheel in build(args.out.resolve(), args.prebuilt):
        print(f"built {wheel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
