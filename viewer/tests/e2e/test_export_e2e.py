"""Getting data out in a real browser (plan 5): Save as CSV from a panel's Data menu (choices,
the size line) gives a file numpy reads back; Copy picture puts a PNG on the clipboard."""

import re

import lbd
import numpy as np
import pytest
from pageui import open_file, row
from playwright.sync_api import Page, expect
from lbd_viewer import server
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
    explore(page).get_by_role("button", name="Data", exact=True).first.click()
    page.get_by_role("menuitem", name="Save as CSV…").click()
    dialog = page.get_by_role("dialog", name="Save as CSV")
    expect(dialog).to_be_visible()
    return dialog


def test_save_as_csv_from_the_data_menu(sweep, viewer, new_page, monkeypatch, tmp_path):
    """Plan 12: the choices, Next, what will be written with its size, Save…: the system's dialog
    says where; cancelled, nothing is written."""
    asked = []

    def dialog_says(folder, name, fmt, title, fallback):
        asked.append((str(folder), name, fmt, title))
        return answer[0]

    answer = [None]
    monkeypatch.setattr(server, "native_save_dialog", dialog_says)
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    dialog = open_dialog(page)
    expect(dialog.get_by_label("as shown", exact=True).locator("xpath=..")).to_have_attribute("title", re.compile("complex mode"))
    dialog.get_by_label("table (matrix)").check()
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_role("status").first).to_contain_text("4 rows × 52 columns")
    dialog.get_by_role("button", name="Back").click()
    dialog.get_by_label("one data point per row").check()
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_role("status").first).to_contain_text("153 rows × 3 columns")
    dialog.get_by_role("button", name="Save…").click()                 # cancelled: the dialog stays
    page.wait_for_timeout(500)
    assert asked == [(str(viewer.data), "sweep_T.csv", "csv", "Save as CSV")]
    expect(dialog).to_be_visible()
    assert not list(viewer.data.glob("*.csv"))
    answer[0] = str(tmp_path / "chosen.csv")                           # any folder: chosen in the dialog
    dialog.get_by_role("button", name="Save…").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_text("Saved ")).to_be_visible()
    a = np.loadtxt(tmp_path / "chosen.csv", delimiter=",", encoding="utf-8")
    assert a.shape == (153, 3)


def test_without_a_save_dialog_the_name_is_typed(sweep, viewer, new_page):
    """Where the system has no dialog (501): the file goes next to the data, named here."""
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    dialog = open_dialog(page)
    dialog.get_by_label("table (matrix)").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Save…").click()
    expect(dialog.get_by_label("File name")).to_have_value("sweep_T.csv")
    dialog.get_by_label("File name").fill("sweep table.csv")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_text("Saved ")).to_be_visible()
    a = np.loadtxt(viewer.data / "sweep table.csv", delimiter=",", encoding="utf-8")
    np.testing.assert_array_equal(a[1:, 1:], sweep.values["T"].data)

    dialog = open_dialog(page)                               # the choice is remembered
    expect(dialog.get_by_label("table (matrix)")).to_be_checked()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Save…").click()
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
        explore(page).get_by_role("button", name="Data", exact=True).first.click()
        page.get_by_role("menuitem", name=entry).click()
        expect(page.get_by_text("Picture copied")).to_be_visible()
        return clipboard_png(page)

    w, h = copy()                                            # as on screen: the stage (with the cuts' room)
    stage = box(".explore-stage")
    assert abs(w - stage["width"]) <= 2 and abs(h - stage["height"]) <= 2
    explore(page).get_by_role("button", name="Data", exact=True).first.click()
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
    explore(page).get_by_role("button", name="Data", exact=True).first.click()
    page.get_by_role("menuitem", name="○ Picture of all panels").click()
    explore(page).get_by_role("button", name="Data", exact=True).first.click()
    page.get_by_role("menuitem", name="Copy picture of all panels").click()
    expect(page.get_by_text("Picture copied")).to_be_visible()
    w, h = clipboard_png(page)
    left = min(b["x"] for b in boxes)
    right = max(b["x"] + b["width"] for b in boxes)
    assert abs(w - (right - left)) <= 2                    # both panels, as laid out


def test_save_picture_uses_the_save_dialog(sweep, viewer, new_page, monkeypatch, tmp_path):
    """Plan 12: the picture goes where the system's dialog says (not to the browser's Downloads)."""
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(tmp_path / "plot.png"))
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).get_by_role("button", name="Data", exact=True).first.click()
    page.get_by_role("menuitem", name="Save picture as PNG…").click()
    expect(page.get_by_text("Saved ")).to_be_visible()
    assert (tmp_path / "plot.png").read_bytes()[:4] == b"\x89PNG"


def test_the_whole_file_as_csv_choosing_a_group(viewer, new_page, monkeypatch, tmp_path):
    """Plan 12: from the panel's dialog, How much → the whole file: the groups of values, one chosen."""
    d = lbd.Dataset(title="Mixed")
    d.add_axis("A", [1.0, 2.0, 3.0])
    d.add_axis("B", [10.0, 20.0])
    d.add_value("u", [0.1, 0.2, 0.3], axes="A")
    d.add_value("v", np.arange(6.0).reshape(3, 2), axes=["A", "B"])
    d.save(viewer.data / "mixed.lbd")
    monkeypatch.setattr(server, "native_save_dialog", lambda folder, name, fmt, title, fallback: str(tmp_path / name))
    page = new_page("Explore")
    frames(page, lambda: row(page, "mixed.lbd").dblclick())
    dialog = open_dialog(page)
    dialog.get_by_label("the whole file").check()
    dialog.get_by_label("v (A, B): 6 rows").check()
    expect(dialog.get_by_label("v (A, B): 6 rows")).to_be_checked()
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_role("status").first).to_contain_text("6 rows × 3 columns")
    dialog.get_by_role("button", name="Save…").click()
    expect(dialog).to_be_hidden()
    a = np.loadtxt(tmp_path / "mixed - v.csv", delimiter=",", encoding="utf-8")
    np.testing.assert_array_equal(a[:, 2], np.arange(6.0))


def test_the_file_menu_saves_the_whole_file(sweep, viewer, new_page, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(tmp_path / "all.csv"))
    page = new_page("Explore")
    frames(page, lambda: row(page, "sweep.lbd").dblclick())
    explore(page).get_by_role("button", name="More", exact=True).first.click()
    page.get_by_role("menuitem", name="Save the whole file as CSV…").click()
    dialog = page.get_by_role("dialog", name="Save the whole file as CSV")
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Save…").click()
    expect(dialog).to_be_hidden()
    assert (tmp_path / "all.csv").read_text(encoding="utf-8").startswith("# ")
