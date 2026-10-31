import json
import sys
import threading
import time
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
    assert r.lbd_version == lbd.FORMAT_VERSION == "1.2"
    assert r.created
    np.testing.assert_array_equal(r["power"].data, d["power"].data)
    assert r["freq"].unit == "Hz" and r["freq"].label == "Frequency"
    assert r["S21"].axes == ["power", "freq"]
    assert r["S21"].data.dtype == np.complex128
    np.testing.assert_array_equal(r["S21"].data, d["S21"].data)
    assert r["mag"].label == "|S21|"


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to replace an open file")
def test_save_waits_for_a_file_another_program_has_open(tmp_path, monkeypatch):
    """A viewer reading the file while a simulation saves it again: the save waits, then goes on."""
    p = make_sweep().save(tmp_path / "sweep.lbd")
    reader = open(p, "rb")                      # like LBD Viewer reading the previous version
    threading.Timer(0.5, reader.close).start()
    t0 = time.monotonic()
    make_sweep().save(p)
    assert time.monotonic() - t0 >= 0.4 and lbd.info(p).title == "Resonator power sweep"
    assert not list(tmp_path.glob("*.tmp-*"))  # no leftover temporary file

    monkeypatch.setattr(lbd.io, "REPLACE_WAIT", 0.3)
    with open(p, "rb"), pytest.raises(PermissionError, match="another program kept it open"):
        make_sweep().save(p)
    assert not list(tmp_path.glob("*.tmp-*"))


def test_file_layout_matches_spec(tmp_path):
    p = make_sweep().save(tmp_path / "sweep.lbd")
    with h5py.File(p, "r") as f:
        assert f.attrs["lbd_format"] == "LBD"
        assert f.attrs["lbd_version"] == "1.2"
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
    assert v["lbd_version"] == "1.2"
    assert v["package"] == lbd.__version__


# ---- created: when the data was created ------------------------------------------------------

def test_created_is_filled_at_the_first_save_and_kept_after(tmp_path):
    d = make_sweep()
    assert d.created is None
    d.save(tmp_path / "a.lbd")
    first = d.created
    assert first and lbd.load(tmp_path / "a.lbd").created == first
    r = lbd.load(tmp_path / "a.lbd")
    r.description = "edited later"
    r.save(tmp_path / "a.lbd")                                   # saved again: the date stays
    assert lbd.load(tmp_path / "a.lbd").created == first
    d.save(tmp_path / "b.lbd")                                   # the same Dataset saved again too
    assert lbd.load(tmp_path / "b.lbd").created == first


def test_created_can_be_given_and_overridden(tmp_path):
    import datetime as dt

    d = lbd.Dataset(title="t", created="2025-03-01T23:30:00+08:00")
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [1.0, 2.0], axes="x")
    d.save(tmp_path / "a.lbd")
    assert lbd.load(tmp_path / "a.lbd").created == "2025-03-01T23:30:00+08:00"   # kept as written
    d.created = dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    d.save(tmp_path / "a.lbd")
    assert lbd.load(tmp_path / "a.lbd").created == "2024-01-02T03:04:05-05:00"
    d.created = "2024-06-01T12:00:00Z"                          # UTC as Z
    d.save(tmp_path / "a.lbd")
    assert lbd.load(tmp_path / "a.lbd").created == "2024-06-01T12:00:00Z"
    d.created = dt.datetime(2024, 6, 1, 12, 0, 0)               # no offset: this computer's
    d.save(tmp_path / "a.lbd")
    got = dt.datetime.fromisoformat(lbd.load(tmp_path / "a.lbd").created)
    assert got.tzinfo is not None and got.replace(tzinfo=None) == dt.datetime(2024, 6, 1, 12, 0, 0)


@pytest.mark.parametrize("bad", ["yesterday", "2025-03-01", 20250301, "2025-13-01T00:00:00+00:00"])
def test_a_created_that_is_no_date_and_time_says_so(tmp_path, bad):
    with pytest.raises(lbd.LBDError, match="created must be a date and time"):
        lbd.Dataset(created=bad)
    d = make_sweep()
    d.created = bad
    with pytest.raises(lbd.LBDError, match="created must be a date and time"):
        d.save(tmp_path / "a.lbd")


# ---- id: the measurement's identity (format 1.1) ---------------------------------------------

def _is_uuid7(text):
    import uuid

    u = uuid.UUID(text)
    return text == str(u) and u.version == 7 and u.variant == uuid.RFC_4122


def test_an_id_is_made_at_the_first_save_and_kept_after(tmp_path):
    import uuid

    d = make_sweep()
    assert d.id is None and d.parent_id is None
    t0 = time.time()
    d.save(tmp_path / "a.lbd")
    assert _is_uuid7(d.id) and d.parent_id is None
    ms = uuid.UUID(d.id).int >> 80                                  # the time field (RFC 9562)
    assert abs(ms / 1000 - t0) < 5
    first = d.id
    r = lbd.load(tmp_path / "a.lbd")
    assert r.id == first
    r.description = "edited"
    r.save(tmp_path / "a.lbd")                                       # the same file: the same id
    assert lbd.info(tmp_path / "a.lbd").id == first
    with pytest.raises(AttributeError):
        r.id = "something else"                                      # read-only


def test_saving_to_another_file_makes_a_new_measurement(tmp_path):
    d = make_sweep()
    d.save(tmp_path / "a.lbd")
    r = lbd.load(tmp_path / "a.lbd")
    r.save(tmp_path / "b.lbd")
    b = lbd.info(tmp_path / "b.lbd")
    assert b.id != d.id and b.parent_id == d.id and _is_uuid7(b.id)
    r.save(tmp_path / "b.lbd")                                       # b again: kept
    assert lbd.info(tmp_path / "b.lbd").id == b.id
    old = r.id
    assert r.new_id() != old and r.parent_id == old                  # on purpose, over the same file
    r.save(tmp_path / "b.lbd")
    assert lbd.info(tmp_path / "b.lbd").parent_id == old


def test_a_copied_file_keeps_its_id_and_an_older_file_gets_one(tmp_path):
    import shutil

    d = make_sweep()
    d.save(tmp_path / "a.lbd")
    shutil.copy(tmp_path / "a.lbd", tmp_path / "copy.lbd")
    c = lbd.load(tmp_path / "copy.lbd")
    assert c.id == d.id
    c.save(tmp_path / "copy.lbd")                                    # saved where it is: kept
    assert lbd.info(tmp_path / "copy.lbd").id == d.id
    with h5py.File(tmp_path / "a.lbd", "a") as f:                    # as written before format 1.1
        del f.attrs["id"]
        f.attrs["lbd_version"] = "1.0"
    old = lbd.load(tmp_path / "a.lbd")
    assert old.id is None
    old.save(tmp_path / "a.lbd")
    assert _is_uuid7(lbd.info(tmp_path / "a.lbd").id) and lbd.info(tmp_path / "a.lbd").parent_id is None


def test_a_malformed_id_warns_and_is_left_out(tmp_path):
    make_sweep().save(tmp_path / "a.lbd")
    with h5py.File(tmp_path / "a.lbd", "a") as f:
        f.attrs["id"] = "not-a-uuid"
    with pytest.warns(lbd.LBDWarning, match="not a UUID"):
        assert lbd.info(tmp_path / "a.lbd").id is None


def test_seeded_generators_never_repeat_an_id(tmp_path):
    import random

    ids = []
    for _ in range(2):
        random.seed(0)
        np.random.seed(0)
        d = make_sweep()
        d.save(tmp_path / f"s{len(ids)}.lbd")
        ids.append(d.id)
    assert ids[0] != ids[1]
    many = {lbd.io.new_uuid7() for _ in range(20000)}
    assert len(many) == 20000 and all(_is_uuid7(u) for u in list(many)[:100])


def _ids_in_a_process(n):
    return [lbd.io.new_uuid7() for _ in range(n)]


@pytest.mark.parametrize("method", ["spawn", "fork"])
def test_processes_at_the_same_moment_get_different_ids(method):
    import multiprocessing as mp

    if method not in mp.get_all_start_methods():
        pytest.skip(f"no {method!r} processes on this system")
    ctx = mp.get_context(method)
    lbd.io.new_uuid7()                                               # the parent has made ids before forking
    with ctx.Pool(6) as pool:
        out = pool.map(_ids_in_a_process, [2000] * 6)
    ids = [u for chunk in out for u in chunk]
    assert len(set(ids)) == len(ids) == 12000
