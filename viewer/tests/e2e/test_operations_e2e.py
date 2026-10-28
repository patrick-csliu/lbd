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


def test_equations_with_their_legend_and_messages(sweep, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    legend = ops(page).locator(".eq-legend")
    expect(legend).to_contain_text("x = t")                           # what the names stand for
    expect(legend).to_contain_text("y = v")
    expect(legend).to_contain_text("power = power, an axis: one per trace")
    box = ops(page).get_by_label("Equation for y")
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
