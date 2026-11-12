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
    expect(kind.locator("option[value=curve]")).to_have_text("Curves")
    expect(kind.locator("option[value=heatmap]")).to_have_text("Map")
    frames(page, lambda: kind.select_option("curve"))
    expect(kind).to_have_value("curve")
    frames(page, lambda: kind.select_option("heatmap"))
    expect(explore(page).get_by_role("button", name="Cuts", exact=True)).to_be_visible()


LOOKS = [   # 16.47: the file, the plot type, a look option of that type (under Display, not Data)
    ("16 density matrix.lbd", "matrix", "Significant digits"),
    ("18 bars.lbd", "bars", "Bars"),
    ("16 density matrix.lbd", "bars3d", "Elevation"),
    ("9 many values.lbd", "histogram", "Bins"),
    ("11 single shot iq.lbd", "scatter", "Equal axes"),
]


def test_look_options_are_under_display(values_files, viewer, new_page):
    page = new_page("Explore")
    for name, kind, option in LOOKS:
        frames(page, lambda: row(page, name).dblclick())
        ctl = explore(page).get_by_role("complementary", name="Controls")
        frames(page, lambda: ctl.get_by_label("Plot type").select_option(kind))
        data = ctl.locator("details.controls-section").filter(has=page.locator("summary", has_text="Data"))
        display = ctl.locator("details.controls-section").filter(has=page.locator("summary", has_text="Display"))
        expect(data.get_by_label(option, exact=True)).to_have_count(0)
        expect(display.get_by_label(option, exact=True)).to_have_count(1)
        if kind == "histogram":                                            # one log switch: Log vertical
            expect(ctl.get_by_label("Log", exact=True)).to_have_count(0)
            expect(display.get_by_text("Log vertical")).to_have_count(1)
