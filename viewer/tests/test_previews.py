"""The Library's previews (plan 8c): what an automatic preview shows, and how it is drawn."""

import io

import numpy as np
import pytest
from PIL import Image

import lbd
from lbd_viewer import previews
from lbd_viewer.previews import PreviewError, automatic_panels, draw, draw_automatic, grid_of


@pytest.fixture()
def style(cfg):
    return cfg.resolve()


def picture(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    assert im.format == "WEBP"
    return im


def test_the_grid_is_explores():
    assert [grid_of(n) for n in range(1, 7)] == [(1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (2, 3)]


def test_automatic_panels_are_explores_first_open(values_files):
    by_name = {p.name: p for p in values_files}
    panels, grid = automatic_panels(lbd.info(by_name["9 many values.lbd"]))
    assert len(panels) == previews.FIRST_PANELS and grid == (2, 2)
    names = [n for n, v in lbd.info(by_name["9 many values.lbd"]).values.items() if v.shape]
    assert [p["spec"]["values"] for p in panels] == [[n] for n in names[:4]]
    panels, grid = automatic_panels(lbd.info(by_name["10 one value.lbd"]))
    assert len(panels) == 1 and grid == (1, 1)
    # single numbers have no panel
    panels, _ = automatic_panels(lbd.info(by_name["8 mixed axes.lbd"]))
    singles = [n for n, v in lbd.info(by_name["8 mixed axes.lbd"]).values.items() if not v.shape]
    assert singles and not any(p["spec"]["values"][0] in singles for p in panels)


def test_every_mock_file_draws_a_webp_of_the_preview_size(values_files, style):
    w, h = previews.PREVIEW_SIZE
    for p in values_files:
        im = picture(draw_automatic(p, style))
        assert im.size == (round(w * previews.PREVIEW_DPR), round(h * previews.PREVIEW_DPR)), p.name


def test_a_curve_preview_is_small(values_files, style):
    rabi = next(p for p in values_files if p.name == "6 rabi.lbd")
    assert len(draw_automatic(rabi, style)) < 60_000


def test_the_saved_figure_view_has_no_part_in_an_automatic_preview(data_dir, style):
    x = np.linspace(0, 1, 50)
    for name, plot in (("plain.lbd", None), ("with view.lbd", {"kind": "curve", "values": ["b"], "complex": "phase"})):
        d = lbd.Dataset(title="t")
        d.add_axis("x", x)
        d.add_value("a", np.sin(x * 5), axes=["x"])
        d.add_value("b", np.exp(1j * x), axes=["x"])
        d.plot = plot
        d.save(data_dir / name)
    a = np.asarray(picture(draw_automatic(data_dir / "plain.lbd", style)))
    b = np.asarray(picture(draw_automatic(data_dir / "with view.lbd", style)))
    assert np.array_equal(a, b)


def test_chosen_panels_with_zoom_and_settings_draw(values_files, style):
    rabi = next(p for p in values_files if p.name == "6 rabi.lbd")
    panels = [{"spec": {"values": ["population"]}, "settings": {"yscale": "linear"},
               "view": {"xlim": [0.1, 0.3], "ylim": [0, 1]}}]
    full = draw(rabi, [{"spec": {"values": ["population"]}, "settings": {}, "view": None}], (1, 1), style, True)
    zoomed = draw(rabi, panels, (1, 1), style, saved_view=True)
    assert np.asarray(picture(zoomed)).shape == np.asarray(picture(full)).shape
    assert not np.array_equal(np.asarray(picture(zoomed)), np.asarray(picture(full)))


def test_a_file_of_single_numbers_says_why_it_has_no_preview(data_dir, style):
    d = lbd.Dataset(title="fit")
    d.add_value("f0", 7.0)
    d.save(data_dir / "numbers.lbd")
    with pytest.raises(PreviewError, match="only single numbers"):
        draw_automatic(data_dir / "numbers.lbd", style)


def test_an_unreadable_file_says_why(data_dir, style):
    (data_dir / "broken.lbd").write_bytes(b"not an hdf5 file")
    with pytest.raises(PreviewError) as e:
        draw_automatic(data_dir / "broken.lbd", style)
    assert str(e.value)
