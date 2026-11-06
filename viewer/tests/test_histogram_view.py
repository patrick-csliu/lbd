"""The plot type Histogram in Explore: counting, settings, large files, cursors, the table."""

import json
import threading
import time
import tracemalloc

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values
from lbd.plot import histogram as hist
from lbd.plot import render as rnd
from lbd_viewer import crange
from lbd_viewer.explore import ExploreError, ExploreSession
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
    monkeypatch.setattr(hist, "blocks", lambda *a, **k: pytest.fail("counted again"))
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


# -- large files, in the background ---------------------------------------------------------------

BIG = {"kind": "histogram", "values": ["x"], "color": "none", "all": ["a", "b"]}


@pytest.fixture()
def big(tmp_path, monkeypatch):
    """A value counted as large: every count goes to the background, in blocks of 500 numbers."""
    d = lbd.Dataset()
    d.add_axis("a", np.arange(10.0))
    d.add_axis("b", np.arange(1000.0))
    d.add_value("x", np.random.default_rng(5).normal(size=(10, 1000)), axes=["a", "b"], unit="V")
    d.save(tmp_path / "big.lbd")
    monkeypatch.setattr(kind, "QUICK", 0)
    monkeypatch.setattr(hist, "BLOCK", 500)
    return tmp_path / "big.lbd"


class Gate:
    """`hist.blocks` that stops at block `after` of call `call` (1: the first pass) until opened."""

    def __init__(self, monkeypatch, call=1, after=1):
        self.reached, self.open, self.calls = threading.Event(), threading.Event(), 0
        real = hist.blocks

        def gated(*a, **k):
            self.calls += 1
            for i, item in enumerate(real(*a, **k)):
                if self.calls == call and i == after:
                    self.reached.set()
                    assert self.open.wait(30)
                yield item

        monkeypatch.setattr(hist, "blocks", gated)


def finished(s, settings=None):
    for _ in range(1200):                                            # up to 60 s (a busy computer)
        meta = picture(s, settings)
        if not (meta["crange"] or {}).get("state") == "working":
            return meta
        time.sleep(0.05)
    raise AssertionError("still counting")


def test_large_file_counts_in_the_background_and_equals_the_whole(big):
    s = session(big, BIG)
    finished(s)
    whole = lbd.load(big)
    want = hist.count(rnd.flat(whole), s.spec)
    assert np.allclose(s.model.edges / s.model.xf, want.edges)
    assert np.array_equal(counts(s)[0], want.counts[0]) and counts(s)[0].sum() == 10_000


def test_progress_then_the_result_is_kept(big, monkeypatch):
    gate = Gate(monkeypatch)
    s = session(big, BIG)
    assert gate.reached.wait(30)
    meta = picture(s)
    assert meta["crange"]["state"] == "working" and meta["crange"]["from"] == "histogram"
    assert 0 < meta["crange"]["fraction"] < 1 and meta["note"].startswith("Counting")
    assert counts(s)[0].sum() == 0                                 # the bins aren't known yet: empty axes
    assert meta["empty"] is None
    gate.open.set()
    assert finished(s)["crange"] is None
    again = session(big, BIG)
    assert picture(again)["crange"] is None and counts(again)[0].sum() == 10_000


def test_partial_counts_are_shown(big, monkeypatch):
    gate = Gate(monkeypatch, call=2, after=3)
    s = session(big, BIG)
    assert gate.reached.wait(30)
    meta = picture(s)
    assert 0 < counts(s)[0].sum() < 10_000 and meta["crange"]["state"] == "working"
    assert meta["full"][1][1] > 0                                  # the view follows the bars
    gate.open.set()
    finished(s)
    assert counts(s)[0].sum() == 10_000


def test_a_new_slider_position_cancels_the_old_count(big, monkeypatch):
    gate = Gate(monkeypatch)
    s = session(big, BIG)
    assert gate.reached.wait(30)
    job = next(iter(kind._jobs.values()))
    s.set_spec({**BIG, "all": ["b"], "index": {"a": 3}})
    assert job.cancelled
    gate.open.set()
    finished(s)
    assert counts(s)[0].sum() == 1000


def test_another_panel_keeps_the_count_alive(big, monkeypatch):
    gate = Gate(monkeypatch)
    s, other = session(big, BIG), session(big, BIG)
    assert gate.reached.wait(30)
    job = next(iter(kind._jobs.values()))
    s.set_spec({**BIG, "all": ["b"], "index": {"a": 3}})
    assert not job.cancelled
    gate.open.set()
    finished(other)
    assert counts(other)[0].sum() == 10_000


def test_the_servers_end_reaches_the_counts(big, monkeypatch):
    gate = Gate(monkeypatch)
    session(big, BIG)
    assert gate.reached.wait(30)
    job = next(iter(kind._jobs.values()))
    crange.cancel_all()
    assert job.cancelled
    gate.open.set()
    crange.forget()
    assert not kind._jobs


def test_failure_says_why(big, monkeypatch):
    def broken(*a, **k):
        raise OSError("the disk went away")
        yield

    monkeypatch.setattr(hist, "blocks", broken)
    s = session(big, BIG)
    meta = finished(s)
    assert meta["crange"]["state"] == "failed"
    assert "couldn't be counted (the disk went away)" in meta["empty"]
    assert counts(s)[0].sum() == 0 and "numbers" not in meta["hidden"]


def test_a_new_file_version_counts_again(big, monkeypatch):
    finished(session(big, BIG))
    s = ExploreSession(big, "v2", BIG, lp.load_style(), 600, 400, 1.0)
    assert picture(s)["crange"] is not None or len(kind._results) == 2
    finished(s)
    assert len(kind._results) == 2


def test_memory_stays_small(tmp_path, monkeypatch):
    """Only the bins, a sample and one block are held, not the numbers."""
    n = 2_000_000
    d = lbd.Dataset()
    d.add_axis("a", np.arange(200.0))
    d.add_axis("b", np.arange(n / 200))
    d.add_value("x", np.random.default_rng(6).normal(size=(200, n // 200)), axes=["a", "b"])
    d.save(tmp_path / "m.lbd")
    monkeypatch.setattr(hist, "BLOCK", 2 ** 14)
    spec = rnd.resolve_spec(lbd.info(tmp_path / "m.lbd"), {**BIG, "options": {"bins": 100}}, warn_unused=False)
    tracemalloc.start()
    try:
        opened = rnd.flat(lbd.open(tmp_path / "m.lbd", hold=False))
        counted = kind._two_passes(kind.Job(2 * n), lambda: hist.blocks(opened, spec, hist.BLOCK), opened, spec)
        opened.close()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert counted.counts[0].sum() == n
    assert peak < n * 8 / 3


# -- after operations and equations ----------------------------------------------------------------

ONE = {"kind": "histogram", "values": ["I"], "color": "none", "all": ["shot"], "index": {"readout_power": 1, "state": 0}}


def test_operations_come_first(iq):
    s = session(iq, ONE)
    finished(s)
    raw = s.model.edges.copy()
    meta = finished(s, {"ops": [{"op": "normalize"}]})
    i = lbd.load(iq).values["I"].data[1, 0]
    assert not np.array_equal(raw, s.model.edges)
    assert s.model.edges[0] / s.model.xf == pytest.approx(((i - i.mean()) / i.std()).min(), rel=0.02)
    assert counts(s)[0].sum() == 200 and meta["ops"]["applied"] == 1
    assert meta["ops"]["notes"] == [None]
    assert "mean" in s.ax.get_xlabel()
    meta = finished(s, {"ops": [{"op": "normalize", "on": False}]})           # off: the stored numbers
    assert np.array_equal(raw, s.model.edges) and meta["ops"]["notes"] == ["off"]


def test_equation_comes_first(iq):
    s = session(iq, ONE)
    finished(s)
    top = s.model.edges[-1] / s.model.xf
    meta = finished(s, {"equations": {"y": "y * 2"}})
    assert s.model.edges[-1] / s.model.xf == pytest.approx(2 * top)
    assert meta["ops"]["equations"]["y"] == {} or "error" not in meta["ops"]["equations"]["y"]


def test_the_page_has_the_names_for_equations(iq):
    meta = picture(session(iq, ONE))
    assert any(n["name"] == "y" for n in meta["ops"]["names"]) and meta["ops"]["applied"] == 0


def test_an_iq_histogram_operation_is_refused(iq):
    s = session(iq, {**ONE, "values": ["IQ"]})
    with pytest.raises(ExploreError, match="I/Q histogram makes a map"):
        s.apply({"ops": [{"op": "iq_histogram", "bins": 20}]})
    s.apply({"ops": [{"op": "iq_histogram", "bins": 20, "on": False}]})


def test_a_chain_on_all_steps_equals_each_step_counted(iq):
    ops = {"ops": [{"op": "subtract_mean"}]}
    s = session(iq, {**ONE, "color": "state", "all": ["shot", "readout_power"], "index": {}, "options": {"bins": 9}})
    finished(s, ops)
    assert [int(c.sum()) for c in counts(s)] == [400, 400]
    data = lbd.load(iq).values["I"].data
    edges = s.model.edges / s.model.xf
    for state in (0, 1):
        want = sum(np.histogram(data[p, state] - data[p, state].mean(), edges)[0] for p in range(2))
        assert np.abs(counts(s)[state] - want).sum() <= 2                # (numbers exactly on an edge may round)


def test_operations_in_the_background_equal_at_once(iq, monkeypatch):
    ops = {"ops": [{"op": "subtract_mean"}]}
    spec = {**ONE, "all": ["shot", "state"], "index": {"readout_power": 0}}
    s = session(iq, spec)
    finished(s, ops)
    want = counts(s)[0].copy()
    kind.forget()
    monkeypatch.setattr(kind, "OPS_QUICK", 0)
    other = session(iq, spec)
    meta = picture(other, ops)
    assert meta["crange"] is None or meta["crange"]["from"] == "histogram"
    finished(other, ops)
    assert np.array_equal(counts(other)[0], want)


def test_operations_need_an_axis_all(iq):
    s = session(iq, {**ONE, "all": [], "color": "none", "index": {"readout_power": 0, "state": 0, "shot": 3}})
    with pytest.raises(ExploreError, match="make one of the axes All"):
        s.apply({"ops": [{"op": "normalize"}]})


def test_too_many_drawings_are_refused_with_a_reason(iq, monkeypatch):
    monkeypatch.setattr(kind, "MOST_DRAWS", 1)
    s = session(iq, {**ONE, "all": ["shot", "state", "readout_power"], "index": {}})
    with pytest.raises(ExploreError, match="would take very long"):
        s.apply({"ops": [{"op": "normalize"}]})


def test_an_operation_that_fails_says_why(iq, monkeypatch):
    s = session(iq, ONE)
    finished(s)
    meta = finished(s, {"equations": {"y": "nonsense + 1"}})
    assert "error" in meta["ops"]["equations"]["y"]
