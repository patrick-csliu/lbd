"""Every public function of lbd.plot with each of its parameters and error cases."""

import json
import warnings

import numpy as np
import pytest

pytest.importorskip("matplotlib")

import matplotlib  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import lbd  # noqa: E402
import lbd.plot as lp  # noqa: E402
from lbd.plot.style import MM  # noqa: E402


def sweep():
    f = np.linspace(4e9, 8e9, 21)
    p = np.arange(-40, 1, 10.0)
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", np.exp(1j * np.outer(p, f) * 1e-10), axes=["power", "freq"])
    return d


def test_public_names():
    assert set(lp.__all__) >= {"prefix", "plot", "quick", "use", "activate", "subplots", "apply", "axis_label",
                               "save", "load_style", "list_styles", "default_style", "PresetStore",
                               "StyleWarning", "RenderWarning", "UnitWarning"}
    for w in (lp.StyleWarning, lp.RenderWarning, lp.UnitWarning):
        assert issubclass(w, lbd.LBDWarning)
    for e in (lp.StyleError, lp.RenderError):
        assert issubclass(e, ValueError)


# ---- load_style -----------------------------------------------------------------------------


def test_load_style_forms(tmp_path, monkeypatch):
    s = lp.load_style({"figure": {"width_mm": 100}})
    assert s.figure.width_mm == 100
    copy = lp.load_style(s)
    copy.figure.width_mm = 50
    assert s.figure.width_mm == 100                         # a copy
    s.save(tmp_path / "x.lbd.json")
    assert lp.load_style(tmp_path / "x.lbd.json").name == "x"
    assert lp.load_style(str(tmp_path / "x.lbd.json")).figure.width_mm == 100
    lp.PresetStore().save("talk", {"figure": {"width_mm": 160}})
    assert lp.load_style("talk").figure.width_mm == 160
    assert lp.load_style(None).figure.width_mm == 85


def test_preset_name_wins_over_a_file_of_the_same_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lp.PresetStore().save("talk", {"figure": {"width_mm": 160}})
    (tmp_path / "talk").write_text(json.dumps({"figure": {"width_mm": 11}}))
    assert lp.load_style("talk").figure.width_mm == 160


def test_existing_file_without_json_suffix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mystyle").write_text(json.dumps({"figure": {"width_mm": 77}}))
    assert lp.load_style("mystyle").figure.width_mm == 77


def test_load_style_errors(tmp_path):
    with pytest.raises(lp.StyleError, match="available"):
        lp.load_style("no-such-preset")
    with pytest.raises(lp.StyleError, match="not found"):
        lp.load_style(tmp_path / "missing.lbd.json")
    with pytest.raises(lp.StyleError, match="empty"):
        lp.load_style("")
    with pytest.raises(TypeError):
        lp.load_style(3)
    with pytest.raises(lp.StyleError, match="unknown style setting"):
        lp.load_style({"figure": {"widht_mm": 1}})


# ---- use / activate / subplots / apply ------------------------------------------------------------


def test_use_restores_settings():
    before = matplotlib.rcParams["font.size"]
    with lp.use({"figure": {"font": {"size_pt": 13}}}) as s:
        assert matplotlib.rcParams["font.size"] == 13 and s.figure.font.size_pt == 13
    assert matplotlib.rcParams["font.size"] == before


def test_activate():
    try:
        s = lp.activate({"figure": {"font": {"size_pt": 12}}})
        assert matplotlib.rcParams["font.size"] == 12 and s.figure.font.size_pt == 12
    finally:
        plt.rcdefaults()


def test_subplots_sizes_and_checks():
    fig, axs = lp.subplots(2, 1, width_mm=100, height_mm=50, sharex=True)
    assert fig.get_size_inches() == pytest.approx((100 * MM, 50 * MM)) and len(axs) == 2
    fig, ax = lp.subplots(style={"figure": {"width_mm": 160}})
    assert fig.get_size_inches()[0] == pytest.approx(160 * MM)
    for bad in (0, -1, float("nan"), "10", True):
        with pytest.raises(ValueError):
            lp.subplots(width_mm=bad)
    with pytest.raises(ValueError):
        lp.subplots(0, 1)
    with pytest.raises(ValueError):
        lp.subplots(1.5, 1)
    with pytest.raises(TypeError, match="width_mm"):
        lp.subplots(figsize=(3, 3))


def test_apply_targets():
    fig, axs = plt.subplots(1, 2)
    axs[0].plot([1, 2], label="a")
    axs[0].legend()
    lp.apply(fig, {"figure": {"axes": {"frame": {"top": False}, "grid": {"visible": True}}}})
    assert not axs[0].spines["top"].get_visible()
    lp.apply(axs[1], "default")
    lp.apply(axs, "default")              # an array of Axes
    lp.apply(list(axs), "default")
    for bad in (None, "fig", [1, 2], []):
        with pytest.raises(TypeError):
            lp.apply(bad)


# ---- axis_label / save ------------------------------------------------------------------------------


def test_axis_label():
    assert lp.axis_label("Frequency", "GHz") == "Frequency (GHz)"
    y_slash = {"figure": {"axes": {"yaxis": {"label": {"unit_format": "slash"}}}}}
    assert lp.axis_label("V", "mV", style=y_slash, axis="y") == "V / mV"
    assert lp.axis_label("V", "mV", style=y_slash, axis="x") == "V (mV)"
    with pytest.raises(ValueError):
        lp.axis_label("V", "mV", axis="Y")
    with pytest.raises(TypeError):
        lp.axis_label("V", 3)


@pytest.mark.parametrize("ext", ["pdf", "svg", "png"])
def test_save_formats_and_metadata(tmp_path, ext):
    fig, ax = lp.subplots()
    ax.plot([1, 2])
    out = lp.save(fig, tmp_path / f"f.{ext}", title="My title", dpi=100)
    data = out.read_bytes()
    assert out.exists() and (b"My title" in data or ext == "pdf")


def test_save_checks(tmp_path):
    fig, ax = lp.subplots()
    with pytest.raises(ValueError, match="no extension"):
        lp.save(fig, tmp_path / "noext")
    with pytest.raises(ValueError, match="can't save"):
        lp.save(fig, tmp_path / "f.xyz")
    for bad in (0, -5, 1.5, True):
        with pytest.raises(ValueError, match="dpi"):
            lp.save(fig, tmp_path / "f.png", dpi=bad)
    with pytest.raises(TypeError):
        lp.save("not a figure", tmp_path / "f.png")
    with pytest.raises(TypeError):
        lp.save(fig, tmp_path / "f.png", title=5)
    with pytest.warns(lbd.LBDWarning, match="title can't be stored"):
        lp.save(fig, tmp_path / "f.tiff", title="t")


# ---- plot -----------------------------------------------------------------------------------------


def test_plot_arguments(tmp_path):
    d = sweep()
    fig = lp.plot(d, "curve", "S21", complex="db", series="none")
    assert fig.axes[0].get_ylabel() == "|S21| (dB)"
    fig, ax = plt.subplots()
    assert lp.plot(d, "heatmap", ["S21"], ax=ax) is ax
    d.save(tmp_path / "s.lbd")
    assert lp.plot(tmp_path / "s.lbd").axes
    assert lp.plot(str(tmp_path / "s.lbd"), file_style=False).axes


def test_plot_errors(tmp_path):
    d = sweep()
    with pytest.raises(TypeError, match="unknown plot setting"):
        lp.plot(d, colour="power")
    with pytest.raises(TypeError):
        lp.plot(d, 5)
    with pytest.raises(TypeError):
        lp.plot(d, file_style="yes")
    with pytest.raises(TypeError, match="lbd.Dataset or a path"):
        lp.plot(np.ones(3))
    with pytest.raises(TypeError, match="Axes"):
        lp.plot(d, ax="panel")
    with pytest.raises(lp.RenderError, match="no value named"):
        lp.plot(d, "curve", "S12")
    d.save(tmp_path / "s.lbd")
    with pytest.raises(lp.RenderError, match="not loaded"):
        lp.plot(lbd.info(tmp_path / "s.lbd"))


def test_plot_warns_about_unused_settings():
    with pytest.warns(lp.RenderWarning, match="not used by a curve"):
        lp.plot(sweep(), "curve", color="power")


def test_plot_style_resolution(tmp_path, monkeypatch):
    d = sweep()
    d.style = {"figure": {"height_mm": 40}}
    fig = lp.plot(d, style={"figure": {"width_mm": 100}})
    assert fig.get_size_inches() == pytest.approx((100 * MM, 40 * MM))      # file style on top
    fig = lp.plot(d, style={"figure": {"width_mm": 100}}, file_style=False)
    assert fig.get_size_inches()[1] == pytest.approx(64 * MM)
    lp.PresetStore().save("talk", {"figure": {"width_mm": 160}})
    d.style_name = "talk"
    assert lp.plot(d).get_size_inches()[0] == pytest.approx(160 * MM)


def test_plot_unknown_style_name_warns():
    d = sweep()
    d.style_name = "from-another-computer"
    with pytest.warns(lp.StyleWarning, match="doesn't exist here"):
        lp.plot(d)


def test_plot_file_style_with_unknown_keys_warns():
    d = sweep()
    d.style = {"figure": {"hologram": 1}}
    with pytest.warns(lp.StyleWarning, match="hologram"):
        lp.plot(d, style="default")


# ---- quick ---------------------------------------------------------------------------------------


def test_quick_kinds():
    x = np.linspace(0, 1, 20)
    fig = lp.quick(x, x ** 2, x_label="t", x_unit="s", title="T", complex="abs", y_scale="linear")
    assert fig.axes[0].get_title() == "T"
    fig = lp.quick(x, {"a": x, "b": x ** 2})
    assert fig.axes[0].get_legend() is not None
    rng = np.random.default_rng(0)
    i, q = rng.normal(size=(2, 50))
    fig = lp.quick(i, q, "scatter", color=np.arange(50.0), color_label="n")
    assert len(fig.axes) == 2
    fig = lp.quick(x, np.arange(3.0), z=np.ones((3, 20)))
    assert len(fig.axes) == 2
    fig, ax = plt.subplots()
    assert lp.quick(x, x, ax=ax) is ax


def test_quick_2d_scatter_pairs_points():
    xs = np.arange(6.0).reshape(2, 3)
    fig = lp.quick(xs, xs * 2, "scatter")
    pts = fig.axes[0].collections[0].get_offsets()
    assert np.allclose(pts[:, 1], pts[:, 0] * 2)


@pytest.mark.parametrize("call, exc, match", [
    (lambda x: lp.quick(x), TypeError, "needs y"),
    (lambda x: lp.quick(x, x, "pie"), ValueError, "kind"),
    (lambda x: lp.quick(x, x, color=x), TypeError, "color is for scatter"),
    (lambda x: lp.quick(x, x[:3]), ValueError, "shape"),
    (lambda x: lp.quick(x, {"a": x[:3]}), ValueError, "series 'a'"),
    (lambda x: lp.quick(x, {}), ValueError, "empty dict"),
    (lambda x: lp.quick(np.array([]), np.array([])), ValueError, "empty"),
    (lambda x: lp.quick(x, ["a"] * 20), ValueError, "numbers"),
    (lambda x: lp.quick(x, x, "heatmap"), TypeError, "needs z"),
    (lambda x: lp.quick(x, np.arange(3.0), z=np.ones((20, 3))), ValueError, "shape"),
    (lambda x: lp.quick(x, x, z=np.ones((20, 20)), color=x), TypeError, "color is for scatter"),
    (lambda x: lp.quick(x, x, "scatter", z=np.ones(3)), TypeError, "only used by heat maps"),
    (lambda x: lp.quick(x.reshape(4, 5), x.reshape(4, 5)), ValueError, "1-D"),
    (lambda x: lp.quick(x, x, title=None, index={"x": 1}), TypeError, "doesn't take"),
    (lambda x: lp.quick(x, x, "scatter", color=x[:2]), ValueError, "color has shape"),
    (lambda x: lp.quick(3.0, 4.0), ValueError, "single number"),
])
def test_quick_errors(call, exc, match):
    with pytest.raises(exc, match=match):
        call(np.linspace(0, 1, 20))


def test_quick_unsorted_curve_warns_about_the_axis():
    with pytest.warns(lbd.LBDWarning, match="not strictly increasing"):
        lp.quick(np.array([0.0, 2.0, 1.0]), np.array([1.0, 2.0, 3.0]))


def test_no_warnings_in_normal_use(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        d = sweep()
        lp.plot(d, "heatmap", "S21", complex="db")
        with lp.use("default"):
            fig, ax = plt.subplots()
            f, u = lp.prefix(d.axes["freq"].data, "Hz")
            ax.plot(f, np.abs(d["S21"].data[0]))
            ax.set_xlabel(lp.axis_label("Frequency", u))
            fig.savefig(tmp_path / "x.pdf")


def test_save_jpg_warns(tmp_path):
    fig, ax = lp.subplots()
    ax.plot([0, 1], [0, 1])
    with pytest.warns(lbd.LBDWarning, match="JPG compresses with loss"):
        p = lp.save(fig, tmp_path / "f.jpg")
    assert p.read_bytes()[:2] == b"\xff\xd8"
