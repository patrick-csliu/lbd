"""A whole file as CSV (lbd.plot.groups, table(group=)): one table per group of values on the
same axes, for any number of axes, complex values, data points of several numbers, variable
sweeps; read block by block."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import tables, whole


@pytest.fixture()
def d():
    """Axes A, B, C with u(A), v(A, B), w(A, B) and t(C), and a single number."""
    d = lbd.Dataset(title="Groups")
    d.add_axis("A", [1.0, 2.0, 3.0], unit="V", label="Bias")
    d.add_axis("B", [10.0, 20.0])
    d.add_axis("C", np.arange(5.0))
    d.add_value("u", [0.1, 0.2, 0.3], axes="A")
    d.add_value("v", np.arange(6.0).reshape(3, 2), axes=["A", "B"], unit="K")
    d.add_value("w", np.arange(6.0).reshape(3, 2) * (1 + 1j), axes=["A", "B"])
    d.add_value("t", np.arange(5.0) ** 2, axes="C")
    d.add_value("fidelity", 0.93)
    d.meta = {"fridge": "Bluefors"}
    return d


def read(path):
    return np.loadtxt(path, delimiter=",", ndmin=2, encoding="utf-8")


def test_the_groups_of_a_file(d, tmp_path):
    d.save(tmp_path / "g.lbd")
    for data in (d, tmp_path / "g.lbd"):
        gs = {g.key: g for g in lp.groups(data)}
        assert sorted(g.values for g in gs.values()) == [["t"], ["u"], ["v", "w"]]
        assert (gs["u"].rows, gs["v"].rows, gs["t"].rows) == (3, 6, 5)
        assert gs["v"].label == "v, w (A, B)" and gs["v"].columns == 5  # A, B, v, w_re, w_im


def test_one_group_as_rows(d, tmp_path):
    out = lp.table(d, group="w").to_csv(tmp_path / "w.csv")
    a = read(out)
    assert a.shape == (6, 5)
    np.testing.assert_array_equal(a[:, 0], [1, 1, 2, 2, 3, 3])
    np.testing.assert_array_equal(a[:, 1], [10, 20] * 3)
    np.testing.assert_array_equal(a[:, 2], np.arange(6.0))
    np.testing.assert_array_equal(a[:, 3] + 1j * a[:, 4], np.arange(6.0) * (1 + 1j))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# A,B,v,w_re,w_im\n")
    assert "fidelity = 0.93" in text and "Bluefors" in text and "in other tables (other axes): u, t" in text
    assert "A: Bias (V)" in text and "v (K)" in text


def test_three_axes_from_a_file_read_in_blocks(tmp_path, monkeypatch):
    d = lbd.Dataset()
    d.add_axis("a", np.arange(4.0))
    d.add_axis("b", np.arange(5.0))
    d.add_axis("c", np.arange(7.0))
    z = np.random.default_rng(1).normal(size=(4, 5, 7))
    d.add_value("z", z, axes=["a", "b", "c"])
    d.save(tmp_path / "z.lbd")
    whole_file = read(lp.table(tmp_path / "z.lbd", group="z").to_csv(tmp_path / "all.csv"))
    monkeypatch.setattr(tables, "BLOCK_NUMBERS", 4 * 3)                # 3 rows at a time: splits the last axis
    t = lp.table(tmp_path / "z.lbd", group="z")
    seen = []
    a = read(t.to_csv(tmp_path / "blocks.csv", progress=seen.append))
    np.testing.assert_array_equal(a, whole_file)
    np.testing.assert_array_equal(a[:, 3], z.ravel())
    np.testing.assert_array_equal(a[:, 0], np.repeat(np.arange(4.0), 35))
    assert len(seen) > 20 and seen[-1] == 1


def test_a_data_point_of_several_numbers(tmp_path):
    d = lbd.Dataset()
    d.add_axis("t", [0.0, 1.0])
    d.add_value("bloch", np.arange(6.0).reshape(2, 3), axes="t", shape=(3,), elements=["x", "y", "z"])
    a = lp.table(d, group="bloch").to_csv(tmp_path / "b.csv")
    assert a.read_text(encoding="utf-8").startswith("# t,bloch_x,bloch_y,bloch_z\n")
    np.testing.assert_array_equal(read(a)[:, 1:], np.arange(6.0).reshape(2, 3))


def test_a_variable_sweep_gives_each_point_its_coordinates(tmp_path):
    """Frequencies chosen per power: the points as measured, with both coordinates."""
    d = lbd.Dataset()
    d.add_group("g")
    d.add_axis("power", group="g")
    d.add_axis("f", group="g")
    d.add_value("S", axes=["power", "f"], dtype="float64")
    for p, fs in ((-20.0, [1.0, 2.0]), (-10.0, [5.0, 6.0, 7.0])):
        d.write(power=p, f=np.array(fs), S=p + np.array(fs))
    d.save(tmp_path / "v.lbd")
    a = read(lp.table(tmp_path / "v.lbd", group="S").to_csv(tmp_path / "v.csv"))
    np.testing.assert_array_equal(a, [[-20, 1, -19], [-20, 2, -18], [-10, 5, -5], [-10, 6, -4], [-10, 7, -3]])


def test_a_map_as_a_matrix_and_what_cant_be_one(d, tmp_path):
    t = lp.table(d, group="u")
    with pytest.raises(ValueError, match="needs two axes"):
        t.check_matrix()
    with pytest.raises(ValueError, match="one number per cell"):
        lp.table(d, group="v").check_matrix()                          # v and w
    d2 = lbd.Dataset()
    d2.add_axis("y", [1.0, 2.0])
    d2.add_axis("x", [5.0, 6.0, 7.0])
    d2.add_value("m", np.arange(6.0).reshape(2, 3), axes=["y", "x"])
    a = read(lp.table(d2, group="m").to_csv(tmp_path / "m.csv", "matrix"))
    np.testing.assert_array_equal(a[1:, 1:], np.arange(6.0).reshape(2, 3))
    np.testing.assert_array_equal(a[0, 1:], [5, 6, 7])


def test_an_unknown_group_says_which_there_are(d):
    with pytest.raises(ValueError, match="groups: u, v, t"):
        lp.table(d, group="nothing")
    with pytest.raises(ValueError, match="in the comments"):
        lp.table(d, group="fidelity")


def test_the_estimate_is_near_the_file(tmp_path):
    d = lbd.Dataset()
    d.add_axis("a", np.arange(200.0))
    d.add_axis("b", np.arange(300.0))
    d.add_value("z", np.random.default_rng(1).normal(size=(200, 300)), axes=["a", "b"])
    t = lp.table(d, group="z")
    est = t.estimate()
    assert est["rows"] == 60000 and est["columns"] == 3
    assert 0.7 < est["bytes"] / t.to_csv(tmp_path / "z.csv").stat().st_size < 1.3


def test_unmeasured_points_have_no_row(tmp_path):
    d = lbd.Dataset()
    d.add_axis("a", [1.0, 2.0, 3.0])
    d.add_value("z", [1.0, np.nan, 3.0], axes="a")
    np.testing.assert_array_equal(read(lp.table(d, group="z").to_csv(tmp_path / "z.csv"))[:, 0], [1, 3])
    assert whole.FileTable(d, "z").estimate()["rows"] == 3
