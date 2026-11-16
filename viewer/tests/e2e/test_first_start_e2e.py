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
    # a synced folder: the edit choice, both explained, the first one chosen
    expect(dialog).to_contain_text("power cut")
    expect(dialog.get_by_role("radio", name="In place")).to_be_checked()
    dialog.get_by_role("radio", name="Copy and swap").check()
    dialog.get_by_role("button", name="Next").click()
    # previews: not every file (that reads every file)
    dialog.get_by_role("radio", name="Only when I click Show preview").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("radio", name="No, never go online").check()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    s = cfg.settings()
    assert s["first_start_done"] is True and s["check_updates"] is False
    assert s["library"]["data_file_edits"] == "copy_and_swap" and s["library"]["read_headers"] is True
    assert s["library"]["previews"] == "off"
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
    # previews of every file would read (download) every file: not offered, the next one chosen
    expect(dialog.get_by_role("radio", name="Every file (in the background)")).to_be_disabled()
    expect(dialog.get_by_role("radio", name="The selected file and rows near it")).to_be_checked()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("radio", name="Yes, check for new versions").check()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    s = cfg.settings()
    assert s["library"]["read_headers"] is False and s["check_updates"] is True
    assert s["library"]["data_file_edits"] == "in_place" and s["library"]["previews"] == "nearby"


def test_each_question_starts_with_its_first_answer(viewer, cfg, context):
    fresh(cfg)
    page = context.new_page()
    page.goto(viewer.url)
    dialog = first_start(page)
    dialog.get_by_role("button", name="Next").click()
    for box in dialog.get_by_role("radio", name="On this computer only").all():
        expect(box).to_be_checked()
    dialog.get_by_role("button", name="Next").click()                  # nothing synced: no edit question
    expect(dialog.get_by_role("radio", name="Every file (in the background)")).to_be_checked()
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_role("radio", name="Yes, check for new versions")).to_be_checked()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    s = cfg.settings()
    assert s["check_updates"] is True and s["library"]["read_headers"] is True
    assert s["library"]["previews"] == "all"


def test_folders_are_kept_until_start_and_can_be_removed(viewer, cfg, context, tmp_path):
    fresh(cfg)
    before = cfg.settings()["roots"]
    other = tmp_path / "more data"
    other.mkdir()
    page = context.new_page()
    page.goto(viewer.url)
    dialog = first_start(page)
    expect(page.get_by_role("tab", name="Library")).to_have_count(0)    # nothing else runs meanwhile
    dialog.get_by_label("A folder's path").fill(str(other))
    dialog.get_by_role("button", name="Add", exact=True).click()
    expect(dialog.locator(".first-start-folders li")).to_have_count(len(before) + 1)
    assert cfg.settings()["roots"] == before                            # not saved yet
    for r in before:                                                    # a folder added by mistake
        dialog.get_by_role("button", name=f"Remove {r}").click()
    expect(dialog.locator(".first-start-folders li")).to_have_count(1)
    for _ in range(3):                                                  # folders, kinds, previews
        dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog).to_be_hidden()
    assert [p.lower() for p in cfg.settings()["roots"]] == [str(other.resolve()).lower()]


def test_a_folder_that_doesnt_exist_is_named_at_start(viewer, cfg, context, tmp_path):
    fresh(cfg)
    page = context.new_page()
    page.goto(viewer.url)
    dialog = first_start(page)
    dialog.get_by_label("A folder's path").fill(str(tmp_path / "missing"))
    dialog.get_by_role("button", name="Add", exact=True).click()
    for _ in range(3):                                                  # folders, kinds, previews
        dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Start").click()
    expect(dialog.get_by_role("alert")).to_contain_text("missing")
    expect(dialog).to_contain_text("Which folders")                     # back on the folders, to fix it
    assert cfg.settings()["first_start_done"] is False


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
