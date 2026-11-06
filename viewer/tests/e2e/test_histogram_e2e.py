"""The plot type Histogram in a real browser, on single-shot data."""

import re

import mock_values
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def shots(viewer):
    mock_values.single_shot_iq(True).save(viewer.data / "iq.lbd")


def open_histogram(page, name="iq.lbd"):
    """The first panel (value `I` of the file) as a histogram."""
    frames(page, lambda: row(page, name).dblclick())
    view = explore(page)
    return view, frames(page, lambda: view.get_by_label("Plot type").select_option("histogram"))


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
    after = frames(page, lambda: slider.press("ArrowRight"))
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
