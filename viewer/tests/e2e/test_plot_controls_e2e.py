"""The plot controls in a real browser, on the cases found while watching a session.

- Changing the plot type away from a saved view gives no "saved view" note.
- A value on another axis can be chosen (it replaces the plot), and a single number is shown.
- An axis with one point is a fixed parameter: no slider.
- The position on an axis that isn't drawn can be typed: it goes to the nearest point.
- DPI next to Width/Height is sent as the style's figure.dpi.
"""

import json
import re

import lbd
import numpy as np
import pytest
from pageui import open_file, plot_type
from playwright.sync_api import Page, expect


@pytest.fixture
def files(viewer):
    """Files like the examples: a saved scatter view, values on two axes plus a single number,
    a fixed parameter, and a sweep."""
    d = lbd.Dataset(title="Readout I/Q")
    d.add_axis("prep", [0.0, 1.0], label="Prepared state")
    d.add_axis("shot", np.arange(40.0), label="Shot")
    rng = np.random.default_rng(1)
    for name in ("I", "Q"):
        d.add_value(name, rng.normal(size=(2, 40)), axes=["prep", "shot"], unit="V")
    d.plot = {"kind": "scatter", "values": ["Q"], "x": "I", "color": "prep"}
    d.save(viewer.data / "readout.lbd")

    d = lbd.Dataset(title="T1 and noise")
    d.add_axis("delay", np.logspace(-7, -3.5, 30), unit="s", label="Delay")
    d.add_axis("f", np.logspace(0, 5, 40), unit="Hz", label="Frequency")
    d.add_value("P1", np.exp(-np.logspace(-7, -3.5, 30) / 21e-6), axes="delay", label="P1")
    d.add_value("S_V", 1e-15 / np.logspace(0, 5, 40), axes="f", unit="V²/Hz", label="S_V")
    d.add_value("T1", 21e-6, unit="s", label="T1")
    d.save(viewer.data / "t1_noise.lbd")

    d = lbd.Dataset(title="One power")
    d.add_axis("power", [-40.0], unit="dBm", label="Power")
    d.add_axis("freq", np.linspace(7e9, 7.01e9, 51), unit="Hz", label="Frequency")
    d.add_value("S21", np.ones((1, 51)), axes=["power", "freq"])
    d.save(viewer.data / "one_power.lbd")

    d = lbd.Dataset(title="Power sweep")
    d.add_axis("power", np.arange(-70.0, 1.0, 5.0), unit="dBm", label="Power")
    d.add_axis("freq", np.linspace(7e9, 7.01e9, 51), unit="Hz", label="Frequency")
    d.add_value("S21", np.ones((15, 51)), axes=["power", "freq"])
    d.save(viewer.data / "power_sweep.lbd")


def body(page: Page):
    return page.locator(".tab-body:not([hidden])")


def notes(page: Page):
    return body(page).locator(".warn-box li")


def wait_for_render(page: Page, action, wanted=lambda sent: True):
    """Do `action` and wait for the redraw it causes (the first one whose request satisfies
    `wanted`: an earlier redraw may still be on its way); returns that request's body."""
    def match(response):
        return response.url.endswith("/api/render") and wanted(json.loads(response.request.post_data))

    with page.expect_response(match) as response:
        action()
    return json.loads(response.value.request.post_data)


def test_changing_the_plot_type_never_blames_the_saved_view(files, new_page):
    page = new_page()
    open_file(page, "readout.lbd")
    expect(plot_type(page)).to_have_value("scatter")
    for kind in ("curve", "heatmap", "scatter", "curve"):
        wait_for_render(page, lambda: plot_type(page).select_option(kind))
        expect(notes(page)).to_have_count(0)


def test_a_value_on_another_axis_replaces_the_plot_and_a_number_is_shown(files, new_page):
    page = new_page()
    open_file(page, "t1_noise.lbd")
    switch = body(page).get_by_role("button", name=re.compile(r"^S_V \(Frequency\)"))
    wait_for_render(page, switch.click, lambda sent: sent["spec"].get("values") == ["S_V"])
    expect(body(page).get_by_role("checkbox", name=re.compile(r"^S_V"))).to_be_checked()
    expect(body(page).locator(".controls")).to_contain_text("Frequency (Hz)")
    expect(notes(page)).to_have_count(0)
    expect(page.locator(".toast")).to_have_count(0)

    number = body(page).get_by_role("button", name="T1 = 21 µs")
    wait_for_render(page, number.click, lambda sent: sent["spec"].get("kind") == "scalar" and sent["spec"].get("values") == ["T1"])
    expect(plot_type(page)).to_have_value("scalar")
    wait_for_render(page, lambda: plot_type(page).select_option("curve"))   # back: a value that fits
    expect(notes(page)).to_have_count(0)
    expect(page.locator(".toast")).to_have_count(0)


def test_an_axis_with_one_point_is_a_fixed_parameter(files, new_page):
    page = new_page()
    open_file(page, "one_power.lbd")
    expect(plot_type(page)).to_have_value("curve")                  # not a 1-row heat map
    expect(body(page).locator(".controls")).to_contain_text("Power = -40 dBm (fixed)")
    expect(body(page).locator(".controls input[type=range]")).to_have_count(0)
    expect(body(page).locator(".controls")).not_to_contain_text("One curve per")
    expect(notes(page)).to_have_count(0)


def test_typing_a_value_goes_to_the_nearest_point(files, new_page):
    page = new_page()
    open_file(page, "power_sweep.lbd")
    if plot_type(page).input_value() != "curve":
        wait_for_render(page, lambda: plot_type(page).select_option("curve"))
    series = body(page).locator("label.field", has_text="One curve per").locator("select")
    wait_for_render(page, lambda: series.select_option("none"))
    box = body(page).get_by_label("Power value")
    expect(box).to_have_value("-70")

    def type_value(text):
        box.fill(text)
        box.press("Enter")

    wait_for_render(page, lambda: type_value("-42"), lambda sent: sent["spec"].get("index") == {"power": 6})  # -40 dBm
    expect(box).to_have_value("-40")
    expect(body(page).locator(".slice-head")).to_contain_text("point 7 of 15")
    wait_for_render(page, lambda: type_value("12"), lambda sent: sent["spec"].get("index") == {"power": 14})  # the end
    expect(body(page).locator(".controls")).to_contain_text("outside the axis")
    box.fill("abc")
    box.press("Enter")
    expect(body(page).locator(".controls")).to_contain_text("Type a number")
    expect(box).to_have_value("0")


def test_dpi_next_to_width_and_height_goes_into_the_style(files, new_page):
    page = new_page()
    open_file(page, "power_sweep.lbd")
    dpi = body(page).get_by_label("DPI (PNG/JPG)")
    wait_for_render(page, lambda: dpi.fill("300"), lambda sent: sent["style"] == {"figure": {"dpi": 300}})
