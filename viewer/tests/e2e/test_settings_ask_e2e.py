"""Settings that change a lot ask first (plan 18, 18.7): a change that writes data files differently,
deletes something, or costs a lot says what will happen, and nothing changes until it is agreed;
Cancel keeps the old value. Risky memory limits are only warned about."""

import re

from pageui import open_settings
from playwright.sync_api import expect


def question(page):
    return page.locator("dialog.confirm-dialog")


def test_the_edit_choice_asks_and_cancel_keeps_it(viewer, cfg, new_page):
    page = new_page("Library")
    dialog = open_settings(page, "Library")
    swap = dialog.get_by_role("radio", name="Copy and swap")
    swap.click()
    expect(question(page)).to_contain_text("Edit data files: copy and swap?")
    expect(question(page)).to_contain_text("power cut")
    question(page).get_by_role("button", name="Cancel").click()
    expect(dialog.get_by_role("radio", name="In place")).to_be_checked()
    assert cfg.settings()["library"]["data_file_edits"] == "in_place"
    swap.click()
    question(page).get_by_role("button", name="Use copy and swap").click()
    expect(swap).to_be_checked()
    assert cfg.settings()["library"]["data_file_edits"] == "copy_and_swap"


def test_reading_every_file_asks_with_how_many(values_files, viewer, cfg, new_page):
    cfg.set_library({"read_headers": False})
    page = new_page("Library")
    dialog = open_settings(page, "Library")
    box = dialog.get_by_label("Read each data file's details")
    box.click()
    expect(question(page)).to_contain_text(re.compile(r"each of the \d+ files"))         # the Library's count
    question(page).get_by_role("button", name="Cancel").click()
    expect(box).not_to_be_checked()
    box.click()
    question(page).get_by_role("button", name="Read them").click()
    expect(box).to_be_checked()


def test_previews_of_every_file_ask(viewer, cfg, new_page):
    cfg.set_library({"previews": "nearby"})
    page = new_page("Library")
    dialog = open_settings(page, "Library")
    dialog.get_by_label("Draw previews of").select_option("all")
    expect(question(page)).to_contain_text("Draw previews of every file?")
    question(page).get_by_role("button", name="Cancel").click()
    expect(dialog.get_by_label("Draw previews of")).to_have_value("nearby")
    assert cfg.settings()["library"]["previews"] == "nearby"


def test_a_reset_names_the_big_settings_it_switches(viewer, cfg, new_page):
    cfg.set_library({"data_file_edits": "copy_and_swap"})
    page = new_page("Library")
    dialog = open_settings(page, "Library")
    dialog.get_by_role("button", name="Reset this section…").click()
    expect(question(page)).to_contain_text("Edit data files: in place")
    question(page).get_by_role("button", name="Cancel").click()
    assert cfg.settings()["library"]["data_file_edits"] == "copy_and_swap"


def test_risky_memory_limits_are_warned_about(viewer, new_page):
    page = new_page("Library")
    dialog = open_settings(page, "Memory")
    box = dialog.get_by_label("Most memory to use, in GB")
    box.fill("100000")
    box.press("Enter")
    expect(dialog.get_by_role("note")).to_contain_text("More than this computer has")
