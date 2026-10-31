"""Format 1.2 (plan 6a): elements of an axis, and the shape of a data point."""

import h5py
import numpy as np
import pytest

import lbd


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "e.lbd"


def test_an_axis_with_elements_is_written_and_read(path):
    d = lbd.Dataset()
    d.add_axis("state", elements=["ground", "excited"], label="Prepared state")
    d.add_axis("device", [1, 2, 5], elements=["Q1", "état 1", "量子"])
    d.add_axis("t", np.linspace(0, 1, 3))
    d.add_value("I", np.zeros((2, 3)), axes=["state", "t"])
    d.save(path)
    r = lbd.load(path)
    assert r.axes["state"].elements == ["ground", "excited"]
    assert list(r.axes["state"].data) == [0, 1]              # numbered itself
    assert r.axes["device"].elements == ["Q1", "état 1", "量子"]
    assert list(r.axes["device"].data) == [1, 2, 5]
    assert r.axes["t"].elements is None and r.axes["t"].role is None
    with h5py.File(path, "r") as f:
        assert f.attrs["lbd_version"] == "1.2"
        assert "role" not in f["axes/state"].attrs


def test_elements_may_repeat(path):
    d = lbd.Dataset()
    d.add_axis("step", elements=["ref", "sample", "ref", "sample"])
    d.save(path)
    assert lbd.load(path).axes["step"].elements == ["ref", "sample", "ref", "sample"]


def test_wrong_elements_are_refused_with_what_to_do():
    d = lbd.Dataset()
    with pytest.raises(lbd.LBDError, match="3 elements for 2 positions"):
        d.add_axis("x", [0, 1], elements=["a", "b", "c"])
    with pytest.raises(TypeError, match="elements must be texts"):
        d.add_axis("x", [0, 1], elements=["a", 2])
    with pytest.raises(TypeError, match="list of texts"):
        d.add_axis("x", [0, 1], elements="ab")
    with pytest.raises(lbd.LBDError, match="coordinates \\(data\\) or its elements"):
        d.add_axis("x")


def test_elements_changed_by_hand_are_checked_at_save(path):
    d = lbd.Dataset()
    d.add_axis("state", elements=["ground", "excited"])
    d.axes["state"].elements = ["ground"]
    with pytest.raises(lbd.LBDError, match="1 elements for 2 positions"):
        d.save(path)


def test_bad_elements_in_a_file_are_ignored_with_a_warning(path):
    d = lbd.Dataset()
    d.add_axis("state", elements=["ground", "excited"])
    d.save(path)
    with h5py.File(path, "a") as f:
        f["axes/state"].attrs.create("elements", np.array(["only one"], dtype=object), dtype=h5py.string_dtype())
        f["axes/state"].attrs["role"] = "nonsense"
    with pytest.warns(lbd.LBDWarning) as caught:
        r = lbd.load(path)
    assert r.axes["state"].elements is None and r.axes["state"].role is None
    text = " ".join(str(w.message) for w in caught)
    assert "elements" in text and "unknown role" in text


def test_a_vector_per_data_point(path):
    d = lbd.Dataset()
    d.add_axis("amp", np.linspace(0, 0.5, 4), unit="V")
    b = np.arange(12.0).reshape(4, 3)
    v = d.add_value("bloch", b, axes=["amp"], shape=(3,), elements=["x", "y", "z"])
    assert v.axes == ["amp"] and v.dims == [("amp",)] and v.point_shape == (3,)
    assert list(d.axes) == ["amp"]                     # the data point isn't a sweep axis
    d.save(path)
    r = lbd.load(path)
    assert np.array_equal(r.values["bloch"].data, b)
    assert r.values["bloch"].axes == ["amp"] and r.values["bloch"].point_shape == (3,)
    assert r.values["bloch"].elements == [["x", "y", "z"]]
    assert list(r.axes) == ["amp"]
    assert lbd.info(path).values["bloch"].point_shape == (3,)
    with h5py.File(path, "r") as f:                    # the file: as format 1.2 lays it out
        assert f["values/bloch"].attrs["axes"] == "amp,bloch_dim1"
        assert f["axes/bloch_dim1"].attrs["role"] == "point" and list(f["axes/bloch_dim1"][()]) == [0, 1, 2]


def test_a_matrix_per_data_point_with_one_dimension_numbered(path):
    d = lbd.Dataset()
    d.add_axis("amp", np.linspace(0, 0.5, 4))
    d.add_value("cov", np.zeros((4, 2, 2)), axes="amp", shape=(2, 2), elements=[["I", "Q"], None])
    d.save(path)
    r = lbd.load(path)
    assert r.values["cov"].point_shape == (2, 2)
    assert r.values["cov"].elements == [["I", "Q"], None]
    assert r.values["cov"].axes == ["amp"] and r.values["cov"].shape == (4, 2, 2)


def test_a_data_point_needs_its_shape_said():
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    with pytest.raises(lbd.LBDError, match=r"say so with shape=\(3,\)"):
        d.add_value("r", np.zeros((5, 3)), axes=["x"])


def test_the_value_axes_come_first():
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    with pytest.raises(lbd.LBDError, match="axes come first"):
        d.add_value("r", np.zeros((3, 5)), axes=["x"], shape=(3,))
    with pytest.raises(lbd.LBDError, match=r"not shape=\(4,\)"):
        d.add_value("r", np.zeros((5, 3)), axes=["x"], shape=(4,))


def test_elements_of_a_data_point_are_checked():
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    with pytest.raises(lbd.LBDError, match="2 elements for 3 positions"):
        d.add_value("r", np.zeros((5, 3)), axes=["x"], shape=(3,), elements=["u", "v"])
    with pytest.raises(lbd.LBDError, match="one list of elements per dimension"):
        d.add_value("c", np.zeros((5, 2, 2)), axes=["x"], shape=(2, 2), elements=[["I", "Q"]])
    with pytest.raises(lbd.LBDError, match="give shape= too"):
        d.add_value("s", np.zeros(5), axes=["x"], elements=["a"])
    with pytest.raises(TypeError, match="shape must be a tuple"):
        d.add_value("s", np.zeros((5, 3)), axes=["x"], shape="3")


def test_a_data_point_axis_name_already_used_is_refused():
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    d.add_axis("r_dim1", [0, 1, 2])
    with pytest.raises(lbd.LBDError, match="needs the name 'r_dim1'"):
        d.add_value("r", np.zeros((5, 3)), axes=["x"], shape=(3,))
    d.add_value("s", np.zeros((5, 3)), axes=["x"], shape=(3,))
    with pytest.raises(lbd.LBDError, match="dimension of a value's data points"):
        d.add_axis("s_dim1", [0, 1, 2])                # the file needs that name for s


def test_older_readers_see_ordinary_axes(path):
    """Every reader so far needs an axis for each dimension: the data point's axes are ordinary
    axes in the file, so files of 1.2 stay readable (only the new attributes are unknown)."""
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    d.add_value("r", np.zeros((5, 3)), axes=["x"], shape=(3,))
    d.save(path)
    with h5py.File(path, "r") as f:
        assert f["values/r"].attrs["axes"] == "x,r_dim1"
        assert f["axes/r_dim1"].shape == (3,)


def test_a_one_point_one_value_file_is_unchanged(path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    v = d.add_value("y", np.zeros(5), axes="x")
    assert v.point_shape == () and v.elements == [] and v.dims == [("x",)]


def test_a_data_point_changed_by_hand_is_checked_at_save(path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    v = d.add_value("r", np.zeros((5, 3)), axes=["x"], shape=(3,), elements=["u", "v", "w"])
    v.point_shape = (4,)
    with pytest.raises(lbd.LBDError, match=r"point_shape=\(4,\)"):
        d.save(path)
    v.point_shape = (3,)
    v.elements = [["u", "v"]]
    with pytest.raises(lbd.LBDError, match="2 elements for 3 positions"):
        d.save(path)
    v.elements = [None]
    d.save(path)
    assert lbd.load(path).values["r"].elements == [None]


def test_a_point_axis_no_value_uses_is_read_as_a_sweep_axis(path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    d.save(path)
    with h5py.File(path, "a") as f:
        f["axes/x"].attrs["role"] = "point"
    with pytest.warns(lbd.LBDWarning, match="read as a sweep axis"):
        r = lbd.load(path)
    assert r.axes["x"].role is None


def test_a_point_axis_also_swept_is_refused(path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(3))
    d.add_value("r", np.zeros((3, 3)), axes=["x"], shape=(3,))
    d.add_axis("x2", np.arange(3))
    d.add_value("s", np.zeros((3, 3)), axes=["x", "x2"])
    d.save(path)
    with h5py.File(path, "a") as f:
        f["values/s"].attrs["axes"] = "r_dim1,x"       # r_dim1 swept first: not s's data point
    with pytest.raises(lbd.LBDError, match="can't be both"):
        lbd.load(path)


def test_the_flat_view_has_an_axis_per_dimension():
    """Drawing code (lbd.plot, the viewer) sees the 1.2 layout: one axis per dimension."""
    from lbd.io import _flat_view

    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    d.add_value("cov", np.zeros((5, 2, 2)), axes="x", shape=(2, 2), elements=[["I", "Q"], None])
    flat = _flat_view(d)
    assert flat.values["cov"].axes == ["x", "cov_dim1", "cov_dim2"]
    assert flat.axes["cov_dim1"].role == "point" and flat.axes["cov_dim1"].elements == ["I", "Q"]
    assert flat.values["cov"].data is d.values["cov"].data          # shared, not copied
    assert _flat_view(flat) is flat and list(d.axes) == ["x"]
