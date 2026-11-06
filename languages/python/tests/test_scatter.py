"""The plot type Scatter: the model, the drawing, many points."""

import sys
from pathlib import Path

import matplotlib.colors as mcolors
import numpy as np
import pytest

import lbd
from lbd.plot import render as rnd
from lbd.plot import scatter as sc
from lbd.plot.style import Style

sys.path.insert(0, str(Path(__file__).parents[3] / "viewer" / "tests"))
import mock_values  # noqa: E402


def shots():
    return mock_values.single_shot_iq(True)


def model_of(d, **spec):
    resolved = rnd.resolve_spec(d, {"kind": "scatter", **spec}, warn_unused=False)
    return sc.prepare_scatter(d, resolved, Style()), resolved


def test_figures_of_saved_scatter_views_are_unchanged():
    """A view without `all`: every point, but for axes fixed in `index`."""
    d = shots()
    m, spec = model_of(d, values="Q", x="I", color="state")
    assert spec["index"] == {} and "all" not in spec
    assert m.series[0][0].size == d.values["I"].data.size
    assert len(m.groups) == 2 and m.groups[1][1] == "Prepared state = excited"
    fixed, _ = model_of(d, values="Q", x="I", index={"state": 1})
    assert fixed.series[0][0].size == d.values["I"].data[:, 1].size


def test_every_source():
    d = shots()
    q = d.values["Q"].data
    m, _ = model_of(d, values="Q", x="shot", index={"state": 0, "readout_power": 0})
    assert np.allclose(m.series[0][0], np.arange(200.0))
    assert np.allclose(m.series[0][1] / m.yf, q[0, 0])
    assert "Shot" in m.x_label and "Q" in m.y_label
    m, _ = model_of(d, values="Q", x="I")
    assert np.allclose(m.series[0][0] / m.xf, d.values["I"].data.ravel())
    assert "I" in m.x_label and m.equal is False
    m, _ = model_of(d, values="IQ", complex="iq")
    z = d.values["IQ"].data.ravel()
    assert np.allclose(m.series[0][0] / m.xf, z.real) and np.allclose(m.series[0][1] / m.yf, z.imag)
    assert m.xf == m.yf and "Re I/Q" in m.x_label and "Im I/Q" in m.y_label and m.equal is True


def test_all_and_a_slider():
    d = shots()
    m, spec = model_of(d, values="IQ", complex="iq", all=["shot", "state"], index={"readout_power": 1})
    assert m.series[0][0].size == 2 * 200 and spec["index"] == {"readout_power": 1}
    assert [s["axis"] for s in spec["slices"]] == ["readout_power"]
    assert np.array_equal(np.unique(m.index[0]["readout_power"]), [1])


def test_with_all_every_other_axis_is_a_slider():
    _, spec = model_of(shots(), values="IQ", complex="iq", color="state", all=["shot"])
    assert list(spec["index"]) == ["readout_power"] and spec["all"] == ["shot"]
    _, spec = model_of(shots(), values="Q", x="shot", all=[])
    assert sorted(spec["index"]) == ["readout_power", "state"]


def test_stored_indices_point_back():
    d = shots()
    m, _ = model_of(d, values="Q", x="I", all=["shot", "state"], index={"readout_power": 1})
    ix = m.index[0]
    assert np.allclose(d.values["Q"].data[ix["readout_power"], ix["state"], ix["shot"]], m.series[0][1] / m.yf)


def test_colour_none_axis_value():
    d = shots()
    m, _ = model_of(d, values="IQ", complex="iq", color="none")
    assert m.groups is None and m.cvals is None
    m, _ = model_of(d, values="IQ", complex="iq", color="state")
    assert [g[1] for g in m.groups] == ["Prepared state = ground", "Prepared state = excited"]
    assert m.groups[0][0].sum() == d.values["IQ"].data[:, 0].size
    m, _ = model_of(d, values="Q", x="I", color="shot")           # a long axis: a colour bar
    assert m.groups is None and m.cvals.size == m.series[0][0].size and "Shot" in m.c_label
    m, _ = model_of(d, values="Q", x="shot", color="I")           # a value: a colour bar
    assert m.groups is None and "I" in m.c_label


def test_equal_axes_is_a_choice():
    d = shots()
    assert model_of(d, values="IQ", complex="iq", options={"equal": False})[0].equal is False
    assert model_of(d, values="Q", x="I", options={"equal": True})[0].equal is True


def test_a_group_has_its_real_coordinates(tmp_path):
    d = mock_values.variable_sweep(True)
    m, spec = model_of(d, values="S21", complex="abs", x="freq", all=[])
    flat = rnd.flat(d)
    assert spec["index"] == {} and m.series[0][0].size == flat.values["S21"].shape[0]
    assert "point number" not in m.x_label and "Hz" in m.x_label
    assert m.series[0][0].max() != flat.values["S21"].shape[0] - 1


# -- many points -----------------------------------------------------------------------------------

COLOURS = Style().figure.axes.colors


def cloud(n=300_000, lone=True):
    rng = np.random.default_rng(1)
    d = lbd.Dataset()
    d.add_axis("t", np.arange(float(n)))
    x, y = rng.normal(size=n), rng.normal(size=n)
    if lone:
        x[0], y[0] = 40.0, 40.0
    d.add_value("x", x, axes="t")
    d.add_value("y", y, axes="t")
    return d


def counted(model, w=200, h=100, xlim=(-50, 50), ylim=(-50, 50), scales=("linear", "linear")):
    return sc.density(model, xlim, ylim, w, h, scales, COLOURS)


def test_above_the_limit_every_point_is_counted():
    d = cloud()
    m, _ = model_of(d, values="y", x="x")
    found = counted(m)
    assert found.total.sum() == 300_000 and found.total.shape == (100, 200)
    assert found.note == "300,000 points: each pixel shows how many are there"
    assert counted(m, xlim=(0, 50)).total.sum() == ((m.series[0][0] >= 0) & (m.series[0][0] <= 50)).sum()


def test_one_lonely_point_shows():
    m, _ = model_of(cloud(), values="y", x="x")
    found = counted(m)
    picture = sc.density_image(m, found)
    alone = picture[int((40 + 50) / 100 * 100), int((40 + 50) / 100 * 200)]
    assert found.total[90, 180] == 1 and alone[3] >= 0.3
    assert picture[..., 3].max() == 1.0
    assert picture[0, 0, 3] == 0                       # nothing there: nothing drawn


def test_groups_keep_their_colour():
    d = lbd.Dataset()
    d.add_axis("g", [0.0, 1.0], elements=["a", "b"])
    d.add_axis("t", np.arange(1000.0))
    x = np.r_[np.full(1000, -1.0), np.full(1000, 1.0)].reshape(2, 1000)
    d.add_value("x", x, axes=["g", "t"])
    d.add_value("y", np.zeros((2, 1000)), axes=["g", "t"])
    m, _ = model_of(d, values="y", x="x", color="g")
    found = counted(m, 4, 1, (-2, 2), (-1, 1))
    picture = sc.density_image(m, found)
    assert len(found.counts) == 2 and found.total.sum() == 2000
    assert np.allclose(picture[0, 1, :3], mcolors.to_rgb(COLOURS[0]))
    assert np.allclose(picture[0, 3, :3], mcolors.to_rgb(COLOURS[1]))


def test_a_colour_value_is_the_mean_in_the_pixel():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(4.0))
    d.add_value("x", np.array([0.1, 0.2, 0.3, 3.0]), axes="t")
    d.add_value("y", np.zeros(4), axes="t")
    d.add_value("c", np.array([1.0, 2.0, 3.0, 10.0]), axes="t")
    m, _ = model_of(d, values="y", x="x", color="c")
    found = counted(m, 2, 1, (0, 4), (-1, 1))
    assert found.sums[0].tolist() == [6.0, 10.0] and found.total[0].tolist() == [3, 1]


def test_log_axes_bins():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("x", np.array([1.0, 10.0, 100.0]), axes="t")
    d.add_value("y", np.array([1.0, 1.0, 1.0]), axes="t")
    m, _ = model_of(d, values="y", x="x")
    found = counted(m, 3, 1, (1, 1000), (0, 2), ("log", "linear"))
    assert found.total[0].tolist() == [1, 1, 1]


def test_below_the_limit_are_markers():
    d = cloud(1000, lone=False)
    m, spec = model_of(d, values="y", x="x")
    fig = rnd.new_figure(Style())
    ax = fig.add_subplot()
    assert len(sc.draw_scatter(fig, ax, m, d, spec, Style())) == 1 and not ax.images


def test_the_density_picture_draws_with_its_colour_bar():
    d = cloud(1000, lone=False)
    m, spec = model_of(d, values="y", x="x")
    found = counted(m)
    fig = rnd.new_figure(Style())
    ax = fig.add_subplot()
    image, bar = sc.draw_scatter(fig, ax, m, d, spec, Style(), image=sc.density_image(m, found), top=int(found.total.max()))
    assert image in ax.images and bar is not None
    assert fig.axes[1].get_ylabel() == "Points per pixel"
