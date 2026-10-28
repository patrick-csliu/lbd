"""Several values at once in the Explore view (plan 4), in a real browser: panels, the active
panel's controls, synchronized axes and cursors, and what is remembered (LBD's database)."""

import lbd
import mock_values
from lbd_viewer.catalog import structure
from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def test_a_view_remembered_before_panels_still_opens(viewer, values_files, new_page):
    """An Explore view remembered by an earlier 1.3.0-dev (one plot, no panels) opens as it was."""
    path = viewer.path("10 one value.lbd")
    viewer.state.catalog.remember(path, structure(lbd.info(path)), mock_values.old_record())
    page = new_page("Explore")
    frames(page, lambda: row(page, "10 one value.lbd").dblclick())
    ops = explore(page).locator(".operations")
    expect(ops.locator(".op-list li")).to_have_count(1)                     # its operation is still there
    expect(ops).to_contain_text("Subtract the mean")
    expect(explore(page).get_by_label("One curve per")).to_have_value("power")
