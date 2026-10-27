"""Files that another program changes while they are open: the page shows the new version by itself.

The user's routine: a simulation writes the same file again and again while the viewer shows it.
- A rewritten file updates its tab; unsaved plot settings are dropped, with a message.
- A file deleted and written again (or half written) is shown as it was until the new one can
  be read.
- A new file appears in the Folders panel without ↻.
- The viewer's own Save view is not mistaken for a change from outside.
- A tab moved to another page while its file changed drops the settings it brought.
"""

import re
import shutil

import lbd
from pageui import menu, open_file, plot_type, row, tab, toast
from playwright.sync_api import Page, expect

DROPPED = "unsaved plot settings were dropped"


def body(page: Page):
    return page.locator(".tab-body:not([hidden])")


def title(page: Page):
    return body(page).locator(".file-head h1")


def note(page: Page):
    return body(page).locator(".disk-note")


def rewrite(viewer, name: str, new_title: str):
    """What the user's program does: write the file again (here with another title, which the
    tab shows as its heading)."""
    d = lbd.load(viewer.path(name))
    d.title = new_title
    d.save(viewer.path(name))


def test_a_rewritten_file_updates_its_tab(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    expect(title(one)).to_have_text("curve")
    rewrite(viewer, "a.lbd", "second run")
    expect(title(one)).to_have_text("second run")
    expect(note(one)).to_contain_text("Updated")
    expect(toast(one, DROPPED)).to_have_count(0)        # nothing was unsaved: nothing to say


def test_unsaved_settings_are_dropped_when_the_file_changes(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    before = plot_type(one).input_value()
    plot_type(one).select_option("scatter")             # an unsaved change
    rewrite(viewer, "a.lbd", "second run")
    expect(toast(one, DROPPED)).to_be_visible()
    expect(title(one)).to_have_text("second run")
    expect(plot_type(one)).to_have_value(before)


def test_a_file_deleted_and_written_again_comes_back(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    expect(title(one)).to_have_text("curve")            # shown first: then it goes away
    d = lbd.load(viewer.path("a.lbd"))
    viewer.data.joinpath("a.lbd").unlink()
    expect(note(one)).to_contain_text("The file is gone")
    expect(title(one)).to_have_text("curve")            # still shown as it was
    d.title = "written again"
    d.save(viewer.path("a.lbd"))
    expect(title(one)).to_have_text("written again")
    expect(note(one)).to_contain_text("Updated")


def test_a_half_written_file_is_read_again_once_complete(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    expect(title(one)).to_have_text("curve")            # shown first: then it is half written
    d = lbd.load(viewer.path("a.lbd"))
    viewer.data.joinpath("a.lbd").write_bytes(b"\x89HDF\r\n half of a file")   # a writer that isn't done
    expect(note(one)).to_contain_text("reading the new version")
    expect(title(one)).to_have_text("curve")
    d.title = "complete"
    d.save(viewer.path("a.lbd"))
    expect(title(one)).to_have_text("complete")
    expect(note(one)).to_contain_text("Updated")


def test_a_new_file_shows_up_in_the_folders_panel(viewer, new_page):
    one = new_page()
    expect(row(one, "a.lbd")).to_be_visible()
    shutil.copy(viewer.data / "a.lbd", viewer.data / "fresh.lbd")
    expect(row(one, "fresh.lbd")).to_be_visible()
    viewer.data.joinpath("fresh.lbd").unlink()
    expect(row(one, "fresh.lbd")).to_have_count(0)


def test_saving_a_view_here_is_not_a_change_from_outside(viewer, new_page):
    one = new_page()
    open_file(one, "a.lbd")
    # Save saves what is drawn: wait for the scatter to be drawn (not an earlier redraw).
    with one.expect_response(lambda r: r.url.endswith("/api/render") and '"scatter"' in (r.request.post_data or "")):
        plot_type(one).select_option("scatter")
    body(one).get_by_role("button", name="Save this view to the file").click()
    expect(toast(one, "Saved this view into the file")).to_be_visible()
    one.wait_for_timeout(3000)                          # a check or two later
    expect(note(one)).to_have_count(0)
    expect(toast(one, DROPPED)).to_have_count(0)
    expect(plot_type(one)).to_have_value("scatter")


def test_a_tab_moved_while_its_file_changed_drops_its_settings(viewer, new_page):
    one = new_page()
    two = new_page()
    one.route("**/api/changes", lambda route: route.abort())   # page 1 hasn't noticed the change yet
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    rewrite(viewer, "a.lbd", "changed during the move")

    tab(one, "a.lbd").click(button="right")
    number = re.search(r"Page (\d+)", two.title()).group(1)
    menu(one, re.compile(rf"^Move to Page {number}")).click()
    expect(tab(two, "a.lbd")).to_be_visible()
    expect(toast(two, "while this tab was being moved")).to_be_visible()
    expect(title(two)).to_have_text("changed during the move")
    expect(plot_type(two)).not_to_have_value("scatter")
