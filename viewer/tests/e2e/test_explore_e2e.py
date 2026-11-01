"""The Explore workspace in a real browser: a file opens there from the folders, the server's
picture appears, a click reads the stored value, the wheel zooms, a double-click shows everything
again, the plot settings change in the same session; and the Library and Figure lead there."""

import json

import httpx

import lbd
import numpy as np
import pytest
from pageui import deliver, row
from playwright.sync_api import Page, expect


@pytest.fixture
def small_map(viewer):
    """5 × 4 cells, uneven along x; each cell's value is column + 5 × row."""
    d = lbd.Dataset(title="Small map")
    d.add_axis("x", [1.0, 2, 4, 8, 16])
    d.add_axis("y", [10.0, 20, 30, 40])
    d.add_value("value", np.arange(5.0)[None, :] + 5 * np.arange(4.0)[:, None], axes=["y", "x"])
    d.plot = {"kind": "heatmap", "x": "x", "y": "y"}
    d.save(viewer.data / "small_map.lbd")


def explore(page: Page):
    """The Explore workspace's area (Figure's is hidden next to it)."""
    return page.locator("main:not([hidden])")


def frames(page: Page, action, quiet_ms: int = 400):
    """Do `action` and return the mapping (X-LBD-Frame) of the last picture it brings: a picture
    asked for before may still arrive first, so this waits until no more come for a moment."""
    def is_picture(r):
        return "/api/explore/" in r.url and r.url.endswith("/render") and r.ok

    got = []

    def collect(r):
        if is_picture(r):
            got.append(r)

    page.on("response", collect)
    try:
        with page.expect_response(is_picture):
            action()
        seen = -1
        while seen != len(got):
            seen = len(got)
            page.wait_for_timeout(quiet_ms)
    finally:
        page.remove_listener("response", collect)
    return json.loads(got[-1].headers["x-lbd-frame"])


def at(page: Page, meta, x, y):
    """Page coordinates of a data point, from a picture's mapping (linear axes)."""
    box = explore(page).locator(".explore-overlay").bounding_box()
    d = meta["dpr"]
    left, top, w, h = (v / d for v in meta["plot"])
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    return box["x"] + left + (x - x0) / (x1 - x0) * w, box["y"] + top + h - (y - y0) / (y1 - y0) * h


def test_explore_reads_zooms_and_resets(small_map, new_page):
    page = new_page("Explore")
    opened = []
    page.on("request", lambda r: opened.append(r) if r.url.endswith("/api/explore") and r.method == "POST" else None)
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    expect(explore(page).locator(".explore-note")).to_have_text("every cell shown")
    assert meta["xlim"] == pytest.approx([0.5, 20]) and meta["ylim"] == pytest.approx([5, 45])

    page.mouse.click(*at(page, meta, 8, 30))
    expect(explore(page).locator(".explore-pick")).to_contain_text("13 at x = 8, y = 30")

    page.mouse.move(*at(page, meta, 8, 30))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < 19.5     # zoomed in ...
    assert zoomed["xlim"][0] < 8 < zoomed["xlim"][1]        # ... around the mouse

    full = frames(page, lambda: explore(page).locator(".explore-overlay").dblclick(position={"x": 5, "y": 5}))
    assert full["xlim"] == pytest.approx([0.5, 20])
    assert len(opened) == 1                                 # one session for all of it


def test_other_plot_settings_redraw_in_the_same_session(small_map, new_page):
    page = new_page("Explore")
    opened = []
    page.on("request", lambda r: opened.append(r) if r.url.endswith("/api/explore") and r.method == "POST" else None)
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    kind = explore(page).get_by_label("Plot type")
    expect(kind).to_have_value("heatmap")
    meta = frames(page, lambda: kind.select_option("curve"))
    expect(explore(page).get_by_label("One curve per")).to_have_value("y")
    assert meta["xlim"] == pytest.approx([1, 16])           # the curves' own range
    assert len(opened) == 1


def test_the_library_shows_a_file_and_opens_it(small_map, new_page):
    page = new_page("Library")
    page.locator(".library-row", has_text="Small map").click()           # the list shows the title
    detail = page.locator(".library-detail")
    expect(detail.locator("h1")).to_have_text("Small map")
    expect(detail).to_contain_text("value")
    frames(page, lambda: detail.get_by_role("button", name="Open in Explore").click())
    expect(page.get_by_role("tab", name="Explore", exact=True)).to_have_attribute("aria-selected", "true")
    expect(explore(page).locator(".tab-label")).to_have_text(["small_map.lbd"])


def test_a_figure_opens_in_explore_and_back(small_map, new_page):
    page = new_page("Figure")
    row(page, "small_map.lbd").dblclick()
    figure = explore(page)
    frames(page, lambda: figure.get_by_role("button", name="Open in Explore").click())
    expect(page.get_by_role("tab", name="Explore", exact=True)).to_have_attribute("aria-selected", "true")
    explore(page).get_by_role("button", name="Open in Figure").click()
    expect(page.get_by_role("tab", name="Figure", exact=True)).to_have_attribute("aria-selected", "true")


def test_files_from_explorer_open_in_the_workspace_set(viewer, small_map, new_page):
    page = new_page("Library")
    # as the settings menu does: every page is told
    httpx.put(f"http://127.0.0.1:{viewer.port}/api/settings", headers={"X-LBD-Token": viewer.state.token},
              json={"open_data_in": "explore"}).raise_for_status()
    deliver(viewer, "small_map.lbd")
    expect(page.get_by_role("tab", name="Explore", exact=True)).to_have_attribute("aria-selected", "true")
    expect(explore(page).locator(".tab-label")).to_have_text(["small_map.lbd"])
    # Explore keeps no hold on the file: the Figure workspace of any page can still open it.
    assert all(not p["files"] for p in viewer.state.pages.page_list())


@pytest.fixture
def sweep(viewer):
    """Five traces of 50 points, trace k at height k."""
    d = lbd.Dataset(title="Sweep")
    d.add_axis("power", [-40.0, -30.0, -20.0, -10.0, 0.0])
    d.add_axis("t", np.arange(50.0))
    d.add_value("v", np.repeat(np.arange(5.0)[:, None], 50, axis=1), axes=["power", "t"])
    d.plot = {"kind": "curve", "x": "t", "series": "power"}
    d.save(viewer.data / "sweep.lbd")


def test_chosen_traces_typed_limits_and_a_swap(sweep, small_map, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).locator(".axis-select .fold").click()                # the list is folded while all are shown
    values = explore(page).locator(".axis-values span")
    frames(page, lambda: values.nth(1).click())                       # only power -30
    frames(page, lambda: values.nth(3).click(modifiers=["ControlOrMeta"]))
    expect(explore(page).locator(".axis-select legend")).to_contain_text("2 of 5")
    box = explore(page).get_by_label("Horizontal from")
    box.fill("10")
    meta = frames(page, lambda: box.press("Enter"))
    assert meta["xlim"][0] == pytest.approx(10)
    # a map: swapping its axes
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    meta = frames(page, lambda: explore(page).get_by_role("button", name="Swap the axes").click())
    assert meta["xlim"] == pytest.approx([5, 45]) and meta["ylim"] == pytest.approx([0.5, 20])


def test_reopening_a_file_shows_what_was_explored(sweep, viewer, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).locator(".axis-select .fold").click()
    frames(page, lambda: explore(page).locator(".axis-values span").nth(4).click())
    page.wait_for_timeout(1500)                                       # remembered a moment later
    page.reload()
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    expect(explore(page).locator(".axis-select legend")).to_contain_text("1 of 5")
    # remembered by LBD, not in the file
    assert lbd.load(viewer.data / "sweep.lbd").plot == {"kind": "curve", "x": "t", "series": "power"}


def test_a_file_that_grows_keeps_the_zoom(sweep, viewer, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    page.mouse.move(*at(page, meta, 25, 2))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -400))
    # the program writing the file adds two traces
    d = lbd.Dataset(title="Sweep")
    d.add_axis("power", [-40.0, -30.0, -20.0, -10.0, 0.0, 10.0, 20.0])
    d.add_axis("t", np.arange(50.0))
    d.add_value("v", np.repeat(np.arange(7.0)[:, None], 50, axis=1), axes=["power", "t"])
    d.plot = {"kind": "curve", "x": "t", "series": "power"}
    with page.expect_response(lambda r: r.url.endswith("/api/explore") and r.request.method == "POST", timeout=15_000):
        d.save(viewer.data / "sweep.lbd")
    again = frames(page, lambda: None)
    assert again["xlim"] == pytest.approx(zoomed["xlim"])           # the zoom stayed
    expect(explore(page).locator(".axis-select legend")).to_contain_text("all 7")


def test_a_value_bigger_than_memory_steps_through_its_slider(viewer, new_page, monkeypatch):
    """Plan 6d: with little memory (a fake), a 3-D value is read by part; each slider position
    shows its own map, and the stored value read back is that position's."""
    from lbd_viewer import memory

    system = lambda: (4 * memory.GB, 2 * memory.GB + 500)          # 500 bytes of room: one map fits
    monkeypatch.setitem(memory._shared, "cache", memory.PartCache(memory.Memory(system=system)))
    d = lbd.Dataset(title="Cube")
    d.add_axis("t", np.arange(6.0))
    d.add_axis("y", [10.0, 20, 30, 40])
    d.add_axis("x", [1.0, 2, 4, 8, 16])
    cells = np.arange(5.0)[None, :] + 5 * np.arange(4.0)[:, None]
    d.add_value("value", 100 * np.arange(6.0)[:, None, None] + cells, axes=["t", "y", "x"])
    d.plot = {"kind": "heatmap", "x": "x", "y": "y"}
    d.save(viewer.data / "cube.lbd")

    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "cube.lbd").dblclick())
    slider = explore(page).get_by_role("slider")
    for t in range(1, 4):
        meta = frames(page, lambda: slider.press("ArrowRight"))
        page.mouse.click(*at(page, meta, 8, 30))
        expect(explore(page).locator(".explore-pick")).to_contain_text(f"{100 * t + 13:g} at x = 8, y = 30")
    assert memory.shared().hits + memory.shared().misses > 0           # it went through the part cache
