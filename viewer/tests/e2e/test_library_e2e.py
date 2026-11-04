"""The Library workspace in a real browser (plan 8a): every data file under the open folders as
one list, with the folders and a date tree to filter, search, sortable columns that are
remembered, the keyboard, the selected file on the right, unreadable files shown with the
reason, files that appear while it is shown, and the setting for not reading headers."""

import re

import httpx
import lbd
import mock_library
from playwright.sync_api import Page, expect
from test_explore_e2e import explore


def rows(page: Page):
    return page.locator(".library-row:not(.loading)")


def lib_row(page: Page, text: str):
    return page.locator(".library-row", has_text=text)


def status(page: Page):
    return page.locator(".library-status")


def shows(page: Page, n: int, timeout: int = 10_000):
    """The list shows n files, without a filter ("n files", not "k of n files")."""
    expect(status(page)).to_have_text(re.compile(rf"^{n} files"), timeout=timeout)


def every_file(viewer) -> int:
    return sum(1 for _ in viewer.data.rglob("*.lbd"))


def test_folders_dates_and_search_filter_the_list(viewer, library_files, new_page):
    page = new_page("Library")
    shows(page, every_file(viewer), 20_000)
    shared = sum(1 for _ in (viewer.data / "Shared").rglob("*.lbd"))
    page.locator(".library-folders").get_by_role("button", name="Shared", exact=True).click()
    shows(page, shared)
    page.locator(".library-folders").get_by_role("button", name="All folders").click()
    shows(page, every_file(viewer))
    # the date tree: 2026 → Mar → 14 (in the file's own time zone: 23:30 +08:00 is still the 14th)
    dates = page.locator(".library-dates")
    dates.get_by_role("button", name="Unfold 2026").click()
    dates.get_by_role("button", name="Unfold Mar 2026").click()
    dates.get_by_role("button", name="14 Mar 2026").click()
    expect(lib_row(page, "Late resonator sweep")).to_be_visible()
    # the zone, shortened; not shown at all on a computer in that zone (the usual case)
    here = page.evaluate("-new Date('2026-03-14T12:00:00').getTimezoneOffset()") == 480
    expect(lib_row(page, "Late resonator sweep")).to_contain_text("2026-03-14 23:30" if here else "2026-03-14 23:30 +08")
    expect(lib_row(page, "Late resonator sweep")).not_to_contain_text("+08:00")
    expect(status(page)).to_contain_text("2026 › Mar › 14")
    page.get_by_role("button", name="Any date").first.click()
    # search: words in the description, a metadata value
    box = page.get_by_label("Search the files")
    box.fill("re-cooling")
    expect(status(page)).to_contain_text('"re-cooling"')
    expect(status(page)).to_contain_text(re.compile(r"\d+ of \d+ files"))
    n = int(re.search(r"(\d+) of", status(page).inner_text()).group(1))
    assert 0 < n < every_file(viewer)
    box.fill("alice")                                                     # meta: operator = Alice
    expect(status(page)).to_contain_text('"alice"')
    expect(rows(page).first).to_be_visible()


def test_columns_sorting_keyboard_and_the_selected_file(viewer, library_files, new_page):
    page = new_page("Library")
    shows(page, every_file(viewer), 20_000)
    page.get_by_role("columnheader", name=re.compile("Name")).get_by_role("button").click()
    expect(page.get_by_role("columnheader", name=re.compile("Name"))).to_have_attribute("aria-sort", "ascending")
    top = httpx.get(f"http://127.0.0.1:{viewer.port}/api/library/list", headers={"X-LBD-Token": viewer.state.token},
                    params={"sort": "name", "order": "asc", "limit": "2"}).json()["rows"]
    # (an unreadable file's name starts with ⚠)
    for k in (0, 1):
        expect(rows(page).nth(k).locator(".cell-name")).to_have_text(
            ("⚠ " if top[k]["error"] else "") + (top[k]["title"] or top[k]["name"]))
    # the column menu: Values added, remembered after a reload
    page.locator(".library-head").click(button="right")
    page.locator(".context-menu").get_by_role("menuitem", name=re.compile("Values")).click()
    expect(page.get_by_role("columnheader", name=re.compile("Values"))).to_be_visible()
    page.reload()
    expect(page.get_by_role("columnheader", name=re.compile("Values"))).to_be_visible(timeout=10_000)
    # the selected file on the right: its axes
    page.get_by_label("Search the files").fill("late resonator")
    lib_row(page, "Late resonator sweep").click()
    detail = page.locator(".library-detail")
    expect(detail.locator("h1")).to_have_text("Late resonator sweep")
    expect(detail).to_contain_text("Frequency")
    expect(detail).to_contain_text("power")
    # ↓ selects the next file; Enter opens it in Explore
    page.get_by_label("Search the files").fill("")
    shows(page, every_file(viewer))
    rows(page).nth(0).click()
    first = detail.locator("h1")
    expect(first).not_to_have_text("Late resonator sweep")
    before = first.inner_text()
    page.keyboard.press("ArrowDown")
    expect(first).not_to_have_text(before)
    expect(rows(page).nth(1)).to_have_attribute("aria-selected", "true")
    page.keyboard.press("Enter")
    expect(page.get_by_role("tab", name="Explore", exact=True)).to_have_attribute("aria-selected", "true")
    expect(explore(page).locator(".tab-label")).to_have_count(1)


def test_an_unreadable_file_and_a_new_file(viewer, library_files, new_page):
    page = new_page("Library")
    shows(page, every_file(viewer), 20_000)
    broken = lib_row(page, "broken.lbd")
    page.get_by_label("Search the files").fill("broken")
    expect(broken).to_have_class(re.compile("unreadable"))
    expect(broken).to_have_attribute("title", re.compile("Can't be read"))
    broken.click()
    expect(page.locator(".library-detail .error-box")).to_contain_text("can't be read")
    page.get_by_label("Search the files").fill("")
    # a file written while the Library is shown appears by itself
    d = lbd.Dataset(title="Measured just now", created="2026-10-29T10:00:00+08:00")
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [3.0, 4.0], axes="x")
    d.save(viewer.data / "just now.lbd")
    expect(lib_row(page, "Measured just now")).to_be_visible(timeout=15_000)


def test_the_notice_and_names_only(viewer, library_files, new_page):
    viewer.state.config.set_library({"read_headers": False})            # before the first index
    page = new_page("Library")
    expect(page.locator(".library-notice")).to_have_count(0)            # headers off: nothing to warn about
    expect(status(page)).to_contain_text("names only")
    shows(page, every_file(viewer), 20_000)
    page.get_by_label("Search the files").fill("late resonator")       # names only: the file name is found
    late = lib_row(page, "late resonator.lbd")                           # no title read: the file name
    expect(late.locator(".cell-date")).to_have_attribute("title", re.compile("no date of its own"))   # the file's date, greyed
    late.click()
    expect(page.locator(".library-detail")).to_contain_text("Frequency")   # read when selected ...
    expect(lib_row(page, "Late resonator sweep")).to_contain_text("2026-03-14 23:30", timeout=10_000)  # ... and its row fills in
    # on again: the notice, once
    viewer.state.config.set_library({"read_headers": True})
    page.reload()
    notice = page.locator(".library-notice")
    expect(notice).to_contain_text("cloud folder")
    notice.get_by_role("button", name="OK").click()
    expect(notice).to_have_count(0)
    page.reload()
    expect(status(page)).to_contain_text("files", timeout=10_000)
    expect(page.locator(".library-notice")).to_have_count(0)


def test_the_panes_are_dragged_wider_and_the_sidebar_hidden(viewer, new_page):
    """The filters and the selected file are dragged at their edges (remembered after a reload);
    the sidebar's toggle is inside it while it is open and at its edge while it is closed."""
    page = new_page("Library")
    expect(rows(page).first).to_be_visible(timeout=20_000)
    left = page.locator(".library-left")
    detail = page.locator(".library-detail")
    before = (left.bounding_box()["width"], detail.bounding_box()["width"])
    for handle, dx in ((".filters-handle", 80), (".detail-handle", -100)):
        box = page.locator(handle).bounding_box()
        page.mouse.move(box["x"] + 3, 300)
        page.mouse.down()
        page.mouse.move(box["x"] + 3 + dx, 300, steps=5)
        page.mouse.up()
    after = (left.bounding_box()["width"], detail.bounding_box()["width"])
    assert after[0] > before[0] + 60 and after[1] > before[1] + 80
    page.reload()
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(rows(page).first).to_be_visible()
    assert abs(left.bounding_box()["width"] - after[0]) < 2 and abs(detail.bounding_box()["width"] - after[1]) < 2
    # the toggle: in the sidebar while open, at the list's edge while closed
    left.get_by_role("button", name="Hide the sidebar").click()
    expect(left).to_be_hidden()
    page.locator(".library-middle").get_by_role("button", name="Show the sidebar").click()
    expect(left).to_be_visible()
    # the same in Explore: the Files sidebar hides with its own button, the tab row shows it again
    page.get_by_role("tab", name="Explore", exact=True).click()
    page.locator(".sidebar").get_by_role("button", name="Hide the sidebar").click()
    expect(page.locator(".sidebar")).to_be_hidden()
    page.locator("main:not([hidden]) .tabbar").get_by_role("button", name="Show the sidebar").click()
    expect(page.locator(".sidebar")).to_be_visible()
