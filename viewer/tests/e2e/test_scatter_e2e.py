"""The plot type Scatter in a real browser, on single-shot data."""

import re

import mock_values
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames
from test_histogram_e2e import rendered
from test_reading_e2e import RECORD_FRAMES


def shots(viewer):
    d = mock_values.single_shot_iq(True)
    d.plot = {"values": ["IQ"]}                          # the first panel: the complex value
    d.save(viewer.data / "iq.lbd")


def open_scatter(page, name="iq.lbd"):
    frames(page, lambda: row(page, name).dblclick())
    view = explore(page)
    return view, frames(page, lambda: view.get_by_label("Plot type").select_option("scatter"))


def test_iq_starts_with_two_clouds_at_one_power(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_scatter(page)
    expect(view.get_by_label("Complex values")).to_have_value("iq")
    expect(view.get_by_label("Colour by")).to_have_value("state")
    expect(view.get_by_role("checkbox", name="All of Shot")).to_be_checked()
    expect(view.get_by_role("checkbox", name="Equal axes")).to_be_checked()
    slider = view.get_by_role("slider")
    expect(slider).to_have_count(1)
    expect(view.get_by_label("Horizontal axis")).to_have_count(0)
    assert meta["equal"] and meta["note"] == "every point shown"
    after = frames(page, lambda: slider.press("ArrowRight"))
    assert after["full"] != meta["full"]


def test_colour_by_none(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_label("Colour by").select_option("none"))
    expect(view.get_by_role("slider")).to_have_count(2)            # the state became a slider


def test_an_axis_to_all_removes_its_slider(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_role("checkbox", name="All of Readout power").click())
    expect(view.get_by_role("slider")).to_have_count(0)


def test_value_against_value(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_role("checkbox", name="Q (V)", exact=True).click())
    expect(view.get_by_label("Complex values")).to_have_count(0)
    meta = frames(page, lambda: view.get_by_label("Horizontal axis").select_option("I"))
    expect(view.get_by_label("Horizontal axis")).to_have_value("I")
    assert meta["sync"]["x"].startswith("I (")


def test_a_click_reads_a_point_and_vertical_isnt_offered(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 900})
    view, meta = open_scatter(page)
    expect(view.get_by_role("button", name="Vertical")).to_have_count(0)
    expect(view.get_by_role("button", name="Crosshair")).to_be_visible()
    left, top, width, height = (v / meta["dpr"] for v in meta["plot"])
    view.locator("canvas.explore-overlay").first.click(position={"x": left + width / 2, "y": top + height / 2})
    numbers = view.locator(".cursor-numbers").first
    expect(numbers).to_contain_text("stored at")
    expect(numbers).to_contain_text("shot[")
    expect(numbers).to_contain_text("Prepared state")
