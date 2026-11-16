"""Where a page starts, and the Files bar on a page with nothing open (plan 16, 16.14 and 16.15)."""

from playwright.sync_api import expect


def test_a_new_page_starts_on_the_library(context, viewer):
    page = context.new_page()
    page.goto(viewer.url)
    expect(page.get_by_role("tab", name="Library", exact=True)).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Figure", exact=True).click()
    page.reload()                                                       # a reload keeps its page
    expect(page.get_by_role("tab", name="Figure", exact=True)).to_have_attribute("aria-selected", "true")


def test_a_page_opened_for_a_file_never_shows_the_library_first(context, viewer, values_files):
    page = context.new_page()
    page.add_init_script("""
        new MutationObserver(() => {
          const t = document.querySelector('[role=tab][aria-selected=true]');
          if (t) (window.__seen = window.__seen || []).push(t.textContent.trim());
        }).observe(document, {subtree: true, childList: true, attributes: true});
    """)
    from urllib.parse import quote

    path = str(values_files[0])
    page.goto(f"{viewer.url}&open={quote(path)}&in=explore")
    expect(page.get_by_role("tab", name="Explore", exact=True)).to_have_attribute("aria-selected", "true")
    expect(page.locator(".explore-picture").first).to_be_visible(timeout=20_000)
    assert "Library" not in page.evaluate("window.__seen || []")


def _hide_files(page):
    page.get_by_role("button", name="Hide the sidebar").first.click()
    expect(page.locator("aside.sidebar")).to_be_hidden()


def test_the_files_bar_shows_on_a_page_with_nothing_open(context, viewer):
    page = context.new_page()
    page.goto(viewer.url)
    page.get_by_role("tab", name="Explore", exact=True).click()
    _hide_files(page)                                                   # hidden while staying: it stays hidden
    page.get_by_role("tab", name="Library", exact=True).click()
    page.get_by_role("tab", name="Explore", exact=True).click()
    expect(page.locator("aside.sidebar")).to_be_visible()


def test_the_files_drawer_opens_on_a_narrow_page_with_nothing_open(context, viewer):
    page = context.new_page()
    page.set_viewport_size({"width": 700, "height": 800})
    page.goto(viewer.url)
    page.get_by_role("tab", name="Explore", exact=True).click()
    expect(page.locator("aside.sidebar")).to_be_visible()
