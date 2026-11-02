"""Files being measured in a real browser (plan 9): the status line with its progress (steady
width), the tab moving to the finished file with a message, a copy from another computer, and
the settings that choose what the status line shows."""

import json
import re

import lbd
import numpy as np
import pytest
from pageui import row
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
    try:
        page = new_page("Explore")
        frames(page, lambda: row(page, "live.lbd.writing").dblclick())
        expect(status(page)).to_contain_text("Measuring")
        expect(status(page)).to_contain_text("15 of 50 points")
        points = status(page).locator(".measuring-part").filter(has_text="points")
        width = points.bounding_box()["width"]
        expect(page.get_by_role("tab", name=re.compile(r"being measured\s*live\.lbd\.writing"))).to_be_visible()
        for i in range(3, 6):
            w.write(power=i, S21=np.full(5, float(i)))
        w.flush()
        w._beat_now(force=True)
        expect(status(page)).to_contain_text("30 of 50 points")
        assert points.bounding_box()["width"] == pytest.approx(width, abs=0.5)    # the line didn't move
    finally:
        w.close(stopped=True)
    expect(page.get_by_text("Finished: now live.lbd")).to_be_visible()
    expect(page.get_by_role("tab", name="live.lbd", exact=True)).to_be_visible()
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
        page.get_by_role("button", name="Settings").click()
        box = page.get_by_role("dialog", name="Settings").get_by_label("Percentage")
        box.click()                                    # saved, then shown unchecked (the server's answer)
        expect(box).not_to_be_checked()
        page.keyboard.press("Escape")
        expect(status(page)).not_to_contain_text("%")
        expect(status(page)).to_contain_text("points")
    finally:
        w.close(stopped=True)
