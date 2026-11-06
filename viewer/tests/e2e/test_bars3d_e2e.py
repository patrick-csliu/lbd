"""3D bars in a real browser: dragging turns the picture, the wheel zooms, keys turn, a click reads
a bar, and nothing of a flat plot is left on the page."""

import lbd
import mock_values as mock
import numpy as np
from pageui import open_file, plot_type, row
from playwright.sync_api import Page, expect
from test_explore_e2e import explore, frames


def files(viewer):
    mock.density_matrix(False).save(viewer.data / "rho.lbd")
    mock.assignment_matrix(True).save(viewer.data / "assign.lbd")


def open_bars(page: Page, name: str = "assign.lbd"):
    frames(page, lambda: row(page, name).dblclick())
    return frames(page, lambda: explore(page).get_by_label("Plot type").select_option("bars3d"))


def middle(page: Page):
    box = explore(page).locator(".explore-overlay").first.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag(page: Page, dx: float, dy: float):
    x, y = middle(page)
    page.mouse.move(x, y)
    page.mouse.down()
    for k in (1, 2, 3, 4):
        page.mouse.move(x + dx * k / 4, y + dy * k / 4)
        page.wait_for_timeout(60)
    page.mouse.up()


def wheel(page: Page, by: float):
    page.mouse.move(*middle(page))
    page.mouse.wheel(0, by)


def test_the_type_is_in_the_menu_and_greyed_above_the_limit(viewer, new_page):
    d = lbd.Dataset(title="Big")
    d.add_axis("a", np.arange(70.0))
    d.add_axis("b", np.arange(70.0))
    d.add_value("v", np.ones((70, 70)), axes=["a", "b"])
    d.save(viewer.data / "big.lbd")
    page = new_page("Explore")
    frames(page, lambda: row(page, "big.lbd").dblclick())
    option = explore(page).get_by_label("Plot type").locator("option[value=bars3d]")
    expect(option).to_have_attribute("disabled", "")
    expect(option).to_have_attribute("title", "3D bars show at most 64 × 64 cells; this has 70 × 70. Use Matrix.")


def test_a_drag_turns_the_picture(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    first = open_bars(page)
    assert first["angle"] == {"elev": 35, "azim": -50, "zoom": 1}
    last = frames(page, lambda: drag(page, 100, 50))
    assert last["angle"]["azim"] == -90 and last["angle"]["elev"] == 55
    assert last["draft"] is False                           # the sharp picture at rest


def test_turning_never_moves_another_panel(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page, "rho.lbd")
    explore(page).get_by_role("button", name="+ Panel").click()
    with page.expect_response(lambda r: r.url.endswith("/render")):
        page.get_by_role("menuitem").first.click()
    page.wait_for_timeout(800)
    seen = []
    page.on("response", lambda r: seen.append(r.headers.get("x-lbd-frame", "")) if r.url.endswith("/render") else None)
    drag(page, 40, 0)
    page.wait_for_timeout(600)
    assert seen and all('"angle"' in s for s in seen if s)


def test_the_boxes_follow_and_set_the_angle(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    elevation, azimuth = explore(page).get_by_label("Elevation"), explore(page).get_by_label("Azimuth")
    expect(elevation).to_have_value("35")
    frames(page, lambda: drag(page, 100, 0))
    expect(azimuth).to_have_value("-90")

    def type_it():
        elevation.fill("10")
        elevation.press("Enter")

    assert frames(page, type_it)["angle"]["elev"] == 10
    meta = frames(page, lambda: explore(page).get_by_role("button", name="Default angle").click())
    assert meta["angle"] == {"elev": 35, "azim": -50, "zoom": 1}


def test_the_wheel_zooms_and_stops_at_its_limits(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    assert frames(page, lambda: wheel(page, -200))["angle"]["zoom"] > 1
    assert frames(page, lambda: wheel(page, -5000))["angle"]["zoom"] == 3
    assert frames(page, lambda: wheel(page, 9000))["angle"]["zoom"] == 0.5


def test_keys_turn_and_home_resets(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    overlay = explore(page).locator(".explore-overlay").first
    overlay.focus()
    assert frames(page, lambda: page.keyboard.press("ArrowRight"))["angle"]["azim"] == -55
    assert frames(page, lambda: page.keyboard.press("Shift+ArrowUp"))["angle"]["elev"] == 50
    assert frames(page, lambda: page.keyboard.press("Home"))["angle"] == {"elev": 35, "azim": -50, "zoom": 1}


def test_double_click_resets(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    frames(page, lambda: drag(page, 50, 0))
    meta = frames(page, lambda: page.mouse.dblclick(*middle(page)))
    assert meta["angle"]["azim"] == -50


def test_a_click_reads_a_bar(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    meta = open_bars(page)
    # the tall bars run along the picture's diagonal: the panel's middle holds a bar's top or nothing,
    # so ask the server where a top is by trying a few places
    numbers = explore(page).locator(".cursor-numbers")
    box = explore(page).locator(".explore-overlay").first.bounding_box()
    for fx in (0.3, 0.4, 0.5, 0.6):
        for fy in (0.2, 0.3, 0.4, 0.5, 0.6):
            with page.expect_response(lambda r: r.url.endswith("/pick")) as answer:
                page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
            if answer.value.json()["pick"]:
                pick = answer.value.json()["pick"]
                expect(numbers).to_contain_text(f"Prepared = {pick['row']}")
                expect(numbers).to_contain_text(f"Measured = {pick['column']}")
                expect(numbers).to_contain_text("Probability = ")
                return
    assert False, f"no bar found in {meta['plot']}"


def test_nothing_2d_is_shown(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    main = explore(page)
    expect(main.get_by_role("button", name="Cuts", exact=True)).to_have_count(0)
    expect(main.get_by_role("button", name="Limits", exact=True)).to_have_count(0)
    expect(main.get_by_role("button", name="Crosshair")).to_have_count(0)
    page.mouse.move(*middle(page))
    expect(main.locator(".mouse-at")).to_have_count(0)


def test_the_angle_is_remembered(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    frames(page, lambda: drag(page, 100, 0))
    page.wait_for_timeout(1500)                             # remembered a moment later
    page.reload()
    meta = frames(page, lambda: row(page, "assign.lbd").dblclick())
    assert meta["angle"]["azim"] == -90


def test_a_slider_keeps_the_angle(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page, "rho.lbd")
    frames(page, lambda: drag(page, 100, 0))
    slider = explore(page).locator(".controls").locator("input[type=range]")
    meta = frames(page, lambda: slider.fill("1"))
    assert meta["angle"]["azim"] == -90


def test_two_panels_on_complex_data_turn_together(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    meta = open_bars(page, "rho.lbd")
    assert meta["note"] == "4 × 4 bars"
    expect(explore(page).get_by_label("Complex values")).to_have_value("re_im")
    assert frames(page, lambda: drag(page, 50, 0))["angle"]["azim"] == -70


def test_figure_has_3d_bars_with_angle_boxes(viewer, new_page):
    files(viewer)
    page = new_page("Figure")
    open_file(page, "assign.lbd")
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok):
        plot_type(page).select_option("bars3d")
    body = page.locator(".tab-body:not([hidden])")
    elevation = body.get_by_label("Elevation")
    expect(elevation).to_have_value("35")
    with page.expect_response(lambda r: "/api/render" in r.url and r.ok) as answer:
        elevation.fill("10")
        elevation.press("Enter")
    assert answer.value.json()["spec"]["options"]["elev"] == 10
    expect(body.get_by_text("Log x")).to_have_count(0)


def test_open_in_figure_keeps_the_angle(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    frames(page, lambda: drag(page, 100, 0))
    explore(page).get_by_role("button", name="Open in Figure").click()
    body = page.locator(".tab-body:not([hidden])")
    expect(plot_type(page)).to_have_value("bars3d")
    expect(body.get_by_label("Azimuth")).to_have_value("-90")


def test_only_shape_keeping_operations(viewer, new_page):
    files(viewer)
    page = new_page("Explore")
    open_bars(page)
    explore(page).locator(".operations").get_by_role("button", name="+ Add operation ▾").click()
    expect(page.get_by_role("menuitem", name="Subtract the mean")).to_be_visible()
    expect(page.get_by_role("menuitem", name="FFT")).to_have_count(0)
