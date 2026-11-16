"""Maps of variable sweeps in a real browser: open, read a stored point, cells, axes, Figure."""

import lbd
import mock_values
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import at, explore, frames


def group_files(viewer):
    for make, name in ((mock_values.triangle, "triangle.lbd"), (mock_values.adaptive_map, "adaptive.lbd")):
        make(True).save(viewer.data / name)


def test_open_a_sweep_as_a_map_and_read_a_point(viewer, new_page):
    group_files(viewer)
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "triangle.lbd").dblclick())
    expect(explore(page).get_by_label("Plot type")).to_have_value("heatmap")
    expect(explore(page).get_by_label("Cells", exact=True)).to_have_value("auto")
    page.mouse.click(*at(page, meta, 2, 4))
    expect(explore(page).locator(".explore-readout .explore-pick").first).to_contain_text("at")
    expect(explore(page).locator(".explore-cut-top canvas")).to_be_visible()
    expect(explore(page).get_by_role("button", name="Row as curve")).to_be_enabled()                  # rows: a step as a curve (16.10)


def test_a_row_of_a_rows_map_opens_its_step_as_a_curve(viewer, new_page):
    """16.10: drawn as Rows, Row as curve shows the step under the cursor against its real B;
    Column as curve, the cursor's place in each step against A. Drawn as nearest points the
    buttons and the menu entries are greyed, saying why."""
    group_files(viewer)
    page = new_page("Explore")
    frames(page, lambda: row(page, "triangle.lbd").dblclick())
    meta = frames(page, lambda: explore(page).get_by_label("Cells", exact=True).select_option("rows"))
    page.mouse.click(*at(page, meta, 2, 4))                              # B = 2 in the step A = 4
    button = explore(page).get_by_role("button", name="Row as curve")
    expect(button).to_be_enabled()
    explore(page).locator(".explore-overlay").click(button="right", position={"x": 60, "y": 60})
    expect(page.locator(".context-menu").get_by_role("menuitem", name="Show row as curve")).to_be_enabled()
    page.keyboard.press("Escape")
    frames(page, lambda: button.click())
    expect(explore(page).get_by_label("Plot type")).to_have_value("curve")
    expect(explore(page).get_by_label("Horizontal axis")).to_have_value("B")
    expect(explore(page).get_by_role("slider")).to_have_value("3")                    # A = 4
    frames(page, lambda: explore(page).get_by_role("button", name="◂ Back to the map").click())
    frames(page, lambda: explore(page).get_by_label("Cells", exact=True).select_option("nearest"))
    page.mouse.click(*at(page, meta, 2, 4))
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("title", "These points have no rows (the map is drawn as nearest points): choose Cells: Rows")


def test_the_strips_show_on_rows_only(viewer, new_page):
    group_files(viewer)
    page = new_page("Explore")
    frames(page, lambda: row(page, "adaptive.lbd").dblclick())
    expect(explore(page).get_by_role("button", name="Cuts", exact=True)).to_have_count(0)
    expect(explore(page).locator(".explore-cut-top")).to_have_count(0)


def test_cells_can_be_chosen(viewer, new_page):
    group_files(viewer)
    page = new_page("Explore")
    frames(page, lambda: row(page, "adaptive.lbd").dblclick())
    frames(page, lambda: explore(page).get_by_label("Cells", exact=True).select_option("smooth"))
    expect(explore(page).get_by_label("Cells", exact=True)).to_have_value("smooth")


def test_swap_axes(viewer, new_page):
    group_files(viewer)
    page = new_page("Explore")
    frames(page, lambda: row(page, "triangle.lbd").dblclick())
    horizontal = explore(page).get_by_label("Horizontal axis")
    before = horizontal.input_value()
    frames(page, lambda: explore(page).get_by_label("Swap the axes").click())
    expect(horizontal).not_to_have_value(before)


def test_figure_draws_the_same_map(viewer, new_page):
    group_files(viewer)
    page = new_page("Figure")
    row(page, "triangle.lbd").dblclick()
    expect(plot_type(page)).to_have_value("heatmap")
    expect(page.locator(".tab-body:not([hidden]) .figure img").first).to_be_visible()
