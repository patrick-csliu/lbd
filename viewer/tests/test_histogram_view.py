"""The plot type Histogram in Explore: counting, settings, large files, cursors, the table."""

import json

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values
from lbd_viewer.explore import ExploreSession
from lbd_viewer.kinds import histogram as kind

WHOLE = {"kind": "histogram", "values": ["I"], "color": "none", "all": ["shot"]}


@pytest.fixture(autouse=True)
def fresh():
    kind.forget()
    yield
    kind.forget()


@pytest.fixture()
def iq(tmp_path):
    path = tmp_path / "iq.lbd"
    mock_values.single_shot_iq(True).save(path)
    return path


def session(path, spec, **kw):
    return ExploreSession(path, "v1", spec, lp.load_style(), 600, 400, 1.0, **kw)


def picture(s, settings=None):
    s.apply(settings or {})
    return s.render(None, None)[1]


def counts(s):
    return [c.counts for c in s.model.series]


def test_open_as_histogram(iq):
    s = session(iq, {"kind": "histogram", "values": ["I"]})
    assert s.kind == "histogram"
    assert s.spec["color"] == "state" and s.spec["all"] == ["shot"]
    meta = picture(s)
    assert meta["strips"] is None and not meta["reduced"]
    assert meta["note"].startswith("400 numbers in ")
    assert s.ax.get_ylabel() == "Count" and "I" in s.ax.get_xlabel()


def test_slider_changes_the_counts(iq):
    s = session(iq, {**WHOLE, "index": {"readout_power": 0, "state": 0}})
    picture(s)
    before = s.model.edges.copy()
    s.set_spec({**WHOLE, "index": {"readout_power": 1, "state": 0}})
    picture(s)
    assert not np.array_equal(before, s.model.edges)
    assert counts(s)[0].sum() == 200


def test_all_counts_every_step(iq):
    s = session(iq, {**WHOLE, "all": ["shot", "state", "readout_power"]})
    picture(s)
    assert counts(s)[0].sum() == 800


def test_colour_by_splits(iq):
    s = session(iq, {**WHOLE, "color": "state", "index": {"readout_power": 1}})
    picture(s)
    assert [c.label for c in s.model.series] == ["ground", "excited"]
    assert [int(c.sum()) for c in counts(s)] == [200, 200]
    assert [t.get_text() for t in s.ax.get_legend().get_texts()] == ["ground", "excited"]


def test_bad_bins_say_so(iq):
    with pytest.raises(ValueError, match="bins must be auto or a whole number"):
        session(iq, {**WHOLE, "options": {"bins": 1}})


def test_limits(iq):
    s = session(iq, {**WHOLE, "options": {"bins": 7}, "index": {"readout_power": 1, "state": 0}})
    meta = picture(s)
    (x0, x1), (y0, y1) = meta["full"]
    assert (x0, x1) == (s.model.edges[0], s.model.edges[-1])
    assert y0 == 0 and y1 == pytest.approx(counts(s)[0].max() * 1.05)
    meta = picture(s, {"yscale": "log"})
    assert meta["yscale"] == "log"
    assert meta["full"][1][0] == pytest.approx(counts(s)[0][counts(s)[0] > 0].min() / 2)


def test_zoom_doesnt_change_the_bins(iq):
    s = session(iq, {**WHOLE, "index": {"readout_power": 1, "state": 0}})
    picture(s)
    before = s.model.edges.copy()
    x0, x1 = s.full[0]
    s.render((x0, (x0 + x1) / 2), None)
    assert np.array_equal(before, s.model.edges)


def test_another_vertical_axis_needs_no_recount(iq, monkeypatch):
    s = session(iq, WHOLE | {"index": {"readout_power": 1, "state": 0}})
    picture(s)
    monkeypatch.setattr(kind.hist, "count", lambda *a, **k: pytest.fail("counted again"))
    s.set_spec({**WHOLE, "index": {"readout_power": 1, "state": 0}, "options": {"hist_y": "fraction", "hist_style": "outline"}})
    picture(s)
    assert s.ax.get_ylabel() == "Fraction" and s.full[1][1] < 1


def test_a_stale_log_horizontal_setting_is_ignored(iq):
    s = session(iq, WHOLE | {"index": {"readout_power": 1, "state": 0}})
    assert picture(s, {"xscale": "log"})["xscale"] == "linear"


def test_not_finite_numbers_and_empty_slices_are_told(tmp_path):
    d = lbd.Dataset()
    d.add_axis("a", [0.0, 1.0])
    d.add_axis("b", np.arange(4.0))
    d.add_value("x", np.array([[1.0, 2.0, 3.0, np.nan], [np.nan] * 4]), axes=["a", "b"])
    d.save(tmp_path / "x.lbd")
    s = session(tmp_path / "x.lbd", {"kind": "histogram", "all": ["b"], "index": {"a": 0}})
    meta = picture(s)
    assert meta["hidden"] == ["1 number isn't finite: not counted"] and meta["empty"] is None
    s.set_spec({"kind": "histogram", "all": ["b"], "index": {"a": 1}})
    meta = picture(s)
    assert "Nothing to show" in meta["empty"]


def test_a_single_number_is_greyed(client, data_dir):
    iq = data_dir / "iq.lbd"
    mock_values.single_shot_iq(True).save(iq)
    kinds = client.post("/api/kinds", json={"path": str(iq), "spec": {"values": ["amplitude"]}}).json()["kinds"]
    row = next(k for k in kinds if k["name"] == "histogram")
    assert "single number" in row["why"] and "amplitude" not in row["values"] and "I" in row["values"]
    assert row["explore"]


def test_the_server_answers_with_the_resolved_choice(client, data_dir):
    iq = data_dir / "iq.lbd"
    mock_values.single_shot_iq(True).save(iq)
    r = client.post("/api/explore", json={"path": str(iq), "spec": {"kind": "histogram", "values": ["I"]},
                                          "width": 400, "height": 300, "dpr": 1})
    r.raise_for_status()
    body = r.json()
    assert body["kind"] == "histogram" and body["spec"]["color"] == "state"
    r = client.post(f"/api/explore/{body['session']}/render", json={"format": "raw", "settings": {}})
    r.raise_for_status()
    assert json.loads(r.headers["X-LBD-Frame"])["ms"]
    bad = client.post(f"/api/explore/{body['session']}/spec", json={"spec": {"kind": "histogram", "options": {"bins": 0}}})
    assert bad.status_code == 400 and "bins must be" in bad.text
