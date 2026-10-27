"""Several viewer pages in a real browser: delivery, moving tabs, file events, overwrite check.

Each test opens pages (browser tabs) on a fresh viewer with the files a.lbd, b.lbd, c.lbd and
acts like a user: double-click in the Folders panel, right-click a tab, pick a menu entry.
"""

import os
import re

from pageui import deliver, menu, open_file, plot_type, row, tab, tab_names, toast, use
from playwright.sync_api import expect


def test_a_double_clicked_file_goes_to_the_page_used_last(viewer, new_page):
    one = new_page()
    two = new_page()
    use(one)                               # page 1 is the one used last

    assert deliver(viewer, "a.lbd")["delivered"]
    expect(tab(one, "a.lbd")).to_be_visible()
    expect(two.locator(".tab")).to_have_count(0)

    # A file already open is shown in the page that has it, even when another page was used since.
    use(two)
    r = deliver(viewer, "a.lbd", "b.lbd")
    assert r["shown"] == [viewer.path("a.lbd")] and r["delivered"]
    expect(tab(two, "b.lbd")).to_be_visible()
    assert tab_names(one) == ["a.lbd"] and tab_names(two) == ["b.lbd"]


def test_a_closed_page_frees_its_number(viewer, new_page):
    one = new_page()
    two = new_page()
    expect(one).to_have_title(re.compile(r"Page 1$"))
    expect(two).to_have_title(re.compile(r"Page 2$"))
    one.close(run_before_unload=True)                  # the tab says goodbye as it closes
    expect(new_page()).to_have_title(re.compile(r"Page 1$"))


def test_move_two_tabs_with_unsaved_changes_to_another_page(viewer, new_page):
    one = new_page()
    two = new_page()
    for name in ("a.lbd", "b.lbd", "c.lbd"):
        open_file(one, name)
    tab(one, "a.lbd").locator(".tab-label").click()
    plot_type(one).select_option("scatter")            # an unsaved change

    # Select a and b (Ctrl+click adds b to the tab on show), then right-click → Move to Page 2.
    tab(one, "b.lbd").locator(".tab-label").click(modifiers=["ControlOrMeta"])   # ⌘ on macOS
    tab(one, "b.lbd").click(button="right")
    number = re.search(r"Page (\d+)", two.title()).group(1)
    menu(one, re.compile(rf"^Move 2 tabs to Page {number}")).click()

    expect(toast(one, "Moved 2 files")).to_be_visible()
    expect(toast(two, "2 files arrived")).to_be_visible()
    assert tab_names(one) == ["c.lbd"]
    assert sorted(tab_names(two)) == ["a.lbd", "b.lbd"]
    tab(two, "a.lbd").locator(".tab-label").click()
    expect(plot_type(two)).to_have_value("scatter")    # the unsaved change came along


def test_move_a_tab_to_a_new_browser_tab(viewer, new_page, context):
    one = new_page()
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    tab(one, "a.lbd").click(button="right")
    with context.expect_page() as popup:
        menu(one, "Move to a new browser tab").click()
    new = popup.value
    expect(new).to_have_title(re.compile(r"Page \d+$"))
    expect(tab(new, "a.lbd")).to_be_visible()
    expect(plot_type(new)).to_have_value("scatter")
    expect(one.locator(".tab")).to_have_count(0)


def test_closing_the_target_during_a_move_keeps_the_files_in_the_source(viewer, new_page):
    one = new_page()
    two = new_page()
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    two.route("**/api/transfers/*/claim", lambda route: None)   # page 2 hangs while taking the files

    tab(one, "a.lbd").click(button="right")
    menu(one, re.compile(r"^Move to Page")).click()
    expect(tab(one, "a.lbd")).to_have_class(re.compile(r"\blocked\b"))   # locked while moving
    two.close(run_before_unload=True)                                     # page 2 says goodbye

    expect(toast(one, "The move was cancelled")).to_be_visible()
    expect(tab(one, "a.lbd")).not_to_have_class(re.compile(r"\blocked\b"))
    expect(plot_type(one)).to_have_value("scatter")                       # nothing was lost


def test_a_file_open_in_another_page_is_shown_there_not_opened_twice(viewer, new_page):
    one = new_page()
    two = new_page()
    open_file(one, "a.lbd")
    row(two, "a.lbd").dblclick()
    dialog = two.get_by_role("dialog")
    expect(dialog).to_contain_text("Already open in Page")
    dialog.get_by_role("button", name=re.compile(r"^Show it in Page")).click()
    expect(two.locator(".tab")).to_have_count(0)
    assert tab_names(one) == ["a.lbd"]


def test_rename_and_trash_in_one_page_update_the_page_with_the_file(viewer, new_page):
    one = new_page()
    two = new_page()
    open_file(two, "a.lbd")
    plot_type(two).select_option("scatter")

    row(one, "a.lbd").click(button="right")
    menu(one, "Rename…").click()
    dialog = one.get_by_role("dialog")
    dialog.get_by_role("textbox").fill("renamed.lbd")
    dialog.get_by_role("button", name="Rename").click()
    expect(tab(two, "renamed.lbd")).to_be_visible()                 # the tab follows the file
    expect(plot_type(two)).to_have_value("scatter")                 # with its unsaved change

    row(one, "renamed.lbd").click(button="right")
    menu(one, re.compile(r"^Move to .*…$")).click()                  # Recycle Bin / Trash
    one.get_by_role("dialog").get_by_role("button", name=re.compile(r"^Move to")).click()
    expect(two.locator(".tab")).to_have_count(0)
    expect(toast(two, "its tab was closed")).to_be_visible()


def test_saving_a_view_of_a_file_changed_since_it_was_opened_asks_first(viewer, new_page):
    one = new_page()
    # The page notices a change on disk by itself (test_live_update_e2e.py). Here it hasn't yet:
    # saving must still ask first.
    one.route("**/api/changes", lambda route: route.abort())
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    path = viewer.path("a.lbd")
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # another program wrote it

    save = one.locator(".tab-body:not([hidden])").get_by_role("button", name="Save this view to the file")
    save.click()
    dialog = one.get_by_role("dialog")
    expect(dialog).to_contain_text("changed since this tab opened it")
    dialog.get_by_role("button", name="Overwrite").click()
    expect(toast(one, "Saved this view into the file")).to_be_visible()

    # The page now knows the new version: saving again doesn't ask.
    one.locator(".toast-close").first.click()
    save.click()
    expect(toast(one, "Saved this view into the file")).to_be_visible()
    expect(one.get_by_role("dialog")).to_have_count(0)
