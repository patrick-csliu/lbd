"""The Explore view (preview) in a real browser: the server's picture appears, a click reads the
stored value, the wheel zooms, a double-click shows everything again, and one session is opened."""

import json

import lbd
import numpy as np
import pytest
from pageui import open_file
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


def frames(page: Page, action):
    """Do `action` and return the mapping (X-LBD-Frame) of the picture it brings."""
    with page.expect_response(lambda r: "/api/explore/" in r.url and r.url.endswith("/render")) as resp:
        action()
    return json.loads(resp.value.headers["x-lbd-frame"])


def at(page: Page, meta, x, y):
    """Page coordinates of a data point, from a picture's mapping (linear axes)."""
    box = page.locator(".explore-overlay").bounding_box()
    d = meta["dpr"]
    left, top, w, h = (v / d for v in meta["plot"])
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    return box["x"] + left + (x - x0) / (x1 - x0) * w, box["y"] + top + h - (y - y0) / (y1 - y0) * h


def test_explore_reads_zooms_and_resets(small_map, new_page):
    page = new_page()
    opened = []
    page.on("request", lambda r: opened.append(r) if r.url.endswith("/api/explore") and r.method == "POST" else None)
    open_file(page, "small_map.lbd")
    meta = frames(page, lambda: page.get_by_role("button", name="Explore (preview)").click())
    expect(page.locator(".explore-note")).to_have_text("every cell shown")
    assert meta["xlim"] == pytest.approx([0.5, 20]) and meta["ylim"] == pytest.approx([5, 45])

    page.mouse.click(*at(page, meta, 8, 30))
    expect(page.locator(".explore-pick")).to_contain_text("13 at x = 8, y = 30")

    x, y = at(page, meta, 8, 30)
    page.mouse.move(x, y)
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < 19.5     # zoomed in ...
    assert zoomed["xlim"][0] < 8 < zoomed["xlim"][1]        # ... around the mouse

    full = frames(page, lambda: page.locator(".explore-overlay").dblclick(position={"x": 5, "y": 5}))
    assert full["xlim"] == pytest.approx([0.5, 20])
    assert len(opened) == 1                                 # one session for all of it
