"""Variable sweeps (axis groups, format 2.0, plan 6c) in a real browser: a file with a group
opens in Explore, its curves on the real axes (16.41), and the axes table names the group."""

from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames


def shown(page):
    return explore(page).locator(".tab-body:not([hidden])")


def test_a_variable_sweep_opens_in_explore(viewer, values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "13 variable sweep.lbd").dblclick())
    expect(shown(page).locator(".panel")).to_have_count(2)                  # S21 and Q
    expect(page.get_by_text("drawn against the point number")).to_have_count(0)


def test_curves_of_a_variable_sweep_offer_its_real_axes(viewer, values_files, new_page):
    """16.41: S21 as curves starts on the real frequencies, one curve per power; Horizontal lists
    Frequency, Power, then the position inside a step; Power horizontal: a point of each step."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "13 variable sweep.lbd").dblclick())
    s21 = shown(page).locator(".panel").filter(has_text="S21").first
    s21.click()
    frames(page, lambda: explore(page).get_by_label("Plot type").select_option("curve"))
    horizontal = explore(page).get_by_label("Horizontal axis")
    expect(horizontal).to_have_value("freq")
    expect(horizontal.locator("option")).to_have_text(["Frequency", "Power", "Frequency (point in step)"])
    expect(explore(page).get_by_label("One curve per")).to_have_value("power")
    frames(page, lambda: horizontal.select_option("power"))
    expect(explore(page).get_by_label("One curve per")).to_have_value("freq_n")


def test_the_axes_table_names_the_group(viewer, values_files, new_page):
    page = new_page("Library")
    page.locator('.library-row[title$="13 variable sweep.lbd"]').click(timeout=20_000)
    table = page.locator(".library-detail")
    expect(table.get_by_text("(variable sweep: depends on Power)").first).to_be_visible(timeout=10_000)
    expect(page.locator('.library-row[title$="13 variable sweep.lbd"]')).to_contain_text("44 points (variable)")
