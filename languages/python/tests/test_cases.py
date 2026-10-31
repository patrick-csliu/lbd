"""The data API's worked cases (planning: plan 6c, "The data API"), each checked on the dataset
as built in memory and as loaded from its file: the two must read the same.

Case 1: all fixed axes. Case 5a: a 2 × 2 matrix per data point on fixed axes. The cases with
axis groups follow with them.
"""

import h5py
import numpy as np
import pytest

import lbd


def case1():
    d = lbd.Dataset("case 1")
    d.add_axis("A", [1, 2, 3])
    d.add_axis("B", [10, 20])
    d.add_axis("C", [0.1, 0.2, 0.3])
    d.add_value("f", np.arange(6.0).reshape(3, 2), axes=["A", "B"])
    d.add_value("h", np.arange(18.0).reshape(3, 2, 3), axes=["A", "B", "C"])
    return d


def case5a():
    d = lbd.Dataset("case 5a")
    d.add_axis("A", [1, 2, 3])
    d.add_axis("B", [10, 20])
    d.add_value("cov", np.arange(24.0).reshape(3, 2, 2, 2), axes=["A", "B"], shape=(2, 2),
                elements=[["I", "Q"], ["I", "Q"]])
    return d


@pytest.fixture(params=["built", "loaded"])
def source(request, tmp_path):
    """A case as built in memory, or after saving and loading it."""
    def get(make):
        d = make()
        if request.param == "built":
            return d
        return lbd.load(d.save(tmp_path / f"{make.__name__}.lbd"))
    return get


def test_case1_all_fixed(source):
    d = source(case1)
    assert list(d.axes) == ["A", "B", "C"]
    assert list(d.axes["B"].data) == [10, 20]
    f, h = d.values["f"], d.values["h"]
    assert f.axes == ["A", "B"] and f.dims == [("A",), ("B",)] and f.point_shape == () and f.shape == (3, 2)
    assert h.axes == ["A", "B", "C"] and h.dims == [("A",), ("B",), ("C",)] and h.shape == (3, 2, 3)
    assert f.data[0, 1] == 1.0 and f.elements == []


def test_case5a_a_matrix_per_point(source):
    d = source(case5a)
    assert list(d.axes) == ["A", "B"]                  # the data point isn't a sweep axis
    cov = d.values["cov"]
    assert cov.axes == ["A", "B"] and cov.dims == [("A",), ("B",)]
    assert cov.point_shape == (2, 2) and cov.shape == (3, 2, 2, 2)
    assert cov.elements == [["I", "Q"], ["I", "Q"]]
    assert np.array_equal(cov.data[0, 1], [[4, 5], [6, 7]])     # the 2 × 2 at A index 0, B index 1
    assert cov.data[0, 1, 0, 1] == 5                              # its I–Q element


def test_writing_takes_a_whole_data_point():
    d = lbd.Dataset()
    d.add_axis("A", [1, 2, 3])
    d.add_axis("B", [10, 20])
    d.add_value("cov", axes=["A", "B"], shape=(2, 2))
    d.write(A=0, B=1, cov=[[1, 0.1], [0.1, 2]])
    assert np.array_equal(d.values["cov"].data[0, 1], [[1, 0.1], [0.1, 2]])
    d.write(A=2, cov=np.ones((2, 2, 2)))                          # a row: one 2 × 2 per B
    assert np.all(d.values["cov"].data[2] == 1)
    with pytest.raises(lbd.LBDError, match=r"a data point of shape \(2, 2\)"):
        d.write(A=0, B=0, cov=[1, 2])
    with pytest.raises(lbd.LBDError, match="no axis or value named"):
        d.write(A=0, B=0, cov_dim1=0, cov=[[1, 2], [3, 4]])     # a data point is given whole


def test_compressed_values_are_chunked_for_reading_parts(tmp_path):
    """A row of a large value is read from one chunk; a data point is never split."""
    d = lbd.Dataset()
    d.add_axis("power", np.arange(200.0))
    d.add_axis("freq", np.arange(4096.0))
    d.add_value("S", np.zeros((200, 4096)), axes=["power", "freq"])
    d.add_value("cov", np.zeros((200, 4096, 2, 2)), axes=["power", "freq"], shape=(2, 2))
    p = d.save(tmp_path / "big.lbd", compression="gzip")
    with h5py.File(p, "r") as f:
        s = f["values/S"].chunks
        assert s[1] == 4096 and s[0] * 4096 * 8 <= 1 << 20       # whole traces, about 1 MB
        assert f["values/cov"].chunks[2:] == (2, 2)
        assert f["values/S"][7].shape == (4096,)


def test_uncompressed_values_are_stored_in_one_piece(tmp_path):
    with h5py.File(case1().save(tmp_path / "c.lbd"), "r") as f:
        assert f["values/h"].chunks is None
