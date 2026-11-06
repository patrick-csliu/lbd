"""The plot type Scatter in Explore: the picture, the cursor, large files, the histograms beside it."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values
from lbd.plot import scatter as sc
from lbd_viewer.explore import ExploreSession

IQ = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "state", "all": ["shot"], "index": {"readout_power": 1}}


@pytest.fixture()
def iq(tmp_path):
    path = tmp_path / "iq.lbd"
    mock_values.single_shot_iq(True).save(path)
    return path


@pytest.fixture()
def many(tmp_path, monkeypatch):
    """Points above the limit (lowered to 500), in two groups."""
    monkeypatch.setattr(sc, "DENSITY_ABOVE", 500)
    rng = np.random.default_rng(3)
    d = lbd.Dataset()
    d.add_axis("g", [0.0, 1.0], elements=["a", "b"])
    d.add_axis("t", np.arange(1000.0))
    d.add_value("x", rng.normal(size=(2, 1000)) + np.array([[-5.0], [5.0]]), axes=["g", "t"], unit="V")
    d.add_value("y", rng.normal(size=(2, 1000)), axes=["g", "t"], unit="V")
    d.save(tmp_path / "many.lbd")
    return tmp_path / "many.lbd"


MANY = {"kind": "scatter", "values": ["y"], "x": "x", "color": "g", "all": ["t"]}


def session(path, spec, version="v1", **kw):
    return ExploreSession(path, version, spec, lp.load_style(), 600, 400, 1.0, **kw)


def frame(s, xlim=None, ylim=None, settings=None, **kw):
    s.apply(settings or {})
    return s.render(xlim, ylim, **kw)[1]


def test_opens_and_zooms(iq):
    s = session(iq, IQ)
    assert s.kind == "scatter"
    meta = frame(s)
    assert meta["note"] == "every point shown" and not meta["reduced"]
    (x0, x1), (y0, y1) = s.full
    mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
    zoomed = frame(s, (x0, mid_x), (y0, mid_y))
    assert zoomed["xlim"][0] <= x0 + 1e-9 and zoomed["xlim"][1] >= mid_x - 1e-9 and zoomed["ylim"][1] >= mid_y - 1e-9
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < frame(s)["xlim"][1] - frame(s)["xlim"][0]


def test_limits_are_the_data_with_a_margin(tmp_path):
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("x", np.array([0.0, 5.0, 10.0]), axes="t")
    d.add_value("y", np.array([1.0, 2.0, 3.0]), axes="t")
    d.save(tmp_path / "a.lbd")
    s = session(tmp_path / "a.lbd", {"kind": "scatter", "values": ["y"], "x": "x"})
    assert s.full[0] == pytest.approx((-0.5, 10.5)) and s.full[1] == pytest.approx((0.9, 3.1))


def test_equal_axes_report_the_limits_really_shown(iq):
    s = session(iq, IQ)
    meta = frame(s)
    assert meta["equal"]
    ax = s.ax
    assert meta["xlim"] == pytest.approx(ax.get_xlim()) and meta["ylim"] == pytest.approx(ax.get_ylim())
    box = ax.get_window_extent()
    per_x = box.width / (meta["xlim"][1] - meta["xlim"][0])
    per_y = box.height / (meta["ylim"][1] - meta["ylim"][0])
    assert per_x == pytest.approx(per_y, rel=1e-3)


def test_above_the_limit_the_points_are_counted_per_pixel(many):
    s = session(many, MANY)
    meta = frame(s)
    assert meta["reduced"] and meta["note"] == "2,000 points: each pixel shows how many are there"
    w, h = meta["plot"][2:]
    assert s.view.image.get_array().shape[:2] == (h, w)
    assert [t.get_text() for t in s.ax.get_legend().get_texts()] == ["Prepared" if False else "g = a", "g = b"]


def test_zooming_counts_again_and_stays_sharp(many):
    s = session(many, MANY)
    frame(s)
    full = np.asarray(s.view.image.get_array()).copy()
    meta = frame(s, (-7.0, -3.0), (-1.0, 1.0))
    now = np.asarray(s.view.image.get_array())
    assert now.shape == full.shape and not np.array_equal(now, full)
    assert int(meta["note"].split()[0].replace(",", "")) < 2000


def test_a_draft_is_counted_at_half_size(many):
    s = session(many, MANY)
    meta = frame(s, draft=True)
    w, h = meta["plot"][2:]
    assert s.view.image.get_array().shape[:2] == (h // 2, w // 2)


def test_a_colour_bar_counts_points_without_colours(many):
    s = session(many, {**MANY, "color": "none", "all": ["t", "g"]})
    frame(s)
    assert s.fig.axes[1].get_ylabel() == "Points per pixel"
    assert s.view.bar.get_clim()[1] >= 2


def test_a_live_file_grows(tmp_path):
    path = tmp_path / "g.lbd"
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("x", np.arange(3.0), axes="t")
    d.add_value("y", np.arange(3.0), axes="t")
    d.save(path)
    s = session(path, {"kind": "scatter", "values": ["y"], "x": "x"})
    frame(s)
    assert s.model.series[0][0].size == 3
    d = lbd.Dataset()
    d.add_axis("t", np.arange(5.0))
    d.add_value("x", np.arange(5.0), axes="t")
    d.add_value("y", np.arange(5.0), axes="t")
    d.save(path)
    s = session(path, {"kind": "scatter", "values": ["y"], "x": "x"}, version="v2")      # (the page reopens it)
    frame(s)
    assert s.model.series[0][0].size == 5


def test_log_scales_say_what_they_hide(iq):
    s = session(iq, {"kind": "scatter", "values": ["Q"], "x": "I", "all": ["shot", "state", "readout_power"]})
    meta = frame(s, settings={"xscale": "log"})
    assert meta["xscale"] == "log" and "aren't shown on the log horizontal axis" in meta["hidden"][0]


def test_a_preview_has_only_the_data(iq):
    s = session(iq, {"kind": "scatter", "values": ["Q"], "x": "I", "color": "shot"}, bare=True)
    frame(s)
    assert len(s.fig.axes) == 1
