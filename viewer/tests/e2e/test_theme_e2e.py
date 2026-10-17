"""The ⚙ Theme setting in a real browser: Light, Dark, or System (follows the operating system).

The setting is saved by the viewer, so every page follows at once and a reload keeps it.
"""

from playwright.sync_api import Page, expect

DARK_BG = "rgb(21, 24, 28)"      # --bg in styles.css
LIGHT_BG = "rgb(246, 247, 249)"


def choose(page: Page, label: str):
    """⚙ (top right) → Theme → `label`."""
    page.get_by_role("button", name="Settings").click()
    page.get_by_role("dialog", name="Settings").get_by_label(label).check()


def background(page: Page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def theme(page: Page):
    return page.locator("html")


def test_dark_and_light_follow_in_every_page_and_after_a_reload(new_page):
    one, two = new_page(), new_page()
    one.emulate_media(color_scheme="light")
    choose(one, "Dark")
    expect(theme(one)).to_have_attribute("data-theme", "dark")
    assert background(one) == DARK_BG
    expect(theme(two)).to_have_attribute("data-theme", "dark")      # the other page follows
    two.reload()
    expect(theme(two)).to_have_attribute("data-theme", "dark")      # kept
    choose(one, "Light")
    expect(theme(two)).to_have_attribute("data-theme", "light")
    assert background(one) == LIGHT_BG


def test_system_follows_the_operating_system(new_page):
    page = new_page()
    choose(page, "Dark")
    choose(page, "System (follows")
    page.emulate_media(color_scheme="dark")
    expect(theme(page)).to_have_attribute("data-theme", "dark")
    page.emulate_media(color_scheme="light")                       # switched while open
    expect(theme(page)).to_have_attribute("data-theme", "light")
