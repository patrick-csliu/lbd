"""Getting data out in a real browser (plan 5): Save as CSV from a panel's Data menu (choices,
the size line) gives a file numpy reads back; Copy picture puts a PNG on the clipboard."""

import lbd
import numpy as np
import pytest
from pageui import open_file, row
from playwright.sync_api import Page, expect
from test_explore_e2e import explore, frames


@pytest.fixture
def sweep(viewer):
    d = lbd.Dataset(title="Sweep")
    d.add_axis("power", [-30.0, -20.0, -10.0], unit="dBm", label="Power")
    d.add_axis("f", np.linspace(4e9, 6e9, 51), unit="Hz", label="Frequency")
    d.add_value("T", np.arange(153.0).reshape(3, 51), axes=["power", "f"], unit="K")
    d.plot = {"kind": "heatmap", "x": "f", "y": "power"}
    d.save(viewer.data / "sweep.lbd")
    return d


def open_dialog(page: Page):
    explore(page).get_by_role("button", name="Data ▾").click()
    page.get_by_role("menuitem", name="Save as CSV…").click()
    dialog = page.get_by_role("dialog", name="Save as CSV")
    expect(dialog).to_be_visible()
    return dialog


def test_save_as_csv_from_the_data_menu(sweep, viewer, new_page):
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    dialog = open_dialog(page)
    expect(dialog.get_by_role("status").first).to_contain_text("153 rows × 3 columns")
    expect(dialog.get_by_label("File name")).to_have_value("sweep_T.csv")
    dialog.get_by_label("table (matrix)").check()
    expect(dialog.get_by_role("status").first).to_contain_text("4 rows × 52 columns")
    dialog.get_by_label("File name").fill("sweep table.csv")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_text("Saved ")).to_be_visible()
    a = np.loadtxt(viewer.data / "sweep table.csv", delimiter=",", encoding="utf-8")
    np.testing.assert_array_equal(a[1:, 1:], sweep.values["T"].data)

    dialog = open_dialog(page)                               # the choice is remembered
    expect(dialog.get_by_label("table (matrix)")).to_be_checked()
    dialog.get_by_label("File name").fill("sweep table.csv")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog.locator(".dialog-error")).to_contain_text("exists already")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()


def clipboard_png(page: Page):
    """The PNG on the clipboard once there is one: (width, height) in pixels."""
    for _ in range(50):
        size = page.evaluate("""async () => {
            for (const item of await navigator.clipboard.read()) {
                if (!item.types.includes("image/png")) continue;
                const bmp = await createImageBitmap(await item.getType("image/png"));
                return [bmp.width, bmp.height];
            }
            return null;
        }""")
        if size:
            return size
        page.wait_for_timeout(100)
    raise AssertionError("no picture on the clipboard")


def test_copy_picture_of_a_panel_and_of_all(sweep, viewer, context, new_page):
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=viewer.url.split("/?")[0])
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    box = lambda css: explore(page).locator(css).bounding_box()    # noqa: E731  (the layout settles: measured late)

    def copy(entry="Copy picture"):
        explore(page).get_by_role("button", name="Data ▾").first.click()
        page.get_by_role("menuitem", name=entry).click()
        expect(page.get_by_text("Picture copied")).to_be_visible()
        return clipboard_png(page)

    w, h = copy()                                            # as on screen: the stage (with the cuts' room)
    stage = box(".explore-stage")
    assert abs(w - stage["width"]) <= 2 and abs(h - stage["height"]) <= 2
    explore(page).get_by_role("button", name="Data ▾").first.click()
    page.get_by_role("menuitem", name="○ Picture of the plot only").click()
    page.evaluate("navigator.clipboard.writeText('')")
    w, h = copy()                                            # the plot alone
    plot = box(".explore-picture")
    assert abs(w - plot["width"]) <= 2 and abs(h - plot["height"]) <= 2


def test_figure_copy_picture(sweep, viewer, context, new_page):
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=viewer.url.split("/?")[0])
    page = new_page("Figure")
    open_file(page, "sweep.lbd")
    page.get_by_role("button", name="Copy picture").click()
    expect(page.get_by_text("Picture copied")).to_be_visible()
    w, h = clipboard_png(page)
    assert w > 300 and h > 200


def test_copy_picture_of_all_panels(viewer, context, new_page):
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=viewer.url.split("/?")[0])
    d = lbd.Dataset(title="Two")
    d.add_axis("t", np.linspace(0, 1, 50), unit="s")
    d.add_value("I", np.sin(np.linspace(0, 6, 50)), axes="t", unit="V")
    d.add_value("Q", np.cos(np.linspace(0, 6, 50)), axes="t", unit="A")     # another unit: a panel each
    d.save(viewer.data / "two.lbd")
    page = new_page("Explore")
    frames(page, lambda: row(page, "two.lbd").dblclick())
    stages = explore(page).locator(".explore-stage")
    expect(stages).to_have_count(2)
    boxes = [stages.nth(k).bounding_box() for k in range(2)]
    explore(page).get_by_role("button", name="Data ▾").first.click()
    page.get_by_role("menuitem", name="○ Picture of all panels").click()
    explore(page).get_by_role("button", name="Data ▾").first.click()
    page.get_by_role("menuitem", name="Copy picture of all panels").click()
    expect(page.get_by_text("Picture copied")).to_be_visible()
    w, h = clipboard_png(page)
    left = min(b["x"] for b in boxes)
    right = max(b["x"] + b["width"] for b in boxes)
    assert abs(w - (right - left)) <= 2                    # both panels, as laid out
