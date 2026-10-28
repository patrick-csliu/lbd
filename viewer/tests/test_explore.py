"""The Explore view's server side (explore.py, /api/explore): pictures of a view, their mapping to
the data, and points read back from the full data."""

import json
import time

import numpy as np
import pytest

import lbd
from lbd_viewer.explore import ExploreSession, Sessions


def open_view(client, path, spec=None, width=640, height=420):
    r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": width, "height": height, "dpr": 1})
    r.raise_for_status()
    return r.json()


def render(client, sid, **view):
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", **view})
    r.raise_for_status()
    meta = json.loads(r.headers["X-LBD-Frame"])
    pixels = np.frombuffer(r.content, dtype=np.uint8).reshape(meta["height"], meta["width"], 4)
    return meta, pixels


def to_px(meta, x, y):
    """Data (plot units, linear axes) to picture pixels, as the browser does."""
    left, top, w, h = meta["plot"]
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    return left + (x - x0) / (x1 - x0) * w, top + h - (y - y0) / (y1 - y0) * h


@pytest.fixture()
def big_map(data_dir):
    """A 1001 x 1001 map with one hot cell, far more cells than the picture has pixels."""
    n = 1001
    z = np.random.default_rng(0).uniform(-0.5, 0.5, (n, n))
    z[700, 300] = 10
    d = lbd.Dataset(title="big map")
    d.add_axis("y", np.linspace(-1, 1, n))
    d.add_axis("x", np.linspace(0, 1, n))
    d.add_value("z", z, axes=["y", "x"])
    path = data_dir / "big_map.lbd"
    d.save(path)
    return path


def test_a_picture_comes_with_its_mapping(client, data_dir):
    o = open_view(client, data_dir / "curve.lbd")
    assert o["kind"] == "curve" and o["spec"]["values"] == ["a"]       # the same default as the figure
    meta, pixels = render(client, o["session"])
    assert pixels.shape == (meta["height"], meta["width"], 4)
    assert meta["xlim"] == o["full"][0] and meta["note"] == "every point shown"
    left, top, w, h = meta["plot"]
    assert 0 < left and 0 <= top and left + w <= meta["width"] and top + h <= meta["height"]
    assert set(meta["ms"]) == {"wait", "reduce", "draw", "encode"}


def test_a_known_point_is_drawn_where_the_mapping_says(client, data_dir):
    """The mapping is what the browser uses to place markers: it must match the picture."""
    d = lbd.Dataset(title="one dot")
    d.add_axis("x", np.arange(5.0))
    d.add_value("y", np.array([0.0, 0, 1, 0, 0]), axes="x")
    d.save(data_dir / "dot.lbd")
    o = open_view(client, data_dir / "dot.lbd")
    meta, pixels = render(client, o["session"])
    px, py = to_px(meta, 2.0, 1.0)                  # the peak of the line
    patch = pixels[int(py) - 2:int(py) + 3, int(px) - 2:int(px) + 3, :3].astype(int)
    assert patch.sum(axis=2).min() < 300            # a dark line pixel right there
    far = pixels[int(to_px(meta, 2.0, 0.5)[1]), int(to_px(meta, 0.5, 0)[0]), :3].astype(int)
    assert far.sum() > 600                          # and background away from it


def test_picking_returns_the_stored_value_not_the_picture(client, data_dir):
    o = open_view(client, data_dir / "curve.lbd")
    meta, _ = render(client, o["session"])
    d = lbd.load(data_dir / "curve.lbd")
    t, a = d.axes["t"].data, d.values["a"].data
    # the 'a' curve at point 17, in plot units (t is shown in µs, so through the session's factor)
    sess = client.app.state.lbd.explore.get(o["session"])
    px, py = sess._to_px(np.array([t[17] * sess.model.xf]), np.array([a[17] * sess.model.yf]))
    p = client.post(f"/api/explore/{o['session']}/pick", json={"x": float(px[0]), "y": float(py[0])}).json()["pick"]
    assert p["kind"] == "point" and p["value_name"] == "a" and p["index"] == {"t": 17}
    assert p["x"]["value"] == t[17] and p["x"]["unit"] == "s"
    assert p["y"] == pytest.approx(a[17], rel=1e-12, abs=1e-15)
    nothing = client.post(f"/api/explore/{o['session']}/pick", json={"x": 1, "y": 1}).json()["pick"]
    assert nothing is None                          # far from every point


def test_a_hot_cell_shows_at_the_full_view_with_max(client, big_map):
    o = open_view(client, big_map)
    meta, pixels = render(client, o["session"], stat="max")
    assert meta["reduced"] and meta["note"].startswith("max of")
    yellow = (pixels[..., 0] > 200) & (pixels[..., 1] > 200) & (pixels[..., 2] < 100)   # viridis' top
    ys, xs = np.nonzero(yellow)
    left, top, w, h = meta["plot"]
    inside = (xs >= left) & (xs < left + w) & (ys >= top) & (ys < top + h)
    assert inside.any()                             # the cell is in the picture ...
    px, py = to_px(meta, 300 / 1000, -1 + 2 * 700 / 1000)
    assert np.min(np.hypot(xs[inside] - px, ys[inside] - py)) < 3      # ... where it is
    mean_meta, mean_pixels = render(client, o["session"], stat="mean")
    assert mean_meta["note"].startswith("mean of")


def test_picking_a_cell_reads_the_full_map(client, big_map):
    o = open_view(client, big_map)
    render(client, o["session"], xlim=[0.29, 0.31], ylim=[0.39, 0.41])
    sess = client.app.state.lbd.explore.get(o["session"])
    px, py = sess._to_px(np.array([0.3]), np.array([0.4]))
    p = client.post(f"/api/explore/{o['session']}/pick", json={"x": float(px[0]), "y": float(py[0])}).json()["pick"]
    assert p["kind"] == "cell" and p["index"] == {"x": 300, "y": 700} and p["value"] == 10


def test_zoomed_in_nothing_is_reduced(client, big_map):
    o = open_view(client, big_map)
    meta, _ = render(client, o["session"], xlim=[0.29, 0.31], ylim=[0.39, 0.41])
    assert not meta["reduced"] and meta["note"] == "every cell shown"
    assert meta["xlim"] == [0.29, 0.31]


def test_clear_errors(client, data_dir):
    r = client.post("/api/explore/nope/render", json={})
    assert r.status_code == 404 and "reopens by itself" in r.json()["detail"]
    r = client.post("/api/explore", json={"path": str(data_dir / "missing.lbd"), "width": 400, "height": 300})
    assert r.status_code == 404
    o = open_view(client, data_dir / "curve.lbd")
    r = client.post(f"/api/explore/{o['session']}/render", json={"xlim": [2, 1]})
    assert r.status_code == 400 and "lowest first" in r.json()["detail"]
    r = client.post(f"/api/explore/{o['session']}/render", json={"stat": "median"})
    assert r.status_code == 400 and "max, min, mean" in r.json()["detail"]
    r = client.post("/api/explore", json={"path": str(data_dir / "curve.lbd"), "width": 10, "height": 10})
    assert r.status_code == 400 and "too small" in r.json()["detail"]
    r = client.post("/api/explore", json={"path": str(data_dir / "curve.lbd"), "spec": {"kind": "scatter"},
                                           "width": 400, "height": 300})
    assert r.status_code == 400 and "Figure view" in r.json()["detail"]


def test_closed_sessions_are_gone(client, data_dir):
    o = open_view(client, data_dir / "curve.lbd")
    client.delete(f"/api/explore/{o['session']}").raise_for_status()
    assert client.post(f"/api/explore/{o['session']}/render", json={}).status_code == 404


def test_sessions_are_limited_and_expire(data_dir):
    import lbd.plot as lp

    style = lp.load_style()
    sessions = Sessions(limit=2, idle=60)
    made = [ExploreSession(data_dir / "curve.lbd", "v", {}, style, 300, 200, 1) for _ in range(3)]
    for s in made:
        sessions.add(s)
    assert len(sessions) == 2
    with pytest.raises(KeyError):
        sessions.get(made[0].id)                    # the least recently used one was closed
    made[1].last_used = time.monotonic() - 120
    with pytest.raises(KeyError):
        sessions.get(made[1].id)                    # unused for longer than `idle`


def test_a_full_view_of_a_large_map_is_quick(client, big_map):
    """A loose limit (machines differ); the real targets are checked by hand at the gate."""
    o = open_view(client, big_map, width=900, height=600)
    t = time.perf_counter()
    meta, _ = render(client, o["session"])
    took = time.perf_counter() - t
    print(f"full view of a 1001x1001 map: {took * 1000:.0f} ms, {meta['ms']}")
    assert took < 2.0


def test_a_resized_panel_is_drawn_at_its_new_size_without_reopening(client, big_map):
    o = open_view(client, big_map, width=640, height=420)
    meta, _ = render(client, o["session"])
    assert (meta["width"], meta["height"]) == (640, 420)
    meta, pixels = render(client, o["session"], width=500, height=380, dpr=1)
    assert (meta["width"], meta["height"]) == (500, 380) and pixels.shape[:2] == (380, 500)
    assert meta["plot"][2] < 500 and meta["note"].startswith("max of")


def test_a_value_as_x_gives_each_trace_its_own_x(client, data_dir):
    """P6: a sweep whose frequency span changes per power, explored with the frequency as x."""
    p = np.array([-40.0, 0.0])
    f = 7e9 + np.outer([1.0, 3.0], np.arange(11.0) - 5) * 1e6
    d = lbd.Dataset(title="varying span")
    d.add_axis("power", p, unit="dBm")
    d.add_axis("point", np.arange(11.0))
    d.add_value("freq", f, axes=["power", "point"], unit="Hz")
    d.add_value("S21", np.arange(22.0).reshape(2, 11), axes=["power", "point"])
    d.save(data_dir / "span.lbd")
    o = open_view(client, data_dir / "span.lbd", spec={"kind": "curve", "values": ["S21"], "x": "freq"})
    meta, _ = render(client, o["session"])
    assert meta["note"] == "every point shown"
    sess = client.app.state.lbd.explore.get(o["session"])
    # point 8 of the second trace: at its own frequency, 7 GHz + 3 * 3 MHz
    px, py = sess._to_px(np.array([f[1, 8] * sess.model.xf]), np.array([19.0 * sess.model.yf]))
    p = client.post(f"/api/explore/{o['session']}/pick", json={"x": float(px[0]), "y": float(py[0])}).json()["pick"]
    assert p["trace"] == 1 and p["index"] == {"point": 8, "power": 1} and p["y"] == 19
    assert p["x"]["axis"] == "freq" and p["x"]["value"] == pytest.approx(f[1, 8]) and p["x"]["unit"] == "Hz"
