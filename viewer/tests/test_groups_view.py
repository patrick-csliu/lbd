"""Files with variable sweeps (axis groups, format 2.0, plan 6c) open in the viewer: a value on two
levels is a map (plan 15a), as curves it is drawn on its real axes (16.41); the file page and the
Library show the group."""

import lbd
import pytest

from lbd.plot import render as rnd
from lbd.plot.style import Style
from lbd_viewer.server import file_summary


@pytest.fixture()
def files(values_files):
    return {p.name: p for p in values_files}


def test_the_summary_shows_the_group(files):
    s = file_summary(lbd.info(files["13 variable sweep.lbd"]))
    assert s["lbd_version"] == "2.0" and s["groups"] == {"scan": ["power", "freq"]}
    axes = {a["name"]: a for a in s["axes"]}
    assert axes["freq"]["group"] == "scan" and axes["freq"]["length"] == 44
    assert axes["freq"]["label"] == "Frequency (point number)"
    values = {v["name"]: v for v in s["values"]}
    assert values["S21"]["axes"] == ["freq"] and values["Q"]["axes"] == ["power"]


def test_the_library_counts_the_points(client, files):
    client.app.state.lbd.library.scan()
    rows = {r["name"]: r for r in client.get("/api/library/list").json()["rows"]}
    assert rows["13 variable sweep.lbd"]["sweep"] == "44 points (variable)"
    assert rows["14 triangle.lbd"]["sweep"] == "15 points (variable)"
    assert rows["13 variable sweep.lbd"]["points"] == 44


def test_curves_are_drawn_against_the_real_axes_without_a_notice(files):
    """16.41: no longer against the point number."""
    svg, spec = rnd.render_file(str(files["13 variable sweep.lbd"]), {"values": ["S21"], "complex": "db", "kind": "curve"},
                                Style(), fmt="svg")
    assert spec["kind"] == "curve" and spec["x"] == "freq" and spec["series"] == "power"
    assert b"point number" not in svg and b"Frequency" in svg


def test_explore_curves_read_a_stored_point(client, files):
    """16.41 in Explore: S21 against Frequency at −30 dBm; a cursor snaps to a stored frequency
    of that step and reads its stored number."""
    path = files["13 variable sweep.lbd"]
    o = client.post("/api/explore", json={"path": str(path), "width": 600, "height": 400, "dpr": 1,
                                          "spec": {"kind": "curve", "values": ["S21"], "series": "none",
                                                   "index": {"power": 2}}})
    assert o.status_code == 200, o.text
    o = o.json()
    sid = o["session"]
    s = client.app.state.lbd.explore.get(sid)
    assert s.spec["x"] == "freq" and s.spec["index"] == {"power": 2}
    real = lbd.open(path)
    parent = real.axes["freq"].parent
    f = real.axes["freq"].data[parent == 2]
    meta = s.render(None, None)[1]
    assert real.axes["power"].data[2] == -30
    x = f[3] * s.model.xf
    c = client.post(f"/api/explore/{sid}/cursors",
                    json={"cursors": [{"x": float(x), "y": 0.0}], "type": "vertical",
                          "xlim": meta["xlim"], "ylim": meta["ylim"], "width": 600, "height": 400}).json()
    cur = c["cursors"][0]
    k = cur["index"]["freq_n"]                     # a stored point of that step, read as stored
    shown = {i["role"]: i["value"] for i in cur["items"]}
    assert shown["x"] == pytest.approx(f[k]) and abs(x - f[k] * s.model.xf) < 2 * (f[1] - f[0]) * s.model.xf
    assert shown["y"] == pytest.approx(abs(real.values["S21"].data[parent == 2][k]))
    client.delete(f"/api/explore/{sid}")
def test_a_two_level_value_opens_as_a_map(files):
    svg, spec = rnd.render_file(str(files["13 variable sweep.lbd"]), {"values": ["S21"], "complex": "db"}, Style(), fmt="svg")
    assert spec["kind"] == "heatmap" and spec["x"] == "freq" and spec["y"] == "power"
    assert b"point number" not in svg


def test_explore_opens_a_file_with_groups(client, files):
    for name in ("13 variable sweep.lbd", "14 triangle.lbd", "15 adaptive map.lbd"):
        r = client.post("/api/explore", json={"path": str(files[name]), "width": 400, "height": 300, "dpr": 1})
        assert r.status_code == 200, r.text
        o = r.json()
        assert o["kind"] == ("curve" if name.startswith("13") else "heatmap")     # 13's first value is on one level
        client.delete(f"/api/explore/{o['session']}")


def test_a_preview_is_drawn(client, files):
    client.app.state.lbd.library.scan()
    r = client.get("/api/library/preview", params={"path": str(files["14 triangle.lbd"])}).json()
    assert r["state"] in ("ready", "queued", "drawing"), r
