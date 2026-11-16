"""Matrix and Bars in a real browser: the Plot menu, a click reading a cell or bar, the type's own
controls, the Figure page, and Open in Figure."""

import mock_values as mock
from pageui import open_file, plot_type, row, tab
from playwright.sync_api import Page, expect
from test_explore_e2e import at, explore, frames
from test_reading_e2e import cursor_answer


def files(viewer, *makers):
    names = {mock.assignment_matrix: "17 assignment matrix.lbd", mock.density_matrix: "16 density matrix.lbd",
             mock.tomography: "12 tomography.lbd", mock.bars: "18 bars.lbd", mock.one_value: "10 one value.lbd",
             mock.rabi: "6 rabi.lbd", mock.single_shot_iq: "11 single shot iq.lbd"}
    for make in makers:
        make(True).save(viewer.data / names[make])
    return [names[m] for m in makers]


def open_as(page: Page, name: str, kind: str):
    """Open a file in Explore and choose a plot type: the last picture's mapping."""
    frames(page, lambda: row(page, name).dblclick())
    return frames(page, lambda: explore(page).get_by_label("Plot type").select_option(kind))


def first_panel_at(page: Page, meta, x, y):
    """As `at`, for a file that opens in several panels."""
    box = explore(page).locator(".explore-overlay").first.bounding_box()
    d = meta["dpr"]
    left, top, w, h = (v / d for v in meta["plot"])
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    return box["x"] + left + (x - x0) / (x1 - x0) * w, box["y"] + top + h - (y - y0) / (y1 - y0) * h


def test_matrix_from_the_plot_menu(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    kind = explore(page).get_by_label("Plot type")
    expect(kind).to_have_value("matrix")
    expect(explore(page).get_by_label("Rows")).to_have_value("prepared")
    expect(explore(page).get_by_label("Columns")).to_have_value("measured")
    expect(explore(page).get_by_label("Log horizontal")).to_have_count(0)


def test_matrix_is_greyed_with_the_reason(viewer, new_page):
    name, = files(viewer, mock.rabi)
    page = new_page("Explore")
    frames(page, lambda: row(page, name).dblclick())
    option = explore(page).get_by_label("Plot type").locator("option[value=matrix]")
    expect(option).to_have_attribute("disabled", "")
    expect(option).to_have_attribute("title", "'I' has one axis with more than one point; this needs two axes, or a matrix in each point")


def test_a_click_reads_a_cell(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    meta = open_as(page, name, "matrix")
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 1, 2)))
    c = a["cursors"][0]
    assert c["index"] == {"prepared": 0, "measured": 1} and c["cell"] == [0.5, 1.5, 1.5, 2.5]
    numbers = explore(page).locator(".cursor-numbers")
    expect(numbers).to_contain_text("Prepared = ground")
    expect(numbers).to_contain_text("Measured = excited")
    expect(numbers).to_contain_text("Probability = 0.025")
    # no line through the cell: only its box, and the numbers
    expect(explore(page).get_by_role("button", name="Vertical")).to_have_count(0)


def test_no_cuts_button(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    expect(explore(page).get_by_role("button", name="Cuts", exact=True)).to_have_count(0)


def test_numbers_off_and_on(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    box = explore(page).get_by_label("Numbers")
    expect(box).to_be_checked()
    frames(page, lambda: box.click())
    expect(box).not_to_be_checked()
    expect(explore(page).get_by_label("Significant digits")).to_be_disabled()
    frames(page, lambda: box.click())
    expect(explore(page).get_by_label("Significant digits")).to_be_enabled()


def test_the_range_choice_is_remembered(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    frames(page, lambda: explore(page).get_by_label("Colour range").select_option("signed"))
    page.wait_for_timeout(1500)                             # the view is remembered a moment later
    page.reload()
    frames(page, lambda: row(page, name).dblclick())
    expect(explore(page).get_by_label("Plot type")).to_have_value("matrix")
    expect(explore(page).get_by_label("Colour range")).to_have_value("signed")


def test_complex_starts_as_re_and_im_and_a_slider_moves_it(viewer, new_page):
    name, = files(viewer, mock.density_matrix)
    page = new_page("Explore")
    meta = open_as(page, name, "matrix")
    expect(explore(page).get_by_label("Complex values")).to_have_value("re_im")
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 5, 3)))
    assert a["cursors"][0]["block"] == "Im"
    expect(explore(page).locator(".cursor-numbers")).to_contain_text("Im ρ")
    # back to curves: Re and Im is no complex mode there
    frames(page, lambda: explore(page).get_by_label("Plot type").select_option("curve"))
    expect(explore(page).get_by_label("Complex values")).to_have_value("abs")


def test_only_operations_that_keep_the_shape_are_offered(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    explore(page).locator(".operations").get_by_role("button", name="+ Add operation ▾").click()
    expect(page.get_by_role("menuitem", name="Subtract the mean")).to_be_visible()
    expect(page.get_by_role("menuitem", name="FFT")).to_have_count(0)
    frames(page, lambda: page.get_by_role("menuitem", name="Subtract the mean").click())
    expect(explore(page).get_by_text("The plot shows")).to_be_visible()


def test_row_sums_option(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    box = explore(page).get_by_label("Row sums")
    meta = frames(page, lambda: box.click())
    expect(box).to_be_checked()
    assert meta["full"][0] == [-0.5, 3.5]                   # the plot has one column more
    meta = frames(page, lambda: box.click())
    assert meta["full"][0] == [-0.5, 2.5]


def test_no_row_sums_box_on_re_and_im(viewer, new_page):
    name, = files(viewer, mock.density_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    expect(explore(page).get_by_label("Row sums")).to_be_disabled()


def figure_shown(page: Page):
    return page.locator(".tab-body:not([hidden]) .figure-host, .tab-body:not([hidden]) .figure").first


def test_matrix_on_the_figure_page(viewer, new_page, tmp_path):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Figure")
    open_file(page, name)
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        plot_type(page).select_option("matrix")
    body = page.locator(".tab-body:not([hidden])")
    expect(body.get_by_label("Rows")).to_have_value("prepared")
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        body.get_by_label("Significant digits").select_option("2")
    expect(body.get_by_label("Significant digits")).to_have_value("2")
    expect(body.get_by_text("Log x")).to_have_count(0)


def test_open_in_figure_keeps_the_matrix(viewer, new_page):
    name, = files(viewer, mock.density_matrix)
    page = new_page("Explore")
    open_as(page, name, "matrix")
    frames(page, lambda: explore(page).get_by_label("Colour range").select_option("unit"))
    frames(page, lambda: explore(page).get_by_label("Significant digits").select_option("2"))
    explore(page).get_by_role("button", name="Open in Figure").click()
    body = page.locator(".tab-body:not([hidden])")
    expect(plot_type(page)).to_have_value("matrix")
    expect(body.get_by_label("Colour range")).to_have_value("unit")
    expect(body.get_by_label("Significant digits")).to_have_value("2")


def test_bars_from_the_plot_menu(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Explore")
    open_as(page, name, "bars")
    expect(explore(page).get_by_label("Plot type")).to_have_value("bars")
    expect(explore(page).get_by_label("Groups")).to_have_value("state")
    expect(explore(page).get_by_label("Log horizontal")).to_have_count(0)
    expect(explore(page).get_by_label("Log vertical")).to_have_count(1)


def test_single_numbers_as_bars(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Explore")
    open_as(page, name, "bars")
    frames(page, lambda: explore(page).get_by_label("Fidelity").click())
    expect(explore(page).get_by_label("Groups")).to_have_count(0)
    frames(page, lambda: explore(page).get_by_label("Visibility").click())
    expect(explore(page).get_by_label("Population")).not_to_be_checked()
    expect(explore(page).get_by_label("Fidelity")).to_be_checked()
    expect(explore(page).get_by_label("Visibility")).to_be_checked()


def test_a_vector_as_bars_with_a_slider(viewer, new_page):
    name, = files(viewer, mock.tomography)
    page = new_page("Explore")
    frames(page, lambda: row(page, name).dblclick())
    frames(page, lambda: explore(page).get_by_label("Plot type").select_option("bars"))
    expect(explore(page).get_by_label("Groups")).to_have_value("bloch_dim1")
    expect(explore(page).get_by_label("Bars in a group")).to_have_value("none")
    expect(explore(page).locator(".controls").get_by_text("(point 1 of 6)")).to_be_visible()       # its slider


def test_all_of_an_axis_on_bars(viewer, new_page):
    name, = files(viewer, mock.one_value)
    page = new_page("Explore")
    open_as(page, name, "bars")
    ui = explore(page)
    expect(ui.get_by_label("Groups")).to_have_value("power")
    expect(ui.get_by_label("Frequency position")).to_have_count(1)               # a slider: one number per bar
    expect(ui.get_by_label("Bar shows")).to_have_count(0)
    expect(ui.get_by_label("Error bars")).to_have_count(0)
    meta = frames(page, lambda: ui.get_by_label("All of Frequency").click())
    expect(ui.get_by_label("Frequency position")).to_have_count(0)               # no slider any more
    expect(ui.get_by_label("Bar shows")).to_have_value("mean")
    cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 1, meta["ylim"][0] + 0.2 * (meta["ylim"][1] - meta["ylim"][0]))))
    expect(ui.locator(".cursor-numbers")).to_contain_text("Mean of |S21|")
    frames(page, lambda: ui.get_by_label("Bar shows").select_option("max"))
    expect(ui.locator(".cursor-numbers")).to_contain_text("Max of |S21|")
    frames(page, lambda: ui.get_by_label("Error bars").click())
    expect(ui.get_by_label("Error bars")).to_be_checked()
    frames(page, lambda: ui.get_by_label("All of Frequency").click())
    expect(ui.get_by_label("Bar shows")).to_have_count(0)
    expect(ui.get_by_label("Error bars")).to_have_count(0)


def test_grouped_and_stacked(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    open_as(page, name, "bars")
    bars = explore(page).get_by_label("Bars", exact=True)
    expect(bars).to_have_value("grouped")
    frames(page, lambda: bars.select_option("stacked"))
    expect(bars).to_have_value("stacked")
    frames(page, lambda: explore(page).get_by_label("Values on the bars").click())
    expect(explore(page).get_by_label("Values on the bars")).to_be_checked()


def test_a_click_reads_a_bar(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    meta = open_as(page, name, "bars")
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 1, 0.1)))     # the middle bar of the middle group
    assert a["cursors"][0]["index"] == {"prepared": 1, "measured": 1}
    numbers = explore(page).locator(".cursor-numbers")
    expect(numbers).to_contain_text("Prepared = excited")
    expect(numbers).to_contain_text("Bar = Measured = excited")
    expect(numbers).to_contain_text("Probability = 0.92")


def test_a_bar_chart_shares_no_cursors_with_curves(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Explore")
    meta = open_as(page, name, "bars")
    cursor_answer(page, lambda: page.mouse.click(*first_panel_at(page, meta, 1, 0.01)))
    expect(explore(page).get_by_text("The other panels at the same x")).to_have_count(0)


def test_a_horizontal_level_on_bars(viewer, new_page):
    name, = files(viewer, mock.assignment_matrix)
    page = new_page("Explore")
    meta = open_as(page, name, "bars")
    explore(page).get_by_role("button", name="Horizontal").click()
    a = cursor_answer(page, lambda: page.mouse.click(*at(page, meta, 1, 0.5)))
    assert abs(a["cursors"][0]["y"] - 0.5) < 0.02


def test_bars_on_the_figure_page(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Figure")
    open_file(page, name)
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        plot_type(page).select_option("bars")
    body = page.locator(".tab-body:not([hidden])")
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        body.get_by_label("Error").check()
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        body.get_by_label("Bars", exact=True).select_option("stacked")
    expect(body.get_by_text("Log y")).to_have_count(1)


def test_open_in_figure_keeps_the_bars(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Explore")
    open_as(page, name, "bars")
    frames(page, lambda: explore(page).get_by_label("Bars", exact=True).select_option("stacked"))
    explore(page).get_by_role("button", name="Open in Figure").click()
    body = page.locator("main:not([hidden]) .tab-body:not([hidden])")      # the Figure page's (Explore's is still there)
    expect(plot_type(page)).to_have_value("bars")
    expect(body.get_by_label("Bars", exact=True)).to_have_value("stacked")
    expect(body.get_by_label("Error")).to_be_checked()


def test_no_cuts_button_on_bars(viewer, new_page):
    name, = files(viewer, mock.bars)
    page = new_page("Explore")
    open_as(page, name, "bars")
    expect(explore(page).get_by_role("button", name="Cuts", exact=True)).to_have_count(0)
