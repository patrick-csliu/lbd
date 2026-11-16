"""Show points (16.39): under Display for curves, on both pages; Open in Figure keeps it."""

import lbd
import numpy as np
from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def test_show_points_in_explore_goes_to_the_figure(viewer, new_page):
    d = lbd.Dataset(title="Wave")
    d.add_axis("t", np.arange(50.0))
    d.add_value("v", np.sin(np.arange(50.0) / 5), axes="t")
    d.save(viewer.data / "wave.lbd")
    page = new_page("Explore")
    frames(page, lambda: row(page, "wave.lbd").dblclick())
    ctl = explore(page).get_by_role("complementary", name="Controls")
    display = ctl.locator("details.controls-section").filter(has=page.locator("summary", has_text="Display"))
    points = display.get_by_label("Show points")
    expect(points).not_to_be_checked()                                # off by default
    frames(page, lambda: points.click())                              # shown checked once the server has it
    expect(points).to_be_checked()
    explore(page).get_by_role("button", name="Open in Figure").click()
    expect(page.get_by_role("tab", name="Figure", exact=True)).to_have_attribute("aria-selected", "true")
    expect(page.locator(".tab-body:not([hidden])").get_by_label("Show points")).to_be_checked()
