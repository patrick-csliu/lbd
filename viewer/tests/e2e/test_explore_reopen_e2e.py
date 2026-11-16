"""Explore after a long pause, in a real browser (plan 16): a view the server closed (unused for a
while) reopens quietly for whatever is asked first: a click, a zoom, a cursor, a size change
(16.38); and a remembered zoom that misses the data shows all of it, while one on the data is kept
(16.12)."""

import lbd
import pytest
from lbd_viewer.catalog import structure
from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import at, explore, frames, small_map  # noqa: F401 - small_map is a fixture


def closed_after_a_pause(viewer, page):
    """The server closes every Explore session, as it does after 10 unused minutes (and only
    once: the reopened ones then stay)."""
    sessions = viewer.state.explore
    sessions.idle = 0.3
    page.wait_for_timeout(500)
    with sessions._lock:
        sessions._expire()
    sessions.idle = 600
    page.wait_for_timeout(200)                                     # closed (in a thread of their own)


def no_error(page):
    expect(explore(page).locator(".explore-error")).to_have_count(0)


def test_a_closed_view_reopens_quietly_for_a_click_a_zoom_and_a_resize(viewer, small_map, new_page):  # noqa: F811
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())

    closed_after_a_pause(viewer, page)
    page.mouse.click(*at(page, meta, 8, 30))                       # a cursor: /cursors found it closed
    expect(explore(page).locator(".explore-pick")).to_contain_text("13 at x = 8, y = 30")
    no_error(page)

    closed_after_a_pause(viewer, page)
    page.mouse.move(*at(page, meta, 8, 30))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))       # a picture: /render found it closed
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < 19.5
    no_error(page)

    closed_after_a_pause(viewer, page)
    size = page.viewport_size
    frames(page, lambda: page.set_viewport_size({"width": size["width"] - 120, "height": size["height"]}))
    no_error(page)


def test_several_requests_on_a_closed_view_share_one_reopening(viewer, small_map, new_page):  # noqa: F811
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    opened = []
    page.on("request", lambda r: opened.append(r) if r.url.endswith("/api/explore") and r.method == "POST" else None)
    closed_after_a_pause(viewer, page)
    page.mouse.move(*at(page, meta, 8, 30))

    def at_once():
        page.mouse.click(*at(page, meta, 8, 30))
        page.mouse.wheel(0, -300)
    zoomed = frames(page, at_once)
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < 19.5            # the zoom asked for, after the reopening
    no_error(page)
    assert len(opened) == 1                                        # one reopening for both


def remembered(viewer, xlim, ylim):
    path = viewer.data / "small_map.lbd"
    viewer.state.catalog.remember(str(path), structure(lbd.info(path)), {
        "spec": {"values": ["value"], "kind": "heatmap", "x": "x", "y": "y"},
        "settings": {}, "stat": "max", "view": {"xlim": xlim, "ylim": ylim},
        "cursors": {"type": "cross", "at": [], "active": 0, "cuts": True, "on": True}, "listOpen": True,
    })


def test_a_remembered_zoom_that_misses_the_data_shows_all_of_it(viewer, cfg, small_map, new_page):  # noqa: F811
    cfg.set_explore({"keep": {"zoom": True}})                          # (not kept by default, 16.44)
    remembered(viewer, [1000.0, 2000.0], [5.0, 45.0])
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    assert meta["xlim"] == pytest.approx([0.5, 20])                # all the data, not an empty corner


def test_a_remembered_zoom_on_the_data_is_kept(viewer, cfg, small_map, new_page):  # noqa: F811
    cfg.set_explore({"keep": {"zoom": True}})                          # (not kept by default, 16.44)
    remembered(viewer, [2.0, 8.0], [15.0, 35.0])
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    assert meta["xlim"] == pytest.approx([2, 8]) and meta["ylim"] == pytest.approx([15, 35])
