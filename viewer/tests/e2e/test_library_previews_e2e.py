"""Previews in the Library, in a real browser (plan 8c): the selected file's picture, the rows near
it drawn ahead, the picture view, the Previews setting (Off: Show preview; "Every file" needs
header reading), a preview chosen in Explore that later changes don't touch, Reset, and files
without a preview saying why."""

import re

import httpx
import lbd
from playwright.sync_api import Page, expect


def row(page: Page, name: str):
    """The list row of a file in the data folder (its tooltip is its path)."""
    return page.locator(f'.library-row[title$="{name}"]')


def preview(page: Page):
    return page.locator(".library-detail .preview")


def put_settings(viewer, library):
    httpx.put(f"http://127.0.0.1:{viewer.port}/api/settings", headers={"X-LBD-Token": viewer.state.token},
              json={"library": library}).raise_for_status()


def change(path):
    """Save the file again with a new description (the same measurement, changed)."""
    d = lbd.load(path)
    d.description = "changed after the preview was chosen"
    d.save(path)


def test_the_selected_file_shows_its_preview_and_the_next_one_is_ready(viewer, new_page):
    page = new_page("Library")
    row(page, "a.lbd").click()
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    expect(preview(page)).to_contain_text("As Explore first shows the file")
    page.keyboard.press("ArrowDown")                         # the row after it was drawn ahead
    expect(preview(page).locator("img")).to_be_visible(timeout=5_000)


def test_the_picture_view_shows_the_files_as_pictures(viewer, new_page):
    page = new_page("Library")
    expect(row(page, "a.lbd")).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Pictures", exact=True).click()
    cards = page.locator(".library-card:not(.loading)")
    expect(cards.first.locator("img")).to_be_visible(timeout=30_000)
    cards.first.click()
    expect(cards.first).to_have_class(re.compile("selected"))
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    page.reload()                                           # remembered
    expect(page.locator(".library-card").first).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="List", exact=True).click()
    expect(row(page, "a.lbd")).to_be_visible()


def test_with_previews_off_a_click_draws_one_and_every_file_needs_headers(viewer, new_page):
    put_settings(viewer, {"previews": "off"})
    page = new_page("Library")
    row(page, "b.lbd").click()
    expect(preview(page)).to_contain_text("Previews are off", timeout=20_000)
    preview(page).get_by_role("button", name="Show preview").click()
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    # the setting: "Every file" can't be chosen while the files' details aren't read
    page.locator("button[aria-label=Settings]").click()
    page.get_by_label(re.compile("Read each data file's details")).uncheck()
    expect(page.get_by_label(re.compile("^Every file"))).to_be_disabled()
    page.get_by_label(re.compile("Read each data file's details")).check()
    expect(page.get_by_label(re.compile("^Every file"))).to_be_enabled()
    page.get_by_label(re.compile("^Every file")).check()
    expect(page.get_by_text(re.compile(r"Picture cache: \d+ picture"))).to_be_visible()


def test_a_preview_chosen_in_explore_stays_until_reset(viewer, new_page):
    page = new_page("Library")
    row(page, "c.lbd").click()
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Open in Explore").click()
    page.locator("main:not([hidden])").get_by_role("button", name="Library preview", exact=True).click()
    expect(page.get_by_text("This view is now the file's preview in the Library.")).to_be_visible(timeout=30_000)
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(preview(page)).to_contain_text("Chosen in Explore on", timeout=10_000)
    # the file changes: the chosen picture stays, and says it was chosen before
    change(viewer.data / "c.lbd")
    expect(preview(page)).to_contain_text("before the file last changed", timeout=20_000)
    preview(page).get_by_role("button", name="Reset preview").click()
    expect(preview(page)).to_contain_text("As Explore first shows the file", timeout=30_000)


def test_a_file_without_a_preview_says_why(viewer, new_page):
    d = lbd.Dataset(title="Fit results")
    d.add_value("f0", 7.0)
    d.save(viewer.data / "numbers.lbd")
    page = new_page("Library")
    row(page, "numbers.lbd").click()
    expect(preview(page)).to_contain_text("only single numbers", timeout=30_000)
