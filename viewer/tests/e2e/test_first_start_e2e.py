"""The first start's questions (plan 18, 18.8): asked until answered, never closed; folders, where
each is kept, the edit choice for a synced folder, and the check for new versions. Settings from
before them, with folders, get only the version question."""

from playwright.sync_api import expect


def first_start(page):
    return page.get_by_role("dialog", name="Welcome to LBD Viewer")


def fresh(cfg):
    """Settings as on a first start: no answers yet (the viewer fixture answers them)."""
    s = cfg.settings()
    s["first_start_done"], s["check_updates"] = False, None
    cfg._save_settings(s)


def test_a_first_start_asks_until_answered(viewer, cfg, context):
    fresh(cfg)
    page = context.new_page()
    page.goto(viewer.url)
    dialog = first_start(page)
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")                                       # can't be closed
    expect(dialog).to_be_visible()
    page.reload()                                                       # nor left: asked again
    expect(first_start(page)).to_be_visible()
    dialog = first_start(page)
    # the folder: the viewer's data folder is open already (the fixture); another is typed
    expect(dialog.locator(".first-start-folders li")).not_to_have_count(0)
    dialog.get_by_role("button", name="Next").click()
    # where each folder is kept: synced
    for box in dialog.get_by_role("radio", name="Synced with other computers").all():
        box.check()
    dialog.get_by_role("button", name="Next").click()
    # a synced folder: the edit choice, both explained, no default
    expect(dialog).to_contain_text("power cut")
    expect(dialog.get_by_role("button", name="Next")).to_be_disabled()
    dialog.get_by_role("radio", name="Copy and swap").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("radio", name="No, never go online").check()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    s = cfg.settings()
    assert s["first_start_done"] is True and s["check_updates"] is False
    assert s["library"]["data_file_edits"] == "copy_and_swap" and s["library"]["read_headers"] is True
    page.reload()
    expect(first_start(page)).to_have_count(0)


def test_a_folder_kept_online_only_turns_reading_off(viewer, cfg, context):
    fresh(cfg)
    page = context.new_page()
    page.goto(viewer.url)
    dialog = first_start(page)
    dialog.get_by_role("button", name="Next").click()
    for box in dialog.get_by_role("radio", name="In the cloud, files kept online only").all():
        box.check()
    dialog.get_by_role("button", name="Next").click()                  # no synced folder: no edit question
    dialog.get_by_role("radio", name="Yes, check for new versions").check()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    s = cfg.settings()
    assert s["library"]["read_headers"] is False and s["check_updates"] is True
    assert s["library"]["data_file_edits"] == "in_place"


def test_an_upgrade_gets_only_the_version_question(viewer, cfg, context):
    s = cfg.settings()
    s["check_updates"] = None                                           # folders, but not asked yet
    cfg._save_settings(s)
    page = context.new_page()
    page.goto(viewer.url)
    dialog = page.get_by_role("dialog", name="Welcome to LBD Viewer")
    expect(dialog).to_contain_text("One question")
    expect(dialog).not_to_contain_text("Which folders")
    dialog.get_by_role("radio", name="No, never go online").check()
    dialog.get_by_role("button", name="OK").click()
    expect(dialog).to_be_hidden()
    assert cfg.settings()["check_updates"] is False and cfg.settings()["first_start_done"] is True


def test_the_version_check_is_turned_on_and_off_in_about(viewer, cfg, new_page):
    from pageui import open_settings

    page = new_page("Library")
    dialog = open_settings(page, "About")
    box = dialog.get_by_label("Check for new versions online")
    expect(box).not_to_be_checked()                                     # the fixture answered no
    box.click()
    expect(box).to_be_checked()
    assert cfg.settings()["check_updates"] is True
