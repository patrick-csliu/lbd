"""Plot types in an Explore session (lbd_viewer.kinds): one class per type, the session asks it."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd_viewer import kinds, reading
from lbd_viewer.explore import KINDS, ExploreError, ExploreSession


def session(tmp_path, spec, make=None):
    d = lbd.Dataset(title="t")
    d.add_axis("a", [1.0, 2.0, 3.0])
    d.add_axis("b", [1.0, 2.0])
    d.add_value("v", np.arange(6.0).reshape(3, 2), axes=["a", "b"])
    d.save(tmp_path / "x.lbd")
    return ExploreSession(tmp_path / "x.lbd", "v", spec, lp.load_style(), 600, 400, 1.0)


def test_the_two_kinds_have_their_class(tmp_path):
    assert {"curve", "heatmap"} <= set(KINDS)
    assert session(tmp_path, {"kind": "heatmap", "x": "a", "y": "b"}).view.kind == "heatmap"
    assert session(tmp_path, {"kind": "curve", "x": "a", "series": "b"}).view.kind == "curve"


def test_a_placeholder_is_refused_with_a_reason(tmp_path):
    with pytest.raises(ExploreError, match="Explore can't show Scatter plots yet"):
        session(tmp_path, {"kind": "scatter", "x": "a"})


VIEW = {"xlim": [0.0, 100.0], "ylim": [0.0, 1.0]}


def test_nearest_point_is_in_pixels():
    # in numbers the first is nearer; on a plot 100 wide and 1 high, the second is
    assert reading.nearest_point([50.0, 53.0], [0.9, 0.5], 50.0, 0.5, VIEW, (500, 500)) == 1


def test_nearest_point_on_log_axes():
    view = {"xlim": [1.0, 1000.0], "ylim": [0.0, 1.0], "xscale": "log"}
    # 40 is nearer 2 in numbers, nearer 500 on a log axis
    assert reading.nearest_point([2.0, 500.0], [0.5, 0.5], 40.0, 0.5, view, (300, 300)) == 1


def test_nearest_point_skips_nan():
    assert reading.nearest_point([50.0, 10.0], [np.nan, 0.5], 50.0, 0.5, VIEW, (500, 500)) == 1
    assert reading.nearest_point([np.nan], [np.nan], 0.0, 0.0, VIEW, (500, 500)) is None


def test_operations_refused_where_not_available(tmp_path, monkeypatch):
    s = session(tmp_path, {"kind": "heatmap", "x": "a", "y": "b"})
    monkeypatch.setattr(type(s.view), "operations", False)
    with pytest.raises(ExploreError, match="Operations aren't available"):
        s.apply({"ops": [{"op": "normalize", "on": True}]})


def test_the_view_adds_notes_and_meta(tmp_path, monkeypatch):
    s = session(tmp_path, {"kind": "heatmap", "x": "a", "y": "b"})
    monkeypatch.setattr(type(s.view), "notes", lambda self: ["a note"])
    monkeypatch.setattr(type(s.view), "meta", lambda self: {"extra": 1})
    assert s.take_notes() == ["a note"]
    assert s.render(None, None)[1]["extra"] == 1


def test_a_panel_without_axes_to_share_has_no_sync(tmp_path, monkeypatch):
    s = session(tmp_path, {"kind": "heatmap", "x": "a", "y": "b"})
    monkeypatch.setattr(type(s.view), "syncs", False)
    assert s.sync_keys() == {}


def kinds_of(client, path, spec=None):
    r = client.post("/api/kinds", json={"path": str(path), "spec": spec or {}})
    r.raise_for_status()
    return {k["name"]: k for k in r.json()["kinds"]}


@pytest.fixture()
def file_with_two(data_dir):
    d = lbd.Dataset(title="two")
    d.add_axis("a", [1.0, 2.0, 3.0])
    d.add_axis("b", [1.0, 2.0])
    d.add_value("line", [1.0, 2.0, 3.0], axes="a")
    d.add_value("map", np.arange(6.0).reshape(3, 2), axes=["a", "b"])
    d.save(data_dir / "two.lbd")
    return data_dir / "two.lbd"


def test_kinds_says_why_not(client, file_with_two):
    k = kinds_of(client, file_with_two, {"values": ["line"]})
    assert k["curve"]["why"] is None and "2 dimensions" in k["heatmap"]["why"]
    assert k["curve"]["explore"] and not k["scatter"]["explore"]


def test_kinds_lists_the_values_that_fit(client, file_with_two):
    assert kinds_of(client, file_with_two)["heatmap"]["values"] == ["map"]


def test_kinds_reads_no_data(client, file_with_two, monkeypatch):
    monkeypatch.setattr(lbd, "load", lambda *a, **k: pytest.fail("data was read"))
    kinds_of(client, file_with_two)
