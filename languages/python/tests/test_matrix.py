"""Matrix (lbd.plot.matrix): a value's cells, drawn with their numbers."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import matrix, render


def two_axes(values=None):
    d = lbd.Dataset(title="t")
    d.add_axis("prepared", [0.0, 1.0, 2.0], elements=["g", "e", "f"])
    d.add_axis("measured", [0.0, 1.0], label="Measured")
    d.add_value("p", np.arange(6.0).reshape(3, 2) if values is None else values, axes=["prepared", "measured"])
    return d


def in_each_point():
    d = lbd.Dataset(title="t")
    d.add_axis("amp", np.arange(5.0), unit="V")
    cov = np.arange(20.0).reshape(5, 2, 2)
    d.add_value("cov", cov, axes="amp", shape=(2, 2), elements=[["I", "Q"], ["I", "Q"]], unit="V^2")
    d.add_value("bloch", np.arange(15.0).reshape(5, 3), axes="amp", shape=(3,), elements=["x", "y", "z"])
    return d, cov


def complex_matrix():
    d = lbd.Dataset(title="t")
    d.add_axis("row", [0.0, 1.0])
    d.add_axis("col", [0.0, 1.0])
    d.add_value("rho", np.array([[1 + 2j, 3j], [-3j, 4 - 2000j]]) * 1e-3, axes=["row", "col"], unit="V", label="ρ")
    return d


def grid_of(d, name, x, y, index=None, mode="abs"):
    spec = {"values": [name], "x": x, "y": y, "index": index or {}, "complex": mode}
    return matrix.read_grid(d, spec, lp.load_style())


def test_two_short_axes():
    g = grid_of(two_axes(), "p", "measured", "prepared")
    assert g.blocks[0].raw.shape == (3, 2)                  # rows = y
    assert g.blocks[0].raw[2, 1] == 5.0
    assert g.row_labels == ["g", "e", "f"] and g.col_labels == ["0", "1"]
    assert g.row_axis == "prepared" and g.col_axis == "measured"


def test_a_matrix_in_each_point():
    d, cov = in_each_point()
    g = grid_of(d, "cov", "cov_dim2", "cov_dim1", {"amp": 3})
    assert np.array_equal(g.blocks[0].raw, cov[3])
    assert g.row_labels == ["I", "Q"] and g.col_labels == ["I", "Q"]


def test_complex_re_and_im():
    g = grid_of(complex_matrix(), "rho", "col", "row", mode="re_im")
    assert [b.title for b in g.blocks] == ["Re", "Im"]
    assert g.blocks[0].raw[1, 1] == pytest.approx(4e-3) and g.blocks[1].raw[1, 1] == pytest.approx(-2.0)
    assert g.unit == "V" and g.zf == 1.0                    # one prefix: for the largest of both blocks
    assert g.blocks[1].z[0, 0] == pytest.approx(g.blocks[1].raw[0, 0] * g.zf)


def test_one_complex_mode():
    g = grid_of(complex_matrix(), "rho", "col", "row", mode="imag")
    assert len(g.blocks) == 1 and g.blocks[0].title == ""
    assert g.blocks[0].raw[0, 1] == pytest.approx(3e-3)
    assert g.label == "Im ρ"


def test_a_vector_is_refused_with_the_reason():
    d, _ = in_each_point()
    with pytest.raises(render.RenderError, match="'bloch' is a vector in each point.*two axes, or a matrix"):
        grid_of(d, "bloch", "bloch_dim1", "amp")
    line = lbd.Dataset(title="t")
    line.add_axis("a", [1.0, 2.0])
    line.add_value("v", [1.0, 2.0], axes="a")
    assert matrix.fits(render.flat(line), "v") == ("'v' has one axis with more than one point; "
                                                   "this needs two axes, or a matrix in each point")
