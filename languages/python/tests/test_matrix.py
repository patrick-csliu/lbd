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


def drawn(d, **spec):
    fig = lp.plot(d, "matrix", **spec)
    fig.canvas.draw()
    ax = fig.axes[0]
    numbers = [a for a in ax.artists if isinstance(a, matrix.CellNumbers)]
    return fig, ax, numbers[0] if numbers else None


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


def test_numbers_in_the_cells():
    d = two_axes(np.array([[0.123456, 2.5], [3.0, -4.0], [1200.0, 0.0]]))
    _, _, numbers = drawn(d, values="p")
    assert [t.get_text() for t in numbers.texts] == ["0.123", "2.5", "3", "−4", "1.2e+03", "0"]
    _, _, numbers = drawn(d, values="p", options={"digits": 5})
    assert numbers.texts[0].get_text() == "0.12346"


def test_rounding_noise_reads_as_zero():
    assert matrix.number_text(1e-17, 3, 0.5) == "0"
    assert matrix.number_text(1e-5, 3, 0.5) == "1e−05"


def test_text_is_readable_on_dark_and_light_cells():
    d = two_axes(np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]))
    _, _, numbers = drawn(d, values="p")
    dark, light = numbers.texts[0], numbers.texts[1]        # viridis: dark at 0, yellow at 1
    assert dark.get_color() == "white" and light.get_color() == "black"


def test_the_range_starts_from_the_data():
    style = lp.load_style()

    def start(values, unit=""):
        d = lbd.Dataset(title="t")
        d.add_axis("a", [0.0, 1.0, 2.0])
        d.add_axis("b", [0.0, 1.0])
        d.add_value("p", np.array(values), axes=["a", "b"], unit=unit)
        spec = render.resolve_spec(d, {"kind": "matrix", "values": "p"})
        return matrix.prepare(d, spec, style)

    unit = start([[0, 1], [0.5, 0.5], [0.2, 0.8]])
    assert unit.range == "unit" and (unit.norm.vmin, unit.norm.vmax) == (0, 1)
    signed = start([[0, -1], [0.5, 0.5], [0.2, 0.8]])
    assert signed.range == "signed" and (signed.norm.vmin, signed.norm.vmax) == (-1, 1) and signed.cmap == "RdBu_r"
    assert signed.norm(0) == 0.5                            # white at zero
    assert start([[0, 3], [0.5, 0.5], [0.2, 0.8]]).range == "auto"
    assert start([[0, 1e-3], [0.5e-3, 0], [0, 0]], unit="V").range == "auto"       # 0 to 1 volt means nothing here


def test_a_fixed_range_is_kept():
    d = two_axes(np.array([[0, 3], [0.5, 0.5], [0.2, 0.8]]))
    spec = render.resolve_spec(d, {"kind": "matrix", "values": "p", "options": {"range": "signed"}})
    m = matrix.prepare(d, spec, lp.load_style())
    assert (m.norm.vmin, m.norm.vmax) == (-1, 1)
    with pytest.raises(render.RenderError, match="range must be one of"):
        render.resolve_spec(d, {"kind": "matrix", "values": "p", "options": {"range": "wide"}})
    style = lp.load_style({"quantities": {"p": {"vmin": -5, "vmax": 5}}})
    m = matrix.prepare(d, spec, style)                      # the style's own range wins, as on a map
    assert (m.norm.vmin, m.norm.vmax) == (-5, 5)


def square(n, m):
    d = lbd.Dataset(title="t")
    d.add_axis("a", np.arange(float(n)))
    d.add_axis("b", np.arange(float(m)))
    d.add_value("v", np.ones((n, m)), axes=["a", "b"])
    return d


def test_33_positions_have_no_numbers_and_a_note():
    with pytest.warns(render.RenderWarning, match="up to 32 × 32; this has 33 × 4 cells"):
        _, _, numbers = drawn(square(33, 4), values="v", y="a", x="b")
    assert numbers is None
    assert len(drawn(square(32, 32), values="v")[2].texts) == 32 * 32


def test_numbers_are_left_out_when_a_cell_is_too_small():
    d = square(30, 30)
    d.values["v"].data[0, 0] = 0.1234567
    _, _, numbers = drawn(d, values="v", options={"digits": 6})
    assert not numbers.fit()


def test_re_and_im_share_a_range():
    d = complex_matrix()
    assert render.resolve_spec(d, {"kind": "matrix", "values": "rho"})["complex"] == "re_im"
    fig, ax, numbers = drawn(d, values="rho")               # complex starts as Re and Im
    meshes = ax.collections
    assert len(meshes) == 2 and meshes[0].norm is meshes[1].norm
    assert [t.get_text() for t in ax.texts] == ["Re", "Im"]
    assert len(numbers.texts) == 8
    assert len(fig.axes) + len(ax.child_axes) == 2          # one colour bar


def test_re_and_im_is_only_for_types_that_show_both():
    with pytest.raises(render.RenderError, match="unknown complex mode 're_im'"):
        render.resolve_spec(complex_matrix(), {"kind": "curve", "complex": "re_im"})


def test_row_zero_is_at_the_top():
    _, ax, numbers = drawn(two_axes(), values="p", x="measured", y="prepared")
    first = next(t for t in numbers.texts if t.get_text() == "0")
    last = next(t for t in numbers.texts if t.get_text() == "5")
    assert first.get_position()[1] > last.get_position()[1]
    labels = dict(zip(ax.get_yticks(), (t.get_text() for t in ax.get_yticklabels())))
    assert labels[2.0] == "g" and labels[0.0] == "f"
    assert ax.get_ylim()[0] < ax.get_ylim()[1]


def test_the_starting_axes():
    d, _ = in_each_point()
    spec = render.resolve_spec(d, {"kind": "matrix", "values": "cov"})
    assert (spec["y"], spec["x"]) == ("cov_dim1", "cov_dim2") and spec["index"] == {"amp": 0}
    three = lbd.Dataset(title="t")
    three.add_axis("long", np.arange(9.0))
    three.add_axis("a", np.arange(3.0))
    three.add_axis("b", np.arange(2.0))
    three.add_value("v", np.ones((9, 3, 2)), axes=["long", "a", "b"])
    spec = render.resolve_spec(three, {"kind": "matrix", "values": "v"})
    assert (spec["y"], spec["x"]) == ("a", "b") and spec["index"] == {"long": 0}
    assert render.resolve_spec(three, {"kind": "matrix", "values": "v", "x": "a", "y": "b"})["y"] == "b"


def test_svg_and_png_export(tmp_path):
    two_axes().save(tmp_path / "m.lbd")
    style = lp.load_style()
    spec = {"kind": "matrix", "values": "p"}
    svg, _ = render.render_file(tmp_path / "m.lbd", spec, style, "svg")
    png, _ = render.render_file(tmp_path / "m.lbd", spec, style, "png")
    assert b"<svg" in svg[:400] and png[:4] == b"\x89PNG"


def test_a_saved_view_keeps_the_matrix(tmp_path):
    d = two_axes()
    d.plot = {"kind": "matrix", "values": ["p"], "x": "prepared", "y": "measured", "options": {"digits": 2, "range": "auto"}}
    d.save(tmp_path / "m.lbd")
    spec = render.resolve_spec(lbd.load(tmp_path / "m.lbd"), {})
    assert spec["kind"] == "matrix" and spec["options"] == {"digits": 2, "range": "auto"} and spec["x"] == "prepared"
