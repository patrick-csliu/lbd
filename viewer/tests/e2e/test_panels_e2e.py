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


def shown(page):
    """The Explore tab on show (other open files' tabs stay in the page, hidden)."""
    return explore(page).locator(".tab-body:not([hidden])")


def panels(page):
    return shown(page).locator(".panel")


def titles(page):
    return [t.strip() for t in shown(page).locator(".panel-title .panel-name").all_inner_texts()]


def add_panel(page, value: str):
    shown(page).get_by_role("button", name="+ Panel ▾").click()
    frames(page, lambda: page.locator(".context-menu").get_by_role("menuitem", name=value, exact=True).click())


def test_one_panel_per_value_on_first_open(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "6 rabi.lbd").dblclick())
    expect(panels(page)).to_have_count(4)                                   # I, Q, phase, population
    assert titles(page) == ["Digitizer I (V)", "Digitizer Q (V)", "Phase (rad)", "Population"]
    expect(shown(page).locator(".panel-heading")).to_have_text("Panel 1: Digitizer I (V)")
    expect(shown(page).locator(".explore-picture")).to_have_count(4)
    # a single number is never a panel; a file with one value looks as before
    frames(page, lambda: row(page, "8 mixed axes.lbd").dblclick())
    expect(panels(page)).to_have_count(4)
    assert "Mixing chamber temperature" not in " ".join(titles(page))
    frames(page, lambda: row(page, "10 one value.lbd").dblclick())
    expect(panels(page)).to_have_count(1)
    expect(shown(page).locator(".panel-title")).to_have_count(0)
    expect(shown(page).locator(".panel-heading")).to_have_count(0)


def test_panels_are_added_removed_duplicated_moved_and_remembered(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "9 many values.lbd").dblclick())
    expect(panels(page)).to_have_count(4)                                   # 8 values: the first 4
    add_panel(page, "Flow")
    expect(panels(page)).to_have_count(5)
    expect(shown(page).locator(".panel-heading")).to_have_text("Panel 5: Flow")   # the new one is active
    add_panel(page, "Still heater (W)")
    expect(panels(page)).to_have_count(6)
    shown(page).get_by_role("button", name="+ Panel ▾").click()          # at most 6
    expect(page.locator(".context-menu").get_by_role("menuitem", name="Flow", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")

    shown(page).get_by_role("button", name="Remove panel 6").click()
    expect(panels(page)).to_have_count(5)
    shown(page).locator(".panel-title").nth(0).click(button="right")
    frames(page, lambda: page.locator(".context-menu").get_by_role("menuitem", name="Duplicate panel").click())
    expect(panels(page)).to_have_count(6)
    first = titles(page)[0]
    assert titles(page)[1] == first
    order = titles(page)
    shown(page).locator(".panel-title").nth(2).drag_to(shown(page).locator(".panel").nth(4))   # moved
    assert titles(page) == order[:2] + order[3:5] + [order[2]] + order[5:]

    shown(page).get_by_label("stacked").check()
    grid = shown(page).locator(".panel-grid")
    assert len(grid.evaluate("g => getComputedStyle(g).gridTemplateColumns").split()) == 2   # 3 rows × 2
    page.keyboard.press("Escape")
    shown(page).locator(".panel .explore-overlay").nth(2).focus()
    page.keyboard.press("5")                                                # keys 1–6: the active panel
    expect(shown(page).locator(".panel-heading")).to_contain_text("Panel 5:")
    before = titles(page)
    page.wait_for_timeout(1500)                                             # remembered a moment later
    page.reload()
    frames(page, lambda: row(page, "9 many values.lbd").dblclick())
    expect(panels(page)).to_have_count(6)
    assert titles(page) == before
    expect(shown(page).get_by_label("stacked")).to_be_checked()
    expect(shown(page).locator(".panel-heading")).to_contain_text("Panel 5:")


def test_the_side_bar_changes_the_active_panel_only(values_files, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "6 rabi.lbd").dblclick())
    shown(page).locator(".panel-title").nth(1).click()                    # makes it the active panel
    expect(shown(page).locator(".panel-heading")).to_have_text("Panel 2: Digitizer Q (V)")
    log = shown(page).get_by_role("checkbox", name="Log vertical")
    meta = frames(page, lambda: log.check())
    assert meta["yscale"] == "log"
    shown(page).locator(".panel-title").nth(0).click()
    expect(log).not_to_be_checked()                                        # panel 1 keeps its own
    shown(page).locator(".panel-title").nth(1).click()
    expect(log).to_be_checked()
    # a value dragged onto a panel joins it
    frames(page, lambda: shown(page).locator(".controls label.check", has_text="Population").drag_to(shown(page).locator(".panel").nth(0)))
    expect(shown(page).locator(".panel-title .panel-name").nth(0)).to_have_text("Digitizer I (V), Population")
