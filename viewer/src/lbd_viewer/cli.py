"""`lbd-view`: start the viewer (or reuse a running one) and open it in the browser.

    lbd-view                      open the viewer
    lbd-view file.lbd             open a file (this is what double-clicking runs)
    lbd-view some/folder          add a folder to the folder panel and open the viewer
"""

from __future__ import annotations

import argparse
import json
import os
import signal
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

from . import VERSION
from .config import Config, ConfigError
from .server import AppState, create_app


def lock_path() -> Path:
    """The "running viewer" record (port, token, pid), so a second `lbd-view` reuses the viewer.
    In the user's runtime folder; LBD_RUNTIME_DIR overrides it (tests, a second copy)."""
    env = os.environ.get("LBD_RUNTIME_DIR")
    d = Path(env) if env else Path(platformdirs.user_runtime_dir("lbd", appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
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


def _open_files_in(port: int, token: str) -> Optional[str]:
    """The running viewer's setting for double-clicked files ("viewer" or "browser-tab"); None
    from a viewer too old to have it."""
    try:
        return _api(port, token, "GET", "/api/state").get("open_files_in")
    except (OSError, ValueError):
        return None


def _deliver(port: int, token: str, files: List[str], dirs: List[str]) -> Optional[dict]:
    """Hand files and folders to the running viewer's open page (server.deliver_files).
    None if that failed: then the caller opens browser tabs as before."""
    try:
        return _api(port, token, "POST", "/api/deliver", {"files": files, "dirs": dirs}, timeout=15)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}").get("detail", e.reason)
        except ValueError:
            detail = e.reason
        print(f"lbd-view: the running viewer refused the files: {detail}", file=sys.stderr)
        return None
    except (OSError, ValueError):
        return None


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
    ap.add_argument("--version", action="version", version=f"lbd-view {VERSION}")
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
            # Stopping. A second Ctrl+C now would cut short what follows (writing labels), so it
            # is ignored until the end; closing the window still stops at once.
            with _ignoring_ctrl_c():
                _wait_for_requests()             # a save still running finishes first
                try:
                    self.state.close()           # labels still waiting are written into their files
                except Exception as e:           # noqa: BLE001 - stopping anyway; said in the log
                    print(f"lbd-view: while stopping: {e}", file=sys.stderr)
            if self.lock:
                try:
                    if json.loads(self.lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                        self.lock.unlink()
                except (OSError, ValueError):
                    pass


GRACEFUL_STOP = 2.0     # seconds the server waits for running requests (a save) to answer when stopping
WAKE_GRACE = 15.0       # after the computer woke up, the open pages have this long to say they are there


class IdleWatch:
    """When the viewer stops by itself (`--idle-exit`): `idle` seconds after the last page's last
    heartbeat (every 10 s from each open page), or 60 s or more if no page ever came.

    After the computer slept, the clock has moved on (on Windows the monotonic clock counts the
    sleep), so the first look would see a long silence and stop the viewer under an open page.
    A look that comes much later than its TICK means the computer slept: the pages then get
    WAKE_GRACE seconds to send their next heartbeat (plan 16.17)."""

    TICK = 2.0

    def __init__(self, idle: float, clock: Callable[[], float] = time.monotonic):
        self.idle, self.clock = idle, clock
        self.last_look = clock()
        self.not_before = 0.0

    def should_stop(self, last_heartbeat: Optional[float], started: float) -> bool:
        if self.idle <= 0:                       # 0: never
            return False
        now = self.clock()
        if now - self.last_look > 3 * self.TICK:  # this watch didn't run: the computer slept
            self.not_before = now + WAKE_GRACE
        self.last_look = now
        if now < self.not_before:
            return False
        limit = self.idle if last_heartbeat else max(self.idle, 60)   # the first tab needs time to start
        return now - (last_heartbeat or started) > limit


def _make_server(config, on_stop: Callable[[], None]):
    """The uvicorn server, with a quick and quiet stop (plan 16.16).

    - `on_stop` runs as the stop begins: the open pages' waiting requests (long polls) answer at
      once, so the server doesn't wait for them.
    - Ctrl+C (Ctrl+Break, or the system asking the program to stop) stops it; a second one
      stops it without waiting. uvicorn's own handler raises the signal again once the server
      has stopped: that printed a KeyboardInterrupt traceback, and on Windows a Ctrl+Break
      ended the program before the waiting labels were written. This one doesn't.
    """
    import uvicorn  # imported late: it is slow to import and not needed when reusing a server

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            if self.should_exit:
                self.force_exit = True
            else:
                self.should_exit = True

        async def shutdown(self, sockets=None) -> None:
            on_stop()
            await super().shutdown(sockets)

    return Server(config)


def _wait_for_requests() -> None:
    """Wait for requests still running in their threads after the server stopped (a save that
    takes longer than GRACEFUL_STOP), so the data is written before the program ends."""
    running = [t for t in threading.enumerate()
               if t.name == "AnyIO worker thread" and t is not threading.current_thread()]
    if not running:
        return
    for t in running:
        t.join(timeout=1.0)
    if any(t.is_alive() for t in running):
        print("lbd-view: waiting for a save to finish...", file=sys.stderr, flush=True)
        for t in running:
            t.join()


class _ignoring_ctrl_c:
    """In the main thread: Ctrl+C and Ctrl+Break do nothing inside the `with` block."""

    SIGNALS = [s for s in (getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)) if s is not None]

    def __enter__(self):
        self.saved = {}
        if threading.current_thread() is threading.main_thread():
            for s in self.SIGNALS:
                self.saved[s] = signal.signal(s, signal.SIG_IGN)
        return self

    def __exit__(self, *exc) -> None:
        for s, handler in self.saved.items():
            signal.signal(s, handler)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    files, dirs = _split_args(args.paths)
    if args.paths and not files and not dirs:
        print("lbd-view: none of the given files or folders exist", file=sys.stderr)
        return 2

    # Reuse a running viewer: hand it the files and folders. Files open in the viewer page that is
    # already open (setting "open_files_in": "viewer"), else in new browser tabs. Without files
    # (the Start menu, the program itself, a folder) a new browser tab opens: a page that is
    # already open can't be brought to the front by the viewer (browsers don't allow it), so
    # "come forward" would show nothing.
    if not args.new and not args.dev:
        running = _running_server()
        if running:
            port, token = running["port"], running["token"]
            if files and not args.no_browser and _open_files_in(port, token) == "viewer":
                result = _deliver(port, token, files, dirs)
                if result is not None:
                    for path in result["busy"]:
                        print(f"lbd-view: {path} is being moved between viewer pages; try again in a moment",
                              file=sys.stderr)
                    if not result["delivered"]:
                        _open_tabs(port, token, result["unplaced"], no_browser=False)
                    return 0
            for d in dirs:
                _hand_over(port, token, "POST", "/api/roots", {"path": d})
            for f in files:
                _hand_over(port, token, "POST", "/api/open", {"path": f})
            _open_tabs(port, token, files, args.no_browser)
            return 0

    try:
        start(args, files, dirs).run()
    except KeyboardInterrupt:                    # Ctrl+C while starting: a normal stop too
        pass
    print("LBD viewer stopped", flush=True)
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
    server = _make_server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                         log_config=log_config, timeout_graceful_shutdown=GRACEFUL_STOP),
                          on_stop=state.pages.close)

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
        watch = IdleWatch(0 if args.dev else args.idle_exit)
        while watch.idle > 0 and not server.should_exit:
            time.sleep(watch.TICK)
            if watch.should_stop(state.last_heartbeat, state.started):
                server.should_exit = True

    threading.Thread(target=after_start, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    return running


if __name__ == "__main__":
    sys.exit(main())
