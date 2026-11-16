"""Filling values piece by piece (plan 6b): `add_value` without data, growing axes,
`Dataset.write`, and the `/measured` masks."""

import h5py
import numpy as np
import pytest

import lbd
from lbd import LBDError


@pytest.fixture()
def d():
    d = lbd.Dataset("sweep")
    d.add_axis("power", np.linspace(-60, 0, 4), unit="dBm")
    d.add_axis("freq", np.linspace(6e9, 7e9, 5), unit="Hz")
    d.add_axis("state", elements=["ground", "excited"])
    d.add_value("S21", axes=["power", "freq"], dtype="complex128")
    d.add_value("T", axes="power")
    d.add_value("n", axes=["state", "power"], dtype="int32")
    return d


def test_a_value_without_data_starts_not_measured(d):
    assert d.values["S21"].data.shape == (4, 5)
    assert np.all(np.isnan(d.values["S21"].data))
    assert d.values["S21"].measured is None              # NaN says it for floats
    assert d.values["n"].data.dtype == np.int32
    assert d.values["n"].measured.shape == (2, 4) and not d.values["n"].measured.any()


def test_a_trace_a_point_and_several_values_at_once(d):
    d.write(power=1, S21=np.arange(5) * 1j, T=4.2)       # a trace and a point
    d.write(power=2, freq=3, S21=1 + 2j)                 # one point
    assert np.array_equal(d.values["S21"].data[1], np.arange(5) * 1j)
    assert d.values["S21"].data[2, 3] == 1 + 2j
    assert np.isnan(d.values["S21"].data[2, 0])
    assert d.values["T"].data[1] == 4.2 and np.isnan(d.values["T"].data[0])


def test_a_whole_map_and_writing_again_replaces(d):
    d.write(S21=np.ones((4, 5)))
    d.write(power=0, S21=np.zeros(5))
    assert d.values["S21"].data[0].sum() == 0 and d.values["S21"].data[1:].sum() == 15


def test_positions_by_element_negative_index_and_dict(d):
    d.write(state="excited", power=-1, n=7)
    d.write({"state": 0, "power": 0}, n=3)
    assert d.values["n"].data[1, 3] == 7 and d.values["n"].data[0, 0] == 3
    assert d.values["n"].measured.sum() == 2


def test_a_data_point_with_a_shape():
    d = lbd.Dataset()
    d.add_axis("amp", np.linspace(0, 1, 3))
    d.add_value("bloch", axes="amp", shape=(3,), elements=["x", "y", "z"])
    d.write(amp=1, bloch=[0.1, 0.2, 0.3])
    assert np.allclose(d.values["bloch"].data[1], [0.1, 0.2, 0.3])
    with pytest.raises(LBDError, match=r"shape \(3,\)"):
        d.write(amp=0, bloch=1.0)


@pytest.mark.parametrize("call, message", [
    (dict(power=1, S21=np.ones(4)), r"needs data of shape \(5,\) \(freq\), not \(4,\)"),
    (dict(power=9, T=1), "out of range for 'power'"),
    (dict(freq=1, T=1), "'T' doesn't lie on 'freq'"),
    (dict(S21=1), r"needs data of shape \(4, 5\)"),
    (dict(state="mid", power=0, n=1), "no element 'mid'"),
    (dict(state=0, power=0, n=1.5), "whole numbers"),
    (dict(state=0, power=0, n=2 ** 40), "can't hold"),
    (dict(power=1, T=1j), "imaginary"),
    (dict(power=1.0, T=1), "an index"),
    (dict(power=1), "at least one value"),
    (dict(nope=1, T=1), "no axis or value named"),
])
def test_clear_errors(d, call, message):
    before = {k: v.data.copy() for k, v in d.values.items()}
    with pytest.raises(LBDError, match=message):
        d.write(**call)
    for k, v in d.values.items():                         # nothing half written
        assert np.array_equal(v.data, before[k], equal_nan=True)


def test_a_name_given_twice(d):
    with pytest.raises(LBDError, match="given twice"):
        d.write({"power": 0}, power=1, T=1)


def test_a_growing_axis_adds_rows():
    d = lbd.Dataset()
    d.add_axis("time", unit="s", grows=True)
    d.add_axis("ch", [1, 2])
    d.add_value("T", axes="time")
    d.add_value("V", axes=["time", "ch"])
    d.add_value("ok", axes="time", dtype="bool")
    d.write(time=0.5, T=1.0, V=[1, 2], ok=True)
    d.write(time=[1.0, 1.5], T=[2.0, 3.0])                # several rows; V and ok not given
    assert list(d.axes["time"].data) == [0.5, 1.0, 1.5]
    assert list(d.values["T"].data) == [1.0, 2.0, 3.0]
    assert d.values["V"].data.shape == (3, 2) and np.isnan(d.values["V"].data[1:]).all()
    assert list(d.values["ok"].measured) == [True, False, False]
    with pytest.raises(LBDError, match="give its coordinate"):
        d.write(T=1.0)


def test_a_growing_axis_must_be_first_and_have_points_to_save(tmp_path):
    d = lbd.Dataset()
    d.add_axis("x", [1, 2])
    d.add_axis("time", grows=True)
    with pytest.raises(LBDError, match="first axis"):
        d.add_value("bad", axes=["x", "time"])
    with pytest.raises(LBDError, match="no data or elements"):
        d.add_axis("t2", [1, 2], grows=True)
    d.add_value("T", axes="time")
    with pytest.raises(LBDError, match="no points yet"):
        d.save(tmp_path / "empty.lbd")


def test_masks_are_saved_only_when_something_is_missing(d, tmp_path):
    d.write(state="excited", power=1, n=5)
    d.write(power=0, T=1.0)
    d.save(tmp_path / "a.lbd")
    with h5py.File(tmp_path / "a.lbd", "r") as f:
        assert list(f["measured"]) == ["n"]
        assert f["measured/n"].dtype == np.uint8
    r = lbd.load(tmp_path / "a.lbd")
    assert r.values["n"].measured[1, 1] and r.values["n"].measured.sum() == 1
    assert r.values["T"].measured is None and np.isnan(r.values["T"].data[1])

    d.write(n=np.ones((2, 4)))                            # now everything is measured
    d.save(tmp_path / "b.lbd")
    with h5py.File(tmp_path / "b.lbd", "r") as f:
        assert "measured" not in f
    assert lbd.load(tmp_path / "b.lbd").values["n"].measured is None


def test_a_mask_of_the_wrong_shape_warns(d, tmp_path):
    d.save(tmp_path / "a.lbd")
    with h5py.File(tmp_path / "a.lbd", "a") as f:
        del f["measured/n"]
        f["measured/n"] = np.ones(3, dtype=np.uint8)
    with pytest.warns(lbd.LBDWarning, match="measured mask"):
        r = lbd.load(tmp_path / "a.lbd")
    assert r.values["n"].measured is None
