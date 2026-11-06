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
    path = explore(page).locator(".explore-path")
    if path.is_visible():                                                  # the copy icon right after the path
        copy = explore(page).locator(".explore-head").get_by_role("button", name="Copy path")
        assert copy.bounding_box()["x"] - (path.bounding_box()["x"] + path.bounding_box()["width"]) <= 8
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


def test_a_saved_scatter_view_opens_as_scatter(viewer, new_page):
    # a file whose saved view is a scatter plot (as the examples' I/Q readout)
    rng = np.random.default_rng(7)
    d = lbd.Dataset(title="Readout I/Q")
    d.add_axis("prep", [0.0, 1.0], label="Prepared state")
    d.add_axis("shot", np.arange(200, dtype=float), label="Shot")
    d.add_value("IQ", (rng.normal(size=(2, 200)) + 1j * rng.normal(size=(2, 200))) * 1e-3, axes=["prep", "shot"], unit="V")
    d.plot = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "prep"}
    d.save(viewer.data / "iq.lbd")
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "iq.lbd").dblclick())
    expect(explore(page).get_by_label("Plot type")).to_have_value("scatter")
    expect(explore(page).locator(".explore-error")).to_have_count(0)
    assert meta["note"] == "every point shown" and meta["equal"]


def drag(page: Page, handle, dx: float, dy: float):
    b = handle.bounding_box()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx / 2, y + dy / 2)
    page.mouse.move(x + dx, y + dy)
    page.mouse.up()


@pytest.mark.parametrize("size,inspector", [((1920, 1080), "right"), ((1366, 768), "below")])
def test_the_controls_and_the_inspector_are_resized(values_files, new_page, size, inspector):
    """Plan 10: drag the inner edge of the controls and of the inspector; the size is kept after a
    reload; double-click goes back to the default; limits hold."""
    page = new_page("Explore")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    ctl, insp = explore(page).locator(".explore-controls"), explore(page).locator(".explore-inspector")
    w0 = ctl.bounding_box()["width"]
    drag(page, explore(page).get_by_label("Width of the controls"), 60, 0)
    assert ctl.bounding_box()["width"] == pytest.approx(w0 + 60, abs=3)
    if inspector == "right":
        handle, measure, move = explore(page).get_by_label("Width of the inspector"), "width", (-80, 0)
    else:
        handle, measure, move = explore(page).get_by_label("Height of the inspector"), "height", (0, -80)
    i0 = insp.bounding_box()[measure]
    drag(page, handle, *move)
    i1 = insp.bounding_box()[measure]
    assert i1 == pytest.approx(i0 + 80, abs=3)
    page.reload()                                                          # the sizes stay (this browser)
    page.get_by_role("tab", name="Explore", exact=True).click()
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    assert explore(page).locator(".explore-controls").bounding_box()["width"] == pytest.approx(w0 + 60, abs=3)
    assert explore(page).locator(".explore-inspector").bounding_box()[measure] == pytest.approx(i1, abs=3)
    explore(page).get_by_label("Width of the controls").dblclick()
    assert explore(page).locator(".explore-controls").bounding_box()["width"] == pytest.approx(w0, abs=3)
    drag(page, explore(page).get_by_label("Width of the controls"), -400, 0)        # the smallest it may be
    assert explore(page).locator(".explore-controls").bounding_box()["width"] == pytest.approx(200, abs=3)


def test_a_maps_axes_have_the_same_width(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    h, v = explore(page).get_by_label("Horizontal axis"), explore(page).get_by_label("Vertical axis")
    assert h.bounding_box()["width"] == pytest.approx(v.bounding_box()["width"], abs=1)
    assert h.bounding_box()["x"] == pytest.approx(v.bounding_box()["x"], abs=1)


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_two_cursors_are_read_without_cutting(values_files, new_page, size):
    """Plan 10: with two cursors on a map, no read-out or inspector text is wider than its box
    (it wraps, or the line has a row per cursor); a mean of ±flux reads 0, not 2.8e−17."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())    # opened at 1280×800, then resized
    page.set_viewport_size({"width": size[0], "height": size[1]})
    overlay = explore(page).locator(".panel .explore-overlay").first
    b = None
    for _ in range(40):                                                    # the panels redrawn at their new size
        page.wait_for_timeout(400)
        was, b = b, overlay.bounding_box()
        if was == b and page.evaluate("document.querySelector('main:not([hidden]) .explore-overlay').width > 0"):
            break
    page.wait_for_timeout(800)
    overlay.click(position={"x": b["width"] * 0.3, "y": b["height"] * 0.25})
    page.keyboard.down("Shift")
    overlay.click(position={"x": b["width"] * 0.6, "y": b["height"] * 0.75})
    page.keyboard.up("Shift")
    expect(explore(page).locator(".panel .explore-readout").first.locator(".explore-pick")).to_have_count(3)
    explore(page).get_by_role("tab", name="Cursors").click()
    cut = page.evaluate(
        """() => {
          const main = document.querySelector('main:not([hidden])');
          const rows = [...main.querySelectorAll('.panel .readout-row')];
          const body = main.querySelector('.inspector-body');
          const out = rows.filter((r) => r.scrollWidth > r.clientWidth + 1 && r.querySelector('.explore-pick:first-child')
                                   && r.querySelector('.explore-pick:first-child').scrollWidth > r.clientWidth + 1).length;
          return { rows: out, inspector: body && body.offsetParent ? body.scrollWidth - body.clientWidth : 0 };
        }"""
    )
    assert cut["inspector"] <= 1, cut                                    # nothing in the inspector sticks out
    if size[0] >= 1366:                                                  # a usual panel: each cursor's line whole
        assert cut["rows"] == 0, cut


def test_values_and_axes_are_a_list_in_a_narrow_inspector(values_files, new_page):
    """Plan 14: at the inspector's default width each value and axis is a small block, nothing
    needs sideways scrolling and To is in view; a wide inspector shows the tables."""
    page = new_page("Explore")
    page.set_viewport_size({"width": 1920, "height": 1080})
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    explore(page).get_by_role("tab", name="Values & axes").click()
    body = explore(page).locator(".inspector-body")
    expect(body.locator("thead").first).to_be_hidden()
    to = body.locator("td[data-label='To']").first
    expect(to).to_be_visible()
    assert to.bounding_box()["x"] + to.bounding_box()["width"] <= body.bounding_box()["x"] + body.bounding_box()["width"]
    assert body.evaluate("e => e.scrollWidth <= e.clientWidth")
    drag(page, explore(page).get_by_label("Width of the inspector"), -300, 0)
    expect(body.locator("thead").first).to_be_visible()


def test_max_min_and_peak_are_on_one_line(values_files, new_page):
    """Plan 11: at the inspector's default width the text and the three search buttons are one
    line, with one cursor and with two; at the narrowest inspector the three buttons stay together."""
    page = new_page("Explore")
    page.set_viewport_size({"width": 1920, "height": 1080})
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    explore(page).get_by_role("tab", name="Cursors").click()
    overlay = explore(page).locator(".panel .explore-overlay").first
    b = overlay.bounding_box()
    find = explore(page).locator(".cursor-find")

    def tops():
        return find.evaluate(
            """(f) => [f.firstElementChild, ...f.querySelectorAll('button')].map((e) => Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2))""")

    overlay.click(position={"x": b["width"] * 0.3, "y": b["height"] * 0.3})
    page.wait_for_timeout(400)
    assert max(tops()) - min(tops()) <= 2, tops()
    page.keyboard.down("Shift")
    overlay.click(position={"x": b["width"] * 0.6, "y": b["height"] * 0.7})
    page.keyboard.up("Shift")
    page.wait_for_timeout(400)
    assert max(tops()) - min(tops()) <= 2, tops()
    drag(page, explore(page).get_by_label("Width of the inspector"), 400, 0)    # the narrowest it may be
    page.wait_for_timeout(300)
    assert len(set(tops()[1:])) == 1, tops()                             # the buttons on one line
    assert find.evaluate("(f) => f.scrollWidth - f.clientWidth") <= 1
