"""Install an old LBD Viewer, then the new one over it, then the old one again (plan 16.26).

    uv run --no-project python scripts/upgrade_test.py --old <old package> --new <new package>

Runs in release.yml's Windows job (setup .exe files) and Linux job (tarballs), on a fresh runner:
it installs into the real user folders, so never run it on your own computer.

1. installs the old version (e.g. v1.2.0 from its release) and starts it;
2. makes settings (a folder, the dark theme), labels (a Library label file next to a data file)
   and a Library database (as a later version would have left them);
3. installs the new version over it: the running old viewer must be stopped by the installer;
4. checks that the settings, labels and Library survive, the new viewer reads the settings, the
   old program folder's files are gone, and `lbd-view --stop` stops the new viewer gently;
5. installs an older version again: it must be refused, leaving the new one installed.
   The refusal is in the installer being run, so v1.2.0's own installer (from before 1.3.0) can't
   refuse: --older is the new installer made with an older version number (release.yml builds it).
Prints one line per step and exits 1 at the first failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO / "examples"))
from make_examples import ensure_examples  # noqa: E402

WINDOWS = sys.platform == "win32"
HOME = Path.home()

if WINDOWS:
    APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "LBDViewer"
    EXE = APP / "lbd-view.exe"
    SETTINGS = Path(os.environ["APPDATA"]) / "lbd"
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "lbd"           # the Library's database (catalog_dir)
else:
    APP = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "lbd-viewer"
    EXE = APP / "lbd-view"
    SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "lbd"
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "lbd"


def step(text: str) -> None:
    print(f"==> {text}", flush=True)


def fail(text: str) -> None:
    print(f"UPGRADE TEST FAILED: {text}", flush=True)
    sys.exit(1)


def install(package: Path) -> int:
    """Run the package's installer unattended; its exit code."""
    if WINDOWS:
        return subprocess.run([str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                               f"/LOG={package.with_suffix('.log')}"]).returncode
    unpacked = Path(tempfile.mkdtemp(prefix="lbd-pkg-"))
    with tarfile.open(package) as t:
        t.extractall(unpacked)                                       # our own release's tarball
    (folder,) = unpacked.iterdir()
    return subprocess.run(["sh", str(folder / "install.sh"), "--no-fonts"], stdin=subprocess.DEVNULL).returncode


def installed_version() -> str:
    if WINDOWS:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{99E94BF7-613F-40EE-9E44-A0E148634E8E}_is1"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    return (APP / "VERSION").read_text().strip() if (APP / "VERSION").exists() else "(none)"


def start_viewer() -> tuple[subprocess.Popen, str, int]:
    """The installed viewer, with the real settings; (process, token, port)."""
    p = subprocess.Popen([str(EXE), "--no-browser", "--new", "--idle-exit", "300"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        line = p.stdout.readline()
        m = re.search(r"127\.0\.0\.1:(\d+)/\?token=([\w-]+)", line)
        if m:
            return p, m[2], int(m[1])
        if not line and p.poll() is not None:
            break
    fail(f"the installed viewer didn't start (exit code {p.poll()})")
    raise AssertionError


def get_state(port: int, token: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"X-LBD-Token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", type=Path, required=True, help="the old version's setup .exe or tarball")
    ap.add_argument("--new", type=Path, required=True, help="the new version's setup .exe or tarball")
    ap.add_argument("--older", type=Path, required=True,
                    help="the new installer, made with an older version number (it must be refused)")
    ap.add_argument("--new-version", required=True, help="the new version, as the installer records it")
    args = ap.parse_args(argv)

    step(f"install the old version ({args.old.name})")
    if install(args.old) != 0:
        fail("the old version didn't install")
    old_version = installed_version()
    print(f"    installed: {old_version}")

    step("make settings, labels and a Library")
    data = HOME / "lbd-upgrade-test-data"
    data.mkdir(exist_ok=True)
    shutil.copy(ensure_examples() / "rabi.lbd", data / "rabi.lbd")   # examples/data, made first in release.yml
    labels = data / ".lbd-library.json"
    labels.write_text(json.dumps({"files": {"rabi.lbd": {"tags": ["upgrade-test"]}}}), encoding="utf-8")
    SETTINGS.mkdir(parents=True, exist_ok=True)
    (SETTINGS / "settings.json").write_text(json.dumps({"roots": [str(data)], "theme": "dark"}), encoding="utf-8")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    library = DATA_DIR / "library.sqlite"
    library.write_bytes(b"a Library index left by an earlier version")
    marker = (APP / "_internal" if WINDOWS else APP) / "left-by-the-old-version.txt"
    marker.write_text("must be gone after the upgrade")
    old_viewer, _, _ = start_viewer()                                 # the installer must stop it
    print(f"    the old viewer runs (process {old_viewer.pid})")

    step(f"install the new version over it ({args.new.name})")
    if install(args.new) != 0:
        fail("the new version didn't install over the old one")
    try:
        old_viewer.wait(timeout=30)
    except subprocess.TimeoutExpired:
        fail("the installer didn't stop the old viewer")
    if installed_version() != args.new_version:
        fail(f"installed version {installed_version()}, expected {args.new_version}")
    if marker.exists():
        fail(f"the old program folder's files are still there: {marker}")
    if json.loads(labels.read_text(encoding="utf-8"))["files"]["rabi.lbd"]["tags"] != ["upgrade-test"]:
        fail("the labels changed")
    if not library.exists():
        fail("the Library database was removed")
    print("    the old viewer was stopped, its program files are gone; settings, labels and Library are there")

    step("the new viewer reads the settings, and stops gently with lbd-view --stop")
    viewer, token, port = start_viewer()
    s = get_state(port, token)
    if s["version"] != args.new_version or s["theme"] != "dark" or str(data) not in s["roots"]:
        fail(f"the new viewer's state: version {s['version']}, theme {s['theme']}, folders {s['roots']}")
    r = subprocess.run([str(EXE), "--stop"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        fail(f"lbd-view --stop failed ({r.returncode}): {r.stdout}{r.stderr}")
    try:
        viewer.wait(timeout=5)
    except subprocess.TimeoutExpired:
        fail("lbd-view --stop said the viewer stopped, but it still runs")
    print(f"    version {s['version']}, theme dark, the folder is listed; stopped")

    step(f"install an older version ({args.older.name}): refused")
    if install(args.older) == 0:
        fail("the older version installed over the new one")
    if installed_version() != args.new_version:
        fail(f"after the refusal the installed version is {installed_version()}")
    print(f"    refused; {args.new_version} is still installed")
    print("UPGRADE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
