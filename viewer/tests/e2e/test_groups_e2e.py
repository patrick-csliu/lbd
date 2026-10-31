"""Variable sweeps (axis groups, format 2.0, plan 6c) in a real browser: a file with a group
opens in Explore (against the point number, with a notice), and the axes table names the group."""

from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def shown(page):
    return explore(page).locator(".tab-body:not([hidden])")


def test_a_variable_sweep_opens_in_explore(viewer, values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "13 variable sweep.lbd").dblclick())
    expect(shown(page).locator(".panel")).to_have_count(2)                  # S21 and Q
    expect(page.get_by_text("drawn against the point number").first).to_be_visible(timeout=10_000)


def test_the_axes_table_names_the_group(viewer, values_files, new_page):
    page = new_page("Library")
    page.locator('.library-row[title$="13 variable sweep.lbd"]').click(timeout=20_000)
    table = page.locator(".library-detail")
    expect(table.get_by_text("variable sweep power → freq").first).to_be_visible(timeout=10_000)
    expect(page.locator('.library-row[title$="13 variable sweep.lbd"]')).to_contain_text("44 points (variable)")
