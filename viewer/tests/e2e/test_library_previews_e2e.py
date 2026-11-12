"""Previews in the Library, in a real browser (plan 8c): the selected file's picture, the rows near
it drawn ahead, the picture view, the Previews setting (Off: Show preview; "Every file" needs
header reading), a preview chosen in Explore that later changes don't touch, Reset, Update
preview and its question (16.43), "Live" for a file being measured, and files without a preview
saying why."""

import re
import time

import httpx
import lbd
import numpy as np
from pageui import open_settings
from playwright.sync_api import Page, expect


def row(page: Page, name: str):
    """The list row of a file in the data folder (its tooltip is its path)."""
    return page.locator(f'.library-row[title$="{name}"]')


def preview(page: Page):
    return page.locator(".library-detail .library-preview")


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
    expect(preview(page)).to_contain_text("it stays when the file changes")
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
    expect(page.locator(".library-detail .library-file-head")).to_be_visible()
    expect(preview(page)).to_have_count(0)                  # the card shows the picture: not again on the right
    page.reload()                                           # remembered
    expect(page.locator(".library-card").first).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="List", exact=True).click()
    expect(row(page, "a.lbd")).to_be_visible()


def test_the_picture_view_sorts_and_shows_the_chosen_fields(viewer, new_page):
    """Plan 14: Name and Date sort the pictures (and the list: one order); ⋯ chooses the name and
    the lines under each picture, and the cards make room for them."""
    for title in ("Zebra Bravo", "Zebra Alpha", "Zebra Charlie"):
        d = lbd.Dataset(title=title)
        d.add_axis("t", [0.0, 1.0])
        d.add_value("v", [1.0, 2.0], axes="t")
        d.save(viewer.data / f"file {title}.lbd")
    page = new_page("Library")
    page.get_by_role("button", name="Pictures", exact=True).click()
    page.get_by_label("Search the files").fill("Zebra")
    names = page.locator(".library-card .card-name")
    expect(names).to_have_count(3)
    order = page.get_by_role("group", name="Sort the files by")
    order.get_by_role("button", name="Name").click()
    expect(names).to_have_text(["Zebra Alpha", "Zebra Bravo", "Zebra Charlie"])
    order.get_by_role("button", name="Name").click()
    expect(names).to_have_text(["Zebra Charlie", "Zebra Bravo", "Zebra Alpha"])
    card = page.locator(".library-card").first
    height = card.bounding_box()["height"]
    fields = card.locator(".card-field")
    expect(fields).to_have_count(1)                                    # the date
    page.get_by_role("button", name="What each picture shows").click()
    page.get_by_role("menuitem", name="Sweep size").click()
    expect(fields).to_have_count(2)
    assert card.bounding_box()["height"] > height
    page.get_by_role("button", name="What each picture shows").click()
    page.get_by_role("menuitem", name="Name: the file name").click()
    expect(names.first).to_contain_text("file Zebra Charlie.lbd")
    page.reload()
    expect(page.locator(".library-card").first.locator(".card-field")).to_have_count(2)
    page.get_by_role("button", name="List", exact=True).click()
    assert "▾" in page.locator("[role=columnheader][data-col=name]").inner_text()   # the list keeps the order


def test_with_previews_off_a_click_draws_one_and_every_file_needs_headers(viewer, new_page):
    put_settings(viewer, {"previews": "off"})
    page = new_page("Library")
    row(page, "b.lbd").click()
    expect(preview(page)).to_contain_text("Previews are off", timeout=20_000)
    preview(page).get_by_role("button", name="Show preview").click()
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    # the setting: "Every file" can't be chosen while the files' details aren't read
    d = open_settings(page, "Library")
    every = d.get_by_label("Draw previews of").locator("option[value=all]")
    d.get_by_label("Read each data file's details").uncheck()
    expect(every).to_be_disabled()
    d.get_by_label("Read each data file's details").check()
    expect(every).to_be_enabled()
    d.get_by_label("Draw previews of").select_option("all")
    expect(d.locator("[data-setting='library.cache']")).to_contain_text(re.compile(r"\d+ pictures? ·"))


def test_a_preview_chosen_in_explore_stays_until_reset(viewer, new_page):
    page = new_page("Library")
    row(page, "c.lbd").click()
    expect(preview(page).locator("img")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Open in Explore").click()
    page.locator("main:not([hidden])").get_by_role("button", name="More", exact=True).click()
    page.get_by_role("menuitem", name="Use as Library picture").click()
    expect(page.get_by_text(re.compile("Library picture updated"))).to_be_visible(timeout=30_000)
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(preview(page)).to_contain_text("Chosen in Explore on", timeout=10_000)
    # the file changes: the chosen picture stays, and says it was chosen before
    change(viewer.data / "c.lbd")
    expect(preview(page)).to_contain_text("before the file last changed", timeout=20_000)
    preview(page).get_by_role("button", name="Reset preview").click()
    expect(preview(page)).to_contain_text("it stays when the file changes", timeout=30_000)


def shown_picture(page: Page) -> bytes:
    """The bytes of the picture the preview box shows."""
    img = preview(page).locator("img")
    expect(img).to_be_visible(timeout=30_000)
    data = img.evaluate("async (i) => Array.from(new Uint8Array(await (await fetch(i.src)).arrayBuffer()))")
    return bytes(data)


def test_update_preview_draws_a_changed_file_again_and_asks_for_a_chosen_picture(viewer, new_page):
    """16.43: a file's preview stays when it changes; right-click → Update preview draws it again.
    A picture chosen in Explore is replaced only after a question."""
    d = lbd.Dataset(title="Own measurement")             # a file of its own (no copies in the folder)
    d.add_axis("t", np.linspace(0, 1, 40))
    d.add_value("v", np.sin(np.linspace(0, 6, 40)), axes="t")
    d.save(viewer.data / "own.lbd")
    page = new_page("Library")
    row(page, "own.lbd").click()
    first = shown_picture(page)
    d = lbd.load(viewer.data / "own.lbd")                 # other data: the same measurement, changed
    d.values["v"].data[:] = np.cos(np.linspace(0, 6, 40))
    d.save(viewer.data / "own.lbd")
    page.wait_for_timeout(3000)                           # the Library has seen the change
    assert shown_picture(page) == first                   # kept
    row(page, "own.lbd").click(button="right")
    page.get_by_role("menuitem", name="Update preview").click()
    expect(page.get_by_role("dialog")).to_have_count(0)   # no question: an automatic picture
    deadline = time.monotonic() + 30
    while shown_picture(page) == first:                   # drawn again, of the data as it is now
        assert time.monotonic() < deadline, "Update preview didn't draw the picture again"
        page.wait_for_timeout(200)
    # a chosen picture: asked first; Cancel keeps it
    page.get_by_role("button", name="Open in Explore").click()
    page.locator("main:not([hidden])").get_by_role("button", name="More", exact=True).click()
    page.get_by_role("menuitem", name="Use as Library picture").click()
    expect(page.get_by_text(re.compile("Library picture updated"))).to_be_visible(timeout=30_000)
    page.get_by_role("tab", name="Library", exact=True).click()
    expect(preview(page)).to_contain_text("Chosen in Explore on", timeout=10_000)
    row(page, "own.lbd").click(button="right")
    page.get_by_role("menuitem", name="Update preview").click()
    question = page.get_by_role("dialog", name="Replace the picture chosen in Explore?")
    expect(question).to_contain_text("can't be drawn again")
    question.get_by_role("button", name="Cancel").click()
    expect(preview(page)).to_contain_text("Chosen in Explore on")
    row(page, "own.lbd").click(button="right")
    page.get_by_role("menuitem", name="Update preview").click()
    question.get_by_role("button", name="Replace it").click()
    expect(preview(page)).to_contain_text("it stays when the file changes", timeout=30_000)


def test_a_file_being_measured_shows_live(viewer, new_page):
    w = lbd.Writer(viewer.data / "live.lbd", title="live")
    w.add_axis("x", np.arange(5.0))
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    w.flush()
    try:
        page = new_page("Library")
        expect(row(page, "live.lbd.writing")).to_contain_text("measuring…", timeout=20_000)
        row(page, "live.lbd.writing").click()
        expect(preview(page)).to_contain_text("Live")
        page.get_by_role("button", name="Pictures", exact=True).click()
        card = page.locator('.library-card[title$="live.lbd.writing"]')
        expect(card.locator(".card-picture")).to_have_text("Live")
    finally:
        w.close(stopped=True)


def test_a_file_without_a_preview_says_why(viewer, new_page):
    d = lbd.Dataset(title="Fit results")
    d.add_value("f0", 7.0)
    d.save(viewer.data / "numbers.lbd")
    page = new_page("Library")
    row(page, "numbers.lbd").click()
    expect(preview(page)).to_contain_text("only single numbers", timeout=30_000)
