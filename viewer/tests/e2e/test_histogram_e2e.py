"""The plot type Histogram in a real browser, on single-shot data."""

import re

import mock_values
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def shots(viewer):
    mock_values.single_shot_iq(True).save(viewer.data / "iq.lbd")


def histogram_frame(page, action):
    """Do `action`; the mapping of the histogram panel's last picture. The file opens with several
    panels, so another panel's picture may come last (16.3): a histogram's shares no y."""
    import json

    got = []

    def collect(r):
        if r.url.endswith("/render") and r.ok and "x-lbd-frame" in r.headers:
            got.append(json.loads(r.headers["x-lbd-frame"]))
    page.on("response", collect)
    try:
        frames(page, action)
        for _ in range(100):                                       # its own picture, once it is here
            mine = [m for m in got if str((m.get("sync") or {}).get("y", "")).startswith("counts of")]
            if mine:
                break
            page.wait_for_timeout(200)
        else:
            raise AssertionError("no picture of this panel came")
        n = len(got)
        page.wait_for_timeout(400)                                 # and no later one of it
        mine = [m for m in got if str((m.get("sync") or {}).get("y", "")).startswith("counts of")] if len(got) > n else mine
    finally:
        page.remove_listener("response", collect)
    return mine[-1]


def open_histogram(page, name="iq.lbd"):
    """The first panel (value `I` of the file) as a histogram."""
    frames(page, lambda: row(page, name).dblclick())
    view = explore(page)
    return view, histogram_frame(page, lambda: view.get_by_label("Plot type").select_option("histogram"))


def test_choose_histogram_and_its_controls(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_histogram(page)
    expect(view.get_by_label("Plot type")).to_have_value("histogram")
    # the starting choice: state colours, all shots, a slider for the power
    expect(view.get_by_label("Colour by")).to_have_value("state")
    expect(view.get_by_role("checkbox", name="All of Shot")).to_be_checked()
    slider = view.get_by_role("slider")
    expect(slider).to_have_count(1)
    expect(view.get_by_label("Draw", exact=True)).to_be_disabled()
    expect(view.get_by_label("Horizontal axis")).to_have_count(0)
    assert meta["note"].startswith("400 numbers in ") and meta["strips"] is None
    after = histogram_frame(page, lambda: slider.press("ArrowRight"))
    assert after["full"] != meta["full"]


def test_colour_by_and_all_change_the_numbers(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_histogram(page)
    meta = frames(page, lambda: view.get_by_label("Colour by").select_option("none"))
    expect(view.get_by_label("Draw", exact=True)).to_be_enabled()
    expect(view.get_by_role("slider")).to_have_count(2)        # the state became a slider
    assert meta["note"].startswith("200 numbers")
    meta = frames(page, lambda: view.get_by_role("checkbox", name="All of Prepared state").click())
    assert meta["note"].startswith("400 numbers")
    expect(view.get_by_role("slider")).to_have_count(1)


def test_fraction_needs_no_recount(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_histogram(page)
    after = frames(page, lambda: view.get_by_label("Vertical axis").select_option("fraction"))
    assert after["note"] == meta["note"] and after["full"][1][1] < 1 < meta["full"][1][1]


def test_bins_are_checked_as_typed(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_histogram(page)
    bins = view.get_by_label("Bins")
    bins.fill("1")
    expect(view.get_by_text("A whole number from 2 to 10000")).to_be_visible()
    meta = frames(page, lambda: bins.fill("7"))
    assert meta["note"].endswith(" 7 bins")
    expect(view.get_by_text("A whole number from 2 to 10000")).to_have_count(0)


def test_values_of_one_unit_overlay(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_histogram(page)
    both = frames(page, lambda: view.get_by_role("checkbox", name="Q (V)", exact=True).click())
    assert both["note"].startswith("800 numbers")


def test_click_reads_the_bin_and_two_cursors_the_count_between(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_histogram(page)
    view.get_by_role("tab", name="Cursors").click()
    canvas = view.locator("canvas.explore-overlay").first
    left, top, width, height = (v / meta["dpr"] for v in meta["plot"])
    canvas.click(position={"x": left + width * 0.3, "y": top + height / 2})
    table = view.get_by_label(re.compile(" to "))
    expect(table.locator("tbody tr")).to_have_count(2)
    expect(table.locator("tbody tr").first).to_contain_text("ground")
    expect(view.get_by_role("button", name="Max", exact=True)).to_have_count(0)
    canvas.click(position={"x": left + width * 0.7, "y": top + height / 2}, modifiers=["Shift"])
    between = view.get_by_label("Between the cursors")
    expect(between.locator("tbody tr")).to_have_count(2)
    expect(between.locator("tbody tr").nth(1)).to_contain_text("excited")


def test_open_in_figure_keeps_the_choices(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_histogram(page)
    frames(page, lambda: view.get_by_label("Bins").fill("7"))
    frames(page, lambda: view.get_by_label("Vertical axis").select_option("fraction"))
    view.get_by_role("button", name="Open in Figure").first.click()
    figure = page.locator("main:not([hidden]) .tab-body:not([hidden])")
    expect(figure.get_by_label("Plot type")).to_have_value("histogram")
    expect(figure.get_by_label("Colour by")).to_have_value("state")
    expect(figure.get_by_label("Bins")).to_have_value("7")
    expect(figure.get_by_label("Vertical axis")).to_have_value("fraction")


def rendered(page, action, quiet_ms=500):
    """Do `action` and return the answer of the last figure it brings."""
    got = []

    def collect(r):
        if r.url.endswith("/api/render") and r.ok:
            got.append(r)

    page.on("response", collect)
    try:
        with page.expect_response(lambda r: r.url.endswith("/api/render")):
            action()
        seen = -1
        while seen != len(got):
            seen = len(got)
            page.wait_for_timeout(quiet_ms)
    finally:
        page.remove_listener("response", collect)
    return got[-1].json()


def figure_of(page, name="iq.lbd"):
    page.get_by_role("tab", name="Figure", exact=True).click()
    rendered(page, lambda: row(page, name).dblclick())
    answer = rendered(page, lambda: plot_type(page).select_option("histogram"))
    assert answer["spec"]["kind"] == "histogram"
    return page.locator("main:not([hidden]) .tab-body:not([hidden])")


def test_histogram_on_the_figure_page(viewer, new_page):
    shots(viewer)
    page = new_page()
    figure = figure_of(page)
    expect(figure.get_by_label("Colour by")).to_have_value("state")
    rendered(page, lambda: figure.get_by_label("Colour by").select_option("none"))
    expect(figure.get_by_label("Draw", exact=True)).to_be_enabled()
    rendered(page, lambda: figure.get_by_label("Bins").fill("5"))
    answer = rendered(page, lambda: figure.get_by_label("Vertical axis").select_option("density"))
    assert answer["spec"]["options"] == {"bins": 5, "hist_style": "bars", "hist_y": "density"}
    assert answer["spec"]["color"] == "none"
    expect(figure.get_by_label("Horizontal axis")).to_have_count(0)
    expect(figure.get_by_text("Log x")).to_have_count(0)


def test_style_changes_the_histogram(viewer, new_page):
    shots(viewer)
    page = new_page()
    figure = figure_of(page)
    rendered(page, lambda: figure.get_by_label("Colour by").select_option("none"))
    figure.get_by_role("button", name="Style changes for this file (JSON)").click()
    figure.locator("textarea").first.fill('{"figure": {"axes": {"histogram": {"fill_alpha": 0.25}}}}')
    answer = rendered(page, lambda: figure.get_by_role("button", name="Apply").first.click())
    assert "opacity: 0.25" in answer["svg"]
