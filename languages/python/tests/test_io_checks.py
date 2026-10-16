"""Every parameter of lbd's file API, and every error and warning: nothing is accepted silently."""

import json
import warnings

import h5py
import numpy as np
import pytest

import lbd
from lbd import LBDError, LBDWarning


def base(n=4):
    d = lbd.Dataset(title="t")
    d.add_axis("x", np.arange(n, dtype=float), unit="s")
    return d


# ---- Dataset() ------------------------------------------------------------------------------


@pytest.mark.parametrize("kw", [{"title": 5}, {"description": None}, {"title": b"x"}])
def test_dataset_text_must_be_str(kw):
    with pytest.raises(TypeError, match="must be a string"):
        lbd.Dataset(**kw)


def test_repr_lists_axes_and_values():
    d = base()
    d.add_value("y", np.ones(4), axes="x", unit="V")
    text = repr(d)
    assert "axis  x[4] s" in text and "value y(x) float64 V" in text


def test_getitem_and_contains():
    d = base()
    d.add_value("y", np.ones(4), axes="x")
    assert d["y"].name == "y" and d["x"].name == "x"
    assert "y" in d and "x" in d and "z" not in d
    with pytest.raises(KeyError, match="no axis or value named 'z'"):
        d["z"]


# ---- add_axis ---------------------------------------------------------------------------------


@pytest.mark.parametrize("data, match", [
    ([], "empty"),
    ([[1, 2], [3, 4]], "1-D"),
    (5.0, "1-D"),
    ([1.0, np.nan], "NaN or inf"),
    ([1.0, np.inf], "NaN or inf"),
    ([True, False], "real numeric"),
    ([1j, 2j], "real numeric"),
    (["a", "b"], "real numeric"),
    (np.ma.masked_array([1.0, 2.0], mask=[0, 1]), "masked"),
])
def test_add_axis_rejects(data, match):
    with pytest.raises(LBDError, match=match):
        lbd.Dataset().add_axis("x", data)


@pytest.mark.parametrize("kw", [{"unit": None}, {"unit": 3}, {"label": 1.5}])
def test_add_axis_text_arguments(kw):
    with pytest.raises(TypeError):
        lbd.Dataset().add_axis("x", [1.0, 2.0], **kw)


def test_add_axis_label_defaults_to_name():
    assert lbd.Dataset().add_axis("freq", [1.0, 2.0]).label == "freq"


@pytest.mark.parametrize("name", ["1x", "", "a b", "x" * 64, None, 3, "_x", "ä"])
def test_invalid_names(name):
    with pytest.raises(LBDError, match="invalid name"):
        lbd.Dataset().add_axis(name, [1.0])


def test_non_monotonic_axis_warns():
    with pytest.warns(LBDWarning, match="not strictly increasing"):
        lbd.Dataset().add_axis("x", [0.0, 2.0, 1.0])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        lbd.Dataset().add_axis("x", [3.0, 2.0, 1.0])   # decreasing is fine
        lbd.Dataset().add_axis("y", [1.0, 1.0])        # two points: no check


def test_long_double_warns_and_is_stored_as_float64():
    if np.dtype(np.longdouble).itemsize <= 8:
        pytest.skip("long double is float64 on this platform")
    with pytest.warns(LBDWarning, match="long double"):
        a = lbd.Dataset().add_axis("x", np.array([1.0, 2.0], dtype=np.longdouble))
    assert a.data.dtype == np.float64


def test_float16_is_stored_as_float32_silently():
    a = lbd.Dataset().add_axis("x", np.array([1.0, 2.0], dtype=np.float16))
    assert a.data.dtype == np.float32


def test_big_endian_is_made_native():
    a = lbd.Dataset().add_axis("x", np.array([1.0, 2.0], dtype=">f8"))
    assert a.data.dtype.byteorder in ("=", "|", "<")


# ---- add_value -------------------------------------------------------------------------------


@pytest.mark.parametrize("axes", ["x", ["x"], ("x",), "x,", np.array(["x"])])
def test_axes_forms(axes):
    d = base()
    if axes == "x,":
        with pytest.raises(LBDError):
            d.add_value("y", np.ones(4), axes=axes)
        return
    assert d.add_value("y", np.ones(4), axes=axes).axes == ["x"]


def test_axes_errors():
    d = base()
    d.add_axis("z", [1.0, 2.0, 3.0, 4.0])
    with pytest.raises(TypeError, match="dict"):
        d.add_value("y", np.ones(4), axes={"x": 0})
    with pytest.raises(TypeError, match="strings"):
        d.add_value("y", np.ones(4), axes=[1])
    with pytest.raises(TypeError):
        d.add_value("y", np.ones(4), axes=5)
    with pytest.raises(LBDError, match="more than once"):
        d.add_value("y", np.ones((4, 4)), axes=["x", "x"])
    with pytest.raises(LBDError, match="does not exist"):
        d.add_value("y", np.ones(4), axes="nope")
    with pytest.raises(LBDError, match="dimension"):
        d.add_value("y", np.ones(4), axes=["x", "z"])
    with pytest.raises(LBDError, match="size 3"):
        d.add_value("y", np.ones(3), axes="x")


def test_scalar_value_with_empty_axes_string():
    d = lbd.Dataset()
    assert d.add_value("q", 3.5, axes="").shape == ()
    assert d.add_value("r", 2.0).axes == []


@pytest.mark.parametrize("data", [["a"], [None], np.array([object()]), np.ma.masked_array([1.0], mask=[1])])
def test_add_value_rejects_non_numeric(data):
    d = lbd.Dataset()
    d.add_axis("x", [0.0])
    with pytest.raises(LBDError):
        d.add_value("y", data, axes="x")


def test_ragged_data():
    d = lbd.Dataset()
    d.add_axis("x", [0.0, 1.0])
    with pytest.raises(LBDError):
        d.add_value("y", [[1.0], [1.0, 2.0]], axes="x")


@pytest.mark.parametrize("dtype, data, ok", [
    ("int32", [1.0, 2.0], True),
    ("int32", [1.5, 2.0], False),          # would truncate
    ("int32", [np.nan, 1.0], False),
    ("uint8", [300, 1], False),            # would wrap
    ("uint8", [-1, 1], False),
    ("int8", [127, -128], True),
    ("bool", [0, 1], True),
    ("bool", [0, 2], False),
    ("float32", [1e39, 1.0], False),       # would become inf
    ("float32", [1.5, 2.5], True),
    ("float64", [1, 2], True),
    ("complex64", [1 + 1j, 2], True),
    ("float64", [1 + 1j, 2], False),       # would drop the imaginary part
    ("complex64", [1e39 + 0j, 0], False),
    ("float128", [1.0, 2.0], False),       # not an LBD type
    ("str", [1.0, 2.0], False),
])
def test_forced_dtype(dtype, data, ok):
    d = lbd.Dataset()
    d.add_axis("x", [0.0, 1.0])
    if ok:
        v = d.add_value("y", data, axes="x", dtype=dtype)
        assert v.dtype == dtype
        assert np.allclose(np.asarray(v.data, dtype=complex), np.asarray(data, dtype=complex))
    else:
        with pytest.raises(LBDError):
            d.add_value("y", data, axes="x", dtype=dtype)


def test_dtype_must_be_str():
    d = base()
    with pytest.raises(TypeError, match="dtype"):
        d.add_value("y", np.ones(4), axes="x", dtype=np.float32)


@pytest.mark.parametrize("kw", [{"unit": None}, {"label": 3}])
def test_add_value_text_arguments(kw):
    with pytest.raises(TypeError):
        base().add_value("y", np.ones(4), axes="x", **kw)


def test_name_shared_between_axis_and_value():
    d = base()
    with pytest.raises(LBDError, match="already used"):
        d.add_value("x", np.ones(4), axes="x")


# ---- save: everything is checked again -----------------------------------------------------


def test_save_rechecks_values_edited_by_hand(tmp_path):
    d = base()
    d.add_value("y", np.ones(4), axes="x")
    d.values["y"].data = np.ones(5)
    with pytest.raises(LBDError, match="size 5"):
        d.save(tmp_path / "a.lbd")
    d.values["y"].data = np.array(["a"] * 4)
    with pytest.raises(LBDError, match="unsupported dtype"):
        d.save(tmp_path / "a.lbd")
    assert not list(tmp_path.iterdir())     # nothing written


def test_save_rechecks_axes_and_names(tmp_path):
    d = base()
    d.axes["x"].data = np.array([1.0, np.nan, 2.0, 3.0])
    with pytest.raises(LBDError, match="NaN"):
        d.save(tmp_path / "a.lbd")
    d = base()
    d.axes["y"] = d.axes["x"]
    with pytest.raises(LBDError, match="key and the name"):
        d.save(tmp_path / "a.lbd")
    d = base()
    d.axes["x"] = "not an axis"
    with pytest.raises(LBDError, match="not an lbd.Axis"):
        d.save(tmp_path / "a.lbd")
    d = base()
    d.title = 5
    with pytest.raises(TypeError):
        d.save(tmp_path / "a.lbd")


def test_save_refuses_unloaded_values(tmp_path):
    d = base()
    d.add_value("y", np.ones(4), axes="x")
    d.save(tmp_path / "a.lbd")
    info = lbd.info(tmp_path / "a.lbd")
    with pytest.raises(LBDError, match="not loaded"):
        info.save(tmp_path / "b.lbd")


@pytest.mark.parametrize("plot, match", [
    ({"kind": "curve", "xscale": "log"}, "unknown plot setting"),
    ({"title": float("nan")}, "NaN"),
    (["curve"], "must be a dict"),
    ({"title": object()}, "JSON"),
])
def test_save_checks_the_saved_view(tmp_path, plot, match):
    d = base()
    d.add_value("y", np.ones(4), axes="x")
    d.plot = plot
    with pytest.raises(LBDError, match=match):
        d.save(tmp_path / "a.lbd")


def test_save_checks_style_and_style_name(tmp_path):
    d = base()
    d.style = "big"
    with pytest.raises(LBDError, match="style must be a dict"):
        d.save(tmp_path / "a.lbd")
    d.style = None
    d.style_name = ""
    with pytest.raises(LBDError, match="empty"):
        d.save(tmp_path / "a.lbd")
    d.style_name = 5
    with pytest.raises(TypeError):
        d.save(tmp_path / "a.lbd")


def test_save_compression_argument(tmp_path):
    with pytest.raises(LBDError, match="compression"):
        base().save(tmp_path / "a.lbd", compression="zip")


def test_save_extension_warning(tmp_path):
    with pytest.warns(LBDWarning, match=".lbd extension"):
        base().save(tmp_path / "a.h5")


def test_failed_save_keeps_old_file_and_attributes(tmp_path):
    d = base()
    d.save(tmp_path / "a.lbd")
    created = d.created
    d.meta["bad"] = None
    with pytest.raises(LBDError):
        d.save(tmp_path / "a.lbd")
    assert d.created == created                     # not changed by the failed save
    assert lbd.load(tmp_path / "a.lbd").meta == {}  # old file intact


# ---- meta ------------------------------------------------------------------------------------


@pytest.mark.parametrize("value, match", [
    (None, "None"),
    (["a", 1], "only text or only numbers"),
    ([[1, 2], [3]], "can't store"),
    ([{"a": 1}], "dicts or None"),
    (2 ** 70, "int64"),
    (object(), "can't store a value"),
    (np.ma.masked_array([1.0]), "masked"),
    (np.array([["a", "b"], ["c", "d"]]), "1-D"),
])
def test_meta_rejects(tmp_path, value, match):
    d = base()
    d.meta["k"] = value
    with pytest.raises(LBDError, match=match):
        d.save(tmp_path / "a.lbd")


@pytest.mark.parametrize("key", ["", "a/b", ".", 5])
def test_meta_bad_keys(tmp_path, key):
    d = base()
    d.meta[key] = 1
    with pytest.raises(LBDError, match="invalid meta key"):
        d.save(tmp_path / "a.lbd")


def test_meta_numpy_scalars_and_bool_arrays(tmp_path):
    d = base()
    d.meta.update({"f": np.float32(1.5), "i": np.int16(3), "b": np.array([True, False]), "empty": []})
    d.save(tmp_path / "a.lbd")
    m = lbd.load(tmp_path / "a.lbd").meta
    assert m["f"] == pytest.approx(1.5) and m["i"] == 3
    assert list(m["b"]) == [1, 0] and len(m["empty"]) == 0


def test_meta_must_be_a_dict(tmp_path):
    d = base()
    d.meta = [1, 2]
    with pytest.raises(LBDError, match="meta must be a dict"):
        d.save(tmp_path / "a.lbd")


# ---- load / info -------------------------------------------------------------------------------


def saved(tmp_path, name="a.lbd"):
    d = base()
    d.add_value("y", np.ones(4), axes="x")
    d.add_value("z", np.zeros(4), axes="x")
    return d.save(tmp_path / name)


def test_load_values_forms(tmp_path):
    p = saved(tmp_path)
    assert lbd.load(p, values="y").values["z"].data is None      # a single name, not its letters
    assert lbd.load(p, values=["y", "z"]).values["z"].data is not None
    assert lbd.load(p, values=()).values["y"].data is None
    with pytest.raises(KeyError, match="no value"):
        lbd.load(p, values="nope")
    with pytest.raises(TypeError):
        lbd.load(p, values=5)
    with pytest.raises(TypeError):
        lbd.load(p, values=[1])


def test_load_missing_and_not_lbd(tmp_path):
    with pytest.raises(FileNotFoundError):
        lbd.load(tmp_path / "nope.lbd")
    (tmp_path / "text.lbd").write_text("hello")
    with pytest.raises(LBDError, match="not an HDF5"):
        lbd.load(tmp_path / "text.lbd")
    with pytest.raises(LBDError, match="folder"):
        lbd.load(tmp_path)


def _raw(tmp_path, build):
    p = tmp_path / "raw.lbd"
    with h5py.File(p, "w") as f:
        f.attrs.update({"lbd_format": "LBD", "lbd_version": "1.0", "title": "", "description": "",
                        "created": "", "writer": "test"})
        f.create_group("meta")
        build(f)
    return p


def test_load_format_violations(tmp_path):
    def no_groups(f):
        pass
    with pytest.raises(LBDError, match="no /axes"):
        lbd.load(_raw(tmp_path, no_groups))

    def bad_name(f):
        f.create_group("axes").create_dataset("1bad", data=[1.0])
        f.create_group("values")
    with pytest.raises(LBDError, match="invalid axis/value name"):
        lbd.load(_raw(tmp_path, bad_name))

    def string_axis(f):
        f.create_group("axes").create_dataset("x", data=np.array([b"a"]))
        f.create_group("values")
    with pytest.raises(LBDError, match="1-D real"):
        lbd.load(_raw(tmp_path, string_axis))

    def string_value(f):
        f.create_group("axes").create_dataset("x", data=[1.0])
        ds = f.create_group("values").create_dataset("v", data=np.array([b"a"]))
        ds.attrs["axes"] = "x"
    with pytest.raises(LBDError, match="unsupported type"):
        lbd.load(_raw(tmp_path, string_value))

    def same_name(f):
        f.create_group("axes").create_dataset("x", data=[1.0])
        ds = f.create_group("values").create_dataset("x", data=[1.0])
        ds.attrs["axes"] = "x"
    with pytest.raises(LBDError, match="axis and a value"):
        lbd.load(_raw(tmp_path, same_name))

    def bad_bool(f):
        f.create_group("axes").create_dataset("x", data=[1.0])
        ds = f.create_group("values").create_dataset("v", data=np.array([0, 1], dtype=np.uint8)[:1])
        ds.attrs["axes"] = "x"
        ds.attrs["lbd_bool"] = np.int64(2)
    with pytest.raises(LBDError, match="lbd_bool"):
        lbd.load(_raw(tmp_path, bad_bool))


def test_load_warnings(tmp_path):
    def odd(f):
        f.create_group("axes").create_dataset("x", data=[1.0, 2.0])
        ds = f.create_group("values").create_dataset("v", data=np.array([0, 5], dtype=np.uint8))
        ds.attrs["axes"] = "x"
        ds.attrs["lbd_bool"] = np.int64(1)
        f["meta"].create_dataset("table", data=[1, 2, 3])
        g = f.create_group("plot")
        g.attrs["spec"] = json.dumps({"kind": "curve", "colour": "x"})
        g.attrs["style"] = json.dumps([1, 2])
    with pytest.warns(LBDWarning) as rec:
        d = lbd.load(_raw(tmp_path, odd))
    text = " | ".join(str(w.message) for w in rec)
    assert "other than 0 and 1" in text
    assert "/meta/table is a dataset" in text
    assert "unknown setting(s) ['colour']" in text
    assert "must be a JSON object" in text
    assert d.plot == {"kind": "curve"} and d.style is None


def test_version_rules(tmp_path):
    def body(f):
        f.create_group("axes")
        f.create_group("values")
    p = _raw(tmp_path, body)
    for ver, exc in (("0.9", LBDError), ("2.0", lbd.LBDVersionError), ("x", LBDError)):
        with h5py.File(p, "r+") as f:
            f.attrs["lbd_version"] = ver
        with pytest.raises(exc):
            lbd.load(p)
    with h5py.File(p, "r+") as f:
        f.attrs["lbd_version"] = "1.7"
    with pytest.warns(LBDWarning, match="newer") as rec:
        lbd.load(p)
    assert rec[0].filename == __file__      # the warning points at the caller, not at lbd


def test_invalid_utf8_warns(tmp_path):
    def body(f):
        f.create_group("axes")
        f.create_group("values")
        f["meta"].attrs["note"] = np.bytes_(b"caf\xe9")
    with pytest.warns(LBDWarning, match="UTF-8"):
        d = lbd.load(_raw(tmp_path, body))
    assert d.meta["note"].startswith("caf")


# ---- set_plot -------------------------------------------------------------------------------


def test_set_plot_arguments(tmp_path):
    p = saved(tmp_path)
    with pytest.raises(TypeError, match="at least one"):
        lbd.set_plot(p)
    with pytest.raises(LBDError, match="unknown plot setting"):
        lbd.set_plot(p, spec={"knd": "curve"})
    with pytest.raises(LBDError, match="NaN"):
        lbd.set_plot(p, spec={"title": float("inf")})
    with pytest.raises(LBDError, match="style must be a dict"):
        lbd.set_plot(p, style=[1])
    with pytest.raises(LBDError, match="empty"):
        lbd.set_plot(p, style_name=" ")
    with pytest.raises(TypeError):
        lbd.set_plot(p, style_name=3)


def test_set_plot_set_and_remove(tmp_path):
    p = saved(tmp_path)
    lbd.set_plot(p, spec={"kind": "curve"}, style={"figure": {"width_mm": 100}}, style_name="thesis")
    d = lbd.info(p)
    assert d.plot == {"kind": "curve"} and d.style_name == "thesis" and d.style["figure"]["width_mm"] == 100
    lbd.set_plot(p, style_name=None)
    assert lbd.info(p).style_name is None and lbd.info(p).plot == {"kind": "curve"}
    lbd.set_plot(p, spec=None, style=None)
    with h5py.File(p) as f:
        assert "plot" not in f


def test_set_plot_on_other_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        lbd.set_plot(tmp_path / "nope.lbd", spec=None)
    (tmp_path / "x.lbd").write_text("no")
    with pytest.raises(LBDError):
        lbd.set_plot(tmp_path / "x.lbd", spec=None)
    p = tmp_path / "plain.lbd"
    with h5py.File(p, "w") as f:
        f.attrs["something"] = 1
    with pytest.raises(LBDError, match="not an LBD file"):
        lbd.set_plot(p, spec=None)


def test_set_plot_extension_warning(tmp_path):
    d = base()
    with pytest.warns(LBDWarning):
        p = d.save(tmp_path / "a.h5")
    with pytest.warns(LBDWarning, match=".lbd extension"):
        lbd.set_plot(p, spec={"kind": "auto"})


def test_errors_are_value_errors():
    assert issubclass(LBDError, ValueError) and issubclass(lbd.LBDVersionError, LBDError)
    assert issubclass(LBDWarning, UserWarning)
    assert lbd.PLOT_SPEC_KEYS >= {"kind", "values", "index"}
