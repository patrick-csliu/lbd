"""Units on plots: unit prefixes (Hz -> GHz) and axis labels, the same way everywhere in LBD.

LBD never converts between units (N to dyne, Hz to rad/s): it only puts a prefix in front of
the unit the data is stored in and scales the numbers to match.
"""

from __future__ import annotations

import math
import warnings
from typing import Tuple

import numpy as np

import lbd

# Every SI prefix and its power of ten.
PREFIXES = {
    "q": -30, "r": -27, "y": -24, "z": -21, "a": -18, "f": -15, "p": -12, "n": -9, "µ": -6,
    "m": -3, "c": -2, "d": -1, "": 0, "da": 1, "h": 2, "k": 3, "M": 6, "G": 9, "T": 12,
    "P": 15, "E": 18, "Z": 21, "Y": 24, "R": 27, "Q": 30,
}
# Other spellings of micro: ASCII "u" and the Greek letter mu (U+03BC); LBD writes the micro sign (U+00B5).
PREFIX_ALIASES = {"u": "µ", "μ": "µ"}
# The automatic choice uses steps of 1000 only (never c, d, da, h).
_AUTO_EXPONENTS = {exp: p for p, exp in PREFIXES.items() if exp % 3 == 0}
# Units that get an automatic prefix. Any other unit only gets one when it is asked for
# explicitly (`to="m"`), because a prefix would be wrong or confusing for it (dB, %, GHz, a.u.).
AUTO_UNITS = frozenset({"Hz", "s", "V", "A", "W", "Ω", "Ohm", "F", "H", "T", "K", "m", "g", "J",
                        "C", "S", "Pa", "N", "eV", "Wb"})
UNIT_FORMATS = ("paren", "bracket", "slash")


class UnitWarning(lbd.LBDWarning):
    """A unit prefix could not be applied as asked (e.g. automatic prefix for an unsupported unit).
    """


def normalize_prefix(to: str) -> str:
    """The canonical spelling of a prefix (`"u"` -> `"µ"`); raises ValueError for unknown ones."""
    if not isinstance(to, str):
        raise TypeError(f"a unit prefix must be a string such as 'k' or 'm', not {type(to).__name__}")
    to = PREFIX_ALIASES.get(to, to)
    if to not in PREFIXES:
        raise ValueError(f"unknown unit prefix {to!r}; use 'auto' or one of: "
                         + ", ".join(repr(p) for p in PREFIXES))
    return to


def prefix_scale(values, unit: str, to: str = "auto", warn: bool = True) -> Tuple[float, str]:
    """(factor, new unit) such that `values * factor`, shown in `new unit`, reads naturally.

    to="auto": pick a prefix in steps of 1000 from the largest absolute finite value, for the
    units in AUTO_UNITS; other units are returned unchanged (with a UnitWarning if `warn`).
    to="k", "m", "c", ... : use that prefix, for any unit. to="": keep the unit as it is.
    """
    if not isinstance(unit, str):
        raise TypeError(f"unit must be a string, not {type(unit).__name__}")
    arr = np.asarray(values)
    if arr.dtype.kind not in "biufc":
        raise TypeError(f"values must be numeric, got dtype {arr.dtype}")
    if to != "auto":
        to = normalize_prefix(to)
        if to == "":
            return 1.0, unit
        if not unit:
            raise ValueError(f"can't put the prefix {to!r} on an empty unit")
        return 10.0 ** -PREFIXES[to], to + unit
    if unit not in AUTO_UNITS:
        if warn and unit:
            warnings.warn(
                f"no automatic prefix for the unit {unit!r} (only {', '.join(sorted(AUTO_UNITS))}); "
                f"the values are unchanged. Pass to='k', 'm', ... to choose a prefix, or to='' to "
                "keep the unit without this warning", UnitWarning, stacklevel=3)
        return 1.0, unit
    if arr.size == 0:
        return 1.0, unit
    mag = np.abs(arr) if arr.dtype.kind == "c" else np.abs(arr.astype(float, copy=False))
    finite = mag[np.isfinite(mag)]
    if finite.size == 0 or float(finite.max()) == 0.0:
        return 1.0, unit
    exp = int(math.floor(math.log10(float(finite.max())) / 3) * 3)
    exp = min(max(exp, min(_AUTO_EXPONENTS)), max(_AUTO_EXPONENTS))
    if exp == 0:
        return 1.0, unit
    return 10.0 ** -exp, _AUTO_EXPONENTS[exp] + unit


def mathsafe(s: str) -> str:
    """Escape unescaped '$' when there is an odd number of them (matplotlib's mathtext would fail)."""
    if not isinstance(s, str):
        raise TypeError(f"expected text, not {type(s).__name__}")
    unescaped = s.replace(r"\$", "")
    if unescaped.count("$") % 2 == 0:
        return s
    out, i = [], 0
    while i < len(s):
        if s.startswith(r"\$", i):
            out.append(r"\$")
            i += 2
        elif s[i] == "$":
            out.append(r"\$")
            i += 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def axis_label(label: str, unit: str = "", fmt: str = "paren") -> str:
    """'Frequency (GHz)', 'Frequency [GHz]' or 'Frequency / GHz'."""
    if fmt not in UNIT_FORMATS:
        raise ValueError(f"unit format must be one of {UNIT_FORMATS}, not {fmt!r}")
    if not isinstance(label, str):
        raise TypeError(f"label must be a string, not {type(label).__name__}")
    if not isinstance(unit, str):
        raise TypeError(f"unit must be a string, not {type(unit).__name__}")
    label, unit = mathsafe(label), mathsafe(unit)
    if not unit:
        return label
    return {"paren": f"{label} ({unit})", "bracket": f"{label} [{unit}]", "slash": f"{label} / {unit}"}[fmt]
