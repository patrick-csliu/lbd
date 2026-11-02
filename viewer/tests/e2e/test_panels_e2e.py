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
    # Dropped on panel 5's title: the panel's middle can be below the window (six panels with
    # toolbars on three lines), and Playwright's drag to a point it must scroll to never starts.
    shown(page).locator(".panel-title").nth(2).drag_to(shown(page).locator(".panel-title").nth(4))   # moved
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


def per_panel(page, action, panels: int = 1, quiet_ms: int = 600):
    """Do `action`; returns each panel's last picture mapping (X-LBD-Frame), by session, once
    pictures of at least `panels` panels came and no more come for a moment."""
    import json
    import re

    got = {}

    def collect(r):
        m = re.search(r"/api/explore/([^/]+)/render$", r.url)
        if m and r.ok:
            got[m.group(1)] = json.loads(r.headers["x-lbd-frame"])

    page.on("response", collect)
    try:
        action()
        deadline = 100
        while len(got) < panels and deadline:
            page.wait_for_timeout(100)
            deadline -= 1
        seen = None
        while seen != {k: v["xlim"] for k, v in got.items()}:
            seen = {k: v["xlim"] for k, v in got.items()}
            page.wait_for_timeout(quiet_ms)
    finally:
        page.remove_listener("response", collect)
    return got


def test_panels_with_the_same_axis_zoom_together(values_files, new_page):
    import pytest

    page = new_page("Explore")
    first = per_panel(page, lambda: row(page, "6 rabi.lbd").dblclick(), panels=4)
    assert len(first) == 4
    full = next(iter(first.values()))["xlim"]
    box = shown(page).locator(".panel .explore-overlay").nth(0).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    zoomed = per_panel(page, lambda: page.mouse.wheel(0, -600), panels=4)
    xs = [m["xlim"] for m in zoomed.values() if not m.get("draft")]
    assert len(zoomed) == 4 and all(x == pytest.approx(xs[0]) for x in xs)      # all four follow
    assert xs[0][1] - xs[0][0] < (full[1] - full[0]) * 0.8
    # show everything (double-click): all four again
    back = per_panel(page, lambda: shown(page).locator(".panel .explore-overlay").nth(2).dblclick(position={"x": 5, "y": 5}), panels=4)
    assert all(m["xlim"] == pytest.approx(full) for m in back.values())

    # sync off: only the panel zoomed
    shown(page).get_by_label("Sync x").uncheck()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    alone = per_panel(page, lambda: page.mouse.wheel(0, -600))
    assert len(alone) == 1


def test_a_panel_of_another_axis_says_it_does_not_follow(values_files, new_page):
    page = new_page("Explore")
    per_panel(page, lambda: row(page, "8 mixed axes.lbd").dblclick(), panels=4)     # Q_i (power), S21, S21_ref (freq), f0 (power)
    shown(page).locator(".panel-title").nth(1).click()                      # the map over frequency
    notes = shown(page).locator(".panel-note")
    expect(notes).to_have_count(2)                                          # the two curves against power
    expect(notes.first).to_have_text("x not synced: Power (dBm), not Frequency (GHz)")
    box = shown(page).locator(".panel .explore-overlay").nth(1).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    zoomed = per_panel(page, lambda: page.mouse.wheel(0, -600), panels=2)
    assert len(zoomed) == 2                                                 # the map and S21_ref only


def test_sliders_of_the_same_axis_move_together_unless_switched_off(values_files, new_page):
    page = new_page("Explore")
    per_panel(page, lambda: row(page, "7 spectroscopy 3d.lbd").dblclick(), panels=2)  # amplitude, phase: maps with a qubit-power slider
    expect(panels(page)).to_have_count(2)
    slider = shown(page).get_by_role("slider")
    expect(slider).to_have_count(1)                                         # the active panel's (side bar)
    per_panel(page, lambda: slider.press("End"))
    shown(page).locator(".panel-title").nth(1).click()
    expect(shown(page).get_by_role("slider")).to_have_value("2")            # the other panel moved too
    shown(page).get_by_label("Sync sliders").uncheck()
    per_panel(page, lambda: shown(page).get_by_role("slider").press("Home"))
    shown(page).locator(".panel-title").nth(0).click()
    expect(shown(page).get_by_role("slider")).to_have_value("2")            # kept its own


def cursor_answers(page, action, panels: int = 1, quiet_ms: int = 600):
    """Do `action`; returns each session's last /cursors answer, once `panels` sessions answered
    and no more answers come for a moment."""
    import re

    got = {}

    def collect(r):
        m = re.search(r"/api/explore/([^/]+)/cursors$", r.url)
        if m and r.ok:
            got[m.group(1)] = r.json()

    page.on("response", collect)
    try:
        action()
        for _ in range(100):
            if len(got) >= panels:
                break
            page.wait_for_timeout(100)
        seen = None
        while seen != len(got) or seen is None:
            seen = len(got)
            page.wait_for_timeout(quiet_ms)
    finally:
        page.remove_listener("response", collect)
    return got


def test_one_cursor_at_the_same_x_in_every_panel(values_files, new_page):
    import pytest

    page = new_page("Explore")
    per_panel(page, lambda: row(page, "6 rabi.lbd").dblclick(), panels=4)
    box = shown(page).locator(".panel .explore-overlay").nth(0).bounding_box()
    answers = cursor_answers(page, lambda: page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5), panels=4)
    xs = [a["cursors"][0]["x"] for a in answers.values()]
    assert len(xs) == 4 and all(x == pytest.approx(xs[0]) for x in xs)      # every panel, the same x
    others = shown(page).get_by_label("The other panels at the same x")
    expect(others.locator("tr")).to_have_count(3)
    expect(others).not_to_contain_text("—")                                 # each has its value there
    # the panel clicked in leads: panel 2's cursor moves the others
    box2 = shown(page).locator(".panel .explore-overlay").nth(1).bounding_box()
    answers = cursor_answers(page, lambda: page.mouse.click(box2["x"] + box2["width"] * 0.3, box2["y"] + box2["height"] * 0.5), panels=4)
    xs2 = [a["cursors"][0]["x"] for a in answers.values()]
    assert all(x == pytest.approx(xs2[0]) for x in xs2) and xs2[0] != pytest.approx(xs[0])
    expect(shown(page).locator(".panel-heading")).to_contain_text("Panel 2:")
    # Max in the active panel moves all of them
    answers = cursor_answers(page, lambda: shown(page).get_by_role("button", name="Max").click(), panels=4)
    xs3 = [a["cursors"][0]["x"] for a in answers.values()]
    assert all(x == pytest.approx(xs3[0]) for x in xs3)
    # sync x off: each panel its own cursors
    shown(page).get_by_label("Sync x").uncheck()
    answers = cursor_answers(page, lambda: page.mouse.click(box2["x"] + box2["width"] * 0.7, box2["y"] + box2["height"] * 0.5))
    assert len(answers) == 1
    expect(shown(page).get_by_label("The other panels at the same x")).to_have_count(0)


def test_a_map_and_a_curve_share_the_cursor_x(values_files, new_page):
    import pytest

    page = new_page("Explore")
    per_panel(page, lambda: row(page, "8 mixed axes.lbd").dblclick(), panels=4)
    shown(page).locator(".panel-title").nth(1).click()                      # the map over frequency
    box = shown(page).locator(".panel .explore-overlay").nth(1).bounding_box()
    answers = cursor_answers(page, lambda: page.mouse.click(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.5), panels=2)
    assert len(answers) == 2                                                 # the map and S21_ref; not the curves vs power
    xs = [a["cursors"][0]["x"] for a in answers.values()]
    assert xs[0] == pytest.approx(xs[1], rel=1e-3)


def test_two_units_in_one_panel_and_a_third_refused(values_files, new_page):
    page = new_page("Explore")
    per_panel(page, lambda: row(page, "6 rabi.lbd").dblclick(), panels=4)
    values = shown(page).locator(".controls fieldset").filter(has_text="Values")
    per_panel(page, lambda: values.get_by_label("Population").click())        # panel 1: I (V) + population (no unit)
    expect(values.get_by_label("Population")).to_be_checked()               # once the server drew it
    expect(shown(page).locator(".panel-title .panel-name").nth(0)).to_have_text("Digitizer I (V), Population")
    expect(values.get_by_label("Phase")).to_be_disabled()                     # a third unit
    expect(values.get_by_label("Digitizer Q")).to_be_enabled()                # V again: the left axis
    # a cursor on the right-hand curve reads its own number (the server tests check the values)
    box = shown(page).locator(".panel .explore-overlay").nth(0).bounding_box()
    cursor_answers(page, lambda: page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5), panels=4)
    expect(shown(page).locator(".cursor-panel .cursor-numbers").first).to_contain_text(" = ")
