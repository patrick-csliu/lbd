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
    """The viewer's memory with little room: a few kB."""
    system = FakeMemory(room=20_000)
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
