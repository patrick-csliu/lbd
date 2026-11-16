"""Files being measured in a real browser (plan 9): the status line with its progress (steady
width), the tab moving to the finished file with a message, a copy from another computer, and
the settings that choose what the status line shows."""

import json
import re

import lbd
import numpy as np
import pytest
from pageui import open_settings, row
from playwright.sync_api import Page, expect
from test_explore_e2e import explore, frames


def sweep_writer(viewer, name="live.lbd", rows=10):
    w = lbd.Writer(viewer.data / name, title="Live sweep")
    w.add_axis("power", np.arange(float(rows)), unit="dBm")
    w.add_axis("freq", np.linspace(1e9, 2e9, 5), unit="Hz")
    w.add_value("S21", axes=["power", "freq"])
    return w


def status(page: Page):
    return explore(page).locator(".measuring-status")


def test_the_status_line_then_the_finished_file(viewer, new_page):
    w = sweep_writer(viewer)
    for i in range(3):
        w.write(power=i, S21=np.full(5, float(i)))
    w.flush()
    # the heartbeat with these 15 points now (by itself: up to 5 s later, too slow for a busy runner)
    w._beat_now(force=True)
    try:
        page = new_page("Explore")
        frames(page, lambda: row(page, "live.lbd.writing").dblclick())
        expect(status(page)).to_contain_text("Measuring")
        expect(status(page)).to_contain_text("15 of 50 points")
        points = status(page).locator(".measuring-part").filter(has_text="points")
        width = points.bounding_box()["width"]
        expect(page.get_by_role("tab", name=re.compile(r"being measured\s*Live sweep"))).to_be_visible()   # the file's title
        for i in range(3, 6):
            w.write(power=i, S21=np.full(5, float(i)))
        w.flush()
        w._beat_now(force=True)
        expect(status(page)).to_contain_text("30 of 50 points")
        assert points.bounding_box()["width"] == pytest.approx(width, abs=0.5)    # the line didn't move
    finally:
        w.close(stopped=True)
    expect(page.get_by_text("Finished: now live.lbd")).to_be_visible()
    expect(page.get_by_role("tab", name="Live sweep", exact=True)).to_be_visible()
    expect(status(page)).to_have_count(0)


def test_a_copy_measured_on_another_computer(viewer, new_page):
    w = sweep_writer(viewer, "copy.lbd")
    w.write(power=0, S21=np.zeros(5))
    w._abandon()                                     # here it's only a copy: no writer holds it
    beat = viewer.data / "copy.lbd.live"
    content = json.loads(beat.read_text(encoding="utf-8"))
    content["computer"] = "LAB-PC"
    beat.write_text(json.dumps(content), encoding="utf-8")
    page = new_page("Explore")
    frames(page, lambda: row(page, "copy.lbd.writing").dblclick())
    expect(status(page)).to_contain_text("Measuring on LAB-PC")
    expect(status(page).get_by_role("button")).to_have_count(0)          # no Recover while it may still run


def test_the_settings_choose_the_parts(viewer, new_page):
    w = sweep_writer(viewer, "parts.lbd")
    w.write(power=0, S21=np.zeros(5))
    w.flush()
    try:
        page = new_page("Explore")
        frames(page, lambda: row(page, "parts.lbd.writing").dblclick())
        expect(status(page)).to_contain_text("%")
        box = open_settings(page, "Measurements").get_by_label("Percentage")
        box.click()                                    # saved, then shown unchecked (the server's answer)
        expect(box).not_to_be_checked()
        page.keyboard.press("Escape")
        expect(status(page)).not_to_contain_text("%")
        expect(status(page)).to_contain_text("points")
    finally:
        w.close(stopped=True)


def test_a_measurement_finishing_while_selected_in_the_library_shows_no_error(viewer, new_page):
    """16.54: the Library's selected file is a measurement that finishes: its selection follows the
    finished file, and no red "This file can't be read" appears on the way."""
    from test_library_e2e import lib_row

    w = sweep_writer(viewer, "selected.lbd")
    w.write(power=0, S21=np.zeros(5))
    w.flush()
    page = new_page("Library")
    try:
        lib_row(page, "Live sweep").first.click(timeout=20_000)
        expect(page.locator(".library-detail .path-name")).to_have_text("selected.lbd.writing")
    finally:
        w.close(stopped=True)
    errors = []
    watch = page.locator(".library-detail .error-box")
    for _ in range(20):                                    # through the finish: never the red box
        if watch.count():
            errors.append(watch.first.inner_text())
        page.wait_for_timeout(150)
    assert not errors
    expect(page.locator(".library-detail .path-name")).to_have_text("selected.lbd", timeout=15_000)
    expect(page.locator(".library-detail .error-box")).to_have_count(0)


def test_the_display_controls_stay_still_while_a_measurement_grows(viewer, new_page):
    """16.55: while the file grows (read again each time), no control of the Display section
    disappears for a moment: their places stay the same."""
    w = sweep_writer(viewer, "grows.lbd", rows=30)
    for i in range(3):
        w.write(power=i, S21=np.full(5, float(i)))
    w.flush()
    try:
        page = new_page("Explore")
        frames(page, lambda: row(page, "grows.lbd.writing").dblclick())
        display = explore(page).locator("details.controls-section", has_text="Display").first
        if not display.evaluate("d => d.open"):
            display.locator("summary").click()
        page.wait_for_timeout(1500)
        heights = []
        watch = ("d => { const out = []; const t = setInterval(() => out.push(d.getBoundingClientRect().height), 40);"
                 " window.__heights = out; window.__stop = () => clearInterval(t); }")
        display.evaluate(watch)
        for i in range(3, 9):                                     # the file grows six times
            w.write(power=i, S21=np.full(5, float(i)))
            w.flush()
            w._beat_now(force=True)
            page.wait_for_timeout(700)
        heights = page.evaluate("() => { window.__stop(); return window.__heights; }")
    finally:
        w.close(stopped=True)
    assert heights and max(heights) - min(heights) <= 2, sorted(set(round(h) for h in heights))
