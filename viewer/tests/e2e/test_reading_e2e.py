"""Reading values in the Explore view, in a real browser: a click puts a cursor on the stored data
and the cuts beside the map come with it, keys move it, Shift+click adds a second cursor with
differences, Max finds the highest cell, typed positions snap to the data, cursors are
remembered, a row is saved as its own file or shown as a curve, the contrast sets the colour
range, and a vertical cursor lists every trace."""

import json

import lbd
import numpy as np
from lbd_viewer import server
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
    # the cursors panel (plan 10): × removes cursor 2 only; Remove cursors both, with Undo
    insp = explore(page).locator(".explore-inspector")
    insp.get_by_role("button", name="Remove cursor 2").click()
    expect(readout(page)).to_have_count(1)
    expect(readout(page).first).to_contain_text("value = 14 at x = 16, y = 30")
    insp.get_by_role("button", name="Remove cursors").click()
    expect(readout(page)).to_have_count(0)
    page.get_by_role("button", name="Undo").click()
    expect(readout(page).first).to_contain_text("value = 14 at x = 16, y = 30")
    insp.get_by_role("button", name="Remove cursors").click()
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
    explore(page).locator(".explore-overlay").click(button="right", position={"x": 60, "y": 60})
    page.locator(".context-menu").get_by_role("menuitem", name="Save row as .lbd…").click()
    dialog = page.locator("dialog.confirm-dialog")                     # no system dialog in the tests: the name typed
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
    expect(explore(page).locator(".cursor-table tbody tr")).to_have_count(5)
    expect(explore(page).locator(".cursor-table tr.on")).to_have_count(1)


def test_two_vertical_cursors_read_as_one_small_table(viewer, new_page):
    """Units in the heads with one prefix per column, one line per trace, nothing cut off at the
    panel's default width, the cursors' traces marked, the rows in the file's order."""
    d = lbd.Dataset(title="Levels")
    d.add_axis("power", np.arange(-60.0, 1.0, 5.0), unit="dBm", label="Power")
    d.add_axis("f", np.linspace(6.99e9, 7.01e9, 41), unit="Hz", label="Frequency")
    d.add_value("v", 1e-3 * (1.123456 + np.arange(13.0)[:, None] + np.linspace(0, 1, 41)[None, :]), axes=["power", "f"], unit="V", label="Level")
    d.plot = {"kind": "curve", "x": "f", "series": "power"}
    d.save(viewer.data / "levels.lbd")
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 1000})
    meta = frames(page, lambda: row(page, "levels.lbd").dblclick())
    panel = explore(page).locator(".cursor-panel")
    explore(page).get_by_role("button", name="Vertical").click()
    explore(page).locator(".explore-overlay").scroll_into_view_if_needed()
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, x0 + 0.25 * (x1 - x0), y0 + 0.07 * (y1 - y0))))
    page.keyboard.down("Shift")
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, x0 + 0.75 * (x1 - x0), y0 + 0.93 * (y1 - y0))))
    page.keyboard.up("Shift")
    assert a["cursors"][0]["trace"] != a["cursors"][1]["trace"]
    table = panel.locator(".cursor-table")
    expect(panel).to_contain_text("Level (mV) at the cursors")
    expect(table.locator("thead th")).to_have_text(["Power (dBm)", "1", "2", "Δ"])
    expect(table.locator("tbody tr")).to_have_count(13)
    expect(table.locator("tbody th").first).to_contain_text("−60")
    expect(table.locator("tr.on")).to_have_count(2)
    expect(table.locator("tr.on .cursor-tag")).to_have_text(["1", "2"])
    assert table.evaluate("e => e.scrollWidth <= e.clientWidth")
    heights = table.locator("tbody tr").evaluate_all("rows => rows.map(r => r.getBoundingClientRect().height)")
    assert max(heights) < 26                                           # every row is one line
    expect(panel.locator(".cursor-value")).to_have_count(0)            # no number twice
    expect(panel).to_contain_text("stored at")
    expect(panel.locator(".cursor-between")).to_contain_text("Frequency")


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


def test_a_late_cursor_answer_does_not_switch_them_back_on(small_map, new_page):
    """The cursors asked for with a new picture answer after K switched them off: K still wins."""
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 8, 30)))
    expect(readout(page).first).to_contain_text("value = 13")
    held = []
    page.route("**/cursors", lambda route: held.append(route))
    page.keyboard.press("+")                                          # zoom: a new picture, its cursors held back
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "the new picture asked for no cursors"
    page.keyboard.press("k")
    expect(explore(page).locator(".explore-readout")).to_contain_text("No cursor type chosen")
    with page.expect_response(lambda r: r.url.endswith("/cursors")):
        for route in held:
            route.continue_()
    page.unroute("**/cursors")
    page.wait_for_timeout(300)                                         # the late answer has had its chance
    expect(explore(page).locator(".explore-readout")).to_contain_text("No cursor type chosen")


def test_the_list_of_rows_folds(small_map, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    select = explore(page).locator(".axis-select")
    expect(select).to_contain_text("all 4")
    expect(select.locator(".axis-values")).to_have_count(0)            # folded while all are shown
    select.locator(".fold").click()
    expect(select.locator(".axis-values li")).to_have_count(4)


def test_a_maps_colours_come_from_every_slice(values_files, new_page):
    """Plan 11: a new panel of a map with a slider takes its colour range from every slice, so the
    range stays when the slider moves; This slice gives each position its own range."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick())
    choice = explore(page).get_by_role("radiogroup", name="Colour range over")
    expect(choice.get_by_label("All slices")).to_be_checked()
    hist = explore(page).locator(".contrast")
    expect(hist).to_contain_text("The values of all", timeout=30_000)        # worked out in the background

    def full():
        frames(page, lambda: hist.get_by_role("button", name="Full").click())
        lo, hi = (explore(page).get_by_label(f"Colour range {e}").input_value() for e in ("from", "to"))
        frames(page, lambda: hist.get_by_role("button", name="Style").click())
        return lo, hi

    every = full()
    slider = explore(page).get_by_role("slider").first
    frames(page, lambda: slider.press("End"))
    assert full() == every                                                   # the same range at every step
    frames(page, lambda: choice.get_by_label("This slice").check())
    expect(hist).not_to_contain_text("The values of all")
    assert full() != every


def test_a_row_is_saved_as_csv(small_map, viewer, new_page, monkeypatch, tmp_path):
    """Plan 12: the Cursors tab saves the row through the cursor as CSV, through the same steps
    as Save as CSV."""
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(tmp_path / "row.csv"))
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 8, 30)))
    explore(page).get_by_role("button", name="Save row as CSV…").click()
    dialog = page.get_by_role("dialog", name="Save this row as CSV")
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_role("status").first).to_contain_text("5 rows × 2 columns")
    dialog.get_by_role("button", name="Save…").click()
    expect(dialog).to_be_hidden()
    text = (tmp_path / "row.csv").read_text(encoding="utf-8")
    assert "cut: row at" in text and "# id: " in text
    assert np.loadtxt(tmp_path / "row.csv", delimiter=",", encoding="utf-8")[:, 1].tolist() == [10, 11, 12, 13, 14]


def badges(page):
    return json.loads(explore(page).locator(".explore-overlay").first.get_attribute("data-badges"))


def overlap(a, b):
    return abs(a["x"] - b["x"]) < (a["w"] + b["w"]) / 2 and abs(a["y"] - b["y"]) < (a["h"] + b["h"]) / 2


def test_the_cursors_numbers_stay_apart(sweep, new_page):
    """Plan 13: the numbers are badges that never lie on top of each other; at one point, one badge."""
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    x, y = at(page, meta, 20, 2)
    cursor_answer(page, lambda: page.mouse.click(x, y))
    page.keyboard.down("Shift")
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 21, 2)))    # the next point: a few pixels away
    page.keyboard.up("Shift")
    two = badges(page)
    assert [b["cursors"] for b in two] == [[0], [1]] and not overlap(*two)
    page.keyboard.down("Shift")
    cursor_answer(page, lambda: page.mouse.click(x, y))                       # the same point
    page.keyboard.up("Shift")
    one = badges(page)
    assert [b["cursors"] for b in one] == [[0, 1]]


def test_a_cursor_has_a_white_edge_on_any_background(small_map, new_page):
    """Plan 13: the cursor's line is drawn over a wider edge, so it shows on a map of its colour."""
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "small_map.lbd").dblclick())
    px, py = at(page, meta, 8, 30)
    cursor_answer(page, lambda: page.mouse.click(px, py))
    # a row of the overlay through the vertical line, away from the circle: edge, colour, edge
    colours = page.evaluate(
        """([x, y]) => {
          const c = document.querySelector('main:not([hidden]) .explore-overlay');
          const r = c.getBoundingClientRect(), s = c.width / r.width;
          const row = c.getContext('2d').getImageData(Math.round((x - r.left - 8) * s), Math.round((y - r.top + 30) * s), Math.round(16 * s), 1).data;
          const px = [];
          for (let i = 0; i < row.length; i += 4) px.push([row[i], row[i + 1], row[i + 2], row[i + 3]]);
          return px;
        }""", [px, py])
    painted = [p for p in colours if p[3] > 100]
    assert any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in painted)     # the white edge
    assert any(p[0] > 150 and p[1] < 110 for p in painted)                    # the red line


def test_a_vertical_and_a_horizontal_cursor_read_every_trace(sweep, new_page):
    """Plan 13: dots where the line meets the traces, the table under the numbers, the two ways of
    reading, and the tick box that turns it off."""
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).get_by_role("button", name="Vertical").click()
    explore(page).locator(".explore-overlay").scroll_into_view_if_needed()
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 25, 2.1)))
    assert len(a["cursors"][0]["points"]) == 5
    panel = explore(page).locator(".cursor-panel")
    expect(panel).to_contain_text("Every trace at")
    expect(panel.get_by_label("Interpolated")).to_be_checked()
    cursor_answer(page, lambda: panel.get_by_label("Nearest stored point").check())
    expect(panel.locator(".cursor-line-head")).not_to_contain_text("≈")
    a = cursor_answer(page, lambda: panel.get_by_label("Every trace at the line").uncheck())
    assert "points" not in a["cursors"][0] and "table" not in a["cursors"][0]
    expect(panel.locator(".cursor-table")).to_have_count(0)
    cursor_answer(page, lambda: panel.get_by_label("Every trace at the line").check())

    a = cursor_answer(page, lambda: explore(page).get_by_role("button", name="Horizontal").click())
    assert "crossings" in a["cursors"][0]
    expect(panel).to_contain_text("Where the traces cross")
    expect(panel.locator(".cursor-table")).to_contain_text("doesn't cross")
