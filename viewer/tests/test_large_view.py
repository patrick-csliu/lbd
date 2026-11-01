"""Values bigger than the memory available (plan 6d, memory.py): read by part, only what is shown,
with the parts read kept while there is room and the next slider positions read ahead. The
memory is a fake here, so a small file counts as "big"."""

import json
import time

import numpy as np
import pytest

import lbd
from lbd import lazy
from lbd_viewer import memory, operations
from lbd_viewer.memory import GB, Cached, Memory, PartCache


class FakeMemory:
    """The operating system's (total, available), set by the test."""

    def __init__(self, room: int):
        self.total = 4 * GB                       # automatic reserve: max(2 GB, 10%) = 2 GB
        self.room = room

    def __call__(self):
        return self.total, 2 * GB + self.room


@pytest.fixture()
def fake(monkeypatch):
    """The viewer's memory with little room: 100 kB (a map of the cube, 19 kB, fits; the cube doesn't)."""
    system = FakeMemory(room=100_000)
    cache = PartCache(Memory(system=system))
    monkeypatch.setitem(memory._shared, "cache", cache)
    return system, cache


@pytest.fixture()
def cube(data_dir):
    """A complex 3-D value, 20 × 30 × 40 points (384 kB): a map over (y, x) per t."""
    rng = np.random.default_rng(1)
    z = rng.normal(size=(20, 30, 40)) + 1j * rng.normal(size=(20, 30, 40))
    d = lbd.Dataset(title="cube")
    d.add_axis("t", np.arange(20.0), unit="s")
    d.add_axis("y", np.linspace(-1, 1, 30))
    d.add_axis("x", np.linspace(1e9, 2e9, 40), unit="Hz")
    d.add_value("z", z, axes=["t", "y", "x"])
    path = data_dir / "cube.lbd"
    d.save(path)
    return path, z


def picture(client, path, spec):
    r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": 400, "height": 300, "dpr": 1})
    r.raise_for_status()
    sid = r.json()["session"]
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw"})
    r.raise_for_status()
    return sid, json.loads(r.headers["X-LBD-Frame"]), r.content


def reads(monkeypatch):
    """The parts read from files: a list of (where, bytes)."""
    seen = []
    real = lazy.OnDisk.__getitem__

    def spy(self, key):
        arr = real(self, key)
        seen.append((self._where, arr.nbytes))
        return arr

    monkeypatch.setattr(lazy.OnDisk, "__getitem__", spy)
    return seen


SPEC = {"kind": "heatmap", "x": "x", "y": "y", "index": {"t": 5}, "complex": "db"}


def test_a_value_that_fits_is_loaded_whole(client, cube, monkeypatch):
    path, _ = cube
    system = FakeMemory(room=10 * GB)
    monkeypatch.setitem(memory._shared, "cache", PartCache(Memory(system=system)))
    d = memory.load_values(path, ["z"], "v")
    assert isinstance(d["z"].data, np.ndarray)


def test_a_big_value_draws_the_same_picture_reading_only_its_slice(client, cube, fake, monkeypatch):
    path, z = cube
    seen = reads(monkeypatch)
    _, meta, by_part = picture(client, path, SPEC)
    assert seen and all(where == "values/z" for where, _ in seen)
    assert max(n for _, n in seen) <= z[5].nbytes            # one map, never the whole cube
    monkeypatch.setitem(memory._shared, "cache", PartCache(Memory(system=FakeMemory(room=10 * GB))))
    _, meta2, whole = picture(client, path, SPEC)
    assert meta["xlim"] == meta2["xlim"] and by_part == whole


def test_parts_are_kept_and_the_next_slider_positions_read_ahead(client, cube, fake, monkeypatch):
    path, z = cube
    _, cache = fake
    sid, _, _ = picture(client, path, SPEC)
    deadline = time.monotonic() + 5
    while len(cache._parts) < 3 and time.monotonic() < deadline:   # t = 5, then 4 and 6 ahead
        time.sleep(0.02)
    assert len(cache._parts) == 3
    seen = reads(monkeypatch)
    r = client.post(f"/api/explore/{sid}/spec", json={"spec": {**SPEC, "index": {"t": 6}}})
    r.raise_for_status()
    assert seen == [] or all(n <= z[0].nbytes for _, n in seen)   # t = 6 came from memory
    assert cache.hits >= 1


def test_parts_are_dropped_oldest_first_when_memory_runs_low(cube, fake):
    path, z = cube
    system, cache = fake
    d = lbd.open(path, hold=False)
    x = Cached(d["z"].data, cache, (str(path), "v"))
    for t in range(4):
        np.testing.assert_array_equal(x[t, :, :], z[t])
    assert len(cache._parts) == 4 and cache.bytes == 4 * z[0].nbytes
    system.room = 0                                   # another program took the memory
    cache.trim()
    assert len(cache._parts) == 1 and cache.bytes == z[0].nbytes       # the newest stays
    np.testing.assert_array_equal(x[3, :, :], z[3])


def test_memory_rule_reserve_and_maximum():
    system = FakeMemory(room=3 * GB)
    m = Memory(system=system)
    assert m.reserve() == 2 * GB and m.room() == 3 * GB
    system.total = 64 * GB                            # 10% of RAM is more than 2 GB
    assert m.reserve() == int(6.4 * GB) and m.room() == 0
    m = Memory(reserve=1 * GB, maximum=2 * GB, system=system)
    assert m.room() == 2 * GB
    PartCache(m).bytes = int(1.5 * GB)
    assert m.room() == int(0.5 * GB)


def test_the_file_is_not_held_while_a_session_shows_it(client, cube, fake):
    path, _ = cube
    picture(client, path, SPEC)
    moved = path.with_name("moved.lbd")
    path.rename(moved)                                # refused on Windows if the viewer held it open
    moved.rename(path)


def test_complex_operations_part_by_part_equal_whole(cube):
    path, _ = cube
    ops = [{"op": "delay", "tau": 1e-9}, {"op": "rotation", "phi": 30}, {"op": "auto_rotate"}]
    spec = {"values": ["z"], "x": "x"}
    whole = operations.complex_data(lbd.load(path), spec, ops)
    with lbd.open(path) as d:
        by_part = operations.complex_data(d, spec, ops)
        np.testing.assert_allclose(by_part["z"]._read((5, slice(None), slice(None))), whole["z"].data[5])
        np.testing.assert_allclose(by_part["z"]._read((slice(None), 3, slice(2, 9))), whole["z"].data[:, 3, 2:9])
        np.testing.assert_allclose(by_part["z"]._read((2, 4, 7)), whole["z"].data[2, 4, 7])


def test_memory_settings(client):
    s = client.get("/api/state").json()["memory"]
    assert s["reserve_gb"] is None and s["maximum_gb"] is None and s["summary_cache_gb"] == 20
    r = client.put("/api/settings", json={"memory": {"maximum_gb": 8, "reserve_gb": 3}})
    r.raise_for_status()
    assert r.json()["memory"]["maximum_gb"] == 8
    assert memory.shared().memory.maximum == 8 * GB and memory.shared().memory.reserve() == 3 * GB
    r = client.put("/api/settings", json={"memory": {"maximum_gb": -1}})
    assert r.status_code == 400 and "number of GB" in r.json()["detail"]
    r = client.put("/api/settings", json={"memory": {"maximum_gb": None, "reserve_gb": None}})
    r.raise_for_status()
    assert memory.shared().memory.maximum is None


# ---- a map bigger than memory: shown from its summary (summaries.py, plan 6d B) ------------------

from lbd_viewer import summaries  # noqa: E402

MAP = {"kind": "heatmap", "x": "x", "y": "y", "index": {"t": 1}, "complex": "db"}


@pytest.fixture()
def big(data_dir):
    """4 maps of 1001 × 1201 complex cells (77 MB), one hot cell in map 1."""
    rng = np.random.default_rng(2)
    z = rng.normal(size=(4, 1001, 1201)) + 1j * rng.normal(size=(4, 1001, 1201))
    z[1, 700, 300] = 1000
    d = lbd.Dataset(title="big")
    d.add_axis("t", np.arange(4.0))
    d.add_axis("y", np.linspace(-1, 1, 1001))
    d.add_axis("x", np.linspace(1e9, 2e9, 1201), unit="Hz")
    d.add_value("z", z, axes=["t", "y", "x"])
    path = data_dir / "big.lbd"
    d.save(path)
    return path, 20 * np.log10(np.abs(z[1]))


def little_room(monkeypatch, room=10 << 20):
    """10 MB of room: a map of 1.2 million cells (29 MB drawn) is too big, its strips are not."""
    cache = PartCache(Memory(system=FakeMemory(room=room)))
    monkeypatch.setitem(memory._shared, "cache", cache)
    return cache


def test_a_map_bigger_than_memory_is_drawn_from_its_summary(client, big, monkeypatch):
    path, z = big
    little_room(monkeypatch)
    sid, meta, by_summary = picture(client, path, MAP)
    s = client.app.state.lbd.explore.get(sid)
    assert s.summarised and len(summaries.shared().entries()) == 1
    assert "max of" in meta["note"]                                   # reduced, as any big map
    monkeypatch.setitem(memory._shared, "cache", PartCache(Memory(system=FakeMemory(room=10 * GB))))
    sid2, meta2, whole = picture(client, path, MAP)
    assert not client.app.state.lbd.explore.get(sid2).summarised
    assert meta2["xlim"] == meta["xlim"] and meta2["note"] == meta["note"]
    assert by_summary == whole                                        # the same picture


def test_a_summary_is_found_again_and_made_again_when_the_file_changes(client, big, monkeypatch):
    path, _ = big
    little_room(monkeypatch)
    picture(client, path, MAP)
    seen = reads(monkeypatch)
    picture(client, path, MAP)
    assert not any(n > 1_000_000 for _, n in seen)                    # no strips read: found on disk
    assert len(summaries.shared().entries()) == 1
    picture(client, path, {**MAP, "complex": "phase"})                # another drawing: another summary
    assert len(summaries.shared().entries()) == 2
    d = lbd.load(path)
    d.meta["changed"] = 1
    time.sleep(0.02)
    d.save(path)                                                       # a new version of the file
    picture(client, path, MAP)
    assert len(summaries.shared().entries()) == 3


def test_reading_a_summarised_map_reads_the_exact_stored_numbers(client, big, monkeypatch):
    path, z = big
    little_room(monkeypatch)
    sid, meta, _ = picture(client, path, MAP)
    s = client.app.state.lbd.explore.get(sid)
    m = s.model.z
    assert m[700, 300] == pytest.approx(z[700, 300])
    np.testing.assert_allclose(m[700, :], z[700])
    np.testing.assert_allclose(m[:, 300], z[:, 300])
    np.testing.assert_allclose(m[np.ix_([3, 9, 5], [10, 2])], z[np.ix_([3, 9, 5], [10, 2])])
    np.testing.assert_allclose(m[10:2:-3, 7], z[10:2:-3, 7])
    r = client.post(f"/api/explore/{sid}/cursors",
                    json={"cursors": [{"x": float(s.model.x[300]), "y": float(s.model.y[700])}], "type": "cross",
                          "xlim": meta["xlim"], "ylim": meta["ylim"], "width": 400, "height": 300})
    r.raise_for_status()
    c = r.json()
    assert c["cursors"][0]["index"] == {"x": 300, "y": 700}
    shown = next(i for i in c["cursors"][0]["items"] if i["role"] == "z")
    assert shown["value"] == pytest.approx(z[700, 300])
    assert len(c["cuts"]["row"]["z"]) > 0 and len(c["cuts"]["column"]["z"]) > 0
    f = client.post(f"/api/explore/{sid}/find", json={"what": "max", "xlim": [1.2, 1.3], "ylim": [0.3, 0.5]})
    f.raise_for_status()
    assert f.json()["y"] == pytest.approx(float(s.model.y[700]))      # the hot cell, read from the file
    h = client.post(f"/api/explore/{sid}/histogram", json={}).json()
    assert h["approximate"] and h["cells"] == z.size
    assert h["highest"] == pytest.approx(z.max(), rel=1e-6) and h["lowest"] == pytest.approx(z.min(), rel=1e-6)


def test_whole_map_work_is_refused_with_a_message(client, big, monkeypatch):
    path, _ = big
    little_room(monkeypatch)
    sid, _, _ = picture(client, path, MAP)
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", "settings": {"select": {"y": [0, 1]}}})
    assert r.status_code == 400 and "choosing rows" in r.json()["detail"]
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", "settings": {"ops": [{"op": "derivative"}]}})
    detail = r.json()["detail"] if r.status_code == 400 else json.loads(r.headers["X-LBD-Frame"])["ops"]["notes"][0]
    assert "more than the memory available" in detail


def test_making_a_summary_shows_progress_and_can_be_cancelled(client, big, monkeypatch):
    import threading

    path, _ = big
    little_room(monkeypatch)
    real = summaries.Job.step

    def slow(self, fraction):
        time.sleep(0.2)
        real(self, fraction)

    monkeypatch.setattr(summaries.Job, "step", slow)
    answer = {}
    t = threading.Thread(target=lambda: answer.update(r=client.post(
        "/api/explore", json={"path": str(path), "spec": MAP, "width": 400, "height": 300, "dpr": 1})))
    t.start()
    deadline = time.monotonic() + 10
    while not client.get("/api/summaries").json()["making"] and time.monotonic() < deadline:
        time.sleep(0.02)
    making = client.get("/api/summaries").json()["making"]
    assert making and making[0]["path"] == str(path.resolve()) and "1,001 × 1,201 cells" in making[0]["what"]
    client.post("/api/summaries/cancel", json={"path": str(path)}).raise_for_status()
    t.join(10)
    assert answer["r"].status_code == 400 and "cancelled" in answer["r"].json()["detail"]
    assert client.get("/api/summaries").json()["making"] == []
    assert not list(summaries.shared().folder.glob("*.part")) and summaries.shared().entries() == []
    assert client.post("/api/summaries/cancel", json={"path": str(path)}).status_code == 404


def test_the_summary_cache_is_trimmed_and_emptied(client, big, monkeypatch):
    path, _ = big
    little_room(monkeypatch)
    for mode in ("db", "phase", "real"):
        sid, _, _ = picture(client, path, {**MAP, "complex": mode})
        client.delete(f"/api/explore/{sid}")
    c = summaries.shared()
    sizes = [p.stat().st_size for p in c.entries()]
    assert len(sizes) == 3
    gb = (sizes[0] + sizes[1]) * 1.01 / GB                            # room for two
    client.put("/api/settings", json={"memory": {"summary_cache_gb": gb}}).raise_for_status()
    assert len(c.entries()) == 2
    assert client.get("/api/summaries").json()["count"] == 2
    out = client.post("/api/summaries/empty").json()
    assert out["removed"] == 2 and out["count"] == out["bytes"] == 0 and c.entries() == []


def test_a_summary_made_in_several_passes_gives_the_same_means(client, big, monkeypatch):
    """Strips of 4 rows (as when memory is very short): two levels per strip, the rest made from
    the stored levels (kept as float32 sums and 16-bit counts)."""
    from lbd.plot.reduce import MapPyramid, cell_edges

    path, z = big
    little_room(monkeypatch, room=1 << 20)
    monkeypatch.setattr(summaries, "MIN_BUDGET", 1201 * 40 * 4)
    sid, _, _ = picture(client, path, MAP)
    s = client.app.state.lbd.explore.get(sid)
    whole = MapPyramid(z, cell_edges(s.model.x), cell_edges(s.model.y))
    for n in (7, 40, 300):                                        # coarse to fine
        px = np.linspace(s.model.x[0], s.model.x[-1], n + 1)
        py = np.linspace(s.model.y[0], s.model.y[-1], n + 1)
        for stat in ("max", "mean"):
            a, b = whole.raster(px, py, stat), s.pyramid.raster(px, py, stat)
            assert a.level == b.level
            np.testing.assert_allclose(b.image, a.image, rtol=1e-5, atol=1e-5, equal_nan=True)


def test_a_preview_never_summarises_a_map_bigger_than_memory(client, big, monkeypatch):
    from lbd.plot.style import Style
    from lbd_viewer import previews

    path, _ = big
    little_room(monkeypatch)
    with pytest.raises(previews.PreviewError, match="too many for a preview; open it in Explore"):
        previews.draw(path, [{"spec": MAP}], (1, 1), Style(), saved_view=False)
    assert summaries.shared().entries() == []


def test_closing_one_view_of_a_summarised_map_keeps_the_others(client, big, monkeypatch):
    path, _ = big
    little_room(monkeypatch)
    a, _, first = picture(client, path, MAP)
    b, _, _ = picture(client, path, MAP)                                # the same summary, opened again
    client.delete(f"/api/explore/{b}").raise_for_status()
    r = client.post(f"/api/explore/{a}/render", json={"format": "raw", "xlim": [1.2, 1.4], "ylim": [0, 0.5]})
    r.raise_for_status()
    r = client.post(f"/api/explore/{a}/render", json={"format": "raw"})
    assert r.content == first


# ---- curves bigger than memory: shown from their summary ------------------------------------------

CURVES = {"kind": "curve", "values": ["S21"], "x": "freq", "series": "power", "complex": "db"}


@pytest.fixture()
def long_traces(data_dir):
    """40 complex traces of 30 001 points (19 MB; 29 MB drawn), a spike on trace 7."""
    rng = np.random.default_rng(4)
    z = rng.normal(size=(40, 30001)) + 1j * rng.normal(size=(40, 30001))
    z[7, 12345] = 500
    d = lbd.Dataset(title="long traces")
    d.add_axis("power", np.linspace(-40, 0, 40), unit="dBm")
    d.add_axis("freq", np.linspace(4e9, 8e9, 30001), unit="Hz")
    d.add_value("S21", z, axes=["power", "freq"])
    d.add_value("S11", z * 0.5, axes=["power", "freq"])
    path = data_dir / "long.lbd"
    d.save(path)
    return path, 20 * np.log10(np.abs(z))


def test_curves_bigger_than_memory_are_drawn_from_their_summary(client, long_traces, monkeypatch):
    path, y = long_traces
    little_room(monkeypatch)
    sid, meta, by_summary = picture(client, path, CURVES)
    s = client.app.state.lbd.explore.get(sid)
    assert s.summarised and meta["note"] == "min and max per pixel column"
    assert s.full[1][0] < y.min() and s.full[1][1] > y.max()           # the range from the summary
    monkeypatch.setitem(memory._shared, "cache", PartCache(Memory(system=FakeMemory(room=10 * GB))))
    sid2, meta2, whole = picture(client, path, CURVES)
    assert not client.app.state.lbd.explore.get(sid2).summarised
    assert meta2["xlim"] == meta["xlim"] and meta2["ylim"] == pytest.approx(meta["ylim"], rel=1e-6)
    differ = np.count_nonzero(np.frombuffer(by_summary, np.uint8) != np.frombuffer(whole, np.uint8))
    assert differ <= len(whole) // 1000                                # the same picture (float32 rounding)


def test_reading_summarised_curves_reads_the_stored_points(client, long_traces, monkeypatch):
    path, y = long_traces
    little_room(monkeypatch)
    sid, meta, _ = picture(client, path, CURVES)
    s = client.app.state.lbd.explore.get(sid)
    f = s.model.xs[0]
    seen = reads(monkeypatch)
    c = client.post(f"/api/explore/{sid}/cursors",
                    json={"cursors": [{"x": float(f[12345]), "y": 0.0, "trace": 7}], "type": "cross",
                          "xlim": meta["xlim"], "ylim": meta["ylim"], "width": 400, "height": 300}).json()
    cur = c["cursors"][0]
    assert cur["index"] == {"freq": 12345, "power": 7}
    assert next(i for i in cur["items"] if i["role"] == "y")["value"] == pytest.approx(y[7, 12345])
    assert max(n for _, n in seen) < 30001 * 16                        # never a whole trace
    c = client.post(f"/api/explore/{sid}/cursors",
                    json={"cursors": [{"x": float(f[12345]), "y": 0.0, "trace": 7, "step": [3, 0]}],
                          "xlim": meta["xlim"], "ylim": meta["ylim"], "width": 400, "height": 300}).json()
    assert c["cursors"][0]["index"]["freq"] == 12348
    r = client.post(f"/api/explore/{sid}/find", json={"what": "max", "xlim": [float(f[12000]), float(f[13000])],
                                                       "ylim": [-100, 100]})
    r.raise_for_status()
    assert r.json()["trace"] == 7 and r.json()["x"] == pytest.approx(float(f[12345]))
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", "xlim": [float(f[12340]), float(f[12350])]})
    r.raise_for_status()                                               # zoomed in: the stored points
    assert json.loads(r.headers["X-LBD-Frame"])["note"] == "every point shown"
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", "settings": {"select": {"power": [7, 30]}}})
    r.raise_for_status()                                               # two traces, from the summary


def test_what_summarised_curves_cant_show_is_refused_with_a_reason(client, long_traces, monkeypatch):
    path, _ = long_traces
    little_room(monkeypatch, room=1 << 20)                # 1 MB: two values of one trace each (60 000 points) too
    for spec, says in (({**CURVES, "complex": "phase_unwrap"}, "unwrapped phase"),
                       ({**CURVES, "values": ["S21", "S11"]}, "one value at a time")):
        r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": 400, "height": 300, "dpr": 1})
        assert r.status_code == 400 and says in r.json()["detail"]
    little_room(monkeypatch)
    sid, _, _ = picture(client, path, CURVES)
    r = client.post(f"/api/explore/{sid}/render", json={"format": "raw", "settings": {"ops": [{"op": "derivative"}]}})
    detail = r.json()["detail"] if r.status_code == 400 else json.loads(r.headers["X-LBD-Frame"])["ops"]["notes"][0]
    assert "more than the memory available" in detail


def test_a_curve_summary_made_in_several_passes_is_found_again(client, long_traces, monkeypatch):
    from lbd.plot.reduce import CurvePyramid

    path, y = long_traces
    little_room(monkeypatch, room=1 << 20)
    monkeypatch.setattr(summaries, "MIN_BUDGET", 40 * 40 * 8)       # stretches of 8 points
    sid, _, _ = picture(client, path, CURVES)
    s = client.app.state.lbd.explore.get(sid)
    x = s.model.xs[0]
    whole = CurvePyramid(x, y * s.model.yf)
    for lo, hi in ((x[0], x[-1]), (x[1000], x[9000])):
        pxe = np.linspace(lo, hi, 301)
        (a, _), (b, _) = whole.minmax(pxe), s.pyramids[id(x)].minmax(pxe)
        for (xa, ya), (xb, yb) in zip(a, b):
            np.testing.assert_array_equal(xa, xb)
            np.testing.assert_allclose(yb, ya, rtol=1e-6)
    client.delete(f"/api/explore/{sid}")
    seen = reads(monkeypatch)
    picture(client, path, CURVES)
    assert max((n for _, n in seen), default=0) < 30001 * 16        # found on disk: nothing made again
    assert len(summaries.shared().entries()) == 1
