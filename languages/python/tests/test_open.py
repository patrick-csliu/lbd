"""lbd.open (plan 6d): the structure at once, value data read only where it is indexed."""

import os

import h5py
import numpy as np
import pytest

import lbd
from lbd.lazy import OnDisk


@pytest.fixture()
def path(tmp_path):
    d = lbd.Dataset("big")
    d.add_axis("power", np.arange(6.0))
    d.add_axis("freq", np.arange(50.0))
    d.add_value("S", np.arange(300.0).reshape(6, 50) + 1j, axes=["power", "freq"])
    d.add_value("ok", np.arange(6) % 2 == 0, axes="power")
    d.add_value("n", axes="power", dtype="int16")
    d.write(power=1, n=7)
    d.add_value("q", 2.5)
    d.meta["T_mK"] = 12
    return d.save(tmp_path / "big.lbd", compression="gzip")


@pytest.fixture()
def reads(monkeypatch):
    """Every selection read from a value's dataset in the file."""
    seen = []
    original = h5py.Dataset.__getitem__

    def spy(self, key):
        if "/values/" in self.name or "/measured/" in self.name:
            seen.append((self.name, key))
        return original(self, key)

    monkeypatch.setattr(h5py.Dataset, "__getitem__", spy)
    return seen


def test_the_structure_is_read_and_the_data_left_on_disk(path, reads):
    with lbd.open(path) as d:
        s = d.values["S"]
        assert isinstance(s.data, OnDisk) and s.data.shape == (6, 50) and s.data.dtype == np.complex128
        assert np.iscomplexobj(s.data) and len(s.data) == 6 and s.data.size == 300
        assert d.meta["T_mK"] == 12 and set(d.axes) == {"power", "freq"}
        assert d.values["ok"].data.dtype == bool
        assert reads == [], "nothing read yet"
        row = s.data[3]
        assert reads == [("/values/S", (3,))] or reads == [("/values/S", (3, slice(0, 50)))]
        assert np.array_equal(row, np.arange(150.0, 200.0) + 1j)


def test_indexing_reads_as_numpy(path):
    whole = lbd.load(path)
    keys = [3, -1, (2, 7), (slice(1, 4), slice(None, None, 7)), (slice(None, None, -2), 3), ...,
            (Ellipsis, 5), [4, 0, 4], (slice(None), [10, 3, 3]), np.arange(6) % 2 == 1, (slice(5, 2), 0),
            (slice(4, None, -3),)]
    with lbd.open(path) as d:
        for k in keys:
            np.testing.assert_array_equal(d.values["S"].data[k], whole.values["S"].data[k], err_msg=str(k))
        np.testing.assert_array_equal(np.asarray(d.values["S"].data), whole.values["S"].data)
        assert d.values["q"].data[()] == 2.5
        np.testing.assert_array_equal(d.values["ok"].data[:], whole.values["ok"].data)
        np.testing.assert_array_equal(d.values["n"].measured[:], whole.values["n"].measured)
        with pytest.raises(IndexError, match="out of bounds"):
            d.values["S"].data[6]
        with pytest.raises(IndexError, match="too many indices"):
            d.values["S"].data[1, 2, 3]


def test_reading_after_close_is_refused(path):
    d = lbd.open(path)
    row = d.values["S"].data[0]
    d.close()
    assert row.shape == (50,)                     # what was read stays
    with pytest.raises(lbd.LBDError, match="is closed: open it again"):
        d.values["S"].data[1]


def test_read_only_by_default(path, tmp_path):
    with lbd.open(path) as d:
        with pytest.raises(lbd.LBDError, match=r"opened read-only \(mode='r'\)"):
            d.write(power=0, n=1)
        with pytest.raises(lbd.LBDError, match="opened read-only"):
            d.save(tmp_path / "copy.lbd")
        with pytest.raises(lbd.LBDError, match="opened read-only"):
            d.values["S"].data[0] = 0
    with pytest.raises(lbd.LBDError, match="mode must be"):
        lbd.open(path, mode="w")


def test_r_plus_writes_in_place_and_saves(path, tmp_path):
    with lbd.open(path, mode="r+") as d:
        d.write(power=2, S=np.zeros(50))
        d.write(power=4, n=9)
        d.meta["checked"] = 1
        d.title = "checked"
        assert d.save() == path                      # in place
        copy = d.save(tmp_path / "copy.lbd")         # piece by piece
        assert d.path == path
    r = lbd.load(path)
    assert np.all(r.values["S"].data[2] == 0) and r.values["n"].data[4] == 9
    assert r.values["n"].measured.tolist() == [False, True, False, False, True, False]
    assert r.meta["checked"] == 1 and r.title == "checked"
    c = lbd.load(copy)
    np.testing.assert_array_equal(c.values["S"].data, r.values["S"].data)
    assert c.values["ok"].data.dtype == bool and c.parent_id == r.id and c.id != r.id
    np.testing.assert_array_equal(c.values["n"].measured, r.values["n"].measured)


def test_r_plus_adds_no_points(tmp_path):
    d = lbd.Dataset()
    d.add_group("AB")
    d.add_axis("A", group="AB")
    d.add_axis("B", group="AB")
    d.add_value("f", axes=["A", "B"])
    d.write(A=1, B=1, f=1.0)
    p = d.save(tmp_path / "g.lbd")
    with lbd.open(p, mode="r+") as o:
        o.write(A=1, B=1, f=2.0)                     # a point that exists: in place
        with pytest.raises(lbd.LBDError, match="to add points"):
            o.write(A=2, B=1, f=3.0)
    assert lbd.load(p).values["f"].data.tolist() == [2.0]


def test_rows_read_one_row_at_a_time(tmp_path, reads):
    d = lbd.Dataset()
    d.add_group("AB")
    d.add_axis("A", group="AB")
    d.add_axis("B", group="AB")
    d.add_value("f", axes=["A", "B"])
    for a in range(1, 4):
        d.write(A=a, B=np.arange(a), f=np.full(a, float(a)))
    p = d.save(tmp_path / "g.lbd")
    with lbd.open(p) as o:
        rows = list(o.values["f"].rows(by="A"))
    assert [r.values["f"].data.tolist() for _, r in rows] == [[1.0], [2.0, 2.0], [3.0, 3.0, 3.0]]
    assert [k for _, k in reads] == [(slice(0, 1),), (slice(1, 3),), (slice(3, 6),)]


def test_a_file_being_written(tmp_path):
    w = lbd.Writer(tmp_path / "live.lbd")
    w.add_axis("x", np.arange(4.0))
    w.add_value("y", axes="x")
    w.write(x=1, y=5.0)
    w.flush()
    with pytest.warns(lbd.LBDWarning, match="still being written"):
        d = lbd.open(w.writing_path)
    with d:
        assert d.values["y"].data[1] == 5.0 and np.isnan(d.values["y"].data[0])
    with pytest.raises(lbd.LBDError, match="mode='r'"):
        lbd.open(w.writing_path, mode="r+")
    w.close()


def test_not_held_open_the_file_can_be_renamed(path, tmp_path):
    d = lbd.open(path, hold=False)
    os.replace(path, tmp_path / "moved.lbd")          # Windows refuses this while a file is open
    with pytest.raises(FileNotFoundError):
        d.values["S"].data[0]
    d.close()
