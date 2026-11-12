"""A new version (plan 16.25): the reminder window on one page only, and Settings → About."""

from datetime import date

from playwright.sync_api import expect

from lbd_viewer.updates import CheckError


def test_the_reminder_shows_once_and_leads_to_settings_about(viewer, context):
    viewer.state.updates.automatic = True                     # as after a real start
    viewer.state.config.set_updates({"latest": "99.0.0", "url": "https://github.com/patrick-csliu/lbd/releases/tag/v99.0.0"})

    first = context.new_page()
    first.goto(viewer.url)
    dialog = first.get_by_role("dialog", name="LBD 99.0.0 is available")
    expect(dialog).to_be_visible()

    second = context.new_page()                                # another page: no second window
    second.goto(viewer.url)
    expect(second.get_by_role("button", name="Settings")).to_be_visible()
    second.wait_for_timeout(500)
    expect(second.get_by_role("dialog", name="LBD 99.0.0 is available")).to_have_count(0)

    dialog.get_by_role("button", name="Install…").click()      # goes to Settings → About
    expect(dialog).to_have_count(0)
    settings = first.get_by_role("dialog", name="Settings")
    expect(settings.get_by_text("LBD 99.0.0 is available.")).to_be_visible()
    expect(settings.get_by_role("link", name="The release page")).to_have_attribute(
        "href", "https://github.com/patrick-csliu/lbd/releases/tag/v99.0.0")
    expect(settings.locator(".update-command code")).to_contain_text("releases/latest/download/install")

    def offline():
        raise CheckError("no connection to GitHub (test)")

    viewer.state.updates.fetch = offline                       # Check now says why it failed
    settings.get_by_role("button", name="Check now").click()
    expect(settings.get_by_role("alert")).to_have_text(
        "Couldn't check for a new version: no connection to GitHub (test).")
    assert viewer.state.config.settings()["updates"]["remind"] == {"later": date.today().isoformat()}
