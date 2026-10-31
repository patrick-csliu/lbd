"""Files being written in the Library, in a real browser (plan 6b): "measuring…" while a
measurement writes, and a stopped one recovered into an .lbd file."""

import lbd
import numpy as np
import pytest
from playwright.sync_api import Page, expect


def row(page: Page, name: str):
    """The list row of a file in the data folder (its tooltip is its path)."""
    return page.locator(f'.library-row[title$="{name}"]')


def test_measuring_and_a_stopped_file_recovered(viewer, new_page):
    w = lbd.Writer(viewer.data / "live.lbd", title="live")
    w.add_axis("x", np.arange(5.0))
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    w.flush()
    with pytest.warns(lbd.LBDWarning, match="stopped with RuntimeError"):
        with pytest.raises(RuntimeError):
            with lbd.Writer(viewer.data / "stopped.lbd", title="stopped") as s:
                s.add_axis("x", np.arange(3.0))
                s.add_value("y", axes="x")
                s.write(x=0, y=2.0)
                raise RuntimeError("instrument did not answer")
    try:
        page = new_page("Library")
        expect(row(page, "live.lbd.writing")).to_contain_text("measuring…", timeout=20_000)
        row(page, "live.lbd.writing").click()
        expect(page.locator(".writing-box")).to_contain_text("Measuring…")
        expect(page.locator(".library-detail .preview")).to_contain_text("No preview while it is being written")

        expect(row(page, "stopped.lbd.writing")).to_contain_text("stopped before finishing")
        row(page, "stopped.lbd.writing").click()
        page.locator(".writing-box").get_by_role("button", name="Recover").click()
        expect(row(page, "stopped.lbd")).to_be_visible(timeout=20_000)
        expect(row(page, "stopped.lbd.writing")).to_have_count(0)
        assert lbd.load(viewer.data / "stopped.lbd").values["y"].data[0] == 2.0
    finally:
        w.close(stopped=True)
