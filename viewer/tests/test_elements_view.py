"""The viewer shows elements and data points (format 1.2, plan 6a): legends, ticks, sliders,
cursor read-outs, the file summary and the Library's sweep size."""

import os

import lbd
import numpy as np
import pytest

from lbd.plot import render as rnd
from lbd.plot.style import Style
from lbd_viewer import library, reading
from lbd_viewer.explore import ExploreSession
from lbd_viewer.server import file_summary


@pytest.fixture()
def files(values_files):
    return {p.name: p for p in values_files}


def test_a_vector_per_point_is_curves_against_the_sweep(files):
    d = lbd.load(files["12 tomography.lbd"])
    spec = rnd.resolve_spec(d, {"values": ["bloch"]}, warn_unused=False)
    assert spec["kind"] == "curve" and spec["x"] == "amp" and spec["series"] == "bloch_dim1"
    model = rnd.prepare_curves(d, spec, Style())
    assert [label for _, label in model.lines] == ["x", "y", "z"]
    cov = rnd.resolve_spec(d, {"values": ["cov"]}, warn_unused=False)
    assert cov["kind"] == "curve" and cov["x"] == "amp" and cov["series"] == "cov_dim1"
    assert any(s["axis"] == "cov_dim2" and s["text"] == "I" and s["elements"] == ["I", "Q"] for s in cov["slices"])


def test_an_axis_with_elements_names_its_ticks_and_legend(files):
    d = lbd.load(files["11 single shot iq.lbd"])
    spec = rnd.resolve_spec(d, {"values": ["I"], "kind": "heatmap", "x": "shot", "y": "state"}, warn_unused=False)
    model = rnd.prepare_map(d, spec, Style())
    assert model.y_ticks is not None and model.y_ticks[1] == ["ground", "excited"]
    assert model.x_ticks is None
    curves = rnd.resolve_spec(d, {"values": ["I"], "kind": "curve", "x": "shot", "series": "state"}, warn_unused=False)
    labels = [label for _, label in rnd.prepare_curves(d, curves, Style()).lines]
    assert labels == ["Prepared state = ground", "Prepared state = excited"]
    svg, _ = rnd.render_file(str(files["11 single shot iq.lbd"]), {"values": ["I"], "kind": "heatmap", "x": "shot",
                                                                   "y": "state"}, Style(), fmt="svg")
    assert b"excited" in svg


def test_many_elements_show_every_kth(tmp_path):
    d = lbd.Dataset()
    d.add_axis("device", elements=[f"Q{i}" for i in range(40)])
    d.add_axis("t", np.linspace(0, 1, 5))
    d.add_value("v", np.zeros((40, 5)), axes=["device", "t"])
    d.save(tmp_path / "many.lbd")
    d = lbd.load(tmp_path / "many.lbd")
    spec = rnd.resolve_spec(d, {"values": ["v"], "kind": "heatmap", "x": "t", "y": "device"}, warn_unused=False)
    ticks = rnd.prepare_map(d, spec, Style()).y_ticks
    assert len(ticks[1]) <= rnd.MAX_ELEMENT_TICKS and ticks[1][0] == "Q0"


def test_a_cursor_reads_the_element(files):
    p = files["11 single shot iq.lbd"]
    s = ExploreSession(p, "v", {"values": ["I"], "kind": "heatmap", "x": "shot", "y": "state"}, Style(), 400, 300, 1)
    try:
        assert reading._axis_item(s, "y", "state", 1)["text"] == "excited"
        assert reading._axis_item(s, "x", "shot", 3)["text"] is None
    finally:
        s.close()


def test_the_file_summary_and_the_library_know_data_points(files):
    summary = file_summary(lbd.info(files["12 tomography.lbd"]))
    axes = {a["name"]: a for a in summary["axes"]}
    assert axes["bloch_dim1"]["role"] == "point" and axes["bloch_dim1"]["elements"] == ["x", "y", "z"]
    assert axes["amp"]["role"] is None and axes["amp"]["elements"] is None
    bloch = next(v for v in summary["values"] if v["name"] == "bloch")
    assert bloch["point_axes"] == ["bloch_dim1"]
    p = files["12 tomography.lbd"]
    row = library.row_from_summary(p, str(p.parent), os.stat(p), summary)
    assert row["sweep"] == str(axes["amp"]["length"])          # the sweep, not the data point's 3 or 2×2
