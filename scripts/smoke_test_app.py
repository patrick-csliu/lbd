"""Start a built LBD Viewer and check that it works, the way a user would first use it.

    uv run python scripts/smoke_test_app.py --exe <app>/lbd-view[.exe] [--release]

Starts the viewer on a free port with an empty settings folder and examples/data, then checks:
  - the session answers and reports the expected version and the built-in style "default";
  - the example folder lists, rabi.lbd renders, and PDF and PNG export work;
with --release (an app that will be shipped), also:
  - the documentation (Help) is the real site, not the "not built" page;
  - the language modules are complete: LICENSE everywhere, and each language that has a build
    step contains its built file (the [[install]] "if_exists" pattern, e.g. lbd-*.whl, LBD.mltbx).
Prints one line per check and exits 1 if any fails. The viewer is stopped at the end.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from check_versions import release_version  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class App:
    """A running viewer and a small client for its HTTP API."""

    def __init__(self, command: List[str], data: Path, config: Path):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.token = ""
        self.output: List[str] = []     # everything the viewer prints, read continuously
        env = {**os.environ, "LBD_CONFIG_DIR": str(config)}
        self.process = subprocess.Popen(
            [*command, "--new", "--no-browser", "--port", str(self.port), "--idle-exit", "120", str(data)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self) -> None:
        for line in self.process.stdout:
            self.output.append(line.rstrip())

    def wait(self, seconds: float = 90) -> None:
        """Wait for the URL that --no-browser prints once the viewer serves; take its token."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for line in self.output:
                m = re.search(r"[?&]token=([\w-]+)", line)
                if m:
                    self.token = m.group(1)
                    return
            if self.process.poll() is not None:
                time.sleep(0.5)            # let the reader collect the last lines
                raise RuntimeError(f"the viewer exited with code {self.process.returncode}:\n"
                                   + "\n".join(self.output[-30:]))
            time.sleep(0.2)
        raise RuntimeError(f"the viewer printed no URL within {seconds:.0f} s:\n" + "\n".join(self.output[-30:]))

    def request(self, method: str, path: str, body=None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "X-LBD-Token": self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    def get(self, path: str) -> bytes:
        return self.request("GET", path)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()


def checks(app: App, data: Path, version: str, release: bool) -> List[Callable[[], str]]:
    """The checks, each returning a short description of what it found (or raising)."""
    rabi = str(data / "rabi.lbd")

    def state():
        s = json.loads(app.get("/api/state"))
        assert s["version"] == version, f"version {s['version']}, expected {version}"
        assert "default" in s["styles"], f"styles {s['styles']}"
        return f"version {s['version']}, styles {s['styles']}"

    def listing():
        names = [f["name"] for f in json.loads(app.get(f"/api/list?path={urllib.parse.quote(str(data))}"))["files"]]
        assert "rabi.lbd" in names, f"files {names}"
        return f"{len(names)} files"

    def render():
        svg = json.loads(app.request("POST", "/api/render", {"path": rabi}))["svg"]
        assert svg.lstrip().startswith(("<?xml", "<svg")), svg[:80]
        return f"SVG, {len(svg) // 1024} KB"

    def export(fmt: str, magic: bytes):
        def check():
            out = app.request("POST", "/api/export", {"path": rabi, "format": fmt})
            assert out.startswith(magic), f"starts with {out[:8]!r}"
            return f"{len(out) // 1024} KB"
        check.__name__ = f"export {fmt.upper()}"
        return check

    def docs():
        page = app.get("/docs/index.html").decode("utf-8", "replace")
        assert "Documentation not built" not in page, "the app has no documentation (Help)"
        assert "Examples" in page, "the docs home page has no Examples section"
        return "the documentation site"

    def sdk():
        info = json.loads(app.get("/api/sdk"))
        assert info["bundled"], "the language modules are not bundled with the app"
        root = Path(info["sdk_dir"])
        problems = [] if (root / "LICENSE").is_file() else [f"{root}: no LICENSE"]
        for lang in info["languages"]:
            folder = Path(lang["folder"])
            manifest = tomllib.loads((folder / "language.toml").read_text(encoding="utf-8"))
            problems += [f"{lang['id']}: no {n}" for n in ("LICENSE", "README.md") if not (folder / n).is_file()]
            if manifest.get("sdk", {}).get("build"):
                built = [i["if_exists"] for i in manifest.get("install", []) if i.get("if_exists")]
                if not any(any(folder.glob(pattern)) for pattern in built):
                    problems.append(f"{lang['id']}: the built file ({', '.join(built)}) is missing")
        assert not problems, "; ".join(problems)
        return ", ".join(lang["id"] for lang in info["languages"])

    found = [state, listing, render, export("pdf", b"%PDF"), export("png", b"\x89PNG")]
    return found + ([docs, sdk] if release else [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exe", required=True, help="the viewer's program, e.g. <app>/lbd-view.exe")
    ap.add_argument("--release", action="store_true", help="also check the docs and the language modules")
    ap.add_argument("--data", type=Path, default=REPO / "examples" / "data")
    args = ap.parse_args(argv)
    command = [args.exe] if Path(args.exe).exists() else args.exe.split()
    return run(command, args.data.resolve(), args.release)


def run(command: List[str], data: Path, release: bool) -> int:
    version = release_version()
    failed = 0
    with tempfile.TemporaryDirectory() as config:
        app = App(command, data, Path(config))
        try:
            app.wait()
            for check in checks(app, data, version, release):
                name = check.__name__.replace("_", " ")
                try:
                    print(f"  ok    {name:12s} {check()}")
                except Exception as e:  # report every check, then fail
                    failed += 1
                    print(f"  FAIL  {name:12s} {type(e).__name__}: {e}")
        except RuntimeError as e:
            print(f"  FAIL  start        {e}")
            failed += 1
        finally:
            app.stop()
    print("SMOKE TEST PASSED" if not failed else f"SMOKE TEST FAILED ({failed} check(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
