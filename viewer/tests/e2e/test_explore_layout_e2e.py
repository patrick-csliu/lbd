"""Explore fills the window at every size: the page never scrolls, the plot is in the first
screen, a cursor's value shows on its panel, maps keep a usable width (or the panels stack), the
inspector shows the file's values, axes and metadata, and nothing is wider than the window.
Full screen, half screen and split windows are everyday sizes."""

import lbd
import numpy as np
import pytest
from pageui import row
from playwright.sync_api import Page, expect
from test_explore_e2e import explore, frames

SIZES = [(1920, 1080), (1366, 768), (960, 1080), (683, 768), (960, 540), (3440, 1440)]


def layout(page: Page):
    return page.evaluate(
        """() => {
          const se = document.scrollingElement, main = document.querySelector('main:not([hidden])');
          const box = (el) => el && el.getBoundingClientRect();
          const pic = box(main.querySelector('.explore-picture')), ro = box(main.querySelector('.explore-readout'));
          const hosts = [...main.querySelectorAll('.explore-host')].map((h) => h.getBoundingClientRect().width);
          const wide = [...main.querySelectorAll('.explore-tab *')].filter((e) => {
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.right > innerWidth + 1 && !e.closest('.explore-controls');   // the drawer is off-screen on purpose
          }).length;
          return { scrollY: se.scrollHeight - innerHeight, scrollX: se.scrollWidth - innerWidth, picTop: pic && pic.top, picBottom: pic && pic.bottom,
                   roTop: ro && ro.top, roBottom: ro && ro.bottom, hosts, wide, h: innerHeight };
        }"""
    )


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_explore_fits_the_window(values_files, new_page, size):
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())    # opened at 1280×800, then resized
    w, h = size
    page.set_viewport_size({"width": w, "height": h})
    page.wait_for_timeout(1200)                                            # the panels are drawn at their new size
    m = layout(page)
    assert m["scrollY"] <= 1 and m["scrollX"] <= 1, m                      # the page never scrolls
    assert m["picTop"] is not None and 0 <= m["picTop"] < h - 60, m        # the plot is in the first screen
    assert m["wide"] == 0, m                                               # nothing sticks out of the window
    assert all(x >= 240 for x in m["hosts"]), m                            # maps keep a usable width (or stack)
    # a click: its value on the panel, in the window
    overlay = explore(page).locator(".panel .explore-overlay").first
    b = overlay.bounding_box()
    overlay.click(position={"x": b["width"] * 0.5, "y": b["height"] * 0.5})
    readout = explore(page).locator(".panel .explore-readout").first
    expect(readout).to_contain_text(" at ")
    m = layout(page)
    assert 0 <= m["roTop"] and m["roBottom"] <= h, m
    # the inspector: the file's values and axes, and its metadata with a filter
    explore(page).get_by_role("tab", name="Values & axes").click()
    body = explore(page).locator(".inspector-body")
    expect(body).to_contain_text("amplitude")
    expect(body).to_contain_text("Axes")
    explore(page).get_by_role("tab", name="Metadata").click()
    expect(body.get_by_label("Filter metadata").or_(body.get_by_text("None"))).to_be_visible()
    assert layout(page)["scrollY"] <= 1


def test_narrow_windows_have_the_controls_in_a_drawer(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    page.set_viewport_size({"width": 683, "height": 768})
    toggle = explore(page).get_by_role("button", name="Controls")
    expect(toggle).to_be_visible()
    controls = explore(page).locator(".explore-controls")
    page.wait_for_timeout(400)                                                     # after its slide
    assert controls.bounding_box()["x"] + controls.bounding_box()["width"] <= 1     # off-screen until asked for
    toggle.click()
    page.wait_for_timeout(300)
    assert controls.bounding_box()["x"] >= 0                                       # slid in over the panels
    expect(explore(page).get_by_label("Plot type")).to_be_visible()
    explore(page).locator(".explore-scrim").click(position={"x": 600, "y": 300})   # a click beside it closes it
    page.wait_for_timeout(300)
    assert controls.bounding_box()["x"] + controls.bounding_box()["width"] <= 1


def test_escape_closes_the_help_and_keeps_the_cursors(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    overlay = explore(page).locator(".panel .explore-overlay").first
    b = overlay.bounding_box()
    overlay.click(position={"x": b["width"] * 0.5, "y": b["height"] * 0.5})
    readout = explore(page).locator(".panel .explore-readout").first
    expect(readout).to_contain_text(" at ")
    explore(page).get_by_role("button", name="Mouse and keys").click()
    expect(page.get_by_role("dialog", name="Mouse and keys")).to_be_visible()
    overlay.focus()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="Mouse and keys")).to_have_count(0)
    expect(readout).to_contain_text(" at ")                                 # the cursor is still there
    page.keyboard.press("Escape")                                           # now Esc removes it, with Undo
    expect(readout).not_to_contain_text(" at ")
    page.get_by_role("button", name="Undo").click()
    expect(readout).to_contain_text(" at ")


def test_a_scatter_view_offers_figure_and_curves(viewer, new_page):
    # a file whose saved view is a scatter plot (as the examples' I/Q readout): Figure draws it
    rng = np.random.default_rng(7)
    d = lbd.Dataset(title="Readout I/Q")
    d.add_axis("prep", [0.0, 1.0], label="Prepared state")
    d.add_axis("shot", np.arange(200, dtype=float), label="Shot")
    d.add_value("IQ", (rng.normal(size=(2, 200)) + 1j * rng.normal(size=(2, 200))) * 1e-3, axes=["prep", "shot"], unit="V")
    d.plot = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "prep"}
    d.save(viewer.data / "iq.lbd")
    page = new_page("Explore")
    row(page, "iq.lbd").dblclick()
    box = explore(page).locator(".explore-error")
    expect(box).to_contain_text("Explore can't show this saved scatter view", timeout=15_000)
    expect(box.get_by_role("button", name="Open in Figure")).to_be_visible()
    frames(page, lambda: box.get_by_role("button", name="Show as curves").click())
    expect(explore(page).locator(".explore-error")).to_have_count(0)
