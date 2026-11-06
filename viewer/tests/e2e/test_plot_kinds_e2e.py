"""The Plot type choice, on both pages: what can't be drawn is greyed and says why."""

import lbd
import numpy as np
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def line_file(viewer):
    d = lbd.Dataset(title="Line")
    d.add_axis("a", [1.0, 2.0, 3.0])
    d.add_value("line", [1.0, 2.0, 3.0], axes="a")
    d.save(viewer.data / "line.lbd")


def test_the_plot_menu_greys_what_cant_be_drawn(viewer, new_page):
    line_file(viewer)
    page = new_page("Explore")
    frames(page, lambda: row(page, "line.lbd").dblclick())
    option = explore(page).get_by_label("Plot type").locator("option[value=heatmap]")
    expect(option).to_have_attribute("disabled", "")
    expect(option).to_contain_text("2 dimensions")
    expect(option).to_have_attribute("title", "'line' is 1-D; a heat map needs 2 dimensions")


def test_curves_and_maps_work_as_before(viewer, new_page):
    d = lbd.Dataset(title="Grid")
    d.add_axis("a", [1.0, 2.0, 3.0])
    d.add_axis("b", [1.0, 2.0])
    d.add_value("v", np.arange(6.0).reshape(3, 2), axes=["a", "b"])
    d.save(viewer.data / "grid.lbd")
    page = new_page("Explore")
    frames(page, lambda: row(page, "grid.lbd").dblclick())
    kind = explore(page).get_by_label("Plot type")
    expect(kind).to_have_value("heatmap")
    expect(kind.locator("option")).to_have_text(["Curves", "Map"])
    frames(page, lambda: kind.select_option("curve"))
    expect(kind).to_have_value("curve")
    frames(page, lambda: kind.select_option("heatmap"))
    expect(explore(page).get_by_role("button", name="Cuts", exact=True)).to_be_visible()
