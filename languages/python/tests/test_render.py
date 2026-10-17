"""Plot spec resolution and drawing (lbd.plot.render): strict checks, warnings, every branch."""

import warnings

import numpy as np
import pytest

pytest.importorskip("matplotlib")

import lbd  # noqa: E402
from lbd.plot import render as rnd  # noqa: E402
from lbd.plot.render import RenderError, RenderWarning, resolve_spec  # noqa: E402
from lbd.plot.style import Style, from_dict  # noqa: E402
from lbd.plot.units import UnitWarning  # noqa: E402


def sweep():
    f = np.linspace(4e9, 8e9, 21)
    p = np.arange(-40, 1, 10.0)
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", np.exp(1j * np.outer(p, f) * 1e-10), axes=["power", "freq"])
    d.add_value("T", np.outer(np.ones(len(p)), f) * 1e-12, axes=["power", "freq"], unit="s")
    d.add_value("Q", 7.0)
    return d


def cube():
    d = lbd.Dataset()
    for n, k in (("a", 2), ("b", 3), ("c", 4)):
        d.add_axis(n, np.arange(k, dtype=float))
    d.add_value("T", np.arange(24.0).reshape(2, 3, 4), axes=["a", "b", "c"])
    return d


def quiet():
    w = warnings.catch_warnings()
    w.__enter__()
    warnings.simplefilter("error")
    return w


# ---- spec checks ----------------------------------------------------------------------------


@pytest.mark.parametrize("spec, match", [
    ({"knd": "curve"}, "unknown plot setting"),
    ({"kind": "pie"}, "unknown plot kind"),
    ({"values": ["S12"]}, "no value named 'S12'"),
    ({"values": [3]}, "value name"),
    ({"values": []}, "value name"),
    ({"complex": "dbm"}, "unknown complex mode"),
    ({"complex": "iq"}, "only exists for scatter"),
    ({"x_scale": "logarithmic"}, "scale must be"),
    ({"x": "nope"}, "horizontal axis"),
    ({"kind": "heatmap", "y": "freq"}, "vertical axis"),
    ({"kind": "curve", "series": "nope"}, "series"),
    ({"index": {"nope": 1}}, "no axis named 'nope'"),
    ({"index": [1]}, "must be a dict"),
    ({"kind": "curve", "series": "none", "index": {"power": 99}}, "out of range"),
    ({"kind": "curve", "series": "none", "index": {"power": 1.5}}, "whole number"),
    ({"kind": "curve", "series": "none", "index": {"power": "2"}}, "whole number"),
    ({"kind": "curve", "series": "none", "index": {"power": True}}, "whole number"),
    ({"kind": "scalar"}, "kind='scalar' was removed"),
    ({"values": "Q", "kind": "curve"}, r"'Q' \(7\) is a single number; it can't be plotted"),
    ({"values": ["S21", "Q"]}, "single number"),
    ({"title": 5}, "title must be text"),
])
def test_invalid_specs_raise(spec, match):
    with pytest.raises(RenderError, match=match):
        resolve_spec(sweep(), spec)


def test_spec_must_be_a_dict():
    with pytest.raises(RenderError):
        resolve_spec(sweep(), [1])


def test_no_values():
    with pytest.raises(RenderError, match="no values"):
        resolve_spec(lbd.Dataset(), {})


def test_heatmap_needs_two_dimensions():
    d = lbd.Dataset()
    d.add_axis("t", [0.0, 1.0])
    d.add_value("v", [1.0, 2.0], axes="t")
    with pytest.raises(RenderError, match="2 dimensions"):
        resolve_spec(d, {"kind": "heatmap"})


def test_auto_kinds():
    d = sweep()
    assert resolve_spec(d, {})["kind"] == "heatmap"
    assert resolve_spec(d, {"kind": "curve"})["values"] == ["S21"]      # never the single number Q


def test_negative_index_counts_from_the_end():
    r = resolve_spec(sweep(), {"kind": "curve", "series": "none", "index": {"power": -1}})
    assert r["index"] == {"power": 4}


def test_resolved_slices_describe_the_fixed_axes():
    r = resolve_spec(cube(), {"index": {"a": 1}})
    assert r["x"] == "c" and r["y"] == "b"
    assert r["slices"] == [{"axis": "a", "index": 1, "length": 2, "label": "a", "unit": "", "value": 1.0}]


# ---- warnings for settings that don't apply ----------------------------------------------------


@pytest.mark.parametrize("spec, match", [
    ({"kind": "curve", "color": "power"}, "not used by a curve"),
    ({"kind": "heatmap", "series": "power"}, "not used by a heatmap"),
    ({"kind": "heatmap", "values": ["S21", "T"]}, "one value"),
    ({"kind": "curve", "values": ["S21", "T"], "series": "power"}, "series='power' is ignored"),
    ({"kind": "curve", "index": {"freq": 2}}, r"index for \['freq'\] is ignored"),
    ({"kind": "scatter", "values": ["T"], "z_label": "x"}, "colour bar label"),
    ({"kind": "scatter", "values": ["S21"], "complex": "iq", "x": "power"}, "I/Q plane"),
    ({"values": ["T"], "complex": "db"}, "has no effect"),
])
def test_unused_settings_warn(spec, match):
    with pytest.warns(RenderWarning, match=match):
        resolve_spec(sweep(), spec)


def test_unused_settings_can_be_ignored_silently():
    w = quiet()
    try:
        resolve_spec(sweep(), {"kind": "curve", "color": "power", "y": "x"}, warn_unused=False)
    finally:
        w.__exit__(None, None, None)


# ---- the saved view is lenient -------------------------------------------------------------------


def test_saved_view_with_missing_value_warns_and_falls_back():
    d = sweep()
    d.plot = {"values": ["gone"], "kind": "curve"}
    with pytest.warns(RenderWarning, match="saved view.*no value named 'gone'"):
        r = resolve_spec(d, {})
    assert r["values"] == ["S21"] and r["kind"] == "curve"


def test_saved_view_bad_index_warns():
    d = sweep()
    d.plot = {"kind": "curve", "series": "none", "index": {"power": 99, "nope": 1}}
    with pytest.warns(RenderWarning) as rec:
        r = resolve_spec(d, {})
    assert r["index"] == {"power": 0}
    assert any("out of range" in str(w.message) for w in rec)


def test_explicit_settings_win_over_saved_view():
    d = sweep()
    d.plot = {"kind": "curve", "complex": "phase"}
    assert resolve_spec(d, {"complex": "db"})["complex"] == "db"
    assert resolve_spec(d, {})["complex"] == "phase"


def test_another_plot_kind_takes_only_the_kind_free_settings_of_the_saved_view():
    """Found while watching a session: a saved scatter view (Q against I) made every switch to
    Curves warn "saved view: 'I' can't be used as horizontal axis". The view isn't wrong; it
    was made for a scatter plot."""
    d = lbd.Dataset()
    d.add_axis("prep", [0.0, 1.0])
    d.add_axis("shot", np.arange(50.0))
    for name in ("I", "Q"):
        d.add_value(name, np.ones((2, 50)), axes=["prep", "shot"], unit="V")
    d.plot = {"kind": "scatter", "values": ["Q"], "x": "I", "color": "prep", "complex": "abs",
              "y_scale": "log", "title": "Readout", "x_label": "I (V)", "index": {"shot": 3}}
    w = quiet()
    try:
        curve = resolve_spec(d, {"kind": "curve"})
        heat = resolve_spec(d, {"kind": "heatmap"})
    finally:
        w.__exit__(None, None, None)
    # kept: values, scales, title; dropped: x, colour, slice, axis label (they belong to the scatter)
    assert curve["values"] == ["Q"] and curve["y_scale"] == "log" and curve["title"] == "Readout"
    assert curve["x"] == "shot" and curve["series"] == "prep" and "x_label" not in curve
    assert heat["x"] == "shot" and heat["y"] == "prep"
    # the same kind still uses the whole saved view
    assert resolve_spec(d, {"kind": "scatter"})["x"] == "I"


def test_a_saved_value_that_cant_make_the_new_kind_is_left_out_quietly():
    d = sweep()
    d.plot = {"kind": "scalar", "values": ["Q"]}
    w = quiet()
    try:
        r = resolve_spec(d, {"kind": "heatmap"})
    finally:
        w.__exit__(None, None, None)
    assert r["values"] == ["S21"]


def test_other_values_drop_a_saved_axis_that_doesnt_fit_quietly():
    """t1_noise.lbd: the saved view draws P1 over delay; choosing S_V (over frequency) must not
    complain that the saved horizontal axis 'delay' doesn't fit S_V."""
    d = lbd.Dataset()
    d.add_axis("delay", np.linspace(0, 1e-4, 5), unit="s")
    d.add_axis("f", np.logspace(0, 5, 6), unit="Hz")
    d.add_value("P1", np.ones(5), axes="delay")
    d.add_value("S_V", np.ones(6), axes="f", unit="V²/Hz")
    d.plot = {"kind": "curve", "values": ["P1"], "x": "delay", "x_scale": "log"}
    w = quiet()
    try:
        r = resolve_spec(d, {"values": ["S_V"]})
    finally:
        w.__exit__(None, None, None)
    assert r["x"] == "f" and r["x_scale"] == "log"          # the scale still applies
    d.plot = {"kind": "curve", "values": ["P1"], "x": "gone"}
    with pytest.warns(RenderWarning, match="saved view"):       # the view's own plot: still told
        resolve_spec(d, {})


# ---- axes with a single point are fixed parameters ---------------------------------------------


def one_power(order):
    """S21 over freq at one fixed power: power is an axis of length 1 (not swept)."""
    d = lbd.Dataset()
    d.add_axis("power", [-40.0], unit="dBm", label="Power")
    d.add_axis("freq", np.linspace(7e9, 7.01e9, 11), unit="Hz", label="Frequency")
    data = np.ones((1, 11)) if order[0] == "power" else np.ones((11, 1))
    d.add_value("S21", data, axes=order)
    return d


@pytest.mark.parametrize("order", [["power", "freq"], ["freq", "power"]])
def test_a_single_point_axis_is_a_fixed_parameter(order):
    for spec in ({}, {"kind": "curve"}):
        r = resolve_spec(one_power(order), spec)
        assert r["kind"] == "curve" and r["x"] == "freq" and "series" not in r
        assert r["slices"] == [{"axis": "power", "index": 0, "length": 1, "label": "Power", "unit": "dBm",
                                "value": -40.0}]
    with pytest.raises(RenderError, match=r"2 axes with more than one point.*\['power'\] is a single point"):
        resolve_spec(one_power(order), {"kind": "heatmap"})


def test_a_single_point_axis_can_still_be_chosen():
    r = resolve_spec(one_power(["power", "freq"]), {"kind": "curve", "x": "power", "series": "freq"})
    assert r["x"] == "power" and r["series"] == "freq"


# ---- scatter ------------------------------------------------------------------------------------


def test_scatter_checks():
    d = sweep()
    with pytest.raises(RenderError, match="not complex"):
        resolve_spec(d, {"kind": "scatter", "values": ["T"], "complex": "iq"})
    with pytest.raises(RenderError, match="horizontal axis"):
        resolve_spec(d, {"kind": "scatter", "values": ["T"], "x": "nope"})
    with pytest.raises(RenderError, match="colour the points"):
        resolve_spec(d, {"kind": "scatter", "values": ["T"], "color": "nope"})
    with pytest.raises(RenderError, match="which is the horizontal axis"):
        resolve_spec(d, {"kind": "scatter", "values": ["T"], "index": {"freq": 1}})
    with pytest.raises(RenderError, match="which is the colour"):
        resolve_spec(d, {"kind": "scatter", "values": ["T"], "color": "power", "index": {"power": 1}})
    r = resolve_spec(d, {"kind": "scatter", "values": ["T"], "color": "none"})
    assert "color" not in r


def test_scatter_colour_needs_matching_values():
    d = sweep()
    d.add_axis("other", np.arange(21.0))
    d.add_value("U", np.ones(21), axes="freq")
    with pytest.raises(RenderError, match="needs every value"):
        resolve_spec(d, {"kind": "scatter", "values": ["T", "U"], "color": "power"})


# ---- drawing ------------------------------------------------------------------------------------


def draw(d, spec, style=None):
    style = style or Style()
    data, resolved = rnd.render_dataset(d, spec, style, fmt="png")
    assert data.startswith(b"\x89PNG")
    return resolved


@pytest.mark.parametrize("spec", [
    {"kind": "curve", "values": ["S21"], "complex": mode} for mode in ("abs", "db", "phase", "phase_deg", "real", "imag")
] + [
    {"kind": "heatmap", "complex": "db", "title": "t", "z_label": "z"},
    {"kind": "scatter", "values": ["S21"], "complex": "iq", "color": "power"},
    {"kind": "scatter", "values": ["T"], "x": "S21", "complex": "abs"},
    {"kind": "scatter", "values": ["T"], "color": "T", "x_scale": "log"},
    {"kind": "curve", "values": ["T"], "series": "none", "index": {"power": 2}, "y_scale": "log"},
])
def test_every_kind_draws(spec):
    draw(sweep(), spec)


def test_many_series_get_a_colour_bar():
    d = lbd.Dataset()
    d.add_axis("n", np.arange(12.0))
    d.add_axis("t", np.linspace(0, 1, 5))
    d.add_value("v", np.ones((12, 5)), axes=["n", "t"])
    fig, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "curve"}), Style())
    assert len(fig.axes) == 2       # plot + colour bar


def test_nan_on_series_axis_does_not_crash():
    d = lbd.Dataset()
    d.add_axis("n", [1.0, 2.0])
    d.add_axis("t", np.linspace(0, 1, 5))
    d.add_value("v", np.ones((2, 5)), axes=["n", "t"])
    d.axes["n"].data = np.array([1.0, np.nan])
    rnd.build_figure(d, resolve_spec(d, {"kind": "curve"}), Style())


def test_mixed_units_warn():
    d = sweep()
    d.add_value("V", np.ones((5, 21)), axes=["power", "freq"], unit="V")
    with pytest.warns(RenderWarning, match="different units"):
        draw(d, {"kind": "curve", "values": ["T", "V"], "series": "none"})


def test_log_scale_with_non_positive_data_warns():
    d = sweep()
    with pytest.warns(RenderWarning, match="values <= 0"):
        draw(d, {"kind": "curve", "values": ["S21"], "complex": "real", "series": "none", "y_scale": "log"})


def test_zeros_in_db_warn():
    d = lbd.Dataset()
    d.add_axis("t", [0.0, 1.0, 2.0])
    d.add_value("z", np.array([0, 1, 1j]), axes="t")
    with pytest.warns(RenderWarning, match="zeros"):
        draw(d, {"complex": "db"})


def test_fixed_prefix_per_quantity():
    d = sweep()
    style = from_dict({"quantities": {"freq": {"prefix": "M"}, "T": {"prefix": "p"}}})
    fig, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "curve", "values": ["T"], "series": "none"}), style)
    assert ax.get_xlabel() == "Frequency (MHz)" and ax.get_ylabel() == "T (ps)"
    assert ax.lines[0].get_xdata()[-1] == pytest.approx(8000.0)


def test_prefix_none_and_auto_off():
    d = sweep()
    style = from_dict({"quantities": {"freq": {"prefix": ""}}})
    _, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "curve", "values": ["T"], "series": "none"}), style)
    assert ax.get_xlabel() == "Frequency (Hz)"
    off = from_dict({"figure": {"axes": {"axis": {"label": {"auto_prefix": False}}}}})
    _, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "curve", "values": ["T"], "series": "none"}), off)
    assert ax.get_xlabel() == "Frequency (Hz)" and ax.get_ylabel() == "T (s)"


def test_prefix_for_a_unitless_quantity_warns():
    d = lbd.Dataset()
    d.add_axis("n", [1.0, 2.0])
    d.add_value("v", [3.0, 4.0], axes="n")
    with pytest.warns(UnitWarning, match="without a unit"):
        rnd.build_figure(d, resolve_spec(d, {}), from_dict({"quantities": {"v": {"prefix": "k"}}}))


def test_quantity_limits_and_log_scale():
    d = sweep()
    style = from_dict({"quantities": {"S21.db": {"vmin": -1, "vmax": 0, "cmap": "magma"},
                                      "T": {"scale": "log", "vmin": 1e-9}}})
    fig, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "heatmap", "complex": "db"}), style)
    mesh = ax.collections[0]
    assert mesh.norm.vmin == -1 and mesh.cmap.name == "magma"
    _, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "curve", "values": ["T"], "series": "none"}), style)
    assert ax.get_yscale() == "log"


def test_colour_bar_can_be_hidden():
    d = sweep()
    style = from_dict({"figure": {"axes": {"image": {"colorbar": {"visible": False}}}}})
    fig, _ = rnd.build_figure(d, resolve_spec(d, {"kind": "heatmap"}), style)
    assert len(fig.axes) == 1


def test_find_quantity_order():
    style = from_dict({"quantities": {"S21.db": {"vmin": -3, "vmax": 0}, "S21": {"vmin": 0, "vmax": 1},
                                      "Temperature": {"vmin": 1, "vmax": 2}}})
    assert rnd.find_quantity(style, "S21", "S21", "db").vmin == -3
    assert rnd.find_quantity(style, "S21", "S21", None).vmin == 0
    assert rnd.find_quantity(style, "T", "Temperature", None).vmin == 1
    assert rnd.find_quantity(style, "X", "X", None).vmin is None


def test_apply_complex_modes():
    z = np.array([3 + 4j])
    assert rnd.apply_complex(z, "S", "V", "abs")[0][0] == 5
    assert rnd.apply_complex(z, "S", "V", "real")[1:] == ("Re S", "V")
    assert rnd.apply_complex(z, "S", "V", "imag")[0][0] == 4
    assert rnd.apply_complex(z, "S", "V", "phase_deg")[2] == "°"
    real = np.array([1, 2])
    out, label, unit = rnd.apply_complex(real, "x", "V", "db")
    assert out.dtype == float and label == "x" and unit == "V"
    with pytest.raises(RenderError):
        rnd.apply_complex(z, "S", "V", "nope")


# ---- output ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["svg", "SVG", "pdf", "png"])
def test_formats(fmt):
    data, _ = rnd.render_dataset(sweep(), {}, Style(), fmt=fmt)
    assert data[:4] in (b"<?xm", b"%PDF", b"\x89PNG")


def test_unknown_format_is_rejected_before_drawing():
    with pytest.raises(RenderError, match="unknown format"):
        rnd.render_dataset(sweep(), {}, Style(), fmt="gif")
    with pytest.raises(RenderError):
        rnd.check_format(5)


def test_bad_math_in_a_label_is_a_render_error():
    with pytest.raises(RenderError, match="matplotlib couldn't draw"):
        rnd.render_dataset(sweep(), {"title": r"$\frac{$"}, Style(), fmt="png")


def test_render_file_reads_only_needed_values(tmp_path):
    d = sweep()
    d.save(tmp_path / "s.lbd")
    data, resolved = rnd.render_file(tmp_path / "s.lbd", {"kind": "curve", "values": ["T"]}, Style(), fmt="svg")
    assert resolved["values"] == ["T"] and data.startswith(b"<?xml")
    assert rnd.needed_values(lbd.info(tmp_path / "s.lbd"), {"values": ["T"], "x": "S21"}) == ["T", "S21"]


def test_metadata_and_safe_filename(tmp_path):
    d = sweep()
    assert rnd.metadata("png", d)["Title"] == "sweep"
    assert rnd.metadata("pdf", lbd.Dataset())["Title"] == ""
    assert rnd.safe_filename("a b/c") == "a_b_c"
    assert rnd.safe_filename("///") == "figure"


def test_single_numbers_are_not_plotted():
    import lbd.plot as lp

    d = lbd.Dataset()
    d.add_value("T1", 21e-6, unit="s", label="T1")
    with pytest.raises(RenderError, match=r"only single numbers \('T1' \(21 µs\)\); there is nothing to plot"):
        lp.plot(d)
    with pytest.raises(RenderError, match="kind='scalar' was removed"):
        lp.plot(sweep(), "scalar")


def test_an_old_saved_single_number_view_falls_back_with_a_warning():
    d = sweep()
    d.plot = {"kind": "scalar", "values": ["Q"]}
    with pytest.warns(RenderWarning, match="saved view") as rec:
        r = resolve_spec(d, {})
    assert r["kind"] == "heatmap" and r["values"] == ["S21"]
    assert any("kind='scalar' was removed" in str(w.message) for w in rec)


def _readout():
    d = lbd.Dataset()
    d.add_axis("state", [0, 1], label="State")
    d.add_axis("shot", np.arange(50.0))
    rng = np.random.default_rng(0)
    d.add_value("IQ", rng.normal(size=(2, 50)) + 1j * rng.normal(size=(2, 50)) + np.array([[0], [3]]),
                axes=["state", "shot"], unit="V")
    d.add_axis("power", np.linspace(-60, 0, 12), unit="dBm", label="Power")
    d.add_value("P", np.ones((12, 50)), axes=["power", "shot"])
    return d


def test_scatter_coloured_by_a_short_axis_gets_a_legend():
    fig, ax = rnd.build_figure(_readout(), resolve_spec(_readout(), {"kind": "scatter", "values": ["IQ"],
                                                                      "complex": "iq", "color": "state"}), Style())
    assert len(fig.axes) == 1                                   # no colour bar
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["State = 0", "State = 1"]


def test_scatter_coloured_by_a_long_axis_or_a_value_gets_a_colour_bar():
    d = _readout()
    fig, ax = rnd.build_figure(d, resolve_spec(d, {"kind": "scatter", "values": ["P"], "x": "shot",
                                                   "color": "power"}), Style())
    assert len(fig.axes) == 2 and ax.get_legend() is None        # 12 powers > 7 colours
    d2 = sweep()
    fig, ax = rnd.build_figure(d2, resolve_spec(d2, {"kind": "scatter", "values": ["T"], "color": "T"}), Style())
    assert len(fig.axes) == 2


def test_render_jpg():
    data, _ = rnd.render_dataset(sweep(), {"kind": "curve", "values": ["S21"]}, Style(), fmt="jpeg")
    assert data[:2] == b"\xff\xd8"
