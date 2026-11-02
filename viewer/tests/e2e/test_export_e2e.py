"""Getting data out in a real browser (plan 5): Save as CSV from a panel's Data menu (choices,
the size line, the warning above 100 MB) gives a file numpy reads back."""

import lbd
import numpy as np
import pytest
from pageui import row
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
