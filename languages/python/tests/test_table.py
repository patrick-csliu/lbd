"""lbd.plot.table: what a plot shows as a table, written as CSV that numpy reads back (plan 5)."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import tables as tb

F = np.linspace(6.99e9, 7.01e9, 41)
P = np.array([-60.0, -50.0, -40.0])


@pytest.fixture()
def d():
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", P, unit="dBm", label="Power")
    d.add_axis("freq", F, unit="Hz", label="Frequency")
    d.add_axis("temp", [0.01, 0.02], unit="K", label="Temperature")
    rng = np.random.default_rng(1)
    z = rng.normal(size=(3, 41, 2)) + 1j * rng.normal(size=(3, 41, 2))
    d.add_value("S21", z, axes=["power", "freq", "temp"], label="S21")
    d.add_value("V", rng.normal(size=(3, 41)) * 1e-6, axes=["power", "freq"], unit="V", label="Voltage")
    return d


def read(path):
    return np.loadtxt(path, delimiter=",", ndmin=2, encoding="utf-8")


def test_curves_as_rows_read_back_with_loadtxt_and_names(d, tmp_path):
    t = lp.table(d, "curve", "S21", x="freq", complex="db", series="power", index={"temp": 1})
    out = t.to_csv(tmp_path / "a.csv")
    a = read(out)
    want = 20 * np.log10(np.abs(d.values["S21"].data[:, :, 1]))
    assert a.shape == (3 * 41, 3)
    np.testing.assert_array_equal(a[:, 0], np.repeat(P, 41))
    np.testing.assert_array_equal(a[:, 1], np.tile(F, 3))
    np.testing.assert_array_equal(a[:, 2], want.ravel())          # full precision: exactly the same numbers
    g = np.genfromtxt(out, delimiter=",", names=True, encoding="utf-8")
    assert g.dtype.names == ("power", "freq", "S21")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# power,freq,S21\n")
    assert "# fixed: Temperature = 0.02 K" in text and "complex mode: db" in text
    assert "\n-60,6990000000," in text                             # whole numbers without .0


def test_a_map_as_a_matrix_both_ways(d, tmp_path):
    t = lp.table(d, "heatmap", "V", x="freq", y="power")
    a = read(t.to_csv(tmp_path / "m.csv", layout="matrix"))
    assert np.isnan(a[0, 0])
    np.testing.assert_array_equal(a[0, 1:], F)
    np.testing.assert_array_equal(a[1:, 0], P)
    np.testing.assert_array_equal(a[1:, 1:], d.values["V"].data)
    b = read(t.to_csv(tmp_path / "m2.csv", layout="matrix", rows_are="x"))
    np.testing.assert_array_equal(b[0, 1:], P)
    np.testing.assert_array_equal(b[1:, 0], F)
    np.testing.assert_array_equal(b[1:, 1:], d.values["V"].data.T)


def test_zoomed_range_and_units_as_shown(d, tmp_path):
    t = lp.table(d, "heatmap", "V", x="freq", y="power", xlim=(7.0e9, 6.995e9), ylim=(-55, -35), units="shown")
    a = read(t.to_csv(tmp_path / "z.csv", layout="matrix"))
    keep = (F >= 6.995e9) & (F <= 7.0e9)
    np.testing.assert_allclose(a[0, 1:], F[keep] / 1e9)
    assert "\nnan,6.995," in (tmp_path / "z.csv").read_text(encoding="utf-8")   # exact text, no 6.995000000000001
    np.testing.assert_array_equal(a[1:, 0], [-50, -40])
    np.testing.assert_allclose(a[1:, 1:], d.values["V"].data[1:][:, keep] * 1e6)
    assert "Frequency (GHz)" in (tmp_path / "z.csv").read_text(encoding="utf-8") and "Voltage (µV)" in (tmp_path / "z.csv").read_text(encoding="utf-8")


def test_stored_numbers_and_both(d, tmp_path):
    t = lp.table(d, "curve", "S21", x="freq", complex="phase", numbers="both")
    out = t.to_csv(tmp_path / "b.csv")
    g = np.genfromtxt(out, delimiter=",", names=True, encoding="utf-8")
    assert g.dtype.names == ("power", "freq", "S21", "S21_re", "S21_im")
    g = g[g["power"] == -60]
    z = d.values["S21"].data[0, :, 0]
    np.testing.assert_array_equal(g["S21"], np.angle(z))
    np.testing.assert_array_equal(g["S21_re"] + 1j * g["S21_im"], z)
    s = lp.table(d, "curve", "V", numbers="stored")
    assert [c.name for c in s.columns()] == ["power", "freq", "V"]
    b = lp.table(d, "curve", "V", numbers="both")
    assert [c.name for c in b.columns()] == ["power", "freq", "V", "V_stored"]


def test_several_values_and_missing_points(d, tmp_path):
    v = d.values["V"].data.copy()
    v[0, :5] = np.nan
    d.add_value("W", v, axes=["power", "freq"], unit="V")
    t = lp.table(d, "curve", ["W"], series="power")
    a = read(t.to_csv(tmp_path / "w.csv"))
    assert a.shape[0] == 3 * 41 - 5                       # points with no number are left out
    with pytest.raises(ValueError, match="holds one value, not 2"):
        lp.table(d, "heatmap", "V", x="freq", y="power", numbers="both").to_csv(tmp_path / "x.csv", layout="matrix")
    with pytest.raises(ValueError, match="rows_are must be"):
        lp.table(d, "curve", "S21", x="freq", series="power", index={"temp": 0}).to_csv(tmp_path / "x.csv", layout="matrix",
                                                                                     rows_are="q")


def test_x_is_a_value(tmp_path):
    d = lbd.Dataset()
    d.add_axis("i", np.arange(4))
    d.add_axis("k", [0, 1])
    d.add_value("t", np.arange(8.0).reshape(4, 2) * 0.5, axes=["i", "k"], unit="s")
    d.add_value("y", np.arange(8.0).reshape(4, 2) ** 2, axes=["i", "k"])
    t = lp.table(d, "curve", "y", x="t")                    # one trace per i, along k
    a = read(t.to_csv(tmp_path / "r.csv"))
    np.testing.assert_array_equal(a[:, 0], np.repeat(np.arange(4), 2))
    np.testing.assert_array_equal(a[:, 1], np.arange(8.0) * 0.5)  # each trace its own x
    np.testing.assert_array_equal(a[:, 2], np.arange(8.0) ** 2)
    with pytest.raises(ValueError, match="own numbers per trace"):
        t.to_csv(tmp_path / "x.csv", layout="matrix")


def test_from_a_file_and_estimate(d, tmp_path):
    d.save(tmp_path / "s.lbd")
    t = lp.table(tmp_path / "s.lbd", "curve", "S21", x="freq", complex="db", series="power")
    est = t.estimate()
    out = t.to_csv(tmp_path / "s.csv")
    assert est["rows"] == 3 * 41 and est["columns"] == 3
    assert 0.8 < est["bytes"] / out.stat().st_size < 1.2
    assert "LBD export: s.lbd" in out.read_text(encoding="utf-8")
    m = lp.table(tmp_path / "s.lbd", "heatmap", "V", x="freq", y="power").estimate("matrix")
    assert (m["rows"], m["columns"]) == (4, 42)


def test_stopping_leaves_no_file(d, tmp_path):
    t = lp.table(d, "curve", "S21", x="freq", series="power")

    def stop(fraction):
        if fraction > 0.3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        t.to_csv(tmp_path / "s.csv", progress=stop)
    assert list(tmp_path.iterdir()) == []


def test_only_curves_and_maps(d):
    with pytest.raises(lp.RenderError, match="curves or a heat map"):
        lp.table(d, "scatter", "V", x="freq")
    with pytest.raises(ValueError, match="layout must be one of"):
        lp.table(d, "curve", "V").to_csv("x.csv", layout="wide")


def test_prefixed_and_scaled():
    assert tb.prefixed("Hz", 1e-9) == "GHz" and tb.prefixed("V", 1e6) == "µV" and tb.prefixed("dB", 1.0) == "dB"
    assert tb.scaled(np.array([7005000000.0]), 1e-9)[0] == 7.005


def test_one_trace_has_no_matrix(tmp_path):
    d = lbd.Dataset()
    d.add_axis("x", np.arange(5.0))
    d.add_value("y", np.arange(5.0) ** 2, axes="x")
    with pytest.raises(ValueError, match="two axes"):
        lp.table(d, "curve", "y").to_csv(tmp_path / "x.csv", layout="matrix")
    a = np.loadtxt(lp.table(d).to_csv(tmp_path / "y.csv"), delimiter=",", encoding="utf-8")
    np.testing.assert_array_equal(a, np.column_stack([np.arange(5.0), np.arange(5.0) ** 2]))
