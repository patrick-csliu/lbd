"""The heartbeat of a measurement, `name.lbd.live` (plan 9, spec §7): written by the Writer while it
measures, read with lbd.writing_progress; how points, totals and the outer axes' pace are counted."""

import json
import os

import numpy as np
import pytest

import lbd
from lbd import LBDError, LBDWarning
from lbd import live as live_module
from lbd.live import ValueProgress, live_path


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(live_module, "_clock", c)
    return c


def sweep(d, rows=4, cols=5):
    d.add_axis("power", np.arange(float(rows)), unit="dBm")
    d.add_axis("freq", np.linspace(1, 2, cols), unit="Hz")
    d.add_value("S21", axes=["power", "freq"], dtype="complex128")


def progress(d, *writes, times=None):
    """A value's progress after these writes (each a dict for Dataset._plan_write)."""
    vp = None
    for k, given in enumerate(writes):
        plan = d._plan_write(given, {}, None)
        for name, index, _ in plan["puts"]:
            vp = vp or ValueProgress(d, d.values[name])
            vp.add(index, 0.0 if times is None else times[k])
        d._grow_levels(plan)
        if plan["grow"] is not None:
            g, coords = plan["grow"]
            d.axes[g].data = np.concatenate([d.axes[g].data, np.atleast_1d(coords)])
    return vp.info()


def test_row_by_row_counts_traces_and_the_outer_axis():
    d = lbd.Dataset()
    sweep(d)
    p = progress(d, *[{"power": i, "S21": np.ones(5)} for i in range(3)], times=[0, 30, 60])
    assert (p["points"], p["total"], p["per_write"]) == (15, 20, 5)
    assert p["axes"] == [{"name": "power", "index": 2, "length": 4, "step_seconds": 30.0}]
    assert p["rate"] == pytest.approx(10 / 60, abs=1e-6)       # points per second, rounded


def test_point_by_point_and_a_point_written_again():
    d = lbd.Dataset()
    sweep(d, rows=2, cols=3)
    p = progress(d, {"power": 0, "freq": 0, "S21": 1}, {"power": 0, "freq": 1, "S21": 1},
                 {"power": 0, "freq": 1, "S21": 2})          # the same point again: counted once
    assert (p["points"], p["total"], p["per_write"]) == (2, 6, 1)
    assert [a["name"] for a in p["axes"]] == ["power", "freq"]


def test_a_block_of_rows_and_the_whole_value():
    d = lbd.Dataset()
    sweep(d)
    assert progress(d, {"S21": np.ones((4, 5))})["points"] == 20


def test_a_growing_axis_or_a_group_has_no_total():
    d = lbd.Dataset()
    d.add_axis("time", grows=True)
    d.add_value("T", axes="time")
    p = progress(d, {"time": 0.0, "T": 1.0}, {"time": 1.0, "T": 2.0})
    assert (p["points"], p["total"]) == (2, None)
    g = lbd.Dataset()
    g.add_group("scan")
    g.add_axis("A", group="scan")
    g.add_axis("B", group="scan")
    g.add_value("y", axes=["A", "B"])
    p = progress(g, {"A": 1.0, "B": 0.5, "y": 1.0}, {"A": 1.0, "B": 0.7, "y": 2.0})
    assert (p["points"], p["total"]) == (2, None)


def test_the_writer_keeps_the_heartbeat_and_removes_it_at_the_finish(tmp_path, clock, monkeypatch):
    path = tmp_path / "sweep.lbd"
    w = lbd.Writer(path, flush_every=1000)        # its own thread stays asleep: the test drives it
    sweep(w)
    w.write(power=0, S21=np.ones(5))
    beat = live_path(path)
    assert beat == tmp_path / "sweep.lbd.live"
    w._beat_now()                                  # due: never written yet
    first = lbd.writing_progress(w.writing_path)
    assert first["lbd_live"] == 1 and first["program"].startswith("python lbd")
    assert first["computer"] and first["process"] == os.getpid()
    assert first["values"]["S21"]["points"] == 5
    w.write(power=1, S21=np.ones(5))
    clock.t += 2
    assert not w._beat.due()                       # changed, but less than 5 s ago
    clock.t += 3
    assert w._beat.due()
    w._beat_now()
    assert lbd.writing_progress(path)["values"]["S21"]["points"] == 10
    clock.t += 29
    assert not w._beat.due()
    clock.t += 1
    assert w._beat.due()                           # nothing new, but the beat is due
    w.close()
    assert not beat.exists() and lbd.writing_progress(path) is None


def test_a_crash_leaves_it_and_recover_removes_it_or_keeps_everything(tmp_path):
    from test_writer import MEASURE, run_python

    path = tmp_path / "crash.lbd"
    writing = tmp_path / "crash.lbd.writing"
    w = run_python(MEASURE, path, 6, "crash")
    out, err = w.communicate(timeout=60)
    assert w.returncode == 3, err
    beat = lbd.writing_progress(writing)
    assert beat is not None and beat["values"]["S21"]["total"] == 6 * 7
    kept = lbd.recover(writing, keep=True)                 # another computer's copy: leave it
    assert kept == tmp_path / "crash (recovered).lbd"
    assert writing.exists() and live_path(writing).exists()
    assert lbd.load(kept).id == lbd.info(kept).id
    assert lbd.recover(writing) == path                    # on the measuring computer
    assert not writing.exists() and not live_path(writing).exists()


def test_reading_a_damaged_or_foreign_heartbeat_says_so(tmp_path):
    p = tmp_path / "x.lbd.live"
    p.write_text('{"lbd_live": 1, "comp', encoding="utf-8")
    with pytest.raises(LBDError, match="incomplete or damaged"):
        lbd.writing_progress(tmp_path / "x.lbd.writing")
    p.write_text(json.dumps({"something": "else"}), encoding="utf-8")
    with pytest.raises(LBDError, match="not an LBD heartbeat"):
        lbd.writing_progress(tmp_path / "x.lbd")


def test_a_heartbeat_that_cant_be_written_is_said_once_and_the_measurement_goes_on(tmp_path, monkeypatch):
    path = tmp_path / "s.lbd"
    w = lbd.Writer(path, flush_every=1000)        # its own thread stays asleep: the test drives it
    sweep(w)
    w.write(power=0, S21=np.ones(5))

    def refuse(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(live_module.os, "replace", refuse)
    with pytest.warns(LBDWarning, match="can't be written.*the measurement goes on"):
        w._beat_now(force=True)
    w._beat_now(force=True)                        # said once only (no second warning)
    monkeypatch.undo()
    w.write(power=1, S21=np.ones(5))
    assert w.close() == path
