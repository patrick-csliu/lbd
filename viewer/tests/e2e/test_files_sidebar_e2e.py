"""The Files sidebar of Explore and Figure in a real browser (it replaced the Folders panel): the
Library's list with this browser tab's filters, stepping through it, a search that narrows only
the sidebar, the filters going along to a new browser tab, the lists chosen in ⚙ Settings, and
the folder tree, which lists images and style files in Figure only."""

import json
import re

import httpx
from PIL import Image
from playwright.sync_api import Page, expect
from pageui import menu, open_settings


def sidebar(page: Page):
    return page.locator(".files-sidebar")


def names(page: Page) -> list:
    return sidebar(page).locator(".files-row .files-name").all_inner_texts()


def choose(page: Page, scope: str):
    """The sidebar's list (the tests' pages start on the folder tree, see conftest)."""
    sidebar(page).get_by_label("Files listed").select_option(scope)


def library_search(page: Page, text: str):
    page.get_by_role("tab", name="Library", exact=True).click()
    page.get_by_label("Search the files").fill(text)
    expect(page.locator(".library-status")).to_contain_text(f'"{text}"')


def test_the_library_selection_and_stepping_through_it(viewer, library_files, new_page):
    page = new_page("Library")
    library_search(page, "resonator")
    first = page.locator(".library-row:not(.loading)").first.inner_text().split("\n")[0]
    page.get_by_role("tab", name="Explore", exact=True).click()
    choose(page, "library")
    # the same files as the Library, its filters shown read-only
    expect(sidebar(page).locator(".files-filters")).to_contain_text('"resonator"')
    expect(sidebar(page).locator(".files-row").first).to_contain_text(first)
    # click: shows the file; ↓: the next one
    sidebar(page).locator(".files-row").nth(0).click()
    expect(page.locator(".tab.active .tab-label")).to_contain_text(first)
    second = sidebar(page).locator(".files-row .files-name").nth(1).inner_text()
    page.keyboard.press("ArrowDown")
    expect(sidebar(page).locator(".files-row.active")).to_contain_text(second)
    expect(page.locator(".tab.active .tab-label")).to_contain_text(second)
    # Edit ↗ goes to the Library, with its filters as they were
    sidebar(page).get_by_role("button", name="Edit ↗").click()
    expect(page.get_by_label("Search the files")).to_have_value("resonator")


def test_the_sidebar_search_narrows_only_the_sidebar(viewer, library_files, new_page):
    page = new_page("Library")
    library_search(page, "resonator")
    page.get_by_role("tab", name="Figure", exact=True).click()
    choose(page, "library")
    sidebar(page).get_by_label("Search in these files").fill("late")
    expect(sidebar(page).locator(".files-row", has_text="Late resonator sweep")).to_be_visible()
    expect(sidebar(page).locator(".files-row", has_text="Resonator sweep 0")).to_have_count(0)
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(page.get_by_label("Search the files")).to_have_value("resonator")   # unchanged


def test_a_new_browser_tab_starts_with_the_same_filters(viewer, library_files, new_page, context):
    page = new_page("Library")
    library_search(page, "fridge")
    page.get_by_role("tab", name="Figure", exact=True).click()
    choose(page, "library")
    row = sidebar(page).locator(".files-row", has_text="Fridge").first   # (metadata matches some others)
    row.click(button="right")
    with context.expect_page() as opened:
        menu(page, "Open in new browser tab").click()
    other = opened.value
    other.get_by_role("tab", name="Figure", exact=True).click()
    sidebar(other).get_by_label("Files listed").select_option("library")
    expect(sidebar(other).locator(".files-filters")).to_contain_text('"fridge"')
    assert "library=" not in other.url                      # taken from the address, then hidden
    # from then on, each tab has its own
    library_search(other, "rabi")
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(page.get_by_label("Search the files")).to_have_value("fridge")


def test_the_lists_offered_are_chosen_in_settings(viewer, library_files, new_page):
    page = new_page("Explore")
    expect(sidebar(page).get_by_label("Files listed")).to_be_visible()
    r = httpx.put(f"http://127.0.0.1:{viewer.port}/api/settings", headers={"X-LBD-Token": viewer.state.token},
                  json={"library": {"sidebar_scopes": ["library"]}}, timeout=15)
    r.raise_for_status()
    page.reload()
    page.get_by_role("tab", name="Explore", exact=True).click()
    # only the Library selection: no choice to make, even though this tab had chosen the folders
    expect(sidebar(page).locator(".files-filters")).to_be_visible()
    expect(sidebar(page).get_by_label("Files listed")).to_have_count(0)
    # ⚙ Settings → Files sidebar
    open_settings(page, "Files sidebar").get_by_label("Recent").check()
    page.keyboard.press("Escape")
    expect(sidebar(page).get_by_label("Files listed")).to_be_visible()
    assert json.loads(page.evaluate("JSON.stringify(Array.from(document.querySelectorAll('.files-scope option')).map(o => o.value))")) == \
        ["library", "recent"]


def test_folders_list_images_and_style_files_in_figure_only(viewer, new_page):
    Image.new("RGB", (4, 4)).save(viewer.data / "photo.png")
    (viewer.data / "paper.lbd.json").write_text(json.dumps({"name": "paper"}))
    page = new_page("Explore")
    tree = sidebar(page).get_by_role("tree")
    expect(tree.locator(".row-label", has_text="curve.lbd")).to_be_visible()     # data files: in both
    expect(tree.locator(".row-label", has_text="photo.png")).to_have_count(0)
    expect(tree.locator(".row-label", has_text="paper.lbd.json")).to_have_count(0)
    page.get_by_role("tab", name="Figure", exact=True).click()
    expect(tree.locator(".row-label", has_text="photo.png")).to_be_visible()
    expect(tree.locator(".row-label", has_text="paper.lbd.json")).to_be_visible()


def put_library(viewer, **changes):
    httpx.put(f"http://127.0.0.1:{viewer.port}/api/settings", headers={"X-LBD-Token": viewer.state.token},
              json={"library": changes}, timeout=15).raise_for_status()


def test_the_layouts_two_lines_one_line_and_columns(viewer, library_files, new_page):
    """Two lines by default (the chosen fields on the second); one line with the file name; columns
    that sort the sidebar only (the Library keeps its order), with column widths kept."""
    page = new_page("Explore")
    choose(page, "library")
    first = sidebar(page).locator(".files-row:not(.loading)").first
    expect(first.locator(".files-line2")).to_be_visible(timeout=20_000)       # two lines
    # one line, the file name as the name
    put_library(viewer, sidebar_layout="one", sidebar_main="file")
    page.reload()
    page.get_by_role("tab", name="Explore", exact=True).click()
    expect(sidebar(page).locator(".files-row .files-name").first).to_contain_text(".lbd")
    expect(sidebar(page).locator(".files-line2")).to_have_count(0)
    # columns: sorting by a column sorts the sidebar, not the Library
    put_library(viewer, sidebar_layout="columns", sidebar_main="title", sidebar_fields=["date", "sweep"])
    page.reload()
    page.get_by_role("tab", name="Explore", exact=True).click()
    head = sidebar(page).locator(".files-colhead")
    head.get_by_role("button", name="Name").click()
    expect(head.locator("[aria-sort='ascending']")).to_contain_text("Name")
    names = [n.removeprefix("⚠ ").removeprefix("★ ") for n in sidebar(page).locator(".files-row .files-name").all_inner_texts()[:5]]
    assert names == sorted(names, key=str.lower)
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(page.locator(".library-head [aria-sort='descending']")).to_contain_text("Date")  # the Library's own sort
    # a column's width is dragged at its title's edge, and kept
    page.get_by_role("tab", name="Explore", exact=True).click()
    cell = head.locator(".files-colcell").nth(1)
    w0 = cell.bounding_box()["width"]
    grip = cell.locator(".col-resize").bounding_box()
    page.mouse.move(grip["x"] + 2, grip["y"] + 5)
    page.mouse.down()
    page.mouse.move(grip["x"] + 42, grip["y"] + 5, steps=5)
    page.mouse.up()
    page.reload()
    page.get_by_role("tab", name="Explore", exact=True).click()
    assert sidebar(page).locator(".files-colhead .files-colcell").nth(1).bounding_box()["width"] > w0 + 30
    # a column's title dragged to another place: the fields' order (Name stays first)
    cells = sidebar(page).locator(".files-colhead .files-colcell")
    expect(cells).to_have_text([re.compile("^Name"), re.compile("^Date"), re.compile("^Sweep")])
    cells.nth(2).scroll_into_view_if_needed()                                       # the sidebar is narrow
    sweep, date = cells.nth(2).bounding_box(), cells.nth(1).bounding_box()
    page.mouse.move(sweep["x"] + 15, sweep["y"] + sweep["height"] / 2)
    page.mouse.down()
    page.mouse.move(date["x"] + 5, date["y"] + date["height"] / 2, steps=8)
    page.mouse.up()
    expect(cells).to_have_text([re.compile("^Name"), re.compile("^Sweep"), re.compile("^Date")])
