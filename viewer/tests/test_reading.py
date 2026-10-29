"""Reading values in the Explore view (reading.py, /api/explore/{id}/cursors, find, histogram,
save-cut): every number comes from the stored data, never from the picture."""

import numpy as np
import pytest

import lbd


def open_view(client, path, spec=None, width=640, height=420):
    r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": width, "height": height, "dpr": 1})
    r.raise_for_status()
    return r.json()


def cursors(client, o, items, kind="cross", view=None, size=(500, 300), cuts=True):
    (x0, x1), (y0, y1) = view or o["full"]
    r = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": items, "type": kind, "xlim": [x0, x1], "ylim": [y0, y1],
                          "width": size[0], "height": size[1], "cuts": cuts})
    r.raise_for_status()
    return r.json()


def item(c, role):
    return next(i for i in c["items"] if i["role"] == role)


@pytest.fixture()
def traces(data_dir):
    """Three traces of 101 points, at heights 0, 10, 20, with a spike and a dip on trace 1."""
    x = np.linspace(0, 1, 101)
    y = np.array([np.full(101, 0.0), np.full(101, 10.0), np.full(101, 20.0)])
    y[1, 30], y[1, 70] = 15.0, 4.0
    y[2, 50] = np.nan
    d = lbd.Dataset(title="traces")
    d.add_axis("power", np.array([-30.0, -20.0, -10.0]), unit="dBm")
    d.add_axis("t", x, unit="s", label="Time")
    d.add_value("v", y, axes=["power", "t"], unit="V")
    path = data_dir / "traces.lbd"
    d.save(path)
    return path


@pytest.fixture()
def small_map(data_dir):
    """A 5 x 4 map: value = column + 10 * row; x 1..5 Hz, y 100..400 A."""
    d = lbd.Dataset(title="map")
    d.add_axis("y", np.array([100.0, 200, 300, 400]), unit="A")
    d.add_axis("x", np.array([1.0, 2, 3, 4, 5]), unit="Hz")
    d.add_value("z", np.arange(5.0)[None, :] + 10 * np.arange(4.0)[:, None], axes=["y", "x"], unit="V")
    d.meta["T_mK"] = 12
    path = data_dir / "small_map.lbd"
    d.save(path)
    return path


SPEC = {"kind": "curve", "x": "t", "series": "power"}


def test_a_click_lands_on_the_nearest_stored_point(client, traces):
    o = open_view(client, traces, spec=SPEC)
    c = cursors(client, o, [{"x": 0.304, "y": 14.0}])["cursors"][0]
    # the nearest point on screen is the spike (trace 1, point 30); its stored values are read out
    assert c["trace"] == 1 and c["index"] == {"t": 30, "power": 1}
    assert c["x"] == pytest.approx(0.3) and item(c, "x")["value"] == pytest.approx(0.3) and item(c, "x")["unit"] == "s"
    assert item(c, "y")["value"] == 15.0 and item(c, "y")["unit"] == "V"
    assert item(c, "series")["value"] == -20.0 and not c["free"]


def test_a_cursor_stays_on_its_trace_and_steps_along_it(client, traces):
    o = open_view(client, traces, spec=SPEC)
    c = cursors(client, o, [{"x": 0.6, "y": 19.0, "trace": 0}])["cursors"][0]   # dragged near trace 2
    assert c["trace"] == 0 and item(c, "y")["value"] == 0.0
    c = cursors(client, o, [{"x": c["x"], "y": c["y"], "trace": 0, "step": [3, 0]}])["cursors"][0]
    assert c["index"]["t"] == 63
    c = cursors(client, o, [{"x": c["x"], "y": c["y"], "trace": 0, "step": [0, -1]}])["cursors"][0]
    assert c["trace"] == 1 and c["index"]["t"] == 63                  # the next trace, same x
    # a missing point is stepped over
    c = cursors(client, o, [{"x": 0.49, "y": 0, "trace": 2, "step": [1, 0]}])["cursors"][0]
    assert c["index"]["t"] == 51


def test_a_free_cursor_keeps_its_position_and_reads_the_nearest_point(client, traces):
    o = open_view(client, traces, spec=SPEC)
    c = cursors(client, o, [{"x": 0.304, "y": 14.0, "free": True}])["cursors"][0]
    assert (c["x"], c["y"], c["free"]) == (0.304, 14.0, True) and item(c, "y")["value"] == 15.0


def test_a_vertical_cursor_lists_every_trace_at_its_x(client, traces):
    o = open_view(client, traces, spec=SPEC)
    c = cursors(client, o, [{"x": 0.7, "y": 3.0}], kind="vertical")["cursors"][0]
    rows = c["table"]["rows"]
    assert c["trace"] == 1 and [r["trace"] for r in rows] == [1, 0, 2]   # its own trace first
    assert [r["value"] for r in rows] == [4.0, 0.0, 20.0] and c["table"]["unit"] == "V"


def test_unchosen_traces_are_not_snapped_to(client, traces):
    o = open_view(client, traces, spec=SPEC)
    client.post(f"/api/explore/{o['session']}/render", json={"settings": {"select": {"power": [0, 2]}}}).raise_for_status()
    c = cursors(client, o, [{"x": 0.5, "y": 10.0}])["cursors"][0]
    assert c["trace"] in (0, 2)


def test_a_map_cursor_reads_its_cell_and_the_cuts_through_it(client, small_map):
    o = open_view(client, small_map, spec={"kind": "heatmap", "x": "x", "y": "y"})
    a = cursors(client, o, [{"x": 3.2, "y": 290.0}, {"x": 5.4, "y": 90.0}])
    c, c2 = a["cursors"]
    assert c["index"] == {"x": 2, "y": 2} and (c["x"], c["y"]) == (3.0, 300.0)
    assert item(c, "z")["value"] == 22.0 and item(c, "z")["unit"] == "V" and item(c, "x")["unit"] == "Hz"
    assert c2["index"] == {"x": 4, "y": 0}                          # off the map: its nearest cell
    row, col = a["cuts"]["row"], a["cuts"]["column"]
    assert row["pos"] == [1, 2, 3, 4, 5] and row["z"] == [20, 21, 22, 23, 24] and row["range"] == [20, 24]
    assert col["pos"] == [100, 200, 300, 400] and col["z"] == [2, 12, 22, 32]
    v = cursors(client, o, [{"x": 3.2, "y": 290.0}], kind="vertical")
    assert "row" not in v["cuts"] and "column" in v["cuts"] and v["cursors"][0]["y"] == 290.0


def test_cuts_of_a_large_map_keep_the_extremes(client, data_dir):
    n = 4000
    z = np.zeros((3, n))
    z[1, 1234] = 9.0
    d = lbd.Dataset(title="wide")
    d.add_axis("y", np.arange(3.0))
    d.add_axis("x", np.arange(float(n)))
    d.add_value("z", z, axes=["y", "x"])
    d.save(data_dir / "wide.lbd")
    o = open_view(client, data_dir / "wide.lbd", spec={"kind": "heatmap", "x": "x", "y": "y"})
    row = cursors(client, o, [{"x": 10, "y": 1}], size=(400, 300))["cuts"]["row"]
    assert len(row["pos"]) <= 2 * 400 + 2 and max(row["z"]) == 9.0     # reduced per pixel, spike kept


def test_a_row_left_out_of_the_map_reads_empty(client, small_map):
    o = open_view(client, small_map, spec={"kind": "heatmap", "x": "x", "y": "y"})
    client.post(f"/api/explore/{o['session']}/render", json={"settings": {"select": {"y": [0, 1]}}}).raise_for_status()
    a = cursors(client, o, [{"x": 2, "y": 300}])
    assert item(a["cursors"][0], "z")["value"] is None and a["cuts"]["column"]["z"] == [1, 11, None, None]


def find(client, o, what, xlim=None, ylim=None, trace=None):
    (x0, x1), (y0, y1) = o["full"]
    r = client.post(f"/api/explore/{o['session']}/find",
                    json={"what": what, "xlim": xlim or [x0, x1], "ylim": ylim or [y0, y1], "trace": trace})
    return r


def test_max_min_and_peak_find_stored_points_in_a_range(client, traces):
    o = open_view(client, traces, spec=SPEC)
    assert find(client, o, "max").json() == {"x": 0.0, "y": 20.0, "trace": 2}
    assert find(client, o, "max", trace=1).json() == {"x": pytest.approx(0.3), "y": 15.0, "trace": 1}
    assert find(client, o, "min", trace=1).json() == {"x": pytest.approx(0.7), "y": 4.0, "trace": 1}
    # peak: farthest from the trace's median (10): the dip at 4 beats the spike at 15
    assert find(client, o, "peak", trace=1).json()["x"] == pytest.approx(0.7)
    assert find(client, o, "peak", trace=1, xlim=[0.1, 0.5]).json()["x"] == pytest.approx(0.3)   # between cursors
    r = find(client, o, "max", xlim=[2, 3])
    assert r.status_code == 400 and "no stored values" in r.json()["detail"]
    assert find(client, o, "highest").status_code == 400


def test_max_on_a_map_searches_the_rectangle(client, small_map):
    o = open_view(client, small_map, spec={"kind": "heatmap", "x": "x", "y": "y"})
    assert find(client, o, "max").json() == {"x": 5.0, "y": 400.0}
    assert find(client, o, "max", xlim=[1.5, 3.5], ylim=[150, 250]).json() == {"x": 3.0, "y": 200.0}


def test_the_histogram_counts_every_shown_cell(client, data_dir):
    z = np.random.default_rng(1).normal(0, 1, (200, 300))
    z[0, 0], z[5, 5] = 1000.0, np.nan                      # an outlier and an empty cell
    d = lbd.Dataset(title="noise")
    d.add_axis("y", np.arange(200.0))
    d.add_axis("x", np.arange(300.0))
    d.add_value("z", z, axes=["y", "x"])
    d.save(data_dir / "noise.lbd")
    o = open_view(client, data_dir / "noise.lbd", spec={"kind": "heatmap", "x": "x", "y": "y"})
    h = client.post(f"/api/explore/{o['session']}/histogram", json={}).json()
    assert sum(h["counts"]) == h["cells"] == 200 * 300 - 1 and len(h["edges"]) == len(h["counts"]) + 1
    assert h["highest"] == 1000.0 and -4 < h["auto"][0] < -2 and 2 < h["auto"][1] < 4   # outlier left out
    o2 = open_view(client, data_dir / "noise.lbd", spec={"kind": "curve", "x": "x", "series": "y"})
    assert client.post(f"/api/explore/{o2['session']}/histogram", json={}).status_code == 400
    # with view settings: only the chosen rows are counted
    h = client.post(f"/api/explore/{o['session']}/histogram", json={"settings": {"select": {"y": [0, 1]}}}).json()
    assert h["cells"] == 2 * 300 and h["highest"] == 1000.0


def test_a_row_is_saved_as_its_own_file(client, small_map):
    o = open_view(client, small_map, spec={"kind": "heatmap", "x": "x", "y": "y"})
    url = f"/api/explore/{o['session']}/save-cut"
    suggested = client.post(url, json={"which": "row", "index": {"x": 2, "y": 1}}).json()["path"]
    assert suggested.endswith("small_map – y = 200 A.lbd")
    r = client.post(url, json={"which": "row", "index": {"x": 2, "y": 1}, "path": suggested})
    assert r.status_code == 200, r.text
    d = lbd.load(suggested)
    assert list(d.axes) == ["x"] and d.values["z"].data.tolist() == [10, 11, 12, 13, 14] and d.values["z"].unit == "V"
    assert d.meta["cut_from"] == "small_map.lbd" and d.meta["cut_index"]["y"] == 1 and d.meta["cut_at"]["y"] == 200
    assert d.meta["source_meta"]["T_mK"] == 12
    assert d.parent_id == lbd.info(small_map).id and d.id not in (None, d.parent_id)   # a new measurement made from it
    r = client.post(url, json={"which": "row", "index": {"x": 2, "y": 1}, "path": suggested})
    assert r.status_code == 400 and "exists already" in r.json()["detail"]          # never overwritten
    assert client.post(url, json={"which": "row", "index": {"x": 2, "y": 1}}).json()["path"].endswith("(2).lbd")
    r = client.post(url, json={"which": "column", "index": {"x": 2, "y": 1}, "path": str(small_map.parent / "c.lbd")})
    assert lbd.load(r.json()["path"]).values["z"].data.tolist() == [2, 12, 22, 32]


def test_a_trace_of_complex_data_is_saved_as_stored(client, data_dir):
    s = np.exp(1j * np.linspace(0, 3, 50))[None, :] * np.array([[1.0], [2.0]])
    d = lbd.Dataset(title="vna")
    d.add_axis("power", np.array([-20.0, -10.0]), unit="dBm")
    d.add_axis("f", np.linspace(4e9, 5e9, 50), unit="Hz")
    d.add_value("S21", s, axes=["power", "f"])
    d.save(data_dir / "vna.lbd")
    o = open_view(client, data_dir / "vna.lbd", spec={"kind": "curve", "x": "f", "series": "power", "complex": "db"})
    c = cursors(client, o, [{"x": 4.5, "y": 6.0}])["cursors"][0]
    assert c["trace"] == 1 and item(c, "y")["unit"] == "dB" and item(c, "y")["value"] == pytest.approx(20 * np.log10(2))
    r = client.post(f"/api/explore/{o['session']}/save-cut",
                    json={"which": "trace", "index": c["index"], "trace": c["trace"], "path": str(data_dir / "t.lbd")})
    out = lbd.load(r.json()["path"])
    assert np.allclose(out.values["S21"].data, s[1]) and out.plot["complex"] == "db"


def test_clear_errors(client, traces):
    o = open_view(client, traces, spec=SPEC)
    url = f"/api/explore/{o['session']}/cursors"
    base = {"xlim": [0, 1], "ylim": [0, 20], "width": 100, "height": 100}
    for body, match in (({"cursors": [{"x": 0, "y": 0}], "type": "diagonal"}, "cursor type"),
                        ({"cursors": []}, "one or two"),
                        ({"cursors": [{"x": "a", "y": 0}]}, "position")):
        r = client.post(url, json={**base, **body})
        assert r.status_code == 400 and match in r.json()["detail"], r.json()
    r = client.post(f"/api/explore/{o['session']}/save-cut", json={"which": "row", "index": {}})
    assert r.status_code == 400 and "trace" in r.json()["detail"]


def test_a_closed_session_answers_closed_not_a_crash(client, traces):
    """A request still on its way when its session closes (e.g. the page moved on) gets 404, which
    the page answers by reopening; never a server error."""
    o = open_view(client, traces, spec=SPEC)
    client.app.state.lbd.explore.get(o["session"]).close()
    r = client.post(f"/api/explore/{o['session']}/render", json={})
    assert r.status_code == 404 and "reopens by itself" in r.json()["detail"]
    r = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": [{"x": 0, "y": 0}], "xlim": [0, 1], "ylim": [0, 1], "width": 9, "height": 9})
    assert r.status_code == 404


def test_only_one_of_several_traces_is_highlighted(client, traces, data_dir):
    o = open_view(client, traces, spec=SPEC)
    client.post(f"/api/explore/{o['session']}/render", json={}).raise_for_status()
    assert "line" in cursors(client, o, [{"x": 0.5, "y": 10}])["cursors"][0]
    d = lbd.Dataset(title="one")
    d.add_axis("t", np.linspace(0, 1, 50))
    d.add_value("v", np.sin(np.linspace(0, 3, 50)), axes="t")
    d.save(data_dir / "one.lbd")
    o = open_view(client, data_dir / "one.lbd")
    client.post(f"/api/explore/{o['session']}/render", json={}).raise_for_status()
    assert "line" not in cursors(client, o, [{"x": 0.5, "y": 0.5}])["cursors"][0]   # nothing to tell apart
