"""Operations in the Explore view, in a real browser: added from the menu, run by the server (what
the plot shows says so, the read-out adds the stored value), reordered, removed, switched off; an
operation that can't apply is red with its reason; the list is remembered after a reload."""

from pageui import row
from playwright.sync_api import Page, expect
from test_explore_e2e import at, explore, frames, sweep  # noqa: F401  (fixtures)


def ops(page: Page):
    return explore(page).locator(".operations")


def add(page: Page, name: str):
    """Add an operation from the menu; returns the mapping of the picture it brings."""
    ops(page).get_by_role("button", name="+ Add operation ▾").click()
    return frames(page, lambda: page.locator(".context-menu").get_by_role("menuitem", name=name, exact=True).click())


def test_operations_are_added_reordered_switched_off_and_remembered(sweep, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    add(page, "Subtract the mean")
    expect(ops(page)).to_contain_text("The plot shows v − mean")
    with page.expect_response(lambda r: r.url.endswith("/cursors")):     # every trace is at 0 now
        page.mouse.click(*at(page, meta, 25, 0))
    expect(explore(page).locator(".explore-readout .explore-pick").first).to_contain_text("v − mean = 0")
    expect(explore(page).locator(".explore-readout .explore-pick").first).to_contain_text("(stored: v = ")

    add(page, "Average of the traces")
    add(page, "Subtract the previous trace")                         # one trace left: can't apply
    rows = ops(page).locator(".op-list li")
    expect(rows.nth(2)).to_have_class("bad")
    expect(rows.nth(2)).to_contain_text("several traces")
    frames(page, lambda: rows.nth(2).get_by_role("button", name="Move up").click())   # before the average now
    expect(rows.nth(1)).to_contain_text("Subtract the previous trace")
    expect(ops(page).locator(".op-list li.bad")).to_have_count(0)
    frames(page, lambda: rows.nth(2).get_by_role("button", name="Remove Average of the traces").click())
    expect(rows).to_have_count(2)

    frames(page, lambda: ops(page).get_by_role("checkbox", name="on", exact=True).uncheck())
    expect(ops(page)).not_to_contain_text("The plot shows")
    frames(page, lambda: ops(page).get_by_role("checkbox", name="on", exact=True).check())
    page.wait_for_timeout(1500)                                        # remembered a moment later
    page.reload()
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    expect(ops(page).locator(".op-list li")).to_have_count(2)
    expect(ops(page)).to_contain_text("The plot shows")
