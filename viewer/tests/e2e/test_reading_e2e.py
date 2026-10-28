"""Reading values in the Explore view, in a real browser: a click puts a cursor on the stored data
and the cuts beside the map come with it, keys move it, Shift+click adds a second cursor with
differences, Max finds the highest cell, typed positions snap to the data, cursors are
remembered, a row is saved as its own file or shown as a curve, the contrast sets the colour
range, and a vertical cursor lists every trace."""

import lbd
from pageui import row
from playwright.sync_api import Page, expect
from test_explore_e2e import at, explore, frames, small_map, sweep  # noqa: F401  (fixtures)


def cursor_answer(page: Page, action):
    """Do `action` and return the server's cursors answer it brings."""
    with page.expect_response(lambda r: r.url.endswith("/cursors")) as resp:
        action()
    return resp.value.json()


def readout(page: Page):
    return explore(page).locator(".explore-readout .explore-pick")


def test_a_click_reads_a_cell_with_its_cuts_and_keys_move_it(small_map, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 8, 30)))
    # the row and the column through the cell, as stored (value = column + 5 × row)
    assert a["cuts"]["row"]["z"] == [10, 11, 12, 13, 14] and a["cuts"]["column"]["z"] == [3, 8, 13, 18]
    expect(readout(page).first).to_contain_text("value = 13 at x = 8, y = 30")
    expect(explore(page).locator(".explore-cut-top canvas")).to_be_visible()
    page.keyboard.press("ArrowRight")                                  # one stored point on
    expect(readout(page).first).to_contain_text("value = 14 at x = 16, y = 30")
    page.keyboard.down("Shift")
    page.mouse.click(*at(page, meta, 2, 10))                           # a second cursor
    page.keyboard.up("Shift")
    expect(readout(page).nth(1)).to_contain_text("value = 1 at x = 2, y = 10")
    expect(readout(page).nth(2)).to_contain_text("Δx = −14")
    page.keyboard.press("Escape")
    expect(explore(page).locator(".explore-readout")).to_contain_text("Click the plot to read a stored value")


def test_max_and_typed_positions_are_on_the_data_and_remembered(small_map, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    cursor_answer(page, lambda: explore(page).get_by_role("button", name="Max").click())
    expect(readout(page).first).to_contain_text("value = 19 at x = 16, y = 40")
    box = explore(page).get_by_label("x of the cursor").first
    box.fill("2.2")                                                    # between cells: snaps to x = 2
    cursor_answer(page, lambda: box.press("Enter"))
    expect(readout(page).first).to_contain_text("value = 16 at x = 2, y = 40")
    page.wait_for_timeout(1500)                                        # remembered a moment later
    page.reload()
    cursor_answer(page, lambda: row(page, "small_map.lbd").dblclick())
    expect(readout(page).first).to_contain_text("value = 16 at x = 2, y = 40")


def test_a_row_is_saved_as_a_file_and_shown_as_a_curve(small_map, viewer, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 8, 30)))
    explore(page).get_by_role("button", name="Save row…").click()
    dialog = page.locator("dialog.confirm-dialog")
    expect(dialog.locator("input")).to_have_value("small_map – y = 30.lbd")
    dialog.get_by_role("button", name="Save").click()
    expect(explore(page).locator(".explore-readout")).to_contain_text("Saved")
    cut = lbd.load(viewer.data / "small_map – y = 30.lbd")
    assert cut.values["value"].data.tolist() == [10, 11, 12, 13, 14] and cut.meta["cut_from"] == "small_map.lbd"
    frames(page, lambda: explore(page).get_by_role("button", name="Row as curve").click())
    expect(explore(page).get_by_label("Plot type")).to_have_value("curve")
    frames(page, lambda: explore(page).get_by_role("button", name="◂ Back to the map").click())
    expect(explore(page).get_by_label("Plot type")).to_have_value("heatmap")


def test_the_contrast_sets_the_colour_range(small_map, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    expect(explore(page).locator(".contrast-hist")).to_be_visible()
    frames(page, lambda: explore(page).locator(".contrast").get_by_role("button", name="Full").click())
    expect(explore(page).get_by_label("Colour range from")).to_have_value("0")
    expect(explore(page).get_by_label("Colour range to")).to_have_value("19")
    frames(page, lambda: explore(page).locator(".contrast").get_by_role("button", name="Style").click())
    expect(explore(page).get_by_label("Colour range from")).to_have_value("")


def test_a_vertical_cursor_lists_every_trace(sweep, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).get_by_role("button", name="Vertical").click()     # far down the side panel: the page scrolls
    explore(page).locator(".explore-overlay").scroll_into_view_if_needed()
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 25, 2.1)))
    assert a["cursors"][0]["trace"] == 2 and len(a["cursors"][0]["table"]["rows"]) == 5
    expect(explore(page).locator(".cursor-table tr")).to_have_count(5)
    expect(explore(page).locator(".cursor-table tr.on")).to_contain_text("2")


def test_cursors_can_be_switched_off_and_back_on(small_map, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 8, 30)))
    expect(readout(page).first).to_contain_text("value = 13")
    page.keyboard.press("k")                                          # off: hidden, a click does nothing
    expect(explore(page).locator(".explore-readout")).to_contain_text("No cursor type chosen")
    expect(explore(page).locator(".explore-cut-top")).to_have_count(0)
    asked = []
    page.on("request", lambda r: asked.append(r) if r.url.endswith("/cursors") else None)
    page.mouse.click(*at(page, meta, 2, 10))
    page.wait_for_timeout(500)
    assert not asked
    cursor_answer(page, lambda: page.keyboard.press("k"))
    expect(readout(page).first).to_contain_text("value = 13 at x = 8, y = 30")   # the same cursor again
    explore(page).get_by_role("button", name="Crosshair").click()      # the chosen type again: none
    expect(explore(page).locator(".explore-readout")).to_contain_text("No cursor type chosen")
    cursor_answer(page, lambda: explore(page).get_by_role("button", name="Vertical").click())
    expect(readout(page).first).to_contain_text("value = 13")


def test_the_list_of_rows_folds(small_map, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    select = explore(page).locator(".axis-select")
    expect(select).to_contain_text("all 4")
    expect(select.locator(".axis-values")).to_have_count(0)            # folded while all are shown
    select.locator(".fold").click()
    expect(select.locator(".axis-values li")).to_have_count(4)
