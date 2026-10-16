"""Tests for lbd.plot (styles, style files, the plotting API, scatter). Needs lbd[plot]."""

import io
import json

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

import lbd  # noqa: E402
import lbd.plot as lp  # noqa: E402
from lbd.plot import render as rnd  # noqa: E402
from lbd.plot.presets import PresetStore  # noqa: E402
from lbd.plot.style import Style, StyleError, from_dict  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path / "config"))
    yield
    plt.close("all")


def sweep():
    f = np.linspace(6.99e9, 7.01e9, 40)
    p = np.arange(-60, 1, 10.0)
    z = 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 1e6) * np.ones((len(p), 1))
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", z, axes=["power", "freq"])
    d.add_value("T", 0.02 + 0.001 * np.abs(z), axes=["power", "freq"], unit="K", label="Temperature")
    return d


# ---- styles ------------------------------------------------------------------------


def test_default_style_follows_aps_and_aip():
    """The built-in default meets the figure rules of APS and AIP journals (see the docs)."""
    s = Style()
    rc = s.to_rcparams()
    assert (s.figure.width_mm, s.figure.height_mm) == (85, 64)           # AIP: 1 column <= 8.5 cm
    assert s.figure.dpi == 600
    assert rc["font.family"] == ["Arial"] and rc["font.size"] == 10
    for key in ("axes.labelsize", "axes.titlesize", "legend.fontsize", "xtick.labelsize", "ytick.labelsize"):
        assert rc[key] == "medium", key                                    # all text = the font size (>= 8 pt)
    for key in ("axes.linewidth", "xtick.major.width", "ytick.major.width", "xtick.minor.width",
                "ytick.minor.width", "grid.linewidth", "lines.linewidth"):
        assert rc[key] >= 0.5, key                                         # APS & AIP: lines >= 0.5 pt
    assert rc["axes.prop_cycle"].by_key()["color"][:3] == ["#000000", "#0072B2", "#E69F00"]
    assert s.figure.axes.axis.label.unit_format == "paren"                  # APS: units in parentheses
    assert rc["image.cmap"] == "viridis" and rc["pdf.fonttype"] == 42 and rc["axes.formatter.useoffset"] is False


def test_axis_overrides():
    s = from_dict({"figure": {"axes": {"axis": {"ticks": {"direction": "out"}},
                                       "yaxis": {"ticks": {"direction": "in"}, "label": {"size_pt": 12}}}}})
    assert s.axis_style("x").ticks.direction == "out"
    assert s.axis_style("y").ticks.direction == "in"
    rc = s.to_rcparams()
    assert rc["xtick.direction"] == "out" and rc["ytick.direction"] == "in"


def test_invalid_style_names_the_key():
    with pytest.raises(StyleError, match="figure.font.size_pt"):
        from_dict({"figure": {"font": {"size_pt": -1}}})


def test_style_file_roundtrip(tmp_path):
    s = from_dict({"figure": {"width_mm": 120, "axes": {"colors": ["#ff0000"]}}, "quantities": {"T": {"vmin": 1}}})
    s.name = "mine"
    p = s.save(tmp_path / "mine.lbd.json")
    assert json.loads(p.read_text())["lbd_style"] == 2
    back = Style.load(p)
    assert back.model_dump() == s.model_dump()
    assert lp.load_style(p).figure.width_mm == 120


def test_mplstyle_export_reproduces_rcparams(tmp_path):
    s = from_dict({"figure": {"width_mm": 120, "height_mm": 80, "dpi": 300, "font": {"size_pt": 11},
                              "axes": {"frame": {"linewidth_pt": 1.1}, "lines": {"width_pt": 2},
                                       "colors": ["#123456", "#abcdef"]}}})
    path = tmp_path / "x.mplstyle"
    path.write_text(s.to_mplstyle(), encoding="utf-8")
    rc = s.to_rcparams()
    with matplotlib.rc_context(fname=str(path)):
        got = matplotlib.rcParams
        assert tuple(got["figure.figsize"]) == pytest.approx(rc["figure.figsize"])
        assert got["savefig.dpi"] == 300
        assert got["font.size"] == 11
        assert got["axes.linewidth"] == pytest.approx(1.1)
        assert got["lines.linewidth"] == 2
        assert got["axes.prop_cycle"].by_key()["color"] == ["#123456", "#abcdef"]
        assert got["xtick.direction"] == "in" and got["font.family"][0] == "Arial"


# ---- presets ------------------------------------------------------------------------


def test_presets_are_shared(tmp_path):
    store = PresetStore()
    store.save("thesis", {"figure": {"font": {"size_pt": 10}}})
    assert "thesis" in lp.list_styles()
    assert lp.load_style("thesis").figure.font.size_pt == 10
    with pytest.raises(StyleError, match="already exists"):
        store.import_file("thesis", {})
    with pytest.raises(StyleError, match="no style preset"):
        lp.load_style("nope")


def test_default_style_follows_viewer_setting(tmp_path):
    PresetStore().save("big", {"figure": {"width_mm": 150}})
    import os
    from pathlib import Path

    (Path(os.environ["LBD_CONFIG_DIR"]) / "settings.json").write_text(json.dumps({"default_style": "big"}))
    assert lp.default_style().figure.width_mm == 150
    assert lp.load_style().name == "big"


# ---- hand-made figures ------------------------------------------------------------


def test_use_gives_exact_size_and_settings():
    with lp.use({"figure": {"width_mm": 50.8, "height_mm": 25.4, "font": {"size_pt": 9}}}) as s:
        fig, ax = plt.subplots()
        assert fig.get_size_inches() == pytest.approx((2.0, 1.0))
        assert matplotlib.rcParams["font.size"] == 9
        assert s.figure.width_mm == 50.8
    assert matplotlib.rcParams["font.size"] != 9 or matplotlib.rcParamsDefault["font.size"] == 9


def test_subplots_save_and_apply(tmp_path):
    fig, axs = lp.subplots(1, 2, style={"figure": {"width_mm": 101.6, "height_mm": 50.8, "dpi": 100}})
    axs[0].plot([1, 2, 3])
    lp.apply(fig, {"figure": {"axes": {"frame": {"linewidth_pt": 2.0, "top": False}}}})
    assert axs[0].spines["left"].get_linewidth() == 2.0
    assert not axs[0].spines["top"].get_visible()
    out = lp.save(fig, tmp_path / "f.png", style={"figure": {"dpi": 100}}, title="demo")
    img = Image.open(out)
    assert img.size == (400, 200)                    # 4 x 2 in at 100 dpi, never cropped
    assert img.text["Title"] == "demo" and img.text["Software"].startswith("LBD ")


def test_prefix_and_axis_label():
    v, u = lp.prefix([7e9, 7.1e9], "Hz")
    assert u == "GHz" and v[0] == pytest.approx(7.0)
    assert lp.axis_label("Frequency", "GHz", style={"figure": {"axes": {"axis": {"label": {"unit_format": "slash"}}}}}) \
        == "Frequency / GHz"


# ---- the tool's plot types -----------------------------------------------------------


def _png(fig, style, tmp_path):
    # lp.save, not fig.savefig: matplotlib reads some settings (e.g. minus signs) while drawing
    out = lp.save(fig, tmp_path / "mine.png", style=style)
    return np.asarray(Image.open(out).convert("RGB"))


def test_plot_in_memory_matches_the_viewer(tmp_path):
    """lp.plot on a Dataset that was never saved draws exactly what the viewer exports."""
    d = sweep()
    style = {"figure": {"dpi": 100}}
    fig = lp.plot(d, kind="heatmap", values="S21", complex="db", style=style)
    mine = _png(fig, style, tmp_path)
    path = d.save(tmp_path / "s.lbd")
    data, _ = rnd.render_file(path, {"kind": "heatmap", "values": ["S21"], "complex": "db"},
                              from_dict(style), fmt="png", display=False)
    theirs = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    assert mine.shape == theirs.shape
    assert np.array_equal(mine, theirs)


def test_plot_file_uses_saved_view(tmp_path):
    d = sweep()
    d.plot = {"kind": "curve", "values": ["S21"], "complex": "phase", "series": "none"}
    d.style = {"figure": {"width_mm": 120}}
    p = d.save(tmp_path / "v.lbd")
    fig = lp.plot(p)
    assert fig.get_size_inches()[0] * 25.4 == pytest.approx(120)
    assert len(fig.axes[0].lines) == 1                         # series "none": one curve


def test_plot_into_existing_axes():
    fig, (a1, a2) = plt.subplots(1, 2)
    d = sweep()
    assert lp.plot(d, "curve", "T", series="none", ax=a1) is a1
    lp.plot(d, "heatmap", "S21", ax=a2, style="default")
    assert len(a1.lines) == 1 and len(a2.collections) == 1


def test_plot_rejects_unknown_settings():
    with pytest.raises(TypeError, match="unknown plot setting"):
        lp.plot(sweep(), colour="T")


# ---- scatter -----------------------------------------------------------------------


def test_scatter_value_vs_axis():
    fig = lp.plot(sweep(), "scatter", "T")
    pc = fig.axes[0].collections[0]
    assert pc.get_offsets().shape == (7 * 40, 2)               # every point of the 2-D value


def test_scatter_value_vs_value_with_color_by_axis():
    fig = lp.plot(sweep(), "scatter", "T", x="S21", color="power",
                  style={"quantities": {"power": {"vmin": -60, "vmax": 0, "cmap": "magma"}}})
    ax = fig.axes[0]
    pc = ax.collections[0]
    assert pc.norm.vmin == -60 and pc.norm.vmax == 0 and pc.cmap.name == "magma"
    assert len(fig.axes) == 2                                   # colour bar
    assert "Power" in fig.axes[1].get_ylabel()


def test_scatter_iq_plane():
    fig = lp.plot(sweep(), "scatter", "S21", complex="iq", color="T")
    ax = fig.axes[0]
    assert ax.get_aspect() == 1.0
    assert ax.get_xlabel().startswith("Re S21") and ax.get_ylabel().startswith("Im S21")


def test_scatter_errors():
    with pytest.raises(lp.RenderError, match="not complex"):
        lp.plot(sweep(), "scatter", "T", complex="iq")
    with pytest.raises(lp.RenderError, match="horizontal"):
        lp.plot(sweep(), "scatter", "T", x="nope")


def test_scatter_index_fixes_an_axis():
    fig = lp.plot(sweep(), "scatter", "T", index={"power": 2})
    assert fig.axes[0].collections[0].get_offsets().shape == (40, 2)


def test_quick():
    x = np.linspace(0, 1, 20)
    fig = lp.quick(x, {"a": x, "b": x ** 2}, x_label="Time", x_unit="s", y_label="Signal", y_unit="V")
    ax = fig.axes[0]
    assert len(ax.lines) == 2 and ax.get_legend() is not None
    assert ax.get_ylabel() == "Signal (V)"
    i, q = np.random.default_rng(0).normal(size=(2, 200))
    fig = lp.quick(i, q, kind="scatter", color=np.hypot(i, q), x_label="I", y_label="Q")
    assert fig.axes[0].collections[0].get_offsets().shape == (200, 2)
    fig = lp.quick(x, np.arange(3.0), z=np.ones((3, 20)), z_label="Z")
    assert len(fig.axes) == 2
