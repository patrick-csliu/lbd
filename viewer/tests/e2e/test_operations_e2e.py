"""Operations in the Explore view, in a real browser: added from the menu, run by the server (what
the plot shows says so, the read-out adds the stored value), reordered, removed, switched off; an
operation that can't apply is red with its reason; the list is remembered after a reload."""

import pytest
from pageui import row
from playwright.sync_api import Page, expect
from test_explore_e2e import at, explore, frames, small_map, sweep  # noqa: F401  (fixtures)


def ops(page: Page):
    return explore(page).locator(".operations")


def add(page: Page, name: str):
    """Add an operation from the menu; returns the mapping of the picture it brings."""
    ops(page).get_by_role("button", name="+ Add operation ▾").click()
    return frames(page, lambda: page.locator(".context-menu").get_by_role("menuitem", name=name, exact=True).click())


def test_operations_are_added_reordered_switched_off_and_remembered(sweep, cfg, new_page):
    cfg.set_explore({"keep": {"operations": True}})                    # (not kept by default, 16.44)
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


def test_calculate_fills_the_delay_and_flattens_the_phase(viewer, new_page):
    import lbd
    import numpy as np

    f = np.linspace(4e9, 4.1e9, 401)
    d = lbd.Dataset(title="VNA")
    d.add_axis("power", [-20.0, -10.0])
    d.add_axis("f", f, unit="Hz")
    d.add_value("S21", np.ones((2, 1)) * np.exp(-2j * np.pi * f[None, :] * 60e-9), axes=["power", "f"])
    d.plot = {"kind": "curve", "x": "f", "series": "power", "complex": "phase_deg"}
    d.save(viewer.data / "vna.lbd")
    page = new_page("Explore")
    frames(page, lambda: row(page, "vna.lbd").dblclick())
    add(page, "Electrical delay")
    expect(ops(page)).to_contain_text("on the complex values")
    frames(page, lambda: ops(page).get_by_role("button", name="Calculate").click())
    expect(ops(page).get_by_label("Delay in ns")).to_have_value("60")
    expect(ops(page).locator(".op-list li.bad")).to_have_count(0)


def test_smoothing_points_can_be_typed_and_a_median_steps_through_odd_numbers(sweep, new_page):
    """Found by the user: a median's arrows gave even numbers, and "15" couldn't be typed (the
    "1" was turned into 2 at once)."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    add(page, "Smooth")
    frames(page, lambda: ops(page).get_by_label("Smooth: method").select_option("median"))
    box = ops(page).get_by_label("Smooth: points")
    expect(box).to_have_value("5")
    frames(page, lambda: box.press("ArrowUp"))
    expect(box).to_have_value("7")                                    # odd only
    frames(page, lambda: box.press("ArrowDown"))
    expect(box).to_have_value("5")
    box.fill("")
    box.press_sequentially("1")                                       # on the way to 15: kept as typed
    expect(box).to_have_value("1")
    frames(page, lambda: box.press_sequentially("5"))
    expect(box).to_have_value("15")
    expect(ops(page)).to_contain_text("median of 15")
    box.fill("8")
    box.press("Enter")
    expect(ops(page)).to_contain_text("An odd number")                # says why, keeps 15
    expect(ops(page)).to_contain_text("median of 15")


def test_equations_with_their_legend_and_messages(sweep, cfg, new_page):
    cfg.set_explore({"keep": {"operations": True}})                    # (not kept by default, 16.44)
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    ops(page).locator(".equations > summary").click()                  # folded until used
    ops(page).locator(".eq-names > summary").click()
    legend = ops(page).locator(".eq-legend")
    rows = legend.locator(".eq-row")                                   # what the names stand for
    expect(rows.filter(has_text="= t").first).to_contain_text("x")
    expect(rows.filter(has_text="= v").first).to_contain_text("y")
    expect(legend.get_by_title("power = power, an axis: one per trace")).to_be_visible()
    expect(legend).to_contain_text("Trigonometry")                     # the functions in groups
    box = ops(page).get_by_label("Equation for y")
    box.click()                                                        # a click in the legend puts it in
    legend.get_by_role("button", name="mean", exact=True).click()
    expect(box).to_have_value("mean(")
    box.fill("y * 2 + power")
    frames(page, lambda: box.press("Enter"))
    expect(ops(page)).to_contain_text("The plot shows y * 2 + power")
    bad = ops(page).get_by_label("Equation for x")
    bad.fill("x +* 2")
    frames(page, lambda: bad.press("Enter"))
    expect(ops(page).locator(".eq-field.bad")).to_contain_text("isn't a formula LBD can read")
    page.wait_for_timeout(1500)                                        # remembered a moment later
    page.reload()
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    expect(ops(page).get_by_label("Equation for y")).to_have_value("y * 2 + power")


def test_a_new_equation_shows_that_axis_whole_and_removes_the_cursors(sweep, new_page):
    """Plan 11: the old limits of an axis whose equation changed mean nothing, so that axis shows
    all its data; the other axis keeps its zoom. An operation that keeps the axes keeps the zoom;
    one that changes what an axis measures (FFT) shows that axis whole."""
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    page.mouse.click(*at(page, meta, 20, 2))                           # a cursor, at the old numbers
    expect(explore(page).locator(".explore-pick").first).to_contain_text("t = 20")
    page.mouse.move(*at(page, meta, 20, 2))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < 40
    ops(page).locator(".equations > summary").click()
    box = ops(page).get_by_label("Equation for x")
    box.fill("x * 10")
    after = frames(page, lambda: box.press("Enter"))
    assert after["xlim"][0] <= 0 and after["xlim"][1] >= 490            # x: all of the new numbers
    assert after["ylim"] == pytest.approx(zoomed["ylim"])               # y: the zoom kept
    expect(explore(page).locator(".cursor-panel")).to_contain_text("Click the plot for cursor 1")   # cursors gone

    box = ops(page).get_by_label("Equation for y")
    box.fill("y * 100")
    after_y = frames(page, lambda: box.press("Enter"))
    assert after_y["ylim"][0] <= 0 and after_y["ylim"][1] >= 400
    assert after_y["xlim"] == pytest.approx(after["xlim"])

    page.mouse.move(*at(page, after_y, 200, 200))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))
    smooth = add(page, "Smooth")                                       # the axes stay what they were
    assert smooth["xlim"] == pytest.approx(zoomed["xlim"]) and smooth["ylim"] == pytest.approx(zoomed["ylim"])


def test_an_fft_shows_its_frequency_axis_whole(sweep, new_page):
    page = new_page("Explore")
    meta = frames(page, lambda: row(page, "sweep.lbd").dblclick())
    page.mouse.move(*at(page, meta, 20, 2))
    zoomed = frames(page, lambda: page.mouse.wheel(0, -600))
    fft = add(page, "FFT")
    assert fft["xlim"] != pytest.approx(zoomed["xlim"])
    assert fft["xlim"][0] <= 0.01 and fft["xlim"][1] >= 0.49           # 0 … 0.5 per step: the whole spectrum


def test_a_new_z_equation_lets_the_colours_follow(small_map, new_page):
    """Plan 11: typed colour limits are in the old numbers; a new z equation clears them."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "small_map.lbd").dblclick())
    frames(page, lambda: explore(page).locator(".contrast").get_by_role("button", name="Full").click())
    expect(explore(page).get_by_label("Colour range to")).to_have_value("19")
    ops(page).locator(".equations > summary").click()
    box = ops(page).get_by_label("Equation for z")
    box.fill("z * 1000")
    frames(page, lambda: box.press("Enter"))
    expect(explore(page).get_by_label("Colour range to")).to_have_value("")
