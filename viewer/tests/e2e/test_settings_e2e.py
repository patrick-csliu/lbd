"""⚙ Settings in a real browser: a dialog with sections (General, Library, Files sidebar, Memory,
Measurements), each fitting without scrolling the page; it stays open when the mouse leaves it;
Find a setting; a dot on a section that was changed, and Reset this section; links straight to a
section; tabs on a narrow window."""

import re

from pageui import open_settings
from playwright.sync_api import Page, expect


def dialog(page: Page):
    return page.get_by_role("dialog", name="Settings")


def test_the_settings_dialog_its_sections_find_and_reset(new_page):
    page = new_page()
    d = open_settings(page, "General")
    box = d.bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= 800                            # nothing below the window
    for section in ("Library", "Files sidebar", "Memory", "Measurements", "General"):
        d.get_by_role("tab", name=re.compile(rf"^{section}")).click()
        expect(d.get_by_role("tabpanel")).to_have_attribute("aria-label", section)
    page.mouse.move(5, 790)                                                            # the mouse leaves: still open
    expect(d).to_be_visible()
    # Find a setting
    d.get_by_label("Find a setting").fill("cloud")
    d.get_by_role("button", name=re.compile("Read each file's details")).click()
    expect(d.get_by_role("tabpanel")).to_have_attribute("aria-label", "Library")
    expect(d.locator("[data-setting='library.read_headers']")).to_be_visible()
    # a change: the section gets its dot; Reset this section puts it back
    measurements = d.get_by_role("tab", name=re.compile("^Measurements"))
    measurements.click()
    expect(measurements).not_to_contain_text("●")
    d.get_by_label("Time left").uncheck()
    expect(measurements).to_contain_text("●")
    d.get_by_role("button", name="Reset this section…").click()
    page.locator("dialog.confirm-dialog").get_by_role("button", name="Reset").click()
    expect(measurements).not_to_contain_text("●")
    expect(d.get_by_label("Time left")).to_be_checked()
    expect(d.get_by_role("tab", name=re.compile("^General"))).to_contain_text("●")     # (the tests open data in Figure)
    page.keyboard.press("Escape")
    expect(d).to_have_count(0)


def test_links_open_a_section_and_a_narrow_window_has_tabs(viewer, new_page):
    page = new_page()
    page.goto(page.url.split("#")[0] + "#settings/memory")
    expect(dialog(page).get_by_role("tabpanel")).to_have_attribute("aria-label", "Memory")
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 600, "height": 800})
    d = open_settings(page, "Measurements")
    tabs = d.get_by_role("tab")
    assert len({round(t.bounding_box()["y"]) for t in tabs.all()}) == 1                # the sections in one row
    assert page.evaluate("document.querySelector('.settings-main').scrollWidth <= document.querySelector('.settings-main').clientWidth")
