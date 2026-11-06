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


def test_the_version_is_in_settings_not_the_header(new_page):
    page = new_page()
    expect(page.locator(".version")).to_have_count(0)
    page.set_viewport_size({"width": 1600, "height": 900})
    help_right = page.get_by_role("link", name="Help").or_(page.get_by_role("button", name="Help")).first.bounding_box()
    assert help_right["x"] + help_right["width"] > 1500             # the right of the header stays at the right
    about = open_settings(page, "About")
    expect(about.locator("[data-setting='about.version']")).to_contain_text(re.compile(r"\d+\.\d+"))
    expect(about.locator("[data-setting='about.format']")).to_contain_text(re.compile(r"\d+\.\d+"))


def test_the_limit_of_a_cursor_line_is_a_setting(new_page):
    page = new_page()
    box = open_settings(page, "Explore").get_by_label("Most traces marked at a cursor line")
    expect(box).to_have_value("20")
    box.fill("7")
    box.press("Enter")
    page.wait_for_timeout(300)
    page.reload()
    expect(open_settings(page, "Explore").get_by_label("Most traces marked at a cursor line")).to_have_value("7")
