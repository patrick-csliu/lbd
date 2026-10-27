"""The open-files bar: its menus are within reach however many tabs are open.

- Right-click on the empty part of the bar, or the ⋯ button at its end: the menu for all tabs.
- Right-click on a tab: that tab, its file (Show in …, Copy path, Rename…), and all tabs.
- Right-click on the file's header: the same as its tab.
"""

import re
import shutil

from pageui import exactly, menu, open_file, tab, tab_names
from playwright.sync_api import expect


def test_the_menu_for_all_tabs_is_reachable_with_many_tabs(viewer, new_page):
    for i in range(20):
        shutil.copy(viewer.data / "curve.lbd", viewer.data / f"run_{i:02d}.lbd")
    one = new_page()
    for i in range(20):
        open_file(one, f"run_{i:02d}.lbd")
    more = one.get_by_role("button", name="Menu for all tabs")
    expect(more).to_be_in_viewport()                    # not scrolled away with the tabs
    more.click()
    expect(menu(one, "Move all tabs to a new browser tab")).to_be_visible()
    menu(one, "Close all").click()
    expect(one.locator(".tab")).to_have_count(0)
    expect(more).to_have_count(0)                       # nothing to act on


def test_right_click_on_the_empty_bar(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    open_file(one, "b.lbd")
    strip = one.locator(".tabs")
    box = strip.bounding_box()
    strip.click(button="right", position={"x": box["width"] - 10, "y": box["height"] / 2})
    expect(menu(one, "Close all")).to_be_visible()
    expect(menu(one, "Copy path")).to_have_count(0)     # no file: this menu is for all tabs
    one.keyboard.press("Escape")


def test_a_tab_menu_has_its_file_and_all_tabs(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    open_file(one, "b.lbd")
    tab(one, "a.lbd").click(button="right")
    for label in ("Close", "Close others", "Move to a new browser tab", "Copy path", "Rename…", "Close all",
                  "Move all tabs to a new browser tab"):
        expect(menu(one, exactly(label))).to_be_visible()
    expect(menu(one, re.compile(r"^Show in "))).to_be_visible()
    menu(one, "Rename…").click()
    dialog = one.get_by_role("dialog")
    dialog.get_by_role("textbox").fill("renamed.lbd")
    dialog.get_by_role("button", name="Rename").click()
    expect(tab(one, "renamed.lbd")).to_be_visible()
    assert (viewer.data / "renamed.lbd").is_file() and not (viewer.data / "a.lbd").exists()


def test_right_click_on_the_file_header_opens_its_tab_menu(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    open_file(one, "b.lbd")
    one.locator(".tab-body:not([hidden]) .file-head h1").click(button="right")
    menu(one, exactly("Close")).click()
    expect(one.locator(".tab")).to_have_count(1)
    assert tab_names(one) == ["a.lbd"]


def test_move_all_tabs_to_another_page(viewer, new_page):
    one = new_page()
    two = new_page()
    open_file(one, "a.lbd")
    open_file(one, "b.lbd")
    one.get_by_role("button", name="Menu for all tabs").click()
    number = re.search(r"Page (\d+)", two.title()).group(1)
    menu(one, re.compile(rf"^Move all tabs to Page {number}")).click()
    expect(two.locator(".tab")).to_have_count(2)
    expect(one.locator(".tab")).to_have_count(0)
