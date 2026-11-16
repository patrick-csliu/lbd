"""Maps of variable sweeps (lbd.plot.groupmap): every cell is a stored number, nothing is invented."""

import sys
from pathlib import Path

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import groupmap, render

sys.path.insert(0, str(Path(__file__).parents[3] / "viewer" / "tests"))
import mock_values  # noqa: E402


def model(d, **spec):
    resolved = render.resolve_spec(d, {"kind": "heatmap", **spec})
    return render.prepare_map(render.flat(d), resolved, lp.load_style())


def pixels(m, n=120):
    (x0, x1), (y0, y1) = groupmap.bounds(m)
    return groupmap.raster(m, np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1))


def group(points):
    d = lbd.Dataset()
    d.add_group("g")
    d.add_axis("a", group="g")
    d.add_axis("b", group="g")
    d.add_value("v", axes=["a", "b"])
    for a, bs in points.items():
        d.write(a=a, b=np.asarray(bs, dtype=float), v=a + np.asarray(bs, dtype=float))
    return d


def test_13_is_rows():
    assert model(mock_values.variable_sweep(False)).cells == "rows"


def test_14_is_rows():
    assert model(mock_values.triangle(False)).cells == "rows"


def test_15_is_nearest():
    assert model(mock_values.adaptive_map(False)).cells == "nearest"


def test_two_levels_open_as_a_map():
    assert render.resolve_spec(mock_values.triangle(True), None)["kind"] == "heatmap"


def test_a_cell_is_one_stored_number():
    for make, name in ((mock_values.triangle, "S"), (mock_values.adaptive_map, "z")):
        m = model(make(False))
        shown = pixels(m)
        assert set(np.round(shown[np.isfinite(shown)], 9)) <= set(np.round(m.z, 9))


def test_nothing_is_drawn_where_nothing_was_measured():
    m = model(group({1.0: [1.0], 2.0: [1.0, 2.0], 3.0: [1.0, 2.0, 3.0], 4.0: [1.0, 2.0, 3.0, 4.0]}))
    assert m.cells == "rows" or np.isfinite(pixels(m)).any()
    m = model(group({1.0: [1.0], 2.0: [1.0, 2.0], 3.0: [1.0, 2.0, 3.0], 4.0: [1.0, 2.0, 3.0, 4.0]}), options={"cells": "rows"})
    shown = pixels(m)
    assert np.isnan(shown[-1 if m.rows_on == "x" else 0, -1])          # a = 1 has no point at b = 4
    assert np.isfinite(shown[-1, -1]) or np.isfinite(shown[-1, 0])


def test_the_outline_stops_nearest():
    m = model(mock_values.adaptive_map(False), options={"cells": "nearest"})
    (x0, x1), (y0, y1) = groupmap.bounds(m)
    outside = groupmap.raster(m, np.array([x1 + 1, x1 + 2, x1 + 3]), np.array([y1 + 1, y1 + 2, y1 + 3]))
    assert np.isnan(outside).all()


def test_smooth_is_only_smooth_when_asked():
    d = mock_values.adaptive_map(False)
    assert model(d).cells == "nearest"
    m = model(d, options={"cells": "smooth"})
    shown = pixels(m)
    assert len(set(np.round(shown[np.isfinite(shown)], 9)) - set(np.round(m.z, 9))) > 0


def test_a_wrong_cells_says_why():
    with pytest.raises(render.RenderError, match="cells must be"):
        model(mock_values.triangle(True), options={"cells": "hexagons"})


def test_swap_makes_strips_upright():
    d = mock_values.triangle(True)
    m = model(d, x="A", y="B")
    assert m.rows_on == "x"
    (x0, x1), (y0, y1) = groupmap.bounds(m)
    assert np.isfinite(pixels(m)).any()


def test_a_third_level_is_a_slider():
    d = lbd.Dataset()
    d.add_group("g")
    for a in "abc":
        d.add_axis(a, group="g")
    d.add_value("v", axes=["a", "b", "c"])
    for a in (1.0, 2.0):
        for b in (10.0, 20.0, 30.0):
            d.write(a=a, b=b, c=np.array([1.0, 2.0, 3.0]) * a, v=np.full(3, a * b))
    r = render.resolve_spec(d, {"kind": "heatmap", "index": {"a": 1}})
    assert r["x"] == "c" and r["y"] == "b" and r["index"] == {"a": 1} and r["slices"][0]["value"] == 2.0
    m = render.prepare_map(render.flat(d), r, lp.load_style())
    assert m.z.size == 9 and set(m.z) == {20.0, 40.0, 60.0}


def test_a_fixed_axis_is_a_slider():
    d = lbd.Dataset()
    d.add_group("g")
    d.add_axis("a", group="g")
    d.add_axis("b", group="g")
    d.add_axis("t", [0.0, 1.0])
    d.add_value("v", axes=["a", "b", "t"])
    for a in (1.0, 2.0):
        for b in (1.0, 2.0, 3.0):
            d.write(a=a, b=b, v=np.array([a, 10 * a]))
    r = render.resolve_spec(d, {"kind": "heatmap", "index": {"t": 1}})
    assert r["index"] == {"t": 1}
    m = render.prepare_map(render.flat(d), r, lp.load_style())
    assert set(m.z) == {10.0, 20.0}


def test_points_on_a_line_fall_back():
    m = model(group({1.0: [1.0], 2.0: [2.0], 3.0: [3.0], 4.0: [4.0]}))
    assert m.cells == "rows" and np.isfinite(pixels(m)).any()


def test_log_axes():
    d = group({1.0: [1.0, 10.0, 100.0], 10.0: [1.0, 10.0, 100.0]})
    m = model(d, x_scale="log")
    (x0, x1), _ = groupmap.bounds(m)
    assert x0 > 0 and x1 > 100
    assert np.isfinite(pixels(m)).any()


def test_a_row_with_one_point_is_seen():
    m = model(group({1.0: [1.0, 2.0, 3.0], 2.0: [2.0], 3.0: [1.0, 2.0, 3.0]}), options={"cells": "rows"})
    shown = pixels(m)
    assert np.isfinite(shown[60]).any()


def test_equal_rows_use_one_mesh():
    d = mock_values.curved_grid(True)
    m = model(d)
    assert groupmap._equal_rows(groupmap.row_cells(m))
    fig = lp.plot(d, kind="heatmap")
    assert len(fig.axes[0].collections) == 1


def test_complex_modes():
    d = mock_values.variable_sweep(True)
    assert model(d, complex="db").z_label != model(d, complex="phase").z_label


def test_units_and_prefixes_as_a_map():
    m = model(mock_values.variable_sweep(False), values=["S21"])
    assert "GHz" in m.x_label and "dBm" in m.y_label and 6 < np.nanmin(m.x) < 8


@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
@pytest.mark.parametrize("cells", ["rows", "nearest", "smooth"])
def test_export(fmt, cells):
    data, _ = render.render_dataset(mock_values.adaptive_map(True) if cells != "rows" else mock_values.triangle(True),
                                    {"kind": "heatmap", "options": {"cells": cells}}, lp.load_style(), fmt=fmt)
    assert len(data) > 500


def test_no_scipy():
    assert "scipy" not in Path(groupmap.__file__).read_text(encoding="utf-8").replace("scipy isn't", "")
