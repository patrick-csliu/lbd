"""The plot type Scatter: the model, the drawing, many points."""

import sys
from pathlib import Path

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
