"""The macOS app (LBD Viewer.app): double-clicked .lbd files, the Dock icon and Quit.

On macOS, opening a file from Finder doesn't start a program with the file name. macOS sends the
app an "open documents" event, starting the app first if needed. Tk receives these events, but
only on the main thread, so the app runs Tk's event loop there and the web server in a
background thread.

packaging/entry.py runs this when Finder starts the app; `lbd-view` with arguments (Terminal,
the smoke test) works as on every other system.
"""

from __future__ import annotations

import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable, List

from . import cli
from .config import ConfigError
from .server import deliver_files

TICK_MS = 200          # how often the event loop checks for work
FIRST_TAB_AFTER = 1.0  # seconds to wait for a document from Finder before opening the main tab


def show_alert(message: str) -> None:
    """A macOS alert, in its own process so the event loop keeps running."""
    text = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(["osascript", "-e", f'display alert "LBD Viewer" message "{text}" as warning'])


class MacApp:
    """What the app does with macOS's events. Tk only calls these; tests call them directly."""

    def __init__(self, running: cli.Running, open_url: Callable[[str], object] = webbrowser.open,
                 alert: Callable[[str], None] = show_alert):
        self.running, self.open_url, self.alert = running, open_url, alert
        self.pending: List[str] = []     # documents that arrived before the server answered
        self.shown = False               # a viewer tab has been opened
        self.started_at = None

    # -- event handlers (called by Tk on the main thread)

    def open_documents(self, *paths: str) -> None:
        """Finder: open these files or folders (also the document that started the app)."""
        self.pending.extend(paths)

    def reopen(self) -> None:
        """The Dock icon was clicked while the app runs: show the viewer."""
        if self.running.server.started:
            self.open_url(self.running.url())
            self.shown = True

    def quit(self) -> None:
        """⌘Q or Dock > Quit."""
        self.running.stop()

    # -- the work, done on each tick of the event loop

    def tick(self, now: float) -> bool:
        """Open pending documents once the server answers. False when the app should quit."""
        if self.running.stopped:
            return False
        if not self.running.server.started:
            return True
        if self.started_at is None:
            self.started_at = now
        if self.pending:
            paths, self.pending = self.pending, []
            self._open(paths)
        elif not self.shown and now - self.started_at >= FIRST_TAB_AFTER:
            self.open_url(self.running.url())      # started from the Dock or Launchpad
            self.shown = True
        return True

    def _open(self, paths: List[str]) -> None:
        """Like lbd-view: files and folders go to the open viewer page (setting "open_files_in":
        "viewer"); a browser tab opens only for what no page took, or with "browser-tab"."""
        state = self.running.state
        problems = [f"{p}: not found" for p in paths if not Path(p).exists()]
        files = [p for p in paths if Path(p).is_file()]
        dirs = []
        for d in (p for p in paths if Path(p).is_dir()):
            try:
                state.config.add_root(d)
                dirs.append(d)
            except ConfigError as e:
                problems.append(f"{d}: {e}")

        tabs, main_tab = files, bool(dirs)    # what needs browser tabs, unless a page takes it
        if state.config.settings()["open_files_in"] == "viewer":
            result = deliver_files(state, files, dirs)
            problems += [f"{p}: being moved between viewer pages; try again in a moment" for p in result["busy"]]
            tabs = result["unplaced"]
            main_tab = bool(dirs) and not result["delivered"] and not tabs
            self.shown = self.shown or result["delivered"]
        for f in tabs:
            self.open_url(self.running.url(state.open_file(f)))
        if main_tab:
            self.open_url(self.running.url())
        self.shown = self.shown or bool(tabs) or main_tab
        if problems:
            self.alert("Couldn't open:\n" + "\n".join(problems))


def run() -> int:
    """Run the app until Quit, or until it is idle (no viewer tab for 90 s, as on other systems)."""
    import tkinter

    running = cli.start(cli.build_parser().parse_args([]), [], [], on_started=lambda r: None)
    app = MacApp(running)
    server = threading.Thread(target=running.run, daemon=True)
    server.start()

    root = tkinter.Tk()
    root.withdraw()                                   # no window: the viewer is in the browser
    root.createcommand("::tk::mac::OpenDocument", app.open_documents)
    root.createcommand("::tk::mac::ReopenApplication", app.reopen)
    root.createcommand("::tk::mac::Quit", app.quit)

    def poll():
        if app.tick(time.monotonic()):
            root.after(TICK_MS, poll)
        else:
            root.quit()

    root.after(TICK_MS, poll)
    root.mainloop()
    running.stop()
    server.join(timeout=10)
    return 0
