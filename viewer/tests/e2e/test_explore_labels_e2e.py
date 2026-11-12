"""Explore's Labels tab (plan 16, 16.31): the file's labels edited in Explore, as in the Library."""

from urllib.parse import quote

import lbd
from pageui import row
from playwright.sync_api import expect
from test_explore_e2e import explore, frames
from test_library_labels_e2e import api_rows, eventually


def labels_tab(page):
    explore(page).get_by_role("button", name="Labels", exact=True).first.click()      # the tag button beside ⓘ
    return explore(page).locator(".inspector-body")


def test_a_tag_added_in_explore_is_in_the_library(values_files, viewer, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "6 rabi.lbd").dblclick())
    body = labels_tab(page)
    expect(explore(page).get_by_role("tab", name="Labels")).to_have_attribute("aria-selected", "true")
    body.get_by_role("button", name="Add a tag").click()
    picker = body.get_by_role("dialog", name="Pick a label")
    box = picker.get_by_role("combobox", name="Label", exact=True)
    box.fill("explored")
    at, size = picker.bounding_box(), page.viewport_size                 # the picker stays inside the window
    assert at["x"] >= 0 and at["y"] >= 0 and at["x"] + at["width"] <= size["width"] and at["y"] + at["height"] <= size["height"]
    box.press("Enter")
    expect(body.get_by_label("Tags", exact=True)).to_contain_text("explored")
    eventually(lambda: [r["name"] for r in api_rows(viewer, tags="explored")], ["6 rabi.lbd"])


def test_the_four_tabs_fit_at_the_narrowest(values_files, new_page):
    page = new_page("Explore")
    page.set_viewport_size({"width": 1280, "height": 800})
    frames(page, lambda: row(page, "6 rabi.lbd").dblclick())
    labels_tab(page)
    tabs = explore(page).locator(".inspector-tabs [role=tab]")
    expect(tabs).to_have_count(4)
    cut = tabs.evaluate_all("ts => ts.filter(t => t.scrollWidth > t.clientWidth + 1).map(t => t.textContent)")
    assert cut == []


def test_a_file_outside_the_library_says_so(viewer, context):
    # in a folder the Library skips (a NAS's thumbnails folder): it can be opened, but has no row
    (viewer.data / "@eaDir").mkdir(exist_ok=True)
    d = lbd.Dataset(title="Elsewhere")
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [1.0, 2.0], axes="x")
    path = d.save(viewer.data / "@eaDir" / "elsewhere.lbd")
    page = context.new_page()
    page.goto(f"{viewer.url}&open={quote(str(path))}&in=explore")
    expect(explore(page).locator(".explore-picture").first).to_be_visible(timeout=20_000)
    body = labels_tab(page)
    expect(body).to_contain_text("isn't in the Library's folders")
