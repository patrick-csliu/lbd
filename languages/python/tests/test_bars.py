"""Bars (lbd.plot.bars): what the groups and the bars in them are, for each kind of data."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import bars, render
from lbd.plot.matrix import CellNumbers

STATES = ["ground", "excited", "second"]


def on_states():
    d = lbd.Dataset(title="t")
    d.add_axis("state", np.arange(3.0), label="State", elements=STATES)
    d.add_value("population", [0.71, 0.24, 0.05], axes="state", label="Population")
    d.add_value("error", [0.02, 0.03, 0.01], axes="state", label="Error")
    d.add_value("lifetime", [40e-6, 22e-6, 9e-6], axes="state", unit="s", label="Lifetime")
    d.add_value("rate", [1.0, 2.0, 3.0], axes="state", unit="Hz", label="Rate")
    d.add_value("fidelity", 0.982, label="Fidelity")
    d.add_value("visibility", 0.91, label="Visibility")
    return d


def bar_set(d, **spec):
    resolved = render.resolve_spec(d, {"kind": "bars", **spec})
    return bars.read_bars(d, resolved, lp.load_style()), resolved


def rectangles(ax):
    return [p for c in ax.containers for p in c.patches]


def test_one_short_axis():
    b, spec = bar_set(on_states(), values="population")
    assert b.groups == STATES and b.names == [""]
    assert b.heights.shape == (1, 3) and b.raw[0, 0] == 0.71
    assert spec["x"] == "state" and "series" not in spec


def test_two_short_axes():
    d = lbd.Dataset(title="t")
    d.add_axis("long", np.arange(40.0))
    d.add_axis("a", [0.0, 1.0], elements=["p", "q"])
    d.add_axis("b", [5.0, 6.0, 7.0], label="B", unit="V")
    d.add_value("v", np.arange(240.0).reshape(40, 2, 3), axes=["long", "a", "b"])
    b, spec = bar_set(d, values="v")
    assert spec["x"] == "a" and spec["series"] == "b" and spec["index"] == {"long": 0}
    assert b.groups == ["p", "q"] and b.names == ["B = 5 V", "B = 6 V", "B = 7 V"]
    assert b.raw.shape == (3, 2) and b.raw[2, 1] == 5.0


def test_several_values_on_a_short_axis():
    b, _ = bar_set(on_states(), values=["population", "error"])
    assert b.groups == STATES and b.names == ["Population", "Error"]
    assert b.raw[1, 1] == 0.03


def test_several_single_numbers():
    b, spec = bar_set(on_states(), values=["fidelity", "visibility"])
    assert b.groups == ["Fidelity", "Visibility"] and b.names == [""]
    assert b.raw[0].tolist() == [0.982, 0.91] and "x" not in spec


def test_a_vector_in_each_point():
    d = lbd.Dataset(title="t")
    d.add_axis("amp", np.arange(5.0), unit="V")
    d.add_value("bloch", np.arange(15.0).reshape(5, 3), axes="amp", shape=(3,), elements=["x", "y", "z"])
    b, spec = bar_set(d, values="bloch", index={"amp": 2})
    assert spec["x"] == "bloch_dim1" and "series" not in spec and spec["index"] == {"amp": 2}
    assert b.groups == ["x", "y", "z"] and b.raw[0].tolist() == [6.0, 7.0, 8.0]


def test_complex_re_and_im():
    d = lbd.Dataset(title="t")
    d.add_axis("a", [0.0, 1.0])
    d.add_value("v", [1 + 2j, 3 - 4j], axes="a", unit="V", label="S")
    b, _ = bar_set(d, values="v", complex="re_im")
    assert b.names == ["Re", "Im"] and b.raw[:, 1].tolist() == [3.0, -4.0]
    one, spec = bar_set(d, values="v")
    assert one.names == [""] and spec["complex"] == "abs" and one.raw[0, 1] == 5.0     # the usual choice first


def test_single_numbers_and_values_dont_mix():
    with pytest.raises(render.RenderError, match="single numbers \\(fidelity\\) and values with axes"):
        bar_set(on_states(), values=["population", "fidelity"])


def test_a_single_number_is_still_refused_for_curves():
    with pytest.raises(render.RenderError, match="is a single number"):
        render.resolve_spec(on_states(), {"kind": "curve", "values": "fidelity"})


def test_the_bars_are_drawn():
    fig = lp.plot(on_states(), "bars", "population")
    ax = fig.axes[0]
    tops = [p.get_height() for p in rectangles(ax)]
    assert tops == pytest.approx([0.71, 0.24, 0.05])
    fig.canvas.draw()
    assert [t.get_text() for t in ax.get_xticklabels()] == STATES
    assert ax.get_ylim()[0] == 0 and ax.get_legend() is None


def test_grouped_side_by_side_with_a_legend():
    fig = lp.plot(on_states(), "bars", ["population", "error"])
    ax = fig.axes[0]
    first, second = (c.patches[0] for c in ax.containers)
    assert first.get_x() + first.get_width() <= second.get_x() + 1e-9
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["Population", "Error"]
    assert first.get_facecolor() != second.get_facecolor()


def test_stacked_negative_values():
    d = lbd.Dataset(title="t")
    d.add_axis("a", [0.0, 1.0])
    d.add_axis("b", [0.0, 1.0, 2.0])
    d.add_value("v", [[1.0, -1.0, 2.0], [-3.0, 4.0, -5.0]], axes=["a", "b"])
    fig = lp.plot(d, "bars", "v", x="a", series="b", options={"layout": "stacked"})
    ax = fig.axes[0]
    group = [c.patches[0] for c in ax.containers]           # a = 0: 1, -1, 2
    assert [p.get_y() for p in group] == [0.0, 0.0, 1.0]    # positive on positive, negative from zero
    assert [p.get_height() for p in group] == [1.0, -1.0, 2.0]
    assert ax.get_ylim()[0] < -5 and ax.get_ylim()[1] > 4
    assert all(p.get_x() == group[0].get_x() for p in group)


def test_negative_bars_go_down_and_zero_is_in_the_axis():
    d = lbd.Dataset(title="t")
    d.add_axis("a", [0.0, 1.0])
    d.add_value("v", [3.0, 5.0], axes="a")
    d.add_value("w", [-3.0, -5.0], axes="a")
    assert lp.plot(d, "bars", "v").axes[0].get_ylim()[0] == 0
    low, high = lp.plot(d, "bars", "w").axes[0].get_ylim()
    assert low < -5 and high == 0


def test_two_units_get_two_axes():
    fig = lp.plot(on_states(), "bars", ["population", "lifetime"])
    ax = fig.axes[0]
    right = ax.child_axes[0]
    assert "µs" in right.get_ylabel() and "Population" in ax.get_ylabel()
    second = ax.containers[1].patches[0]
    assert second.get_height() == pytest.approx(0.71)       # the tallest of each unit equally tall


def test_three_units_are_refused():
    with pytest.raises(render.RenderError, match="3 units.*a chart shows two"):
        lp.plot(on_states(), "bars", ["population", "lifetime", "rate"])


def test_stacked_needs_one_unit():
    with pytest.raises(render.RenderError, match="stacked bars need one unit"):
        lp.plot(on_states(), "bars", ["population", "lifetime"], options={"layout": "stacked"})


def test_2000_bars_draw():
    d = lbd.Dataset(title="t")
    d.add_axis("a", np.arange(2000.0))
    d.add_value("v", np.arange(2000.0), axes="a")
    fig = lp.plot(d, "bars", "v")
    fig.canvas.draw()
    assert len(rectangles(fig.axes[0])) == 2000
    assert len(fig.axes[0].get_xticklabels()) <= render.MAX_ELEMENT_TICKS + 1


def numbers_of(ax):
    return next(a for a in ax.artists if isinstance(a, CellNumbers))


def test_values_on_bars():
    fig = lp.plot(on_states(), "bars", "population", options={"numbers": True})
    fig.canvas.draw()
    numbers = numbers_of(fig.axes[0])
    assert [t.get_text() for t in numbers.texts] == ["0.71", "0.24", "0.05"]
    assert numbers.fit()


def test_values_left_out_when_bars_are_narrow():
    d = lbd.Dataset(title="t")
    d.add_axis("a", np.arange(300.0))
    d.add_value("v", 1.2345 + np.arange(300.0), axes="a")
    fig = lp.plot(d, "bars", "v", options={"numbers": True})
    fig.canvas.draw()
    assert not numbers_of(fig.axes[0]).fit()


def test_a_wrong_layout_says_why():
    with pytest.raises(render.RenderError, match="layout must be one of"):
        lp.plot(on_states(), "bars", "population", options={"layout": "piled"})


def test_svg_and_png_export(tmp_path):
    on_states().save(tmp_path / "b.lbd")
    style = lp.load_style()
    spec = {"kind": "bars", "values": ["population", "error"]}
    svg, _ = render.render_file(tmp_path / "b.lbd", spec, style, "svg")
    png, _ = render.render_file(tmp_path / "b.lbd", spec, style, "png")
    assert b"<svg" in svg[:400] and png[:4] == b"\x89PNG"


def test_a_saved_view_keeps_the_bars(tmp_path):
    d = on_states()
    d.plot = {"kind": "bars", "values": ["fidelity", "visibility"], "options": {"numbers": True}}
    d.save(tmp_path / "b.lbd")
    spec = render.resolve_spec(lbd.load(tmp_path / "b.lbd"), {})
    assert spec["kind"] == "bars" and spec["values"] == ["fidelity", "visibility"]


# ---- All of an axis: one bar stands for many numbers (16.48) ----------------------------------


def power_sweep():
    """As `10 one value.lbd`: a complex S21 over power and frequency, with one empty point."""
    d = lbd.Dataset(title="t")
    d.add_axis("power", [-30.0, -20.0, -10.0], label="Power", unit="dBm")
    d.add_axis("frequency", np.linspace(4e9, 5e9, 5), label="Frequency", unit="Hz")
    s21 = (np.arange(15.0).reshape(3, 5) + 1) * np.exp(0.3j * np.arange(5))
    s21[1, 2] = np.nan                                        # one empty point
    d.add_value("S21", s21, axes=["power", "frequency"], label="S21")
    return d, np.abs(s21)


def test_all_of_an_axis_gives_one_bar_per_group_the_mean():
    d, magnitude = power_sweep()
    b, spec = bar_set(d, values="S21", x="power", series="none", all=["frequency"])
    assert spec["all"] == ["frequency"] and spec["slices"] == [] and "series" not in spec
    assert len(b.groups) == 3 and b.names == [""]
    assert b.raw[0] == pytest.approx(np.nanmean(magnitude, axis=1))
    assert np.isfinite(b.raw).all()                            # the empty point is left out, not NaN


@pytest.mark.parametrize("stat,f", [("median", np.nanmedian), ("max", np.nanmax), ("min", np.nanmin),
                                     ("sum", np.nansum)])
def test_each_statistic(stat, f):
    d, magnitude = power_sweep()
    b, _ = bar_set(d, values="S21", x="power", series="none", all=["frequency"], options={"stat": stat})
    assert b.raw[0] == pytest.approx(f(magnitude, axis=1))


def test_an_empty_point_is_left_out():
    d, magnitude = power_sweep()
    b, _ = bar_set(d, values="S21", x="power", series="none", all=["frequency"])
    assert b.raw[0, 1] == pytest.approx(np.mean(magnitude[1, [0, 1, 3, 4]]))


def test_a_group_with_no_numbers_has_no_bar():
    d = lbd.Dataset(title="t")
    d.add_axis("a", [0.0, 1.0])
    d.add_axis("b", [0.0, 1.0, 2.0])
    d.add_value("v", [[1.0, 2.0, 3.0], [np.nan] * 3], axes=["a", "b"])
    b, _ = bar_set(d, values="v", x="a", series="none", all=["b"], options={"stat": "sum"})
    assert b.raw[0, 0] == 6.0 and np.isnan(b.raw[0, 1])       # not a sum of 0


def test_the_axis_title_says_which_statistic():
    d, _ = power_sweep()
    ax = lp.plot(d, "bars", "S21", x="power", series="none", all=["frequency"], options={"stat": "median"}).axes[0]
    assert ax.get_ylabel().startswith("Median of |S21|")
    assert lp.plot(d, "bars", "S21", x="power", series="none").axes[0].get_ylabel().startswith("|S21|")


def test_all_keeps_bars_in_a_group():
    d, magnitude = power_sweep()
    d.add_axis("rep", [0.0, 1.0])
    d.add_value("v", np.stack([magnitude, 2 * magnitude], axis=-1), axes=["power", "frequency", "rep"])
    b, spec = bar_set(d, values="v", x="power", series="rep", all=["frequency"])
    assert b.raw.shape == (2, 3) and b.raw[1] == pytest.approx(2 * np.nanmean(magnitude, axis=1))


def test_an_all_axis_is_not_chosen_for_the_bars_in_a_group():
    d, magnitude = power_sweep()
    d.add_axis("rep", [0.0, 1.0])
    d.add_value("v", np.stack([magnitude, 2 * magnitude], axis=-1), axes=["power", "frequency", "rep"])
    _, spec = bar_set(d, values="v", x="power", all=["rep"])          # rep alone would start as the bars
    assert spec["all"] == ["rep"] and spec["series"] == "frequency"


def test_a_wrong_statistic_says_why():
    d, _ = power_sweep()
    with pytest.raises(render.RenderError, match="stat must be one of"):
        lp.plot(d, "bars", "S21", x="power", all=["frequency"], options={"stat": "mode"})


def error_bars(ax):
    return [c for c in ax.containers if type(c).__name__ == "ErrorbarContainer"]


def test_error_bars_only_with_all():
    d, magnitude = power_sweep()
    with_all = lp.plot(d, "bars", "S21", x="power", series="none", all=["frequency"], options={"errors": True}).axes[0]
    (drawn,) = error_bars(with_all)
    segments = drawn.lines[2][0].get_segments()
    spread = [s[1][1] - s[0][1] for s in segments]
    assert spread == pytest.approx(2 * np.nanstd(magnitude, axis=1))    # one standard deviation each way
    assert not error_bars(lp.plot(d, "bars", "S21", x="power", series="none", options={"errors": True}).axes[0])
    assert not error_bars(lp.plot(d, "bars", "S21", x="power", series="none", all=["frequency"]).axes[0])


def test_all_of_a_drawn_axis_is_ignored_with_a_warning():
    d, _ = power_sweep()
    with pytest.warns(render.RenderWarning, match="all.*'power'.*groups"):
        _, spec = bar_set(d, values="S21", x="power", series="none", all=["power", "frequency"])
    assert spec["all"] == ["frequency"]
