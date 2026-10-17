"""What a user does and sees in a viewer page, for the browser tests: find a file's row or tab,
open a file, pick a menu entry, switch to a page, double-click a file in Explorer / Finder."""

import re

import httpx
from playwright.sync_api import Page, expect


def exactly(name: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(name)}$")


def row(page: Page, name: str):
    """The Folders panel row of a file."""
    return page.get_by_role("treeitem").filter(has=page.locator(".row-label", has_text=exactly(name)))


def tab(page: Page, name: str):
    """The tab of a file (its label may start with a lock sign while it is being moved)."""
    return page.locator(".tab").filter(has=page.locator(".tab-label", has_text=re.compile(rf"{re.escape(name)}$")))


def tab_names(page: Page) -> list:
    return [t.removeprefix("⇢ ").removeprefix("🔒 ") for t in page.locator(".tab-label").all_inner_texts()]


def open_file(page: Page, name: str):
    row(page, name).dblclick()
    expect(tab(page, name)).to_be_visible()


def plot_type(page: Page):
    """The Plot type choice of the tab on show."""
    return page.locator(".tab-body:not([hidden])").get_by_label("Plot type")


def toast(page: Page, text: str):
    return page.locator(".toast", has_text=text)


def menu(page: Page, label):
    return page.locator(".context-menu").get_by_role("menuitem", name=label)


def use(page: Page):
    """Switch to this browser tab. Headless Chromium doesn't fire the window's focus event on
    bring_to_front, so it is fired here, as a real browser does when the user switches tabs."""
    page.bring_to_front()
    page.evaluate("window.dispatchEvent(new Event('focus'))")


def deliver(viewer, *names) -> dict:
    """What a double-click in Explorer / Finder does: `lbd-view <file>` hands it to the viewer."""
    r = httpx.post(f"http://127.0.0.1:{viewer.port}/api/deliver", headers={"X-LBD-Token": viewer.state.token},
                   json={"files": [viewer.path(n) for n in names], "dirs": []}, timeout=15)
    r.raise_for_status()
    return r.json()
