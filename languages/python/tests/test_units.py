"""Unit prefixes and axis labels (lbd.plot.units and lbd.plot.prefix)."""

import numpy as np
import pytest

pytest.importorskip("matplotlib")

import lbd.plot as lp  # noqa: E402
from lbd.plot.units import (  # noqa: E402
    AUTO_UNITS,
    PREFIXES,
    UnitWarning,
    axis_label,
    mathsafe,
    normalize_prefix,
    prefix_scale,
)


# ---- automatic prefix -------------------------------------------------------------------


@pytest.mark.parametrize("values, unit, expected", [
    ([6.99e9, 7.01e9], "Hz", "GHz"),
    ([1e-6, 5e-6], "s", "µs"),
    ([2.0, 5.0], "V", "V"),          # no prefix needed
    ([999.0], "m", "m"),
    ([1000.0], "m", "km"),
    ([-3e-3, 1e-3], "A", "mA"),       # the largest absolute value decides
    ([1e-18], "s", "as"),             # beyond the old f…T range
    ([2e15], "Hz", "PHz"),
    ([1e40], "Hz", "QHz"),            # clamped to the largest prefix
    ([1e-40], "s", "qs"),
])
def test_auto_prefix_choice(values, unit, expected):
    factor, new_unit = prefix_scale(np.array(values), unit)
    assert new_unit == expected
    exp = PREFIXES[new_unit[: len(new_unit) - len(unit)]]
    assert factor == pytest.approx(10.0 ** -exp)


@pytest.mark.parametrize("values", [[], [0.0, 0.0], [np.nan, np.inf]])
def test_auto_prefix_without_usable_numbers_keeps_the_unit(values):
    assert prefix_scale(np.array(values, dtype=float), "Hz") == (1.0, "Hz")


def test_auto_prefix_uses_magnitude_of_complex_data():
    assert prefix_scale(np.array([3e-3 + 4e-3j]), "V") == (1e3, "mV")


def test_auto_prefix_never_picks_c_d_da_h():
    for v in (0.01, 0.1, 10.0, 100.0):
        _, unit = prefix_scale(np.array([v]), "m")
        assert unit[:-1] not in ("c", "d", "da", "h")


@pytest.mark.parametrize("unit", ["dBm", "GHz", "a.u.", "Oe", "%"])
def test_auto_prefix_for_other_units_warns_and_keeps_values(unit):
    with pytest.warns(UnitWarning, match="no automatic prefix"):
        assert prefix_scale(np.array([7e9]), unit) == (1.0, unit)
    assert prefix_scale(np.array([7e9]), unit, warn=False) == (1.0, unit)


def test_empty_unit_gets_no_prefix_and_no_warning():
    assert prefix_scale(np.array([7e9]), "") == (1.0, "")


def test_auto_units_are_base_units():
    assert {"Hz", "s", "V", "m", "g", "Ohm", "Ω"} <= AUTO_UNITS
    assert "GHz" not in AUTO_UNITS and "dB" not in AUTO_UNITS


# ---- explicit prefix -----------------------------------------------------------------------


@pytest.mark.parametrize("to", sorted(p for p in PREFIXES if p))
def test_every_prefix_works_for_any_unit(to):
    factor, unit = prefix_scale(np.array([1.0]), "Oe", to=to)
    assert unit == to + "Oe"
    assert factor == pytest.approx(10.0 ** -PREFIXES[to])


@pytest.mark.parametrize("alias", ["u", "μ", "µ"])
def test_micro_spellings(alias):
    assert prefix_scale(np.array([1e-6]), "s", to=alias) == (pytest.approx(1e6), "µs")
    assert normalize_prefix(alias) == "µ"


def test_empty_prefix_keeps_the_unit_silently():
    assert prefix_scale(np.array([7e9]), "dBm", to="") == (1.0, "dBm")


def test_centi_on_metres():
    assert prefix_scale(np.array([0.05]), "m", to="c") == (pytest.approx(100.0), "cm")


@pytest.mark.parametrize("bad", ["x", "K", "milli", "auto ", "Mi"])
def test_unknown_prefix_is_an_error(bad):
    with pytest.raises(ValueError, match="unknown unit prefix"):
        prefix_scale(np.array([1.0]), "Hz", to=bad)


def test_prefix_needs_a_unit():
    with pytest.raises(ValueError, match="empty unit"):
        prefix_scale(np.array([1.0]), "", to="k")


@pytest.mark.parametrize("unit", [None, 3, b"Hz", ["Hz"]])
def test_unit_must_be_text(unit):
    with pytest.raises(TypeError, match="unit must be a string"):
        prefix_scale(np.array([1.0]), unit)


def test_values_must_be_numeric():
    with pytest.raises(TypeError, match="numeric"):
        prefix_scale(np.array(["a", "b"]), "Hz")


def test_prefix_type_must_be_text():
    with pytest.raises(TypeError):
        normalize_prefix(3)


# ---- lp.prefix (public) ---------------------------------------------------------------------


def test_lp_prefix_scales_values():
    v, u = lp.prefix([7e9, 7.1e9], "Hz")
    assert u == "GHz" and v == pytest.approx([7.0, 7.1])
    v, u = lp.prefix(np.array([7e9]), "Hz", to="M")
    assert u == "MHz" and v == pytest.approx([7000.0])
    v, u = lp.prefix([3.0], "Oe", to="m")
    assert u == "mOe" and v == pytest.approx([3000.0])


def test_lp_prefix_values_round_trip():
    raw = np.array([1.5e-7, 2.5e-7])
    scaled, unit = lp.prefix(raw, "s")
    assert unit == "ns"
    assert scaled * 10.0 ** PREFIXES["n"] == pytest.approx(raw)   # 150 ns -> 1.5e-7 s


def test_lp_prefix_respects_a_style_without_auto_prefix():
    off = {"figure": {"axes": {"axis": {"label": {"auto_prefix": False}}}}}
    v, u = lp.prefix([7e9], "Hz", style=off)
    assert u == "Hz" and v[0] == 7e9
    # an explicit prefix ignores that setting
    assert lp.prefix([7e9], "Hz", to="G", style=off)[1] == "GHz"
    # per-axis override
    y_off = {"figure": {"axes": {"yaxis": {"label": {"auto_prefix": False}}}}}
    assert lp.prefix([7e9], "Hz", style=y_off, axis="y")[1] == "Hz"
    assert lp.prefix([7e9], "Hz", style=y_off, axis="x")[1] == "GHz"


def test_lp_prefix_warns_for_unsupported_auto_unit():
    with pytest.warns(lp.UnitWarning):
        v, u = lp.prefix([1e-3], "dBm")
    assert u == "dBm" and v[0] == 1e-3


def test_lp_prefix_checks_axis():
    with pytest.raises(ValueError, match="axis"):
        lp.prefix([1.0], "Hz", axis="z")


def test_si_is_gone():
    assert not hasattr(lp, "si")


# ---- labels ------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, expected", [
    ("paren", "Frequency (GHz)"), ("bracket", "Frequency [GHz]"), ("slash", "Frequency / GHz")])
def test_axis_label_formats(fmt, expected):
    assert axis_label("Frequency", "GHz", fmt) == expected


def test_axis_label_without_unit():
    assert axis_label("Count", "", "slash") == "Count"


def test_axis_label_errors():
    with pytest.raises(ValueError, match="unit format"):
        axis_label("x", "m", "round")
    with pytest.raises(TypeError):
        axis_label(None, "m")
    with pytest.raises(TypeError):
        axis_label("x", None)


@pytest.mark.parametrize("text, expected", [
    ("$x$", "$x$"),                    # balanced math stays math
    ("costs 5$", r"costs 5\$"),        # a lone $ is escaped
    (r"a \$ and $b$", r"a \$ and $b$"),  # escaped $ doesn't count
    (r"a \$ b$", r"a \$ b\$"),
    ("plain", "plain"),
])
def test_mathsafe(text, expected):
    assert mathsafe(text) == expected


def test_mathsafe_type():
    with pytest.raises(TypeError):
        mathsafe(5)
