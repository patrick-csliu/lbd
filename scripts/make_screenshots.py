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
  // a neutral example path instead of the scratch folder's (first: a shorter path can move the page)
  for (const el of document.querySelectorAll(".path, .path-line .path-folder"))
    el.textContent = el.textContent.replace(/^.*[\\/]Lab data/, String.raw`C:\Users\me\Documents\Lab data`);
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

    # several recorded values (panels): the Rabi mock file of the viewer's tests
    sys.path.insert(0, str(REPO / "viewer" / "tests"))
    import mock_values

    mock_values.rabi(small=False).save(folder / "rabi_readout.lbd")

    # a library of measurements over two years (the Library's list): the viewer tests' mock library
    import mock_library

    mock_library.write_library(folder / "Lab library", 120)

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
    # the Files sidebar offers every list; most shots open files from its folder tree (see main)
    cfg.set_library({"sidebar_scopes": ["library", "folders", "starred", "recent"]})
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


def fresh(page: Page, url: str, workspace: str = "Figure") -> None:
    """A new page with nothing open (tabs are not restored), showing a workspace (most shots are
    of Figure)."""
    page.goto(url)
    page.locator(".page-badge").wait_for()
    page.get_by_role("tab", name=workspace, exact=True).click()
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
        (6, "main:not([hidden]) .tabs .tab", 0, "b"),
        (7, ".tab-body:not([hidden]) .file-head", 0, "r"),
        (8, ".tab-body:not([hidden]) .controls", 0, "tr"),
        (9, ".tab-body:not([hidden]) .figure-toolbar", 0, "b"),
        (10, ".tab-body:not([hidden]) .figure", 0, "tr"),
        (11, ".tab-body:not([hidden]) .save-row", 0, "r"),
    ])
    save(page, VIEWER_IMG / "overview.png")


@shot
def explore(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Explore")
    page.locator(".row-label", has_text="sweep.lbd").first.dblclick()
    host = page.locator("main:not([hidden]) .explore-overlay")
    page.locator("main:not([hidden]) .explore-readout .mono").wait_for()
    page.wait_for_timeout(800)
    box = host.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.5)   # read a cell
    page.locator("main:not([hidden]) .explore-pick").wait_for()
    page.keyboard.press("c")                    # without the cuts (shown in reading.png): all fits
    page.wait_for_timeout(1500)
    mark(page, [
        (1, ".pages", 0, "b"),
        (2, "main:not([hidden]) .tabs .tab", 0, "b"),
        (3, "main:not([hidden]) .controls .field", 0, "r"),
        (4, "main:not([hidden]) .axis-select", 0, "r"),
        (5, "main:not([hidden]) .explore-note", 0, "b"),
        (6, "main:not([hidden]) .explore-host", 0, "tr"),
        (7, "main:not([hidden]) .explore-pick", 0, "b"),
    ])
    save(page, VIEWER_IMG / "explore.png")


@shot
def explore_reading(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Explore")
    page.locator(".row-label", has_text="sweep.lbd").first.dblclick()
    host = page.locator("main:not([hidden]) .explore-overlay")
    page.locator("main:not([hidden]) .explore-readout .mono").wait_for()
    explore_area = page.locator("main:not([hidden])")
    explore_area.get_by_label("Plot type").select_option("heatmap")               # the sweep as a map
    page.wait_for_timeout(1200)
    explore_area.get_by_label("Complex values").select_option("db")
    page.wait_for_timeout(1500)
    box = host.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.35, box["y"] + box["height"] * 0.45)      # cursor 1
    page.locator("main:not([hidden]) .explore-pick").first.wait_for()
    page.keyboard.down("Shift")
    page.mouse.click(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.7)        # cursor 2
    page.keyboard.up("Shift")
    page.locator("main:not([hidden]) .explore-pick").nth(1).wait_for()
    page.wait_for_timeout(600)
    mark(page, [
        (1, "main:not([hidden]) .explore-cut-top", 0, "l"),
        (2, "main:not([hidden]) .explore-cut-right", 0, "t"),
        (3, "main:not([hidden]) .explore-host", 0, "tr"),
    ])
    save(page, VIEWER_IMG / "reading.png")


@shot
def explore_operations(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Explore")
    page.locator(".row-label", has_text="sweep.lbd").first.dblclick()
    area = page.locator("main:not([hidden])")
    page.locator("main:not([hidden]) .explore-readout .mono").wait_for()
    area.get_by_label("Plot type").select_option("heatmap")
    page.wait_for_timeout(1200)
    area.get_by_label("Complex values").select_option("db")
    page.wait_for_timeout(1200)
    area.locator(".operations").get_by_role("button", name="+ Add operation ▾").click()
    page.locator(".context-menu").get_by_role("menuitem", name="Subtract the mean", exact=True).click()
    page.wait_for_timeout(1000)
    area.get_by_label("Subtract the mean: along").select_option("traces")      # along Power: the background
    page.wait_for_timeout(2000)
    mark(page, [
        (1, "main:not([hidden]) .operations", 0, "r"),
        (2, "main:not([hidden]) .explore-host", 0, "tr"),
    ])
    save(page, VIEWER_IMG / "operations.png")


@shot
def explore_equations(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Explore")
    page.locator(".row-label", has_text="sweep.lbd").first.dblclick()
    area = page.locator("main:not([hidden])")
    page.locator("main:not([hidden]) .explore-readout .mono").wait_for()
    area.get_by_label("Complex values").select_option("db")
    page.wait_for_timeout(1200)
    box = area.get_by_label("Equation for z")
    box.fill("z - max(z)")                      # each power's row against its own maximum
    box.press("Enter")
    page.wait_for_timeout(1500)
    area.locator(".equations").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    mark(page, [
        (1, "main:not([hidden]) .eq-legend", 0, "r"),
        (2, "main:not([hidden]) .eq-field", 2, "r"),
    ])
    save(page, VIEWER_IMG / "equations.png", clip=region(page, "main:not([hidden]) .operations", pad=16, extra_right=40))


@shot
def explore_panels(page: Page, url: str, ctx) -> None:
    page.set_viewport_size({"width": SIZE["width"], "height": 1420})   # the panels and the Cursors section
    fresh(page, url, "Explore")
    page.locator(".row-label", has_text="rabi_readout.lbd").first.dblclick()
    area = page.locator("main:not([hidden])")
    expect_pictures = area.locator(".panel .explore-picture")
    for k in range(4):
        expect_pictures.nth(k).wait_for()
    page.wait_for_timeout(1500)
    box = area.locator(".panel .explore-overlay").nth(0).bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.42, box["y"] + box["height"] * 0.5)   # one cursor in every panel
    area.locator(".cursor-others").wait_for()
    page.mouse.move(5, 400)                     # no "mouse at" line: the panels keep their size
    page.wait_for_timeout(1500)
    mark(page, [                                # the numbers of the list in explore.md
        (1, "main:not([hidden]) .panel-bar button", 0, "L"),
        (2, "main:not([hidden]) .panel.active", 0, "L"),
        (3, "main:not([hidden]) .panel-title", 1, "t"),
        (4, "main:not([hidden]) .controls fieldset", 0, "r"),
        (5, "main:not([hidden]) .panel-sync", 0, "r"),
    ])
    save(page, VIEWER_IMG / "panels.png")
    page.set_viewport_size(SIZE)


@shot
def library(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Library")
    page.locator(".library-row").first.wait_for(timeout=60_000)   # the index reads the files first
    page.get_by_role("button", name="OK", exact=True).click()     # the first-time notice (described in the text)
    page.get_by_label("Search the files").fill("resonator")       # a search, shown as it is used
    rows = page.locator(".library-row", has_text="Late resonator sweep")
    rows.first.wait_for()
    rows.first.click()
    page.locator(".library-detail h1", has_text="Late resonator sweep").wait_for()
    page.locator(".library-detail .preview img").wait_for(timeout=60_000)   # drawn by the server
    page.mouse.move(5, 400)
    page.wait_for_timeout(800)
    mark(page, [                                # the numbers of the list in library.md
        (1, ".library-tree[aria-label='Folders']", 0, "r"),
        (2, ".library-tree[aria-label='Dates']", 0, "r"),
        (3, ".library-search", 0, "r"),
        (4, ".library-head", 0, "b"),
        (5, ".library-detail .library-file-head", 0, "L"),
    ])
    save(page, VIEWER_IMG / "library.png")


@shot
def library_pictures(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Library")
    page.locator(".library-row").first.wait_for(timeout=60_000)
    notice = page.get_by_role("button", name="OK", exact=True)
    if notice.is_visible():
        notice.click()
    page.get_by_role("button", name="Pictures", exact=True).click()
    cards = page.locator(".library-card:not(.loading)")
    cards.nth(1).click()
    page.wait_for_function(                             # the pictures in view, drawn (or why not)
        "() => [...document.querySelectorAll('.library-card:not(.loading)')].every(c => !c.textContent.includes('Drawing'))",
        timeout=60_000)
    page.locator(".library-detail .library-file-head").wait_for()   # (no second preview on the right)
    page.mouse.move(5, 400)
    page.wait_for_timeout(800)
    mark(page, [])                                      # no numbers; the path as on the other shots
    save(page, VIEWER_IMG / "library-pictures.png")
    page.get_by_role("button", name="List", exact=True).click()   # as the other shots expect


@shot
def folders(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    expand(page, "examples")
    page.locator(".row-label", has_text="sweep.lbd").first.click(button="right")
    page.locator(".context-menu").wait_for()
    mark(page, [
        (1, ".sidebar .filter", 0, "r"),
        (2, ".sidebar .filter-row .icon", 0, "r"),
        (3, ".sidebar .root-row", 0, "r"),
        (4, ".sidebar .dir-row", 0, "r"),
        (5, ".sidebar .file-row", 0, "r"),
        (6, ".context-menu", 0, "tr"),
    ])
    save(page, VIEWER_IMG / "folders.png", clip={"x": 0, "y": 0, "width": 640, "height": 520})


@shot
def files_sidebar(page: Page, url: str, ctx) -> None:
    fresh(page, url, "Library")
    page.locator(".library-row").first.wait_for(timeout=60_000)
    notice = page.get_by_role("button", name="OK", exact=True)
    if notice.is_visible():
        notice.click()
    page.get_by_label("Search the files").fill("resonator")
    page.locator(".library-row", has_text="Late resonator sweep").first.wait_for()
    page.get_by_role("tab", name="Figure", exact=True).click()
    page.locator(".files-scope").select_option("library")
    row = page.locator(".files-row", has_text="Late resonator sweep").first
    row.dblclick()                                       # in Figure: plotted (a click shows what is inside)
    page.locator(".tab-body:not([hidden]) .figure img").first.wait_for()
    settle(page)
    mark(page, [
        (1, ".sidebar .files-scope", 0, "r"),
        (2, ".sidebar .files-filters", 0, "r"),
        (3, ".sidebar .filter", 0, "r"),
        (4, ".sidebar .files-row.active", 0, "r"),
        (5, "main:not([hidden]) .folders-toggle", 0, "b"),
    ])
    save(page, VIEWER_IMG / "files-sidebar.png", clip={"x": 0, "y": 0, "width": 720, "height": 560})


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
        (3, ".settings-popover .settings-title", 2, "L"),
    ])
    box = pop.bounding_box()
    save(page, VIEWER_IMG / "settings.png", clip={"x": box["x"] - 48, "y": 0, "width": SIZE["width"] - box["x"] + 48,
                                                  "height": box["y"] + box["height"] + 16})


@shot
def styles_page(page: Page, url: str, ctx) -> None:
    fresh(page, url)
    open_file(page, "sweep.lbd")               # the preview shows the open file
    page.get_by_role("button", name="Styles", exact=True).click()
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
    page.get_by_role("button", name="Language modules", exact=True).click()
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
                ctx.add_init_script("try { if (!sessionStorage.getItem('lbd-sidebar-scope')) "
                                    "sessionStorage.setItem('lbd-sidebar-scope', 'folders') } catch (e) {}")
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
