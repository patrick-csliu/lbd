"""Files being measured (plan 9, live.py): their state as this computer can know it (measuring
here, on another computer, no sign lately, stopped), progress as steady text, the tab and LBD's
records following the finished file, Recover as a copy for another computer's file, and the rule
that no viewer action writes into a file being measured."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

import lbd
from lbd_viewer import live
from lbd_viewer.live import LiveWatch, _Steady, progress_parts, time_left_text
from test_writing_view import measuring, stopped


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def heartbeat(writing: Path, computer="OTHER-PC", points=10, total=90, step=31.0, rate=0.3, **more):
    """Write a heartbeat file as a Writer on another computer would (spec §7)."""
    beat = {"lbd_live": 1, "computer": computer, "process": 1, "program": "python lbd 1.3.0",
            "started": "2026-11-03T10:00:00+08:00", "updated": "2026-11-03T10:01:00+08:00", "beat_every": 30,
            "longest_gap": step,
            "values": {"S21": {"points": points, "total": total, "per_write": 1, "rate": rate,
                               "axes": [{"name": "power", "index": points - 1, "length": total,
                                         "step_seconds": step}]}}}
    beat.update(more)
    p = writing.with_name(writing.name[: -len(".writing")] + ".live")
    p.write_text(json.dumps(beat), encoding="utf-8")
    return p


def touch(p: Path, wall: float):
    os.utime(p, (wall, wall))


# ---- the state -------------------------------------------------------------------------------------

def test_measuring_here(data_dir):
    w = measuring(data_dir)
    try:
        st = LiveWatch().status(str(w.writing_path))
        assert st["state"] == "measuring" and st["computer"] == live.this_computer()
    finally:
        w.close()


def test_another_computers_heartbeat_elsewhere_then_silent_then_back(data_dir):
    s = stopped(data_dir)                  # a file with no writer here: its lock tells nothing
    os.remove(s.with_name("stopped.lbd.live"))
    clock, wall = Clock(), Clock(1_700_000_000.0)
    watch = LiveWatch(clock=clock, wall=wall, computer="LAPTOP")
    beat = heartbeat(s)
    touch(beat, wall.t)
    st = watch.status(str(s))
    assert (st["state"], st["computer"]) == ("elsewhere", "OTHER-PC")
    clock.t += 599
    assert watch.status(str(s))["state"] == "elsewhere"
    clock.t += 2                                       # 10 min without a change it saw
    st = watch.status(str(s))
    assert st["state"] == "silent" and st["since"] == pytest.approx(wall.t)
    heartbeat(s, points=11)                             # the sync brings a new heartbeat
    touch(beat, wall.t + 700)
    assert watch.status(str(s))["state"] == "elsewhere"


def test_slow_steps_wait_longer_before_silent(data_dir):
    s = stopped(data_dir)
    clock, wall = Clock(), Clock(1_700_000_000.0)
    watch = LiveWatch(clock=clock, wall=wall, computer="LAPTOP")
    touch(heartbeat(s, longest_gap=400.0), wall.t)     # a step of almost 7 min seen
    watch.status(str(s))
    clock.t += 1200
    assert watch.status(str(s))["state"] == "elsewhere"     # 3 × 400 + 60 s: still waiting
    clock.t += 100
    assert watch.status(str(s))["state"] == "silent"


def test_this_computers_heartbeat_without_its_writer_is_stopped(data_dir):
    s = stopped(data_dir)                               # its Writer left a heartbeat naming this computer
    assert s.with_name("stopped.lbd.live").exists()
    assert LiveWatch().status(str(s))["state"] == "stopped"


def test_no_heartbeat_judged_by_the_data_file(data_dir):
    s = stopped(data_dir)
    os.remove(s.with_name("stopped.lbd.live"))
    clock, wall = Clock(), Clock(1_700_000_000.0)
    watch = LiveWatch(clock=clock, wall=wall, computer="LAPTOP")
    touch(s, wall.t - 30)                              # changed 30 s ago (by its own time)
    st = watch.status(str(s))
    assert st["state"] == "elsewhere" and st["computer"] is None
    clock.t += 200
    assert watch.status(str(s))["state"] == "stopped"


# ---- progress as steady text ----------------------------------------------------------------------

def parts(value, steady=None, now=0.0):
    return {p["kind"]: p for p in progress_parts(value, steady or _Steady(), now)}


def test_progress_parts_and_their_widths():
    p = parts({"points": 47069, "total": 180090, "per_write": 2001, "rate": 64.0,
               "axes": [{"name": "power", "index": 22, "length": 90, "step_seconds": 31.2},
                        {"name": "freq", "index": 5, "length": 2001, "step_seconds": 0.01}]})
    assert p["axes"]["text"] == "power 23 of 90" and p["axes"]["width"] == "power 90 of 90"
    assert [k for k in p] == ["axes", "percent", "points", "time"]      # the fast axis is left out
    assert p["percent"]["text"] == "26 %"
    assert p["points"]["text"] == "47 000 of 180 090 points"    # 64 points/s: rounded to 100s… of 1000s
    assert len(p["points"]["width"]) >= len(p["points"]["text"])
    assert p["time"]["text"] == "about 35 min left"


def test_unknown_total_shows_points_only():
    p = parts({"points": 1204, "total": None, "per_write": 1, "rate": 0.05, "axes": []})
    assert list(p) == ["points"] and p["points"]["text"] == "1 204 points"


def test_slow_percentages_get_a_decimal_and_the_estimate_waits_for_steps():
    p = parts({"points": 2, "total": 9000, "per_write": 1, "rate": 0.001, "axes": []})
    assert p["percent"]["text"] == "0.0 %" and p["time"]["text"] == "estimating…"


def test_time_left_never_bounces():
    steady = _Steady()
    value = {"points": 300, "total": 1000, "per_write": 10, "rate": 1.0, "axes": []}
    shown = [parts(value, steady, 0)["time"]["text"]]            # 700 s
    for t, rate in ((10, 1.05), (20, 0.97), (30, 1.02)):          # small wobbles of the pace
        value = {**value, "points": 300 + t, "rate": rate}
        shown.append(parts(value, steady, t)["time"]["text"])
    assert shown == ["about 10 min left"] * 4
    value = {**value, "points": 340, "rate": 0.5}                 # the pace halves: a new estimate
    assert parts(value, steady, 40)["time"]["text"] == "about 20 min left"


def test_time_left_text_steps():
    assert [time_left_text(s) for s in (37, 170, 1490, 7800)] == \
        ["about 40 s", "about 3 min", "about 25 min", "about 2 h 10 min"]


# ---- through the server ---------------------------------------------------------------------------

def test_api_live_and_no_repeated_warning(client, data_dir):
    w = measuring(data_dir)
    try:
        st = client.get("/api/live", params={"path": str(w.writing_path)}).json()
        assert st["state"] == "measuring" and st["progress"]
        r = client.post("/api/explore", json={"path": str(w.writing_path), "width": 400, "height": 300, "dpr": 1})
        assert not any("still being written" in m for m in r.json()["warnings"])
        assert client.get("/api/live", params={"path": str(data_dir / "curve.lbd")}).status_code == 400
    finally:
        w.close()


def test_the_finished_file_takes_over(client, data_dir):
    w = measuring(data_dir)
    p = str(w.writing_path)
    client.get("/api/live", params={"path": p})                         # seen while measured (its id)
    client.put("/api/explore/remembered", json={"path": p, "state": {"panels": [{"spec": {}}], "active": 0}})
    w.close(stopped=True)
    out = client.post("/api/changes", json={"files": [p], "dirs": []}).json()
    finished = str(data_dir / "live.lbd")
    assert out["files"][p] is None and out["finished"] == {p: finished}
    assert client.app.state.lbd.catalog.view(finished) is not None        # the remembered view followed
    again = client.post("/api/changes", json={"files": [p], "dirs": []}).json()
    assert again["finished"] == {p: finished}                            # said again; followed once


def test_recover_another_computers_file_makes_a_copy(client, data_dir):
    s = stopped(data_dir)
    beat = heartbeat(s)                                  # it says: measured on another computer
    r = client.post("/api/file/recover", json={"path": str(s)})
    assert r.status_code == 200, r.text
    assert r.json() == {"path": str(data_dir / "stopped (recovered).lbd"), "copy": True}
    assert s.exists() and beat.exists()                   # nothing removed: it travels back otherwise
    beat.unlink()
    heartbeat(s, computer=live.this_computer())         # this computer's: recovered in place
    r = client.post("/api/file/recover", json={"path": str(s)})
    assert r.json()["copy"] is False and not s.exists()


def test_settings_for_the_status(client):
    s = client.get("/api/state").json()["measurements"]
    assert s == {"progress": True, "time": True, "percent": True, "points": True, "axes": True, "notify": False}
    r = client.put("/api/settings", json={"measurements": {"time": False, "notify": True}})
    assert r.json()["measurements"]["time"] is False
    r = client.put("/api/settings", json={"measurements": {"speed": True}})
    assert r.status_code == 400 and "unknown measurement setting" in r.json()["detail"]


def test_a_cursor_on_a_cell_not_measured_yet(client, data_dir):
    w = lbd.Writer(data_dir / "map.lbd")
    w.add_axis("power", [1.0, 2.0, 3.0])
    w.add_axis("freq", [10.0, 20.0, 30.0, 40.0])
    w.add_value("S21", axes=["power", "freq"])
    w.write(power=0, S21=np.arange(4.0))                  # one row of three measured
    w.flush()
    try:
        o = client.post("/api/explore", json={"path": str(w.writing_path), "spec": {"kind": "heatmap"},
                                             "width": 400, "height": 300, "dpr": 1}).json()
        r = client.post(f"/api/explore/{o['session']}/cursors",
                        json={"cursors": [{"x": 20.0, "y": 3.0}], "type": "cross", "xlim": [5, 45], "ylim": [0.5, 3.5],
                              "width": 400, "height": 300}).json()
        texts = json.dumps(r)
        assert "not measured yet" in texts
    finally:
        w.close()


# ---- the rule: only the measuring program writes into a file being measured ----------------------

# Every endpoint about files that changes something, sorted by what it does with a file being
# measured. REFUSED ones are checked in test_writing_view.test_actions_refused.
REFUSED = {"/api/file/plot", "/api/file/rename", "/api/file/trash", "/api/library/duplicate",
           "/api/library/give-ids", "/api/library/resolve"}
ELSEWHERE = {   # write only beside the file (the labels file), into LBD's database, or a new file
    "/api/library/labels", "/api/library/missing", "/api/library/preview/want", "/api/library/preview/choose",
    "/api/library/preview/clear", "/api/file/recover",
}


def test_every_endpoint_that_changes_something_is_sorted(client):
    """A new endpoint that changes things fails here until it is sorted into REFUSED (with a
    refusal for files being measured) or ELSEWHERE (it never writes into the data file)."""
    routes = {r.path for r in client.app.routes
              if set(getattr(r, "methods", set()) or ()) & {"POST", "PUT", "DELETE"}
              and r.path.startswith(("/api/file", "/api/library"))}
    unsorted = sorted(routes - REFUSED - ELSEWHERE)
    assert not unsorted, f"sort these endpoints for files being measured (plan 9 rule): {unsorted}"
    assert REFUSED | ELSEWHERE <= routes, sorted((REFUSED | ELSEWHERE) - routes)
