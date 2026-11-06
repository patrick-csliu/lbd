"""The plot type Histogram: counting, the model and the drawing."""

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

import lbd
from lbd.plot import histogram as hist
from lbd.plot import render as rnd
from lbd.plot.histogram import auto_bins, count_bins
from lbd.plot.style import Style

sys.path.insert(0, str(Path(__file__).parents[3] / "viewer" / "tests"))
import mock_values  # noqa: E402


def test_count_bins_is_numpys_histogram():
    x = np.random.default_rng(1).normal(size=1000)
    edges, counts = count_bins(x, 17)
    want, want_edges = np.histogram(x, 17)
    assert np.array_equal(edges, want_edges) and np.array_equal(counts, want)
    assert counts.dtype == np.int64
    _, top = count_bins([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    assert top.tolist() == [1, 2]                      # the last bin includes its right edge


def test_count_bins_ignores_nan_and_infinity():
    _, counts = count_bins([1.0, 2.0, np.nan, np.inf, -np.inf], 2)
    assert counts.sum() == 2


def test_numbers_outside_a_range_are_not_counted():
    edges, counts = count_bins([0.0, 1.0, 5.0], 2, (0.0, 2.0))
    assert edges.tolist() == [0.0, 1.0, 2.0] and counts.tolist() == [1, 1]


def test_blocks_counted_with_the_same_edges_add_up():
    x = np.random.default_rng(2).normal(size=1000)
    edges, whole = count_bins(x, 30)
    parts = sum(count_bins(block, edges)[1] for block in np.array_split(x, 7))
    assert np.array_equal(parts, whole)


def test_one_number_widens_the_range():
    edges, counts = count_bins([3.0, 3.0], 2)
    assert edges[0] == 2.5 and edges[-1] == 3.5 and counts.sum() == 2


def test_numbers_differing_by_rounding_only_count_as_one():
    edges, counts = count_bins([1.0, 1.0 + 2e-16, 1.0 + 4e-16], 14)
    assert edges[0] == pytest.approx(0.5) and counts.sum() == 3


def test_no_values_says_so():
    with pytest.raises(ValueError, match="no values to count"):
        count_bins([np.nan], 5)
    edges, counts = count_bins([np.nan], 5, (0.0, 1.0))        # with a range there is something to show
    assert edges.size == 6 and counts.sum() == 0


def test_complex_is_refused():
    with pytest.raises(ValueError, match="complex"):
        count_bins(np.array([1 + 1j]), 5)


@pytest.mark.parametrize("bins", [1, 0, -3, 10_001, 2.5, True])
def test_bins_outside_the_limits_say_so(bins):
    with pytest.raises(ValueError, match="2 to 10000"):
        count_bins([1.0, 2.0], bins)


def test_auto_bins_grows_with_the_data_and_stays_in_limits():
    rng = np.random.default_rng(3)
    few, many = auto_bins(rng.normal(size=100)), auto_bins(rng.normal(size=100_000))
    assert 2 <= few < many <= 200
    assert auto_bins(rng.normal(size=100_000), most=20) == 20
    assert auto_bins([1.0]) == 2 and auto_bins([]) == 2


def test_auto_bins_from_a_sample():
    x = np.random.default_rng(4).normal(size=1_000_000)
    sample = x[::100]
    assert auto_bins(sample) < auto_bins(sample, count=x.size)
    wide = auto_bins(sample, count=x.size, span=(-100.0, 100.0), most=10_000)
    assert wide > auto_bins(sample, count=x.size, most=10_000)
    whole = auto_bins(x, most=10_000)
    assert abs(auto_bins(sample, count=x.size, span=(x.min(), x.max()), most=10_000) - whole) <= 0.05 * whole


def test_auto_bins_with_no_spread():
    assert auto_bins(np.ones(1024)) == 11              # Sturges: log2(n) + 1
    x = np.r_[np.zeros(1000), 1.0]                     # the middle half is one number
    assert auto_bins(x) == int(np.ceil(np.log2(x.size) + 1))


# -- model and drawing ---------------------------------------------------------------------------

def mock(name, tmp_path, small=True):
    mock_values.MAKERS[name](small).save(tmp_path / name)
    return tmp_path / name


def model_of(d, **spec):
    resolved = rnd.resolve_spec(d, {"kind": "histogram", **spec}, warn_unused=False)
    return hist.prepare(d, resolved, Style()), resolved


def shots():
    return mock_values.single_shot_iq(True)


def test_prepare_counts_one_value():
    d = mock_values.rabi(True)
    m, _ = model_of(d, values="I")
    assert len(m.series) == 1 and m.series[0].counts.sum() == d.values["I"].data.size
    assert m.style == "bars" and m.y_label == "Count" and m.x_unit == "mV"
    assert m.edges[0] == pytest.approx(d.values["I"].data.min() * 1e3)


def test_all_and_slider_choose_the_numbers():
    d = shots()
    m, spec = model_of(d, values="I", color="none", all=["shot"], index={"readout_power": 1, "state": 1})
    assert m.series[0].counts.sum() == 200 and spec["index"] == {"readout_power": 1, "state": 1}
    data = d.values["I"].data[1, 1] * m.xf
    assert m.edges[0] == pytest.approx(data.min()) and m.edges[-1] == pytest.approx(data.max())
    m, spec = model_of(d, values="I", color="none", all=["shot", "state", "readout_power"])
    assert m.series[0].counts.sum() == d.values["I"].data.size and spec["index"] == {}


def test_the_starting_choice():
    _, spec = model_of(shots(), values="I")
    assert spec["color"] == "state" and spec["all"] == ["shot"] and list(spec["index"]) == ["readout_power"]


def test_colour_by_gives_one_series_per_step():
    m, _ = model_of(shots(), values="I", color="state", all=["shot"], index={"readout_power": 1})
    assert [s.label for s in m.series] == ["ground", "excited"]
    assert [int(s.counts.sum()) for s in m.series] == [200, 200]
    assert m.style == "outline" and m.series[0].colour != m.series[1].colour


def test_colours_refuse_too_many_steps_and_a_missing_axis():
    with pytest.raises(rnd.RenderError, match="too many for colours"):
        model_of(shots(), values="I", color="shot")
    d = mock_values.mixed_axes(True)
    a, b = list(d.values)[:2]
    if d.values[a].axes != d.values[b].axes:
        with pytest.raises(rnd.RenderError, match="no such axis"):
            model_of(d, values=[a, b], color=d.values[a].axes[0])


def test_several_values_share_edges():
    d = shots()
    m, _ = model_of(d, values=["I", "Q"], color="none", all=["shot", "state", "readout_power"])
    assert [s.label for s in m.series] == ["I", "Q"] and m.style == "outline"
    both = np.concatenate([d.values["I"].data.ravel(), d.values["Q"].data.ravel()]) * m.xf
    assert m.edges[0] == pytest.approx(both.min()) and m.edges[-1] == pytest.approx(both.max())
    assert all(s.counts.sum() == d.values["I"].data.size for s in m.series)
    m, _ = model_of(d, values=["I", "Q"], color="state", all=["shot"])
    assert [s.label for s in m.series] == ["I, ground", "I, excited", "Q, ground", "Q, excited"]


def test_different_units_are_refused():
    with pytest.raises(rnd.RenderError, match="'I', 'fidelity' have different units"):
        model_of(shots(), values=["I", "fidelity"], color="none")


def test_complex_mode_is_applied_first():
    d = shots()
    z = d.values["IQ"].data[0, 0]
    for mode, numbers in (("abs", np.abs(z)), ("phase", np.angle(z))):
        m, _ = model_of(d, values="IQ", complex=mode, color="none", all=["shot"], index={"readout_power": 0, "state": 0})
        assert m.edges[0] / m.xf == pytest.approx(numbers.min())
        assert m.edges[-1] / m.xf == pytest.approx(numbers.max())
    assert "arg" in m.x_label
    with pytest.raises(rnd.RenderError, match="scatter"):
        model_of(d, values="IQ", complex="iq")


def test_an_unwrapped_phase_runs_along_the_last_axis():
    d = lbd.Dataset()
    d.add_axis("a", [0.0, 1.0])
    d.add_axis("b", np.arange(50.0))
    d.add_value("z", np.exp(1j * np.arange(100.0).reshape(2, 50) * 0.3), axes=["a", "b"])
    m, _ = model_of(d, values="z", complex="phase_unwrap", color="none", all=["a", "b"])
    assert m.edges[-1] / m.xf > 2 * np.pi                       # it went past one turn
    parts = list(hist.iter_parts(rnd.flat(d).values["z"], {"complex": "phase_unwrap", "all": ["a", "b"]}, block=1))
    assert len(parts) == 2 and all(p[1].size == 50 for p in parts)


def test_integer_values_get_a_bin_each():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(6.0))
    d.add_value("n", np.array([3, 3, 4, 7, 7, 7]), axes="t")
    m, _ = model_of(d, values="n")
    assert m.edges.tolist() == [2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
    assert m.series[0].counts.tolist() == [2, 1, 0, 0, 3]
    m, _ = model_of(d, values="n", options={"bins": 2})
    assert m.edges.size == 3
    d.values["n"].data = np.array([0, 1, 2, 3, 4, 1000])
    m, _ = model_of(d, values="n")
    assert m.edges[0] == 0                                     # too wide for a bin each


def test_points_not_measured_are_left_out():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(4.0))
    d.add_value("n", np.array([5, 5, 0, 0]), axes="t")
    d.values["n"].measured = np.array([True, True, False, False])
    m, _ = model_of(d, values="n")
    assert m.series[0].counts.sum() == 2 and m.left_out == 0 and m.edges[0] == 4.5


def test_not_finite_numbers_are_left_out_with_a_note():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(5.0))
    d.add_value("x", np.array([1.0, 2.0, np.nan, np.inf, 3.0]), axes="t")
    m, spec = model_of(d, values="x")
    assert m.series[0].counts.sum() == 3 and m.left_out == 2
    assert hist.notes_of(m) == ["2 numbers aren't finite: not counted"]
    fig = rnd.new_figure(Style())
    with pytest.warns(rnd.RenderWarning, match="2 numbers aren't finite"):
        hist.draw(fig, fig.add_subplot(), m, d, spec, Style())


def test_no_numbers_at_all_draw_empty_axes_and_say_so():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(2.0))
    d.add_value("x", np.array([np.nan, np.nan]), axes="t")
    m, _ = model_of(d, values="x")
    assert m.series[0].counts.sum() == 0 and m.left_out == 2


def test_by_parts_equals_whole(tmp_path):
    path = mock("11 single shot iq.lbd", tmp_path)
    spec = {"kind": "histogram", "values": ["I"], "color": "state", "all": ["shot"], "index": {"readout_power": 1}}
    whole = lbd.load(path)
    resolved = rnd.resolve_spec(whole, spec, warn_unused=False)
    a = hist.prepare(whole, resolved, Style())
    with lbd.open(path) as d:
        b = hist.count(rnd.flat(d), resolved, block=37)
    assert np.allclose(a.edges / a.xf, b.edges)
    for s, c in zip(a.series, b.counts):
        assert np.array_equal(s.counts, c)


def test_fraction_sums_to_one():
    m, _ = model_of(shots(), values="I", all=["shot"], options={"hist_y": "fraction"})
    assert all(hist.heights(m, s).sum() == pytest.approx(1) for s in m.series)
    assert m.y_label == "Fraction"


def test_density_integrates_to_one():
    m, _ = model_of(shots(), values="I", all=["shot"], options={"hist_y": "density"})
    assert all((hist.heights(m, s) * np.diff(m.edges)).sum() == pytest.approx(1) for s in m.series)
    assert m.y_label == f"Density (1/{m.x_unit})"


def test_log_axis_draws_with_empty_bins():
    d = lbd.Dataset()
    d.add_axis("t", np.arange(5.0))
    d.add_value("x", np.array([0.0, 0.0, 0.0, 0.0, 10.0]), axes="t")
    m, spec = model_of(d, values="x", y_scale="log", options={"bins": 5})
    assert m.series[0].counts.tolist() == [4, 0, 0, 0, 1]
    fig = rnd.new_figure(Style())
    ax = fig.add_subplot()
    hist.draw(fig, ax, m, d, spec, Style())
    fig.canvas.draw()
    assert ax.get_yscale() == "log" and ax.get_ylim()[0] == pytest.approx(0.5)


@pytest.mark.parametrize("style", ["bars", "outline"])
def test_drawing_follows_the_style(style):
    d = shots()
    custom = Style.model_validate({"figure": {"axes": {"histogram": {"fill_alpha": 0.25, "line_width": 3}}}})
    resolved = rnd.resolve_spec(d, {"kind": "histogram", "values": "I", "color": "none", "options": {"hist_style": style}},
                                warn_unused=False)
    m = hist.prepare(d, resolved, custom)
    fig = rnd.new_figure(custom)
    artist = hist.draw(fig, fig.add_subplot(), m, d, resolved, custom)[0]
    if style == "bars":
        assert artist.get_alpha() == 0.25 and artist.get_fill()
    else:
        assert artist.get_linewidth() == 3


@pytest.mark.parametrize("bins", ["x", 1, 10_001, 2.5, True])
def test_bad_bins_say_so(bins):
    with pytest.raises(rnd.RenderError, match="bins must be"):
        model_of(shots(), values="I", options={"bins": bins})


def test_a_single_number_is_not_offered():
    d = rnd.flat(shots())
    assert "single number" in hist.fits(d, "amplitude")
    assert hist.fits(d, "I") is None


def test_every_mock_file_with_numbers_draws(tmp_path):
    for path in mock_values.write_all(tmp_path, small=True):
        d = lbd.load(path)
        f = rnd.flat(d)
        names = [n for n in f.values if hist.fits(f, n) is None]
        assert names, path.name
        for name in names:
            with warnings.catch_warnings():                # variable sweeps: "all its points are counted"
                warnings.simplefilter("ignore", rnd.RenderWarning)
                png, _ = rnd.render_dataset(d, {"kind": "histogram", "values": name}, Style(), fmt="png", warn_unused=False)
            assert png[:4] == b"\x89PNG"


@pytest.mark.parametrize("name, value", [("13 variable sweep.lbd", "S21"), ("14 triangle.lbd", "S"), ("15 adaptive map.lbd", "z")])
def test_a_group_counts_all_its_points(tmp_path, name, value):
    d = lbd.load(mock(name, tmp_path))
    m, spec = model_of(d, values=value)
    assert m.series[0].counts.sum() == d.values[value].data.size
    assert spec["index"] == {} and spec["color"] == "none"
    assert "variable sweep" in hist.notes_of(m)[0]
    with pytest.raises(rnd.RenderError, match="variable sweep"):
        model_of(d, values=value, color=rnd.flat(d).values[value].axes[0])
