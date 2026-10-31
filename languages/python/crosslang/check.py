"""Check every <root>/*/fixture.lbd against the fixture definition in README.md."""

import sys
from pathlib import Path

import tempfile

import numpy as np

import lbd


def check(path: Path) -> None:
    d = lbd.load(path)
    assert d.title == "Fixture – ünïcode", d.title
    assert d.created == "2025-03-01T23:30:00+08:00", d.created
    import shutil
    import uuid

    u = uuid.UUID(d.id)
    assert str(u) == d.id and u.version == 7 and u.variant == uuid.RFC_4122, f"id {d.id!r}"
    with tempfile.TemporaryDirectory() as tmp:          # copied as a file, saved in place: same id
        shutil.copy(path, Path(tmp) / "copy.lbd")
        lbd.load(Path(tmp) / "copy.lbd").save(Path(tmp) / "copy.lbd")
        assert lbd.info(Path(tmp) / "copy.lbd").id == d.id, "id after saving a copy in place"
    with tempfile.TemporaryDirectory() as tmp:          # loaded and saved again: created kept
        d2 = lbd.load(path)
        d2.save(Path(tmp) / "again.lbd")
        again = lbd.load(Path(tmp) / "again.lbd")
        assert again.created == "2025-03-01T23:30:00+08:00", "created after saving again"
        assert again.id != d.id and again.parent_id == d.id, "saved to another file: a new id, parent_id"
    np.testing.assert_array_equal(d["x"].data, np.arange(10.0))
    assert d["x"].unit == "s" and d["a"].unit == "V" and d["b"].unit == "A" and d["c"].unit == "Hz"
    np.testing.assert_array_equal(d["y"].data, np.arange(10.0) ** 2)
    assert d["y"].unit == "s^2"
    assert d["k"].data.dtype == np.int32
    np.testing.assert_array_equal(d["k"].data, [(i + 1) * (-1) ** i for i in range(10)])
    assert d["mask"].data.dtype == np.bool_
    np.testing.assert_array_equal(d["mask"].data, np.arange(10) % 2 == 0)
    i, j, k = np.ogrid[0:3, 0:4, 0:2]
    assert d["M"].axes == ["a", "b"] and d["M"].data.shape == (3, 4)
    np.testing.assert_array_equal(d["M"].data, (10 * i + j)[:, :, 0])
    assert d["Z"].data.dtype == np.complex128
    np.testing.assert_array_equal(d["Z"].data, ((i + 1) + 1j * (j + 1))[:, :, 0])
    assert d["T"].axes == ["a", "b", "c"]
    np.testing.assert_array_equal(d["T"].data, 100 * i + 10 * j + k)
    assert d["q"].axes == [] and float(d["q"].data) == 42.5
    assert d["state"].elements == ["ground", "état 1", "量子"], d["state"].elements
    np.testing.assert_array_equal(d["state"].data, [0, 1, 2])
    np.testing.assert_array_equal(d["S"].data, [0.5, 1.5, 2.5])
    assert d["C"].axes == ["a", "C_dim1", "C_dim2"] and d["C"].point_shape == (2, 2), d["C"].axes
    assert d["C"].elements == [["I", "Q"], None], d["C"].elements
    assert d["C_dim1"].role == "point" and d["C_dim2"].role == "point" and d["a"].role is None
    r, c = np.ogrid[0:2, 0:2]
    np.testing.assert_array_equal(d["C"].data, 100 * np.arange(3)[:, None, None] + 10 * r + c)
    m = d.meta
    assert m["sample"] == "chip – é"
    assert m["T_mK"] == 12
    assert list(m["names"]) == ["a", "b"]
    np.testing.assert_array_equal(np.ravel(m["vec"]), [1, 2, 3])
    np.testing.assert_array_equal(m["mat"], [[0, 1, 2], [3, 4, 5]])
    assert m["vna"]["ifbw_Hz"] == 1000.0 and m["vna"]["averages"] == 4
    assert d.plot["kind"] == "heatmap" and list(d.plot["values"]) == ["M"]
    assert d.style_name == "thesis"
    assert isinstance(d.matplotlib, str) and d.matplotlib, "plot matplotlib version"


def check_live(path: Path) -> None:
    assert not Path(str(path) + ".writing").exists(), "the .writing file is left"
    d = lbd.load(path)
    assert d.title == "Live – ü", d.title
    s = d["S21"].data
    assert s.dtype == np.complex128 and s.shape == (3, 3), s.shape
    np.testing.assert_array_equal(s[:2], np.arange(1, 3)[:, None] + 1j * np.arange(1, 4)[None, :])
    assert np.all(np.isnan(s[2])), "power 3 is not measured"
    np.testing.assert_array_equal(d["time"].data, [0, 1, 2, 3])
    np.testing.assert_array_equal(d["T"].data, [0, 10, 20, 30])
    assert d["T"].measured is None and d["S21"].measured is None
    assert d["n"].data.dtype == np.int32
    np.testing.assert_array_equal(d["n"].data, [[0, 3, 0], [7, 0, 0]])
    np.testing.assert_array_equal(d["n"].measured, [[False, True, False], [True, False, False]])
    assert d["state"].elements == ["ground", "excited"]


root = Path(sys.argv[1])
failed = False
for name, test in (("fixture.lbd", check), ("live.lbd", check_live)):
    for p in sorted(root.glob(f"*/{name}")):
        try:
            test(p)
            print(f"  python reads {p.parent.name:7s} {name:11s} OK")
        except Exception as e:  # noqa: BLE001 - report every failure, then exit non-zero
            failed = True
            print(f"  python reads {p.parent.name:7s} {name:11s} FAILED: {type(e).__name__}: {e}")
sys.exit(1 if failed else 0)
