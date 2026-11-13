"""The plot type Scatter in a real browser, on single-shot data."""

import re

import mock_values
from pageui import plot_type, row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames
from test_histogram_e2e import rendered
from test_reading_e2e import RECORD_FRAMES


def shots(viewer):
    d = mock_values.single_shot_iq(True)
    d.plot = {"values": ["IQ"]}                          # the first panel: the complex value
    d.save(viewer.data / "iq.lbd")


def scatter_frame(page, action):
    """Do `action`; the mapping of the scatter panel's last picture. The file opens with several
    panels, so another panel's picture may come last (16.3): the scatter's has the strips' counts."""
    import json

    got = []

    def collect(r):
        if r.url.endswith("/render") and r.ok and "x-lbd-frame" in r.headers:
            got.append(json.loads(r.headers["x-lbd-frame"]))
    page.on("response", collect)
    try:
        frames(page, action)
        for _ in range(100):                                       # its own picture, once it is here
            mine = [m for m in got if "sides" in m]
            if mine:
                break
            page.wait_for_timeout(200)
        else:
            raise AssertionError("no picture of this panel came")
        n = len(got)
        page.wait_for_timeout(400)                                 # and no later one of it
        mine = [m for m in got if "sides" in m] if len(got) > n else mine
    finally:
        page.remove_listener("response", collect)
    return mine[-1]


def open_scatter(page, name="iq.lbd"):
    frames(page, lambda: row(page, name).dblclick())
    view = explore(page)
    return view, scatter_frame(page, lambda: view.get_by_label("Plot type").select_option("scatter"))


def test_iq_starts_with_two_clouds_at_one_power(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_scatter(page)
    expect(view.get_by_label("Complex values")).to_have_value("iq")
    expect(view.get_by_label("Colour by")).to_have_value("state")
    expect(view.get_by_role("checkbox", name="All of Shot")).to_be_checked()
    equal = view.get_by_role("checkbox", name="Equal axes")
    expect(equal).not_to_be_checked()                              # off unless asked (16.32)
    slider = view.get_by_role("slider")
    expect(slider).to_have_count(1)
    expect(view.get_by_label("Horizontal axis")).to_have_count(0)
    assert not meta.get("equal") and meta["note"] == "every point shown"
    meta = frames(page, lambda: equal.click())
    assert meta["equal"]
    import json

    got = []
    page.on("response", lambda r: got.append(json.loads(r.headers["x-lbd-frame"]))
            if r.url.endswith("/render") and r.ok and "x-lbd-frame" in r.headers else None)
    frames(page, lambda: slider.press("ArrowRight"))
    after = [m for m in got if m.get("equal")][-1]                 # this scatter's picture (the slider moves every panel)
    assert after["full"] == meta["full"]                           # the same limits at every step (16.49)
    assert after["plot"] == meta["plot"]


def test_colour_by_none(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_label("Colour by").select_option("none"))
    expect(view.get_by_role("slider")).to_have_count(2)            # the state became a slider


def test_an_axis_to_all_removes_its_slider(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_role("checkbox", name="All of Readout power").click())
    expect(view.get_by_role("slider")).to_have_count(0)


def test_value_against_value(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    frames(page, lambda: view.get_by_role("checkbox", name="Q (V)", exact=True).click())
    expect(view.get_by_label("Complex values")).to_have_count(0)
    meta = frames(page, lambda: view.get_by_label("Horizontal axis").select_option("I"))
    expect(view.get_by_label("Horizontal axis")).to_have_value("I")
    assert meta["sync"]["x"].startswith("I (")


def test_a_click_reads_a_point_and_vertical_isnt_offered(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 900})
    view, meta = open_scatter(page)
    expect(view.get_by_role("button", name="Vertical")).to_have_count(0)
    expect(view.get_by_role("button", name="Crosshair")).to_be_visible()
    left, top, width, height = (v / meta["dpr"] for v in meta["plot"])
    view.locator("canvas.explore-overlay").first.click(position={"x": left + width / 2, "y": top + height / 2})
    numbers = view.locator(".cursor-numbers").first
    expect(numbers).to_contain_text("stored at")
    expect(numbers).to_contain_text("shot[")
    expect(numbers).to_contain_text("Prepared state")


def test_histograms_replace_cuts_on_scatter(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 900})
    view, meta = open_scatter(page)
    button = view.get_by_role("button", name="Histograms", exact=True).first
    expect(button).to_have_attribute("aria-pressed", "true")
    assert meta["sides"]["labels"] and meta["strips"] == "histograms"
    top = view.locator(".explore-cut-top canvas, canvas.explore-cut-top").first
    expect(top).to_be_visible()
    inked = """c => c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0)"""
    assert top.evaluate(inked)
    view.locator(".explore-overlay").first.focus()
    frames(page, lambda: page.keyboard.press("c"))
    expect(button).to_have_attribute("aria-pressed", "false")


def test_zooming_counts_the_view(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    view, meta = open_scatter(page)
    whole = sum(sum(c) for c in meta["sides"]["x"]["counts"])
    left, top, width, height = (v / meta["dpr"] for v in meta["plot"])
    overlay = view.locator("canvas.explore-overlay").first
    box = overlay.bounding_box()

    def zoom():
        page.mouse.move(box["x"] + left + width * 0.05, box["y"] + top + height * 0.05)
        page.mouse.down()
        page.mouse.move(box["x"] + left + width * 0.4, box["y"] + top + height * 0.4, steps=4)   # (equal axes: a square-ish box)
        page.mouse.up()

    after = scatter_frame(page, zoom)                              # x is synced: every panel draws (16.3)
    assert sum(sum(c) for c in after["sides"]["x"]["counts"]) < whole


def test_histograms_come_and_go_in_one_change(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 900})
    view, _ = open_scatter(page)
    button = view.get_by_role("button", name="Histograms", exact=True).first
    for pressed in ("false", "true"):
        page.wait_for_timeout(700)
        page.evaluate(RECORD_FRAMES)
        button.click()
        expect(button).to_have_attribute("aria-pressed", pressed)
        page.wait_for_timeout(1500)
        assert page.evaluate("window.__mismatch") == []


def test_hovering_a_strip_says_the_bin(viewer, new_page):
    shots(viewer)
    page = new_page("Explore")
    page.set_viewport_size({"width": 1600, "height": 900})
    view, _ = open_scatter(page)
    top = view.locator("canvas.explore-cut-top, .explore-cut-top canvas").first
    expect(top).to_be_visible()
    top.hover()
    expect(view.get_by_text(re.compile(r" to .*points"))).to_be_visible()


def test_figure_scatter_slider_and_all(viewer, new_page):
    shots(viewer)
    page = new_page()
    rendered(page, lambda: row(page, "iq.lbd").dblclick())
    answer = rendered(page, lambda: plot_type(page).select_option("scatter"))
    assert answer["spec"]["complex"] == "iq" and answer["spec"]["color"] == "state" and answer["spec"]["all"] == ["shot"]
    figure = page.locator("main:not([hidden]) .tab-body:not([hidden])")
    expect(figure.get_by_label("Colour by")).to_have_value("state")
    expect(figure.get_by_role("slider")).to_have_count(1)
    answer = rendered(page, lambda: figure.get_by_role("checkbox", name="All of Readout power").click())
    assert sorted(answer["spec"]["all"]) == ["readout_power", "shot"] and answer["spec"]["index"] == {}
    expect(figure.get_by_role("slider")).to_have_count(0)


def test_histograms_beside_the_plot_on_the_figure_page(viewer, new_page):
    shots(viewer)
    page = new_page()
    rendered(page, lambda: row(page, "iq.lbd").dblclick())
    rendered(page, lambda: plot_type(page).select_option("scatter"))
    figure = page.locator("main:not([hidden]) .tab-body:not([hidden])")
    answer = rendered(page, lambda: figure.get_by_role("checkbox", name="Histograms beside the plot").click())
    assert answer["spec"]["options"]["sides"] is True


def test_scatter_offers_its_three_operations(viewer, new_page):
    """16.50 / 16.8: the page lists exactly what the server offers for Scatter."""
    shots(viewer)
    page = new_page("Explore")
    view, _ = open_scatter(page)
    view.get_by_role("button", name="+ Add operation ▾").click()
    items = page.locator(".context-menu").get_by_role("menuitem")
    expect(items).to_have_text(["Rotation", "Auto-rotate each trace", "Subtract the mean"])
    frames(page, lambda: items.filter(has_text="Rotation").first.click())
    expect(view.locator(".operations li")).to_have_count(1)


def test_the_cursor_shows_in_its_colour_on_a_dark_picture(viewer, new_page):
    """18.3: in the dark theme a scatter plot's picture is dark; the cursor's edge was white and
    wider than its red line, so the cursor looked white. The edge is dark there now."""
    shots(viewer)
    page = new_page("Explore")
    page.emulate_media(color_scheme="dark")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    view, meta = open_scatter(page)
    overlay = view.locator("canvas.explore-overlay").first
    left, top, width, height = (v / meta["dpr"] for v in meta["plot"])
    overlay.click(position={"x": left + width * 0.3, "y": top + height * 0.4})
    expect(view.locator(".explore-readout .explore-pick").first).to_be_visible()
    page.wait_for_timeout(300)
    light = overlay.evaluate("""c => {
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        let n = 0;
        for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 128 && d[i] > 200 && d[i + 1] > 200 && d[i + 2] > 200) n++;
        return n;
    }""")
    assert light < 100, f"{light} white pixels on the cursor layer"         # (before the fix: 454; the badge's number: about 10)
