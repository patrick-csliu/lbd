"""`lbd-view`: start the viewer (or reuse a running one) and open it in the browser.

    lbd-view                      open the viewer
    lbd-view file.lbd             open a file (this is what double-clicking runs)
    lbd-view some/folder          add a folder to the folder panel and open the viewer
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, List, Optional

import platformdirs

import lbd

from . import __version__
from .config import Config, ConfigError
from .server import AppState, create_app


def lock_path() -> Path:
    d = Path(platformdirs.user_runtime_dir("lbd", appauthor=False, ensure_exists=True))
    return d / "server.json"


def _api(port: int, token: str, method: str, path: str, body: Optional[dict] = None, timeout: float = 2.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"X-LBD-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def _running_server() -> Optional[dict]:
    """The lock file of a viewer that is running and answering, else None."""
    try:
        info = json.loads(lock_path().read_text(encoding="utf-8"))
        pong = _api(info["port"], info["token"], "GET", "/api/ping", timeout=1.5)
        if pong.get("app") == "lbd-viewer":
            return info
    except (OSError, ValueError, KeyError):
        pass
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def viewer_url(port: int, token: str, open_path: Optional[str] = None) -> str:
    q = {"token": token}
    if open_path:
        q["open"] = open_path
    return f"http://127.0.0.1:{port}/?{urllib.parse.urlencode(q)}"


def _split_args(paths: List[str]):
    """(files, folders) among `paths`; paths that don't exist are reported on stderr."""
    files, dirs = [], []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            dirs.append(str(p.resolve()))
        elif p.is_file():
            files.append(str(p.resolve()))
        else:
            print(f"lbd-view: not found: {raw}", file=sys.stderr)
    return files, dirs


def _port(text: str) -> int:
    n = int(text)
    if not 0 <= n <= 65535:
        raise argparse.ArgumentTypeError(f"{n} is not a port number (0-65535)")
    return n


def _seconds(text: str) -> float:
    v = float(text)
    if not v >= 0:
        raise argparse.ArgumentTypeError("must be 0 (never) or a positive number of seconds")
    return v


def _hand_over(port: int, token: str, method: str, path: str, body: dict) -> None:
    """Send a request to the running viewer; report (don't crash on) a refusal."""
    try:
        _api(port, token, method, path, body)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}").get("detail", e.reason)
        except ValueError:
            detail = e.reason
        print(f"lbd-view: the running viewer refused {body.get('path')}: {detail}", file=sys.stderr)


def _open_tabs(port: int, token: str, files: List[str], no_browser: bool) -> None:
    urls = [viewer_url(port, token, f) for f in files] or [viewer_url(port, token)]
    for u in urls:
        if no_browser:
            print(u, flush=True)  # at once, also when the output goes to a pipe or a log
        else:
            webbrowser.open(u)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lbd-view", description="LBD viewer")
    ap.add_argument("paths", nargs="*", help=".lbd files to open, or folders to add to the folder panel")
    ap.add_argument("--port", type=_port, default=0, help="port (default: any free port)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.add_argument("--idle-exit", type=_seconds, default=90.0,
                    help="stop after this many seconds without an open viewer tab (0 = never)")
    ap.add_argument("--dev", action="store_true",
                    help="development: port 8765, token 'dev', never exit; for the Vite dev server")
    ap.add_argument("--new", action="store_true", help="always start a new server")
    ap.add_argument("--version", action="version", version=f"lbd-view {__version__}")
    return ap


class Running:
    """A started viewer: `run()` serves until it stops (idle, `stop()`, Ctrl+C), in any thread."""

    def __init__(self, state: AppState, server, port: int, lock: Optional[Path]):
        self.state, self.server, self.port, self.lock = state, server, port, lock

    def url(self, open_path: Optional[str] = None) -> str:
        return viewer_url(self.port, self.state.token, open_path)

    def stop(self) -> None:
        self.server.should_exit = True

    @property
    def stopped(self) -> bool:
        return self.server.should_exit

    def run(self) -> None:
        try:
            self.server.run()
        finally:
            if self.lock:
                try:
                    if json.loads(self.lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                        self.lock.unlink()
                except (OSError, ValueError):
                    pass


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    files, dirs = _split_args(args.paths)
    if args.paths and not files and not dirs:
        print("lbd-view: none of the given files or folders exist", file=sys.stderr)
        return 2

    # Reuse a running viewer: hand it the files/folders and open browser tabs.
    if not args.new and not args.dev:
        running = _running_server()
        if running:
            port, token = running["port"], running["token"]
            for d in dirs:
                _hand_over(port, token, "POST", "/api/roots", {"path": d})
            for f in files:
                _hand_over(port, token, "POST", "/api/open", {"path": f})
            _open_tabs(port, token, files, args.no_browser)
            return 0

    start(args, files, dirs).run()
    return 0


def start(args: argparse.Namespace, files: List[str], dirs: List[str],
          on_started: Optional[Callable[[Running], None]] = None) -> Running:
    """Set up a viewer for `files` and `dirs` (not yet serving: call `.run()`).

    on_started runs once the server answers; by default it opens the browser tabs (or prints the
    URLs with --no-browser). The macOS app passes its own (see macapp.py).
    """
    cfg = Config()
    for d in dirs:
        try:
            cfg.add_root(d)
        except ConfigError as e:
            print(f"lbd-view: {e}", file=sys.stderr)

    port = args.port or (8765 if args.dev else _free_port())
    state = AppState(cfg, token="dev" if args.dev else None, port=port)
    for f in list(files):
        try:
            state.open_file(f)
        except FileNotFoundError:
            print(f"lbd-view: not found: {f}", file=sys.stderr)
            files.remove(f)
    app = create_app(state)

    import uvicorn  # imported late: it is slow to import and not needed when reusing a server

    log_config = None if sys.stdout is None else uvicorn.config.LOGGING_CONFIG  # windowed (no console) builds
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=log_config))

    lock = None
    if not args.dev:
        lock = lock_path()
        lock.write_text(json.dumps({"port": port, "token": state.token, "pid": os.getpid()}), encoding="utf-8")
    running = Running(state, server, port, lock)

    def after_start():
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.05)
        if on_started:
            on_started(running)
        elif args.dev:
            print(f"LBD viewer (dev) on http://127.0.0.1:{port}/  token: dev")
        else:
            _open_tabs(port, state.token, files, args.no_browser)

    def watchdog():
        idle = 0 if args.dev else args.idle_exit
        while idle > 0 and not server.should_exit:
            time.sleep(2)
            last = state.last_heartbeat or state.started
            # Give the first browser tab extra time to start up.
            limit = idle if state.last_heartbeat else max(idle, 60)
            if time.monotonic() - last > limit:
                server.should_exit = True

    threading.Thread(target=after_start, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    return running


if __name__ == "__main__":
    sys.exit(main())
