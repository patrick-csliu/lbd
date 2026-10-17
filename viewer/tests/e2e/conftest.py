"""End-to-end tests: a real viewer server and real browser pages (Playwright, headless Chromium).

These test what the rule tests can't: the web UI's side of the page rules, with several pages
open at once. Setup (once):

    uv sync --all-packages
    uv run playwright install chromium

Without Chromium (or without the built web UI) every test here is skipped with the reason.
The viewer runs in this process with short page timeouts, so a test waits seconds, not minutes.
"""

import re
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright is not installed: uv sync --all-packages")

import uvicorn  # noqa: E402

from lbd_viewer import server  # noqa: E402
from lbd_viewer.pages import Pages  # noqa: E402
from lbd_viewer.server import AppState, create_app  # noqa: E402

TOKEN = "e2e"
TIMEOUT_MS = 10_000   # the longest any single step may take before the test fails


@pytest.fixture(scope="session")
def browser():
    if not (server.STATIC_DIR / "index.html").is_file():
        pytest.skip("the web UI is not built: npm run build in viewer/web")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"Chromium for Playwright is missing (uv run playwright install chromium): {e}")
        yield b
        b.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Viewer:
    """A viewer server on a free port, plus a data folder with three files: a.lbd, b.lbd, c.lbd."""

    def __init__(self, cfg, data_dir: Path):
        self.data = data_dir
        for name in ("a", "b", "c"):
            shutil.copy(data_dir / "curve.lbd", data_dir / f"{name}.lbd")
        self.port = _free_port()
        pages = Pages(ack_timeout=1, transfer_timeout=2, new_tab_timeout=3)
        self.state = AppState(cfg, token=TOKEN, port=self.port, pages=pages)
        cfg.add_root(str(data_dir))
        config = uvicorn.Config(create_app(self.state), host="127.0.0.1", port=self.port,
                                log_level="warning", timeout_graceful_shutdown=1)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("the viewer server didn't start")
            time.sleep(0.02)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={TOKEN}"

    def path(self, name: str) -> str:
        return str((self.data / name).resolve())

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def viewer(cfg, data_dir, monkeypatch):
    # "Move to the Recycle Bin" deletes the file at once: tests never fill the real trash.
    monkeypatch.setattr(server.files.send2trash, "send2trash", lambda p: Path(p).unlink())
    v = Viewer(cfg, data_dir)
    yield v
    v.stop()


@pytest.fixture
def context(browser, viewer):
    """One browser window: its pages share pop-ups (a "new browser tab" opens in it).
    Closed before the viewer stops (it uses `viewer`), so no page is still waiting on it."""
    c = browser.new_context(viewport={"width": 1280, "height": 800})
    c.set_default_timeout(TIMEOUT_MS)
    sync_api.expect.set_options(timeout=TIMEOUT_MS)
    yield c
    c.close()


@pytest.fixture
def new_page(context, viewer):
    """Open the viewer in a new browser tab; returns the Playwright page once it has its number."""

    def open_page():
        page = context.new_page()
        page.goto(viewer.url)
        sync_api.expect(page).to_have_title(re.compile(r"Page \d+$"))
        return page

    return open_page
