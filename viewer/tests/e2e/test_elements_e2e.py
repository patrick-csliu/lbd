"""Elements and data points (format 1.2, plan 6a) in a real browser: a slider over a data point's
dimension shows and takes its element, and the axes table lists elements."""

from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def shown(page):
    return explore(page).locator(".tab-body:not([hidden])")


def test_a_slider_shows_and_takes_an_element(viewer, values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "12 tomography.lbd").dblclick())
    expect(shown(page).locator(".panel")).to_have_count(2)                  # Bloch vector, covariance
    shown(page).locator(".panel").nth(1).click(position={"x": 5, "y": 5})
    box = shown(page).get_by_label("Covariance (dim2) value")
    expect(box).to_have_value("I")
    box.fill("q")
    frames(page, lambda: box.press("Enter"))
    expect(box).to_have_value("Q")
    expect(shown(page).get_by_text("(point 2 of 2)")).to_be_visible()
    box.fill("nonsense")
    box.press("Enter")
    expect(shown(page).get_by_text("Type one of: I, Q")).to_be_visible()
    expect(box).to_have_value("Q")


def test_the_axes_table_lists_elements(viewer, values_files, new_page):
    page = new_page("Library")
    page.locator('.library-row[title$="12 tomography.lbd"]').click(timeout=20_000)
    table = page.locator(".library-detail")
    expect(table.get_by_text("x, y, z")).to_be_visible(timeout=10_000)
    expect(table.get_by_text("(inside each data point)").first).to_be_visible()
    page.locator('.library-row[title$="11 single shot iq.lbd"]').click()
    expect(table.get_by_text("ground, excited")).to_be_visible(timeout=10_000)
