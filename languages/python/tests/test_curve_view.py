"""Curves of a variable sweep on its real axes (plan 16, 16.41): a value on two levels of an axis
group (B chosen per A) is drawn against B, one curve per step of A, each with its own x and
length; against A it is one curve per position inside a step; a value on A alone joins it when A
is horizontal. `lp.plot`, `lp.table` and the viewer share this (`lbd.groups.curve_view`)."""

import warnings

import lbd
import lbd.plot as lp
import matplotlib
import numpy as np
import pytest
from lbd.groups import curve_view
from lbd.plot import render as rnd
from lbd.plot.style import Style

matplotlib.use("Agg")

POWERS = np.linspace(-60, 0, 21)


def resonator() -> lbd.Dataset:
    """As the viewer's mock file 13: per power its own frequencies (more at low power), Q per power."""
    d = lbd.Dataset(title="Variable sweep")
    d.add_group("scan")
    d.add_axis("power", group="scan", unit="dBm", label="Power")
    d.add_axis("freq", group="scan", unit="Hz", label="Frequency")
    d.add_value("S21", axes=["power", "freq"], dtype="complex128")
    d.add_value("Q", axes="power", label="Quality factor")
    for p in POWERS:
        f = np.linspace(7e9 - 3e6 + p * 1e4, 7e9 + 3e6 + p * 1e4, 40 + int(-p / 10))
        d.write(power=p, freq=f, S21=1 - 0.5 / (1 + 1j * (f - 7e9) / 1e6))
        d.write(power=p, Q=1e4 + p)
    return d


def triangle() -> lbd.Dataset:
    """As mock file 14: A = 1 … 40 and for each A, B = 1 … A."""
    d = lbd.Dataset(title="Triangle")
    d.add_group("tri")
    d.add_axis("A", group="tri")
    d.add_axis("B", group="tri")
    d.add_value("S", axes=["A", "B"])
    for a in range(1, 41):
        b = np.arange(1, a + 1)
        d.write(A=a, B=b, S=a * 100 + b)
    return d


def curves(d, **spec):
    out = rnd.resolve_spec(d, {"kind": "curve", **spec})
    return out, rnd.prepare_curves(d, out, Style())


def stored(d, value, outer, k):
    """The stored points of step k: (inner coordinates, values)."""
    real = d.values[value]
    a, b = d.groups[d.axes[outer].group].order
    parent = np.asarray(d.axes[b].parent)
    return np.asarray(d.axes[b].data)[parent == k], np.asarray(real.data)[parent == k]


def test_the_view_pads_each_step_and_shares_nothing_it_changes():
    d = triangle()
    v = curve_view(d)
    assert v.values["S"].axes == ["A", "B_n"] and v.values["S"].shape == (40, 40)
    assert v.values["B"].axes == ["A", "B_n"] and v.axes["B_n"].label == "B (point in step)"
    np.testing.assert_array_equal(v.axes["A"].data, np.arange(1, 41))
    row = v.values["S"].data[11]                                      # A = 12: 12 points, then missing
    np.testing.assert_array_equal(row[:12], 1200 + np.arange(1, 13))
    assert np.all(np.isnan(row[12:]))
    assert curve_view(v) is v and d.values["S"].data.shape == (820,)


def test_s_against_b_at_a_12():
    d = triangle()
    out, m = curves(d, values="S")
    assert out["x"] == "B" and out["series"] == "A"                   # starts on the inner level's coordinates
    x, y = m.xs[11], m.lines[11][0]
    keep = np.isfinite(y)
    b, s = stored(d, "S", "A", 11)
    np.testing.assert_array_equal(x[keep], b)
    np.testing.assert_array_equal(y[keep], s)
    assert m.lines[11][1] == "A = 12"


def test_s21_against_frequency_at_minus_30_dbm():
    d = resonator()
    out, m = curves(d, values="S21", series="none", index={"power": 10})
    assert out["x"] == "freq" and POWERS[10] == -30
    f, s = stored(d, "S21", "power", 10)
    y = m.lines[0][0]
    keep = np.isfinite(y)
    assert keep.sum() == f.size == 43
    np.testing.assert_allclose(m.xs[0][keep] / m.xf, f)
    np.testing.assert_allclose(y[keep], np.abs(s))


def test_the_outer_axis_horizontal_gives_point_n_of_each_step():
    d = triangle()
    out, m = curves(d, values="S", x="A")
    assert out["series"] == "B_n" and m.lines[2][1] == "point 2 of each step"
    y = m.lines[2][0]
    # the 3rd point of each step: A = 3 … 40 have one, A = 1 and 2 don't (left out)
    assert np.all(np.isnan(y[:2]))
    np.testing.assert_array_equal(y[2:], np.arange(3, 41) * 100 + 3)


def test_q_joins_s21_with_power_horizontal_and_is_refused_with_frequency():
    d = resonator()
    out, m = curves(d, values=["S21", "Q"], x="power", index={"freq_n": 0})
    assert [label for _, label in m.lines] == ["|S21|", "Quality factor"]
    np.testing.assert_array_equal(m.lines[1][0], 1e4 + POWERS)
    with pytest.raises(rnd.RenderError, match="one number per step of Power.*with Power horizontal they can"):
        curves(d, values=["S21", "Q"])


def test_no_notice_for_two_levels():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out, _ = curves(resonator(), values="S21")
    assert out["real_axes"]["coordinates"] == ["freq"]
    assert {a["name"]: a["in_step"] for a in out["real_axes"]["axes"]} == {"power": False, "freq_n": True}


def test_plot_and_table_give_the_same_lines(tmp_path):
    p = triangle().save(tmp_path / "t.lbd")
    fig = lp.plot(p, "curve", "S")
    drawn = [line.get_xydata() for line in fig.axes[0].get_lines()]
    assert len(drawn) == 40 and len(drawn[11][np.isfinite(drawn[11][:, 1])]) == 12
    t = lp.table(p, "curve", "S")
    csv = t.to_csv(tmp_path / "t.csv")
    rows = np.loadtxt(csv, delimiter=",")
    assert rows.shape == (820, 3)                                     # every stored point once, no padding
    a12 = rows[rows[:, 0] == 12]
    np.testing.assert_array_equal(a12[:, 1:], drawn[11][np.isfinite(drawn[11][:, 1])])
    with pytest.raises(ValueError, match="its own numbers per trace"):
        t.to_csv(tmp_path / "m.csv", layout="matrix")
