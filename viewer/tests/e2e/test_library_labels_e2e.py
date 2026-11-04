"""Labels in the Library, in a real browser (plan 8b): star, project, users, tags and a comment on
one or several files; the label trees filter the list and search finds labels; copies of one
measurement share labels; copies that differ are explained and resolved; a file duplicated as a
new measurement; labels whose file disappeared are listed as missing and discarded."""

import re
import shutil

import httpx
import lbd
from playwright.sync_api import Page, expect
from test_library_e2e import every_file, lib_row, rows, shows, status


def detail(page: Page):
    return page.locator(".library-detail")


def eventually(get, want, timeout=10.0):
    """Wait until get() returns `want` (the index and the page catch up within seconds)."""
    import time

    end = time.monotonic() + timeout
    while (got := get()) != want:
        assert time.monotonic() < end, f"still {got!r}, wanted {want!r}"
        time.sleep(0.2)


def api_rows(viewer, **params):
    return httpx.get(f"http://127.0.0.1:{viewer.port}/api/library/list", headers={"X-LBD-Token": viewer.state.token},
                     params={"limit": "500", **params}).json()["rows"]


def find(page: Page, text: str):
    """Search for `text` and select the one row found."""
    page.get_by_label("Search the files").fill(text)
    expect(rows(page)).to_have_count(1)
    rows(page).first.click()


def pick(page: Page, button: str, label: str):
    """Open a label picker in the right column, type a label and choose it."""
    detail(page).get_by_role("button", name=button).click()
    box = detail(page).get_by_role("textbox", name="Label", exact=True)
    box.fill(label)
    box.press("Enter")


def test_labels_on_one_and_several_files_filter_and_search(viewer, library_files, new_page):
    page = new_page("Library")
    shows(page, every_file(viewer), 20_000)
    find(page, "Late resonator sweep")
    detail(page).get_by_role("button", name="Star", exact=True).click()      # the ☆ in front of the title
    expect(rows(page).first).to_contain_text("★")
    expect(detail(page).get_by_role("button", name="Starred (click: unstar)")).to_be_visible()
    pick(page, "Add a tag", "flux/bias")
    expect(detail(page).get_by_label("Tags", exact=True)).to_contain_text("flux/bias")
    pick(page, "Set the project", "Qubit A/Device 3")
    expect(detail(page).get_by_label("Project", exact=True)).to_contain_text("Qubit A/Device 3")
    pick(page, "Add a user", "Lab A/Qubit team/Patrick")
    comment = detail(page).get_by_label("Comment")
    comment.fill("punch-out seen at high power")
    comment.blur()
    eventually(lambda: [r["comment"] for r in api_rows(viewer, q="punch-out") if r["comment"]], ["punch-out seen at high power"])

    # the label trees on the left filter the list (a parent includes its children)
    page.get_by_label("Search the files").fill("")
    shows(page, every_file(viewer))
    tags = page.locator(".library-labels").get_by_role("tree", name="Tags")
    tags.get_by_role("button", name="flux", exact=True).click()
    expect(status(page)).to_contain_text(re.compile(r"^1 of \d+ files"))
    tags.get_by_role("button", name="flux", exact=True).click()                   # again: cleared
    page.locator(".library-labels").get_by_role("tree", name="Project").get_by_role("button", name="Qubit A", exact=True).click()
    expect(rows(page)).to_have_count(1)
    page.get_by_role("button", name="Any project").click()
    page.locator(".library-labels").get_by_label("★ Starred only").check()
    expect(rows(page)).to_have_count(1)
    page.locator(".library-labels").get_by_label("★ Starred only").uncheck()
    page.get_by_label("Search the files").fill("seen at high power")              # the comment is searched
    expect(rows(page)).to_have_count(1)

    # several files at once: Ctrl+click, Space stars them, a tag on both
    page.get_by_label("Search the files").fill("Rabi amplitude")
    expect(rows(page).nth(1)).to_be_visible()
    rows(page).nth(0).click()
    rows(page).nth(1).click(modifiers=["ControlOrMeta"])
    expect(detail(page).locator("h1")).to_have_text("2 files selected")
    page.keyboard.press("Space")
    expect(rows(page).nth(0)).to_contain_text("★")
    expect(rows(page).nth(1)).to_contain_text("★")
    pick(page, "Add a tag", "both")
    eventually(lambda: len(api_rows(viewer, tags="both")), 2)


def make_copies(viewer):
    a, b = viewer.data / "copies A", viewer.data / "copies B"
    a.mkdir()
    b.mkdir()
    d = lbd.Dataset(title="Copied sweep", description="original", created="2026-10-29T09:00:00+08:00")
    d.add_axis("x", [1.0, 2.0, 3.0])
    d.add_value("y", [1.0, 4.0, 9.0], axes="x")
    d.save(a / "copied.lbd")
    shutil.copy2(a / "copied.lbd", b / "copied.lbd")                             # a backup elsewhere
    return a / "copied.lbd", b / "copied.lbd"


def test_copies_share_labels_and_copies_that_differ_are_explained(viewer, library_files, new_page):
    first, second = make_copies(viewer)
    page = new_page("Library")
    page.get_by_label("Search the files").fill("Copied sweep")
    expect(rows(page)).to_have_count(2, timeout=20_000)
    expect(rows(page).first).to_contain_text("2 copies")
    rows(page).first.click()
    expect(detail(page).get_by_role("note", name="Copies")).to_contain_text("an identical copy; labels are shared")
    pick(page, "Add a tag", "shared")
    eventually(lambda: sorted(len(r["tags"]) for r in api_rows(viewer, q="Copied sweep")), [1, 1])   # both

    # one copy edited after copying: both rows warn, the box explains
    d = lbd.load(second)
    d.description = "edited after copying"
    d.save(second)
    expect(page.locator(".library-row.conflict")).to_have_count(2, timeout=15_000)
    expect(page.locator(".library-conflicts")).to_contain_text("look like copies of each other but differ")
    rows(page).first.click()
    box = detail(page).get_by_role("region", name="Copies of one measurement that differ")
    expect(box).to_contain_text("hidden identity")
    expect(box.locator(".conflict-differs")).to_contain_text("description")
    box.get_by_role("button", name="They are the same measurement").click()
    expect(page.locator(".library-row.conflict")).to_have_count(0, timeout=10_000)

    # changed again: asked again; this time it becomes a separate measurement
    d.description = "edited once more"
    d.save(second)
    expect(page.locator(".library-row.conflict")).to_have_count(2, timeout=15_000)
    page.locator(".library-row.conflict").first.click()
    detail(page).get_by_role("button", name="Make this a new measurement").click()
    page.locator(".confirm-dialog").get_by_role("button", name="Make it a new measurement").click()
    expect(page.locator(".library-row.conflict")).to_have_count(0, timeout=10_000)
    assert lbd.info(first).id != lbd.info(second).id


def test_duplicate_as_new_measurement_and_missing_labels(viewer, library_files, new_page):
    first, _ = make_copies(viewer)
    page = new_page("Library")
    page.get_by_label("Search the files").fill("Copied sweep")
    expect(rows(page)).to_have_count(2, timeout=20_000)
    lib_row(page, "Copied sweep").first.click(button="right")
    page.locator(".context-menu").get_by_role("menuitem", name="Duplicate as new measurement").click()
    expect(rows(page)).to_have_count(3, timeout=10_000)
    copies = [p for p in viewer.data.rglob("copied (copy).lbd")]
    assert len(copies) == 1 and lbd.info(copies[0]).parent_id == lbd.info(first).id

    # a labelled file deleted outside LBD: its labels are listed as missing, then discarded
    page.get_by_label("Search the files").fill("Late resonator sweep")
    expect(rows(page)).to_have_count(1)
    rows(page).first.click()
    pick(page, "Add a tag", "keep me")
    eventually(lambda: len(api_rows(viewer, tags="keep me")), 1)
    target = next(viewer.data.rglob("late resonator.lbd"))
    target.unlink()
    missing = page.locator(".library-labels").get_by_role("button", name=re.compile(r"Missing files: 1"))
    expect(missing).to_be_visible(timeout=15_000)
    missing.click()
    panel = detail(page)
    expect(panel).to_contain_text("late resonator.lbd")
    expect(panel).to_contain_text("tag keep me")
    panel.get_by_role("button", name="Discard").click()
    page.locator(".confirm-dialog").get_by_role("button", name="Discard").click()
    expect(missing).to_have_count(0, timeout=10_000)
