"""Annotations in a plot spec (matplotlib calls drawn on the plot), and the matplotlib version
recorded with a saved view."""

import warnings

import h5py
import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, Rectangle  # noqa: E402

import lbd  # noqa: E402
import lbd.plot as lp  # noqa: E402
from lbd.plot.render import RenderError, RenderWarning, check_annotations  # noqa: E402

MHZ = {"quantities": {"freq": {"prefix": "M"}}}     # fixed units: annotations are in MHz


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def sweep():
    d = lbd.Dataset("sweep")
    f = np.linspace(6.99e9, 7.01e9, 101)
    p = np.array([-60.0, -40.0, -20.0])
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", 1 - 0.8 * np.exp(-((f[None, :] - 7e9) / 1e6) ** 2) + 0 * p[:, None],
                axes=["power", "freq"], label="|S21|")
    d.add_value("trace", np.cos(np.linspace(0, 6, 101)), axes=["freq"], label="Trace")
    d.add_value("Q", 1.2e5, label="Q")
    return d


# ---- checks -------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad, match", [
    ({"method": "axvlin"}, "no method 'axvlin'; did you mean axvline"),
    ({"method": "get_xlim"}, "can't be used"),
    ({"method": "clear"}, "can't be used"),
    ({"method": "cla"}, "can't be used"),
    ({"method": "_request_autoscale_view"}, "no method"),
    ({"method": "figure.savefig"}, "no method"),
    ({"method": 3}, "method must be text"),
    ({"patch": "Rectangl"}, "no shape 'Rectangl'; did you mean Rectangle"),
    ({"patch": "Patch3D"}, "no shape"),
    ({"patch": 1}, "patch must be text"),
    ({"method": "axvline", "patch": "Rectangle"}, "exactly one"),
    ({"args": [1]}, "exactly one"),
    ({"method": "axvline", "args": 1}, "args must be a list"),
    ({"method": "axvline", "kwargs": [1]}, "kwargs must be an object"),
    ({"method": "axvline", "colour": "red"}, "unknown key"),
    ("axvline", "must be an object"),
])
def test_bad_entries_are_errors(bad, match):
    with pytest.raises(RenderError, match=match):
        check_annotations([bad])


def test_must_be_a_list():
    with pytest.raises(RenderError, match="must be a list"):
        check_annotations({"method": "axvline"})


def test_good_entries_pass():
    items = [{"method": "axvline", "args": [1]}, {"method": "set_xlim", "args": [0, 1]},
             {"patch": "Rectangle", "args": [[0, 0], 1, 1], "kwargs": {"fill": False}}]
    assert check_annotations(items) == items


# ---- drawing ------------------------------------------------------------------------------------


def test_methods_are_called_on_the_axes():
    d = sweep()
    fig = lp.plot(d, "curve", "trace", style=MHZ, annotations=[
        {"method": "axvline", "args": [7000], "kwargs": {"ls": ":"}},
        {"method": "axhspan", "args": [-0.5, 0.5], "kwargs": {"alpha": 0.1}},
        {"method": "text", "args": [6995, 0.8, "$T_2^*$ = 12 µs"]},
        {"method": "annotate", "args": ["dip"], "kwargs": {"xy": [7000, 0], "xytext": [0.1, 0.9],
                                                           "textcoords": "axes fraction",
                                                           "arrowprops": {"arrowstyle": "->"}}},
    ])
    ax = fig.axes[0]
    texts = [t.get_text() for t in ax.texts]
    assert "$T_2^*$ = 12 µs" in texts and "dip" in texts
    assert any(list(line.get_xdata()) == [7000, 7000] for line in ax.lines)
    assert ax.get_legend() is None                       # one curve, no labelled annotation


def test_labelled_annotation_joins_the_legend():
    fig = lp.plot(sweep(), "curve", "trace", style=MHZ, annotations=[
        {"method": "plot", "args": [[7000], [1]], "kwargs": {"marker": "o", "ls": "", "label": "peak"}}])
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert labels == ["Trace", "peak"]


@pytest.mark.parametrize("kind, values", [("curve", "trace"), ("heatmap", "S21"), ("scatter", "trace")])
def test_patches_on_every_kind(kind, values):
    fig = lp.plot(sweep(), kind, values, style=MHZ, annotations=[
        {"patch": "Rectangle", "args": [[6995, -50], 10, 20], "kwargs": {"fill": False}},
        {"patch": "Ellipse", "args": [[7000, -40], 4, 10]}])
    ax = fig.axes[0]
    kinds = [type(p) for p in ax.patches]
    assert Rectangle in kinds and Ellipse in kinds


def test_scalar_gets_annotations_too():
    fig = lp.plot(sweep(), "scalar", "Q", annotations=[
        {"method": "text", "args": [0.5, 0.2, "fitted"], "kwargs": {"ha": "center"}}])
    assert "fitted" in [t.get_text() for t in fig.axes[0].texts]


def test_matplotlib_errors_name_the_entry():
    with pytest.raises(RenderError, match=r"annotations\[1\] \(axvline\): AttributeError"):
        lp.plot(sweep(), "curve", "trace", style=MHZ, annotations=[
            {"method": "axvline", "args": [7000]},
            {"method": "axvline", "args": [7000], "kwargs": {"colour_typo": "red"}}])
    with pytest.raises(RenderError, match=r"annotations\[0\] \(Rectangle\)"):
        lp.plot(sweep(), "curve", "trace", style=MHZ, annotations=[{"patch": "Rectangle", "args": [1]}])


def test_error_mentions_a_different_matplotlib_version():
    d = sweep()
    d.matplotlib = "1.0.0"
    with pytest.raises(RenderError, match="saved with matplotlib 1.0.0"):
        lp.plot(d, "curve", "trace", style=MHZ, annotations=[{"method": "axvline", "kwargs": {"nope": 1}}])


# ---- units ------------------------------------------------------------------------------------


def test_automatic_prefix_warns():
    with pytest.warns(RenderWarning, match="'freq' \\(now GHz\\) is chosen automatically"):
        lp.plot(sweep(), "curve", "trace", annotations=[{"method": "axvline", "args": [7.0]}])


def test_fixed_prefix_or_no_prefix_is_quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        lp.plot(sweep(), "curve", "trace", style=MHZ, annotations=[{"method": "axvline", "args": [7000]}])
        no_auto = {"figure": {"axes": {"axis": {"label": {"auto_prefix": False}}}}}
        lp.plot(sweep(), "curve", "trace", style=no_auto, annotations=[{"method": "axvline", "args": [7e9]}])
        lp.plot(sweep(), "curve", "trace")                 # no annotations: no warning either


# ---- saved view ---------------------------------------------------------------------------------


def test_saved_annotations_are_drawn(tmp_path):
    p = tmp_path / "s.lbd"
    sweep().save(p)
    ann = [{"method": "axvline", "args": [7000]}]
    lbd.set_plot(p, spec={"kind": "curve", "values": ["trace"], "annotations": ann}, style=MHZ)
    assert lbd.load(p).plot["annotations"] == ann
    fig = lp.plot(p)
    assert any(list(line.get_xdata()) == [7000, 7000] for line in fig.axes[0].lines)


def test_broken_saved_annotations_warn_and_are_skipped(tmp_path):
    p = tmp_path / "s.lbd"
    d = sweep()
    d.plot = {"kind": "curve", "values": ["trace"], "annotations": [{"method": "no_such_method"}]}
    d.save(p)
    with pytest.warns(RenderWarning, match="no_such_method"):
        fig = lp.plot(p)
    assert fig.axes[0].lines


def test_explicit_empty_list_overrides_the_saved_one(tmp_path):
    p = tmp_path / "s.lbd"
    d = sweep()
    d.plot = {"kind": "curve", "values": ["trace"], "annotations": [{"method": "axvline", "args": [7.0]}]}
    d.save(p)
    fig = lp.plot(p, annotations=[])
    assert len(fig.axes[0].lines) == 1


@pytest.mark.parametrize("bad", ["axvline", [1], {"method": "axvline"}])
def test_files_only_take_a_list_of_objects(tmp_path, bad):
    with pytest.raises(lbd.LBDError, match="annotations must be a list"):
        lbd.set_plot(tmp_path / "x.lbd", spec={"annotations": bad})


# ---- matplotlib version -----------------------------------------------------------------------


def test_version_written_with_the_saved_view(tmp_path):
    p = tmp_path / "s.lbd"
    d = sweep()
    d.save(p)
    assert lbd.load(p).matplotlib is None                 # no saved view: no version
    lbd.set_plot(p, spec={"kind": "curve"})
    assert lbd.load(p).matplotlib == matplotlib.__version__
    lbd.set_plot(p, spec=None)                            # the view removed: the group goes too
    with h5py.File(p) as f:
        assert "plot" not in f
    d.style_name = "thesis"
    d.save(p)
    assert lbd.load(p).matplotlib == matplotlib.__version__


def test_version_kept_when_matplotlib_is_missing(tmp_path, monkeypatch):
    import lbd.io

    p = tmp_path / "s.lbd"
    d = sweep()
    d.plot = {"kind": "curve"}
    d.matplotlib = "3.0.0"
    monkeypatch.setattr(lbd.io, "_matplotlib_version", lambda: None)
    d.save(p)
    assert lbd.load(p).matplotlib == "3.0.0"
