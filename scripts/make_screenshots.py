"""Make the screenshots of LBD Viewer in the documentation, with numbered callouts.

    uv run python scripts/make_screenshots.py                 # all shots
    uv run python scripts/make_screenshots.py overview folders # only these

Run it when the viewer's look changed (see docs/developers/releases.md). It starts the viewer from
this checkout with a scratch settings folder and example files, opens it in headless Chromium
(Playwright) in the light theme, and for each shot:

1. puts the viewer in the state to show (a file open, a menu open, ...);
2. draws numbered round markers and dashed outlines over the parts the page describes. They are
   an overlay added to the page for the picture, not part of the viewer;
3. saves a PNG into docs/.../img/.

Each page's text has a numbered list matching the markers. The images are committed, so the docs
build without Chromium. tests/scripts/test_screenshots.py checks that every shot is used in the
docs and every image the docs use exists.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
SCRATCH = Path(tempfile.mkdtemp(prefix="lbd-screenshots-"))
# Before importing lbd: its presets live in the settings folder.
os.environ["LBD_CONFIG_DIR"] = str(SCRATCH / "config")
os.environ["LBD_RUNTIME_DIR"] = str(SCRATCH / "runtime")

import lbd  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from lbd_viewer import server  # noqa: E402
from lbd_viewer.config import Config  # noqa: E402
from lbd_viewer.server import AppState, create_app  # noqa: E402

VIEWER_IMG = REPO / "docs" / "viewer" / "img"
QUICKSTART_IMG = REPO / "docs" / "getting-started" / "img"
TOKEN = "screenshots"
SIZE = {"width": 1280, "height": 800}

# A mark: (number, CSS selector, which match (0 = first), where the number sits): "tl" / "tr" the
# top left / right corner, "l" / "r" the middle of the left / right edge, "L" just outside the
# left edge (in the margin, covering nothing), "t" / "b" the middle of the top / bottom edge.
Mark = Tuple[int, str, int, str]

MARK_JS = r"""
(marks) => {
  document.getElementById("doc-marks")?.remove();
  const layer = document.createElement("div");
  layer.id = "doc-marks";
  layer.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:99999";
  for (const [n, selector, nth, where] of marks) {
    const el = document.querySelectorAll(selector)[nth];
    if (!el) throw new Error(`mark ${n}: nothing matches ${selector} [${nth}]`);
    const r = el.getBoundingClientRect();
    const box = document.createElement("div");
    box.style.cssText = `position:fixed;left:${r.left - 2}px;top:${r.top - 2}px;width:${r.width + 4}px;` +
      `height:${r.height + 4}px;border:2px dashed #e8590c;border-radius:6px;box-sizing:border-box`;
    const dot = document.createElement("div");
    const x = where === "L" ? r.left - 16 : where === "t" || where === "b" ? r.left + r.width / 2
      : where.includes("r") ? r.right : r.left;
    const y = where === "b" ? r.bottom : where === "l" || where === "r" || where === "L" ? r.top + r.height / 2 : r.top;
    dot.textContent = String(n);
    dot.style.cssText = `position:fixed;left:${x - 12}px;top:${y - 12}px;width:24px;height:24px;` +
      "border-radius:50%;background:#e8590c;color:#fff;font:bold 13px/24px system-ui,sans-serif;" +
      "text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgb(0 0 0/.4);box-sizing:content-box";
    layer.append(box, dot);
  }
  document.body.append(layer);
  // a neutral example path instead of the scratch folder's
  for (const el of document.querySelectorAll(".path"))
    el.textContent = el.textContent.replace(/^.*[\\/]Lab data/, String.raw`C:\Users\me\Documents\Lab data`);
}
"""


INSTALLED_JS = r"""
([source, installed]) => {
  const forms = [[source, installed], [source.replaceAll("\\", "/"), installed.replaceAll("\\", "/")]];
  const walk = document.createTreeWalker(document.querySelector(".sdk-page"), NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode())
    for (const [a, b] of forms) n.textContent = n.textContent.replaceAll(a, b);
  for (const note of document.querySelectorAll(".sdk-page .note"))
    if (note.textContent.includes("source folder")) note.remove();
}
"""


# ---- the example files -------------------------------------------------------------------------


def make_files(folder: Path) -> None:
    """The Quick start's sweep, the repository's example files, and two small cases."""
    folder.mkdir(parents=True)
    # the Quick start's code (docs/getting-started/quickstart.md, Python tab)
    f = np.linspace(6.99e9, 7.01e9, 401)
    p = np.arange(-60, 1, 5.0)
    f0 = 7e9 - 2e6 * 10 ** (p / 20)                   # the resonance moves down at high power
    s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - f0[:, None]) / 0.6e6)
    d = lbd.Dataset(title="Resonator power sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "freq"])
    d.meta["T_mK"] = 12
    d.save(folder / "sweep.lbd")

    shutil.copytree(REPO / "examples" / "data", folder / "examples")

    # values on two different axes, and a single number
    delay = np.logspace(-7, -3.5, 60)
    freq = np.logspace(0, 5, 300)
    rng = np.random.default_rng(3)
    d = lbd.Dataset(title="T1 and noise")
    d.add_axis("delay", delay, unit="s", label="Delay")
    d.add_axis("f", freq, unit="Hz", label="Frequency")
    d.add_value("P1", np.exp(-delay / 21e-6) + rng.normal(0, 0.01, delay.size), axes="delay", label="P1")
    d.add_value("S_V", 1e-15 * (1 / freq ** 0.92 + 3e-4), axes="f", unit="V²/Hz", label="S_V")
    d.add_value("T1", 21e-6, unit="s", label="T1")
    d.save(folder / "t1_noise.lbd")

    # a parameter that wasn't swept: an axis with one point
    d = lbd.Dataset(title="Resonator at one power")
    d.add_axis("power", [-40.0], unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21[8:9], axes=["power", "freq"])
    d.save(folder / "one_power.lbd")


# ---- the viewer --------------------------------------------------------------------------------


def start_viewer(data: Path) -> Tuple[str, uvicorn.Server]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = Config(SCRATCH / "config")
    cfg.add_root(str(data))
    state = AppState(cfg, token=TOKEN, port=port)
    srv = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the viewer didn't start")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/?token={TOKEN}", srv


# ---- helpers for the shots ---------------------------------------------------------------------


def settle(page: Page) -> None:
    """Wait until no figure is being drawn."""
    page.wait_for_timeout(300)
    page.locator("text=Rendering…").wait_for(state="hidden", timeout=15_000)
    page.wait_for_timeout(200)


def open_file(page: Page, name: str) -> None:
    """Double-click a file in the folder panel (it may be inside a folder: open that first)."""
    row = page.locator(".row-label", has_text=name).first
    row.dblclick()
    page.locator(".tab-label", has_text=name).wait_for()
    page.locator(".tab-body:not([hidden]) .figure img, .tab-body:not([hidden]) .numbers-only").first.wait_for()
    settle(page)


def expand(page: Page, folder: str) -> None:
    page.locator(".row-label", has_text=folder).first.click()
    page.wait_for_timeout(300)


def body(page: Page):
    return page.locator(".tab-body:not([hidden])")


def choose(page: Page, label: str, value: str) -> None:
    body(page).get_by_label(label).select_option(value)
    settle(page)


def mark(page: Page, marks: List[Mark]) -> None:
    page.evaluate(MARK_JS, [list(m) for m in marks])


def save(page: Page, path: Path, clip: Dict[str, float] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), clip=clip)
    print(f"  {path.relative_to(REPO)}")


def region(page: Page, selector: str, pad: int = 12, nth: int = 0, extra_right: int = 0, extra_bottom: int = 0):
    """A clip around an element, with some margin."""
    box = page.locator(selector).nth(nth).bounding_box()
    x, y = max(0, box["x"] - pad), max(0, box["y"] - pad)
    return {"x": x, "y": y, "width": min(SIZE["width"] - x, box["width"] + 2 * pad + extra_right),
            "height": min(SIZE["height"] - y, box["height"] + 2 * pad + extra_bottom)}


def fresh(page: Page, url: str) -> None:
    """A new page with nothing open (tabs are not restored)."""
    page.goto(url)
    page.locator(".page-badge").wait_for()
    page.wait_for_timeout(500)


# ---- the shots ---------------------------------------------------------------------------------

SHOTS: Dict[str, Callable] = {}


def shot(fn: Callable) -> Callable:
    SHOTS[fn.__name__] = fn
    return fn


@shot
def overview(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    mark(page, [
        (1, ".pages", 0, "b"),
        (2, ".page-badge", 0, "b"),
        (3, ".settings", 0, "b"),
        (4, ".help-button", 0, "b"),
        (5, ".sidebar", 0, "r"),
        (6, ".tabs .tab", 0, "b"),
        (7, ".tab-body:not([hidden]) .file-head", 0, "r"),
        (8, ".tab-body:not([hidden]) .controls", 0, "tr"),
        (9, ".tab-body:not([hidden]) .figure-toolbar", 0, "b"),
        (10, ".tab-body:not([hidden]) .figure", 0, "tr"),
        (11, ".tab-body:not([hidden]) .save-row", 0, "r"),
    ])
    save(page, VIEWER_IMG / "overview.png")


@shot
def folders(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    expand(page, "examples")
    page.locator(".row-label", has_text="sweep.lbd").first.click(button="right")
    page.locator(".context-menu").wait_for()
    mark(page, [
        (1, ".sidebar .filter", 0, "r"),
        (2, ".sidebar .panel-head .actions", 0, "tl"),
        (3, ".sidebar .root-row", 0, "r"),
        (4, ".sidebar .dir-row", 0, "r"),
        (5, ".sidebar .file-row", 0, "r"),
        (6, ".context-menu", 0, "tr"),
    ])
    save(page, VIEWER_IMG / "folders.png", clip={"x": 0, "y": 0, "width": 640, "height": 520})


@shot
def plot_controls(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "t1_noise.lbd")
    controls = ".tab-body:not([hidden]) .controls"
    mark(page, [
        (1, f"{controls} select", 0, "L"),
        (2, f"{controls} .checks", 0, "L"),
        (3, f"{controls} .value-group", 0, "L"),
        (4, f"{controls} .value-group", 1, "L"),
        (5, f"{controls} select", 1, "L"),
        (6, f"{controls} .field.inline", 0, "L"),
        (7, f"{controls} fieldset", 1, "L"),
        (8, f"{controls} fieldset", 2, "L"),
    ])
    save(page, VIEWER_IMG / "plot-controls.png", clip=region(page, controls, pad=34))


@shot
def slider(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    choose(page, "Plot type", "curve")
    body(page).locator("label.field", has_text="One curve per").locator("select").select_option("none")
    settle(page)
    controls = ".tab-body:not([hidden]) .controls"
    mark(page, [
        (1, f"{controls} input[type=range]", 0, "L"),
        (2, f"{controls} .slice-value input", 0, "t"),
    ])
    save(page, VIEWER_IMG / "slider.png", clip=region(page, f"{controls} fieldset", pad=34))


@shot
def fixed_parameter(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "one_power.lbd")
    controls = ".tab-body:not([hidden]) .controls"
    mark(page, [(1, f"{controls} .field", 4, "L")])
    save(page, VIEWER_IMG / "fixed-parameter.png", clip=region(page, f"{controls} fieldset", pad=34))


@shot
def save_export(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    choose(page, "Complex data as", "db")
    figure_col = ".tab-body:not([hidden]) .figure-col"
    mark(page, [
        (1, f"{figure_col} .figure-toolbar select", 0, "tl"),
        (2, f"{figure_col} .figure-toolbar button", 0, "tl"),
        (3, ".tab-body:not([hidden]) .save-row button", 0, "tl"),
        (4, ".tab-body:not([hidden]) .save-row button", 1, "tl"),
    ])
    save(page, VIEWER_IMG / "save-export.png", clip=region(page, figure_col, pad=16))


@shot
def tabs_menu(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    other = ctx.new_page()
    fresh(other, url)                        # Page 2
    page.bring_to_front()
    open_file(page, "sweep.lbd")
    open_file(page, "t1_noise.lbd")
    page.locator(".tab-label", has_text="sweep.lbd").click(button="right")
    menu = page.locator(".context-menu")
    menu.wait_for()
    # Entries: Close, Close others, Move to Page 2, Move to a new browser tab | Show in Explorer,
    # Copy path, Rename… | Close all, Move all tabs to Page 2, Move all tabs to a new browser tab.
    mark(page, [
        (1, ".page-badge", 0, "tr"),
        (2, ".tabs .tab", 0, "l"),
        (3, ".context-menu [role=menuitem]", 2, "r"),
        (4, ".context-menu [role=menuitem]", 3, "r"),
        (5, ".context-menu [role=menuitem]", 4, "r"),
        (6, ".context-menu [role=menuitem]", 7, "r"),
    ])
    box = menu.bounding_box()
    save(page, VIEWER_IMG / "tabs-menu.png", clip={"x": 0, "y": 0, "width": 900, "height": box["y"] + box["height"] + 16})



@shot
def settings(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    page.get_by_role("button", name="Settings").click()
    pop = page.locator(".settings-popover")
    pop.wait_for()
    mark(page, [
        (1, ".settings-popover .settings-title", 0, "L"),
        (2, ".settings-popover .settings-title", 1, "L"),
    ])
    box = pop.bounding_box()
    save(page, VIEWER_IMG / "settings.png", clip={"x": box["x"] - 48, "y": 0, "width": SIZE["width"] - box["x"] + 48,
                                                  "height": box["y"] + box["height"] + 16})


@shot
def styles_page(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")               # the preview shows the open file
    page.get_by_role("tab", name="Styles").click()
    page.locator(".style-editor").wait_for()
    page.locator(".preview img").wait_for()
    page.wait_for_timeout(800)
    mark(page, [
        (1, ".style-list ul", 0, "r"),
        (2, ".style-list .panel-head .actions", 0, "b"),
        (3, ".editor-head .actions", 0, "tl"),
        (4, ".style-editor .group", 0, "tl"),
        (5, ".preview", 0, "tl"),
    ])
    save(page, VIEWER_IMG / "styles-page.png")


@shot
def language_modules(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    page.get_by_role("tab", name="Language modules").click()
    page.locator(".sdk-page").wait_for()
    page.wait_for_timeout(500)
    # Shown as an installed viewer shows it: its module folder, not this checkout's.
    installed = r"C:\Users\me\AppData\Local\Programs\LBDViewer\sdk"
    page.evaluate(INSTALLED_JS, [str(REPO / "languages"), installed])
    mark(page, [
        (1, ".lang-tabs", 0, "l"),
        (2, ".lang-body .code", 0, "L"),
        (3, ".lang-body .copy", 0, "r"),
    ])
    save(page, VIEWER_IMG / "language-modules.png")


# -- the Quick start


@shot
def quickstart_open(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    mark(page, [
        (1, ".sidebar .file-row.active", 0, "r"),
        (2, ".tab-body:not([hidden]) .controls", 0, "tl"),
        (3, ".tab-body:not([hidden]) .figure", 0, "tl"),
    ])
    save(page, QUICKSTART_IMG / "quickstart-open.png")


@shot
def quickstart_curves(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    choose(page, "Complex data as", "db")
    choose(page, "Plot type", "curve")
    controls = ".tab-body:not([hidden]) .controls"
    mark(page, [
        (1, f"{controls} label.field", 0, "l"),
        (2, f"{controls} label.field", 1, "l"),
        (3, f"{controls} label.field", 3, "l"),
    ])
    save(page, QUICKSTART_IMG / "quickstart-curves.png", clip=region(page, ".tab-body:not([hidden]) .plot-area", pad=8))


@shot
def quickstart_save(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")
    choose(page, "Complex data as", "db")
    mark(page, [
        (1, ".tab-body:not([hidden]) .save-row button", 0, "tl"),
        (2, ".tab-body:not([hidden]) .figure-toolbar button", 0, "tl"),
    ])
    save(page, QUICKSTART_IMG / "quickstart-save.png", clip=region(page, ".tab-body:not([hidden]) .figure-col", pad=16))


# ---- run ---------------------------------------------------------------------------------------


def main(names: List[str]) -> int:
    unknown = [n for n in names if n.replace("-", "_") not in SHOTS]
    if unknown:
        print(f"unknown shot(s) {unknown}; the shots are: {', '.join(SHOTS)}", file=sys.stderr)
        return 2
    if not (server.STATIC_DIR / "index.html").is_file():
        print("the web UI is not built: npm run build in viewer/web", file=sys.stderr)
        return 2
    make_files(SCRATCH / "Lab data")
    url, srv = start_viewer(SCRATCH / "Lab data")
    print("Screenshots:")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name in [n.replace("-", "_") for n in names] or list(SHOTS):
                # a fresh browser window per shot: one page, nothing left from the shot before
                ctx = browser.new_context(viewport=SIZE, color_scheme="light")
                ctx.set_default_timeout(15_000)
                page = ctx.new_page()
                SHOTS[name](page, url, ctx)
                # close the pages saying goodbye, so the viewer frees their files at once
                for open_page in ctx.pages:
                    if not open_page.is_closed():
                        open_page.close(run_before_unload=True)
                time.sleep(0.5)
                ctx.close()
            browser.close()
    finally:
        srv.should_exit = True
        shutil.rmtree(SCRATCH, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
