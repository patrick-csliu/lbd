"""Matrix: cells with their numbers, for density and assignment matrices, covariance.

`read_grid` gives the numbers of a value on two axes, which may be the two dimensions inside a data
point; 3D bars show the same data. The other axes are fixed at `spec["index"]`, as on a map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from . import render as r
from .style import Style
from .units import mathsafe

KIND = None


@dataclass
class GridBlock:
    """One picture of the cells: the whole value, or its real or imaginary part."""

    title: str                  # "", "Re" or "Im"
    z: np.ndarray               # (rows, columns), plot units
    raw: np.ndarray             # the same, stored units (for numbers, row sums, tables)


@dataclass
class Grid:
    """The cells of a value, with what is needed to name them."""

    value: str
    row_axis: str
    col_axis: str
    row_labels: List[str]
    col_labels: List[str]
    blocks: List[GridBlock]     # one, or two for re_im (same shape, same factor)
    label: str
    unit: str                   # with the prefix, e.g. "S", "mV"
    zf: float                   # plot units per stored unit, shared by the blocks


def fits(d, name: str) -> "str | None":
    """None if `name` can be drawn as cells, otherwise why not. `d`: the flat view (`render.flat`)."""
    v = d.values[name]
    swept = r._swept(v)
    needs = "this needs two axes, or a matrix in each point"
    if sum(r._is_point(d, a) for a in v.axes) == 1:
        return f"'{name}' is a vector in each point; {needs}"
    if len(swept) < 2:
        return f"'{name}' has {'one axis' if swept else 'no axis'} with more than one point; {needs}"
    return None


def position_labels(axis) -> List[str]:
    """The axis's `elements`, otherwise its numbers as short text."""
    elements = getattr(axis, "elements", None)
    if elements is not None:
        return [mathsafe(e) for e in elements]
    return [f"{v:.4g}".replace("-", "−") for v in np.asarray(axis.data, dtype=float)]


def read_grid(d, spec, style: Style) -> Grid:
    """The cells of `spec["values"][0]`: rows on `spec["y"]`, columns on `spec["x"]`."""
    d = r.flat(d)
    name = spec["values"][0]
    v = d.values[name]
    why = fits(d, name)
    if why:
        raise r.RenderError(why)
    z = r._take(v, [spec["y"], spec["x"]], spec["index"])
    mode = spec["complex"]
    if mode == "re_im" and np.iscomplexobj(z):
        raws = [("Re", z.real), ("Im", z.imag)]
        label, unit = v.label, v.unit
    else:
        shown, label, unit = r.apply_complex(z, v.label, v.unit, "abs" if mode == "re_im" else mode, axis=1)
        raws = [("", shown)]
    q = r.find_quantity(style, name, v.label, mode if np.iscomplexobj(z) else None)
    auto = style.axis_style("y").label.auto_prefix and q.vmin is None and q.vmax is None
    zf, shown_unit = r._unit_scale(np.concatenate([np.ravel(a) for _, a in raws]), unit, q, auto)
    return Grid(value=name, row_axis=spec["y"], col_axis=spec["x"],
                row_labels=position_labels(d.axes[spec["y"]]), col_labels=position_labels(d.axes[spec["x"]]),
                blocks=[GridBlock(title, a * zf, a) for title, a in raws], label=label, unit=shown_unit, zf=zf)
