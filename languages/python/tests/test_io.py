import json
import warnings

import h5py
import numpy as np
import pytest

import lbd


def make_sweep():
    f = np.linspace(4e9, 8e9, 41)
    p = np.arange(-40, 1, 4.0)
    s21 = np.exp(1j * np.outer(p, f) * 1e-10)
    d = lbd.Dataset(title="Resonator power sweep", description="test")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "freq"])
    d.add_value("mag", np.abs(s21), axes="power,freq", unit="", label="|S21|")
    return d


def test_roundtrip_values_and_axes(tmp_path):
    d = make_sweep()
    p = d.save(tmp_path / "sweep.lbd")
    r = lbd.load(p)
    assert r.title == "Resonator power sweep"
    assert r.description == "test"
    assert r.writer == f"python lbd {lbd.__version__}"
    assert r.lbd_version == "1.0"
    assert r.created
    np.testing.assert_array_equal(r["power"].data, d["power"].data)
    assert r["freq"].unit == "Hz" and r["freq"].label == "Frequency"
    assert r["S21"].axes == ["power", "freq"]
    assert r["S21"].data.dtype == np.complex128
    np.testing.assert_array_equal(r["S21"].data, d["S21"].data)
    assert r["mag"].label == "|S21|"


def test_file_layout_matches_spec(tmp_path):
    p = make_sweep().save(tmp_path / "sweep.lbd")
    with h5py.File(p, "r") as f:
        assert f.attrs["lbd_format"] == "LBD"
        assert f.attrs["lbd_version"] == "1.0"
        assert f["values/S21"].attrs["axes"] == "power,freq"
        # complex is stored as compound {r, i}
        t = f["values/S21"].id.get_type()
        assert isinstance(t, h5py.h5t.TypeCompoundID)
        assert [t.get_member_name(i) for i in range(t.get_nmembers())] == [b"r", b"i"]
        assert set(f.keys()) == {"axes", "values", "meta"}


def test_dtypes(tmp_path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5))
    d.add_value("i16", np.arange(5, dtype=np.int16), axes="x")
    d.add_value("f32", np.arange(5, dtype=np.float32), axes="x")
    d.add_value("c64", np.arange(5).astype(np.complex64), axes="x")
    d.add_value("mask", np.array([True, False, True, False, True]), axes="x")
    d.add_value("forced", np.arange(5), axes="x", dtype="float32")
    d.add_value("half", np.arange(5, dtype=np.float16), axes="x")
    r = lbd.load(d.save(tmp_path / "t.lbd"))
    assert r["i16"].data.dtype == np.int16
    assert r["f32"].data.dtype == np.float32
    assert r["c64"].data.dtype == np.complex64
    assert r["mask"].data.dtype == np.bool_
    np.testing.assert_array_equal(r["mask"].data, [True, False, True, False, True])
    assert r["forced"].data.dtype == np.float32
    assert r["half"].data.dtype == np.float32
    with h5py.File(tmp_path / "t.lbd", "r") as f:
        assert f["values/mask"].dtype == np.uint8
        assert f["values/mask"].attrs["lbd_bool"] == 1


def test_scalar_value(tmp_path):
    d = lbd.Dataset()
    d.add_value("fit_Q", 12345.6, unit="")
    r = lbd.load(d.save(tmp_path / "s.lbd"))
    assert r["fit_Q"].axes == []
    assert r["fit_Q"].data.shape == ()
    assert float(r["fit_Q"].data) == pytest.approx(12345.6)


def test_meta_roundtrip(tmp_path):
    d = lbd.Dataset()
    d.meta = {
        "T_mK": 12,
        "sample": "R7 – chip 3",  # non-ASCII
        "gain": 1.5,
        "flag": True,
        "z": 1 + 2j,
        "vec": [1.0, 2.0, 3.0],
        "mat": np.arange(6.0).reshape(2, 3),
        "names": ["a", "b"],
        "vna": {"ifbw_Hz": 1000.0, "averages": 4, "port": {"n": 2}},
    }
    r = lbd.load(d.save(tmp_path / "m.lbd"))
    m = r.meta
    assert m["T_mK"] == 12 and isinstance(m["T_mK"], int)
    assert m["sample"] == "R7 – chip 3"
    assert m["gain"] == 1.5
    assert m["flag"] == 1
    assert m["z"] == 1 + 2j
    np.testing.assert_array_equal(m["vec"], [1.0, 2.0, 3.0])
    assert m["mat"].shape == (2, 3)
    assert m["names"] == ["a", "b"]
    assert m["vna"]["averages"] == 4
    assert m["vna"]["port"]["n"] == 2


def test_plot_and_style(tmp_path):
    d = make_sweep()
    d.plot = {"kind": "heatmap", "values": ["S21"], "complex": "db"}
    d.style = {"figure": {"width_mm": 120}}
    d.style_name = "thesis"
    r = lbd.load(d.save(tmp_path / "p.lbd"))
    assert r.plot == d.plot
    assert r.style == d.style
    assert r.style_name == "thesis"
    with h5py.File(tmp_path / "p.lbd", "r") as f:
        assert json.loads(f["plot"].attrs["spec"])["kind"] == "heatmap"


def test_info_and_partial_load(tmp_path):
    p = make_sweep().save(tmp_path / "sweep.lbd")
    i = lbd.info(p)
    assert i["S21"].data is None
    assert i["S21"].shape == (11, 41)
    assert i["S21"].dtype == "complex128"
    part = lbd.load(p, values=["mag"])
    assert part["mag"].data is not None and part["S21"].data is None
    with pytest.raises(KeyError):
        lbd.load(p, values=["nope"])


def test_compression(tmp_path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(100))
    d.add_axis("y", np.arange(200))
    d.add_value("z", np.zeros((100, 200)), axes=["x", "y"])
    p = d.save(tmp_path / "c.lbd", compression="gzip")
    with h5py.File(p, "r") as f:
        assert f["values/z"].compression == "gzip"
    np.testing.assert_array_equal(lbd.load(p)["z"].data, 0)


@pytest.mark.parametrize(
    "build, msg",
    [
        (lambda d: d.add_axis("1bad", [1, 2]), "invalid name"),
        (lambda d: d.add_axis("x2", [[1, 2]]), "must be 1-D"),
        (lambda d: d.add_value("v", [1, 2, 3], axes="x"), "has length"),
        (lambda d: d.add_value("v", [1, 2], axes="nope"), "does not exist"),
        (lambda d: d.add_value("v", [[1, 2]], axes="x"), "dimension"),
        (lambda d: d.add_value("x", [1, 2], axes="x"), "already used"),
        (lambda d: d.add_value("v", ["a", "b"], axes="x"), "numeric"),
        (lambda d: d.add_value("v", [1j, 2j], axes="x", dtype="float64"), "imaginary"),
    ],
)
def test_validation_errors(build, msg):
    d = lbd.Dataset()
    d.add_axis("x", [1.0, 2.0])
    with pytest.raises(lbd.LBDError, match=msg):
        build(d)


def test_meta_none_rejected(tmp_path):
    d = lbd.Dataset()
    d.meta["x"] = None
    with pytest.raises(lbd.LBDError, match="None"):
        d.save(tmp_path / "n.lbd")
    assert not list(tmp_path.iterdir()), "failed save must not leave files behind"


def test_version_checks(tmp_path):
    p = make_sweep().save(tmp_path / "v.lbd")
    with h5py.File(p, "a") as f:
        f.attrs["lbd_version"] = "1.7"
    with pytest.warns(UserWarning, match="newer"):
        lbd.load(p)
    with h5py.File(p, "a") as f:
        f.attrs["lbd_version"] = "2.0"
    with pytest.raises(lbd.LBDVersionError):
        lbd.load(p)


def test_not_lbd(tmp_path):
    p = tmp_path / "plain.lbd"
    with h5py.File(p, "w") as f:
        f["x"] = [1, 2]
    with pytest.raises(lbd.LBDError, match="not an LBD file"):
        lbd.load(p)


def test_unknown_content_ignored(tmp_path):
    p = make_sweep().save(tmp_path / "u.lbd")
    with h5py.File(p, "a") as f:
        f.create_group("extra")["raw"] = np.arange(3)
        f.attrs["future_thing"] = "x"
        f["values/S21"].attrs["future_attr"] = 1
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        r = lbd.load(p)
    assert "S21" in r


def test_fixed_length_strings_accepted(tmp_path):
    """Other writers (e.g. MATLAB high-level API) may write fixed-length ASCII strings."""
    p = make_sweep().save(tmp_path / "fx.lbd")
    with h5py.File(p, "a") as f:
        f.attrs["title"] = np.bytes_(b"fixed title")
        f["axes/freq"].attrs["unit"] = np.bytes_(b"Hz")
    r = lbd.load(p)
    assert r.title == "fixed title"
    assert r["freq"].unit == "Hz"


def test_version_function():
    v = lbd.version()
    assert v["lbd_version"] == "1.0"
    assert v["package"] == lbd.__version__
