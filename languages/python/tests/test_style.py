"""The Style model: unknown keys, checked values and assignments, fonts, files."""

import json

import pytest

pytest.importorskip("matplotlib")

from lbd.plot.style import (  # noqa: E402
    LEGEND_LOCATIONS,
    QuantityStyle,
    Style,
    StyleError,
    StyleWarning,
    check_font_installed,
    deep_diff,
    deep_merge,
    from_dict,
    read_style_file,
    rcparams_to_mplstyle,
    validate,
)


# ---- unknown settings -------------------------------------------------------------------


@pytest.mark.parametrize("data, path, suggestion", [
    ({"figure": {"widht_mm": 120}}, "figure.widht_mm", "figure.width_mm"),
    ({"figure": {"font": {"sise_pt": 9}}}, "figure.font.sise_pt", "figure.font.size_pt"),
    ({"figure": {"axes": {"xaxis": {"label": {"pad": 3}}}}}, "figure.axes.xaxis.label.pad", "pad_pt"),
    ({"quantities": {"S21": {"vmn": 0}}}, "quantities.S21.vmn", "vmin"),
    ({"figur": {}}, "figur", "figure"),
])
def test_unknown_setting_is_an_error_with_a_suggestion(data, path, suggestion):
    with pytest.raises(StyleError, match="unknown style setting") as e:
        from_dict(data)
    assert path in str(e.value) and suggestion in str(e.value)


def test_unknown_setting_from_a_file_warns_and_is_dropped():
    with pytest.warns(StyleWarning, match="figure.widht_mm"):
        s = from_dict({"figure": {"widht_mm": 120, "height_mm": 50}}, unknown="warn", where="x.lbd.json")
    assert s.figure.height_mm == 50 and s.figure.width_mm == 85


def test_unknown_mode_argument():
    with pytest.raises(ValueError):
        from_dict({}, unknown="ignore")


def test_model_construction_forbids_extra_keys():
    with pytest.raises(Exception):
        Style(nonsense=1)


# ---- values -----------------------------------------------------------------------------------


@pytest.mark.parametrize("data, where", [
    ({"figure": {"width_mm": 5}}, "figure.width_mm"),
    ({"figure": {"dpi": 10_000}}, "figure.dpi"),
    ({"figure": {"facecolor": "notacolour"}}, "figure.facecolor"),
    ({"figure": {"axes": {"frame": {"color": "#12"}}}}, "figure.axes.frame.color"),
    ({"figure": {"axes": {"colors": []}}}, "figure.axes.colors"),
    ({"figure": {"axes": {"colors": ["red", "nope"]}}}, "figure.axes.colors"),
    ({"figure": {"axes": {"image": {"cmap": "virdis"}}}}, "figure.axes.image.cmap"),
    ({"figure": {"axes": {"legend": {"location": "top"}}}}, "figure.axes.legend.location"),
    ({"figure": {"axes": {"lines": {"marker": "@"}}}}, "figure.axes.lines.marker"),
    ({"figure": {"axes": {"scatter": {"marker": "zz"}}}}, "figure.axes.scatter.marker"),
    ({"figure": {"axes": {"grid": {"linestyle": "~"}}}}, "figure.axes.grid.linestyle"),
    ({"figure": {"axes": {"xaxis": {"ticks": {"direction": "up"}}}}}, "figure.axes.xaxis"),
    ({"quantities": {"T": {"vmin": 2, "vmax": 1}}}, "quantities.T"),
    ({"quantities": {"T": {"vmin": float("nan")}}}, "quantities.T"),
    ({"quantities": {"T": {"scale": "log", "vmin": 0}}}, "quantities.T"),
    ({"quantities": {"T": {"prefix": "x"}}}, "quantities.T.prefix"),
    ({"quantities": {"T": {"cmap": "nope"}}}, "quantities.T.cmap"),
    ({"lbd_style": 0}, "lbd_style"),
    ({"lbd_style": 1}, "lbd_style"),
])
def test_invalid_values_name_the_setting(data, where):
    with pytest.raises(StyleError) as e:
        from_dict(data)
    assert where in str(e.value)


def test_close_colour_map_name_is_suggested():
    with pytest.raises(StyleError, match="did you mean viridis"):
        from_dict({"figure": {"axes": {"image": {"cmap": "virdis"}}}})


@pytest.mark.parametrize("loc", LEGEND_LOCATIONS)
def test_every_legend_location_is_valid(loc):
    assert from_dict({"figure": {"axes": {"legend": {"location": loc}}}}).figure.axes.legend.location == loc


def test_good_values():
    s = from_dict({"figure": {"facecolor": "none", "axes": {"lines": {"marker": ""}, "scatter": {"edgecolor": "none"},
                                                             "colors": ["#000", "C1", "tab:red"]}},
                   "quantities": {"f": {"prefix": "u"}, "g": {"prefix": ""}, "S21.db": {"vmin": -30, "vmax": 0}}})
    assert s.quantities["f"].prefix == "µ" and s.quantities["g"].prefix == ""


def test_assignments_are_checked():
    s = Style()
    with pytest.raises(StyleError, match="width_mm"):
        s.figure.width_mm = -5
    with pytest.raises(StyleError):
        s.figure.axes.frame.color = "nope"
    s.figure.width_mm = 120
    assert s.figure.width_mm == 120
    with pytest.raises(Exception):
        s.figure.widht_mm = 3


def test_newer_style_version_warns():
    with pytest.warns(StyleWarning, match="newer LBD"):
        from_dict({"lbd_style": 99})


def test_quantity_model_directly():
    with pytest.raises(Exception):
        QuantityStyle(vmin=3, vmax=3)
    assert QuantityStyle(prefix="M").prefix == "M"


# ---- axis_style ---------------------------------------------------------------------------------


def test_axis_style():
    s = from_dict({"figure": {"axes": {"yaxis": {"ticks": {"direction": "out"}}}}})
    assert s.axis_style("y").ticks.direction == "out"
    assert s.axis_style("x").ticks.direction == "in"
    with pytest.raises(ValueError, match="'x' or 'y'"):
        s.axis_style("z")


# ---- style format ------------------------------------------------------------------------------


def test_old_flat_layout_is_rejected():
    with pytest.raises(StyleError, match="unknown style setting.*'font'"):
        from_dict({"font": {"size_pt": 9}})


def test_old_style_version_is_rejected():
    with pytest.raises(StyleError, match="style version 1 is not supported"):
        from_dict({"lbd_style": 1})


@pytest.mark.parametrize("bad", [[1], "x", 3])
def test_style_must_be_an_object(bad):
    with pytest.raises(StyleError, match="JSON object"):
        from_dict(bad)


def test_none_is_the_defaults():
    assert from_dict(None) == Style()


# ---- fonts ------------------------------------------------------------------------------------


def test_missing_font_is_an_error_naming_the_alternatives():
    s = from_dict({"figure": {"font": {"family": "NoSuchFont123"}}})   # loading is fine
    with pytest.raises(StyleError, match="'NoSuchFont123' is not installed") as e:
        s.to_rcparams()
    assert "DejaVu Sans" in str(e.value) and "sans-serif" in str(e.value)
    with pytest.raises(StyleError, match="not installed"):
        check_font_installed("NoSuchFont123")


@pytest.mark.parametrize("family", ["serif", "sans-serif", "monospace", "DejaVu Sans", "DejaVu Serif"])
def test_available_fonts_pass(family):
    check_font_installed(family)
    assert from_dict({"figure": {"font": {"family": family}}}).to_rcparams()["font.family"] == [family]


def test_similar_installed_fonts_are_suggested():
    with pytest.raises(StyleError, match="similar installed fonts: DejaVu Sans Mono"):
        check_font_installed("DejaVu Sans Mon")


def test_mplstyle_export_does_not_need_the_font():
    s = from_dict({"figure": {"font": {"family": "NoSuchFont123"}}})
    assert "font.family: NoSuchFont123" in s.to_mplstyle()
    assert s.to_rcparams(check_font=False)["font.family"] == ["NoSuchFont123"]


# ---- files ------------------------------------------------------------------------------------


def test_read_style_file_errors(tmp_path):
    with pytest.raises(StyleError, match="not found"):
        read_style_file(tmp_path / "nope.lbd.json")
    (tmp_path / "bad.lbd.json").write_text("{nope")
    with pytest.raises(StyleError, match="not a valid style file"):
        read_style_file(tmp_path / "bad.lbd.json")
    (tmp_path / "list.lbd.json").write_text("[1]")
    with pytest.raises(StyleError, match="JSON object"):
        read_style_file(tmp_path / "list.lbd.json")
    with pytest.raises(StyleError, match="can't read"):
        read_style_file(tmp_path)          # a folder


def test_style_load_warns_about_unknown_keys(tmp_path):
    p = tmp_path / "s.lbd.json"
    p.write_text(json.dumps({"figure": {"width_mm": 99, "future_setting": 1}}))
    with pytest.warns(StyleWarning, match="future_setting"):
        s = Style.load(p)
    assert s.figure.width_mm == 99


def test_save_load_roundtrip(tmp_path):
    s = from_dict({"name": "x", "figure": {"width_mm": 100}, "quantities": {"f": {"prefix": "M"}}})
    s.save(tmp_path / "x.lbd.json")
    assert Style.load(tmp_path / "x.lbd.json") == s


# ---- helpers ----------------------------------------------------------------------------------


def test_deep_merge_and_diff():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    merged = deep_merge(base, {"a": {"b": 5}})
    assert merged == {"a": {"b": 5, "c": 2}, "d": 3} and base["a"]["b"] == 1
    assert deep_merge(base, None) == base
    assert deep_diff(merged, base) == {"a": {"b": 5}}


def test_diff_of_defaults_is_empty():
    assert Style().diff() == {}


def test_validate_names_problems():
    data = Style().model_dump()
    data["figure"]["dpi"] = 1
    with pytest.raises(StyleError, match="figure.dpi"):
        validate(data)


def test_mplstyle_export():
    text = rcparams_to_mplstyle(Style().to_rcparams(), title="T")
    assert text.startswith("# T") and "axes.prop_cycle: cycler('color'" in text
    assert "#" not in text.split("figure.facecolor:")[1].splitlines()[0]
    assert "unit prefixes" in Style().to_mplstyle()
