"""Maps of variable sweeps in Explore: pictures, cursors on the stored points, cuts on rows."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values
from lbd.plot import groupmap
from lbd_viewer import reading
from lbd_viewer.explore import ExploreError, ExploreSession


def session(tmp_path, maker, spec=None, small=False):
    d = maker(small)
    p = tmp_path / "x.lbd"
    d.save(p)
    first = next(n for n, v in d.values.items() if len(v.dims) and len(v.dims[0]) >= 2)
    return ExploreSession(p, "v", {"kind": "heatmap", "values": [first], **(spec or {})}, lp.load_style(), 700, 500, 1.0)


def read(s, cursors, kind="cross", cuts=True, together=False):
    (x0, x1), (y0, y1) = s.full
    return reading.cursors(s, cursors, kind, {"xlim": [x0, x1], "ylim": [y0, y1]}, (500, 300), cuts, together=together)


@pytest.mark.parametrize("maker,cells", [(mock_values.variable_sweep, "rows"), (mock_values.triangle, "rows"),
                                         (mock_values.adaptive_map, "nearest"), (mock_values.curved_grid, "rows")])
def test_each_group_file_opens_as_a_map(tmp_path, maker, cells):
    s = session(tmp_path, maker)
    assert s.kind == "heatmap" and s.model.cells == cells and s.view.name == "groupmap"
    body, meta = s.render(None, None)
    assert meta["strips"] == ("cuts" if cells == "rows" else None) and len(body) > 1000


def test_zoom_is_sharp(tmp_path):
    s = session(tmp_path, mock_values.adaptive_map)
    (x0, x1), (y0, y1) = s.full
    s.render((x0, x0 + (x1 - x0) / 20), (y0, y0 + (y1 - y0) / 20))
    image = np.asarray(s.image.get_array())
    assert image.shape[0] > 100 and image.shape[1] > 100


def test_a_draft_picture(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    meta = s.render(None, None, draft=True)[1]
    assert meta["draft"] and s.image.get_array().shape[0] < s._plot_area()[3]


def test_colour_limits_and_log(tmp_path):
    s = session(tmp_path, mock_values.curved_grid)
    s.apply({"clim": [0.1, 0.5]})
    assert s.image.norm.vmin == 0.1 and s.image.norm.vmax == 0.5
    s.apply({"cscale": "log"})
    assert s.image.norm.__class__.__name__ == "LogNorm"


def test_operations_say_why(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    s.apply({"ops": [{"op": "normalize", "on": True}]})                # offered none (16.50): left out
    assert s.ops_info()["notes"] == ["left out: Normalize (not offered on a variable sweep's map)"]


def test_a_cursor_reads_the_stored_point(tmp_path):
    d = mock_values.variable_sweep(False)
    s = session(tmp_path, mock_values.variable_sweep)
    c = read(s, [{"x": s.model.x[100], "y": s.model.y[100]}])["cursors"][0]
    coords = lbd.load(tmp_path / "x.lbd").coords("S21")
    point = c["index"]["freq"]
    assert c["items"][0]["value"] == pytest.approx(coords["freq"][point])
    assert c["items"][1]["value"] == pytest.approx(coords["power"][point])
    assert "cell" in c


def test_a_cursor_in_pixels_on_uneven_axes(tmp_path):
    s = session(tmp_path, mock_values.adaptive_map)
    m = s.model
    c = read(s, [{"x": float(m.x[7]), "y": float(m.y[7])}])["cursors"][0]
    assert c["x"] == m.x[7] and c["y"] == m.y[7] and "cell" not in c


def test_the_row_cut_is_the_rows_own_points(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    m = s.model
    i = int(np.flatnonzero(m.row == 20)[3])
    a = read(s, [{"x": float(m.x[i]), "y": float(m.y[i])}])
    assert len(a["cuts"]["row"]["pos"]) == int((m.row == 20).sum())


def test_the_column_cut_says_each_x(tmp_path):
    s = session(tmp_path, mock_values.variable_sweep, small=True)
    m = s.model
    a = read(s, [{"x": float(m.x[3]), "y": float(m.y[3])}])
    assert len(a["cuts"]["column"]["at"]) == len(a["cuts"]["column"]["pos"]) == m.row_at.size


def test_two_cursors_two_cuts(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    m = s.model
    a = read(s, [{"x": float(m.x[5]), "y": float(m.y[5])}, {"x": float(m.x[300]), "y": float(m.y[300])}])
    assert a["cuts2"]["row"]["z"] != a["cuts"]["row"]["z"]


def test_no_cuts_on_a_scattered_map(tmp_path):
    s = session(tmp_path, mock_values.adaptive_map)
    assert "cuts" not in read(s, [{"x": float(s.model.x[3]), "y": float(s.model.y[3])}])


def test_max_min_peak(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    (x0, x1), (y0, y1) = s.full
    p = reading.find(s, "max", [x0, x1], [y0, y1])
    i = int(np.nanargmax(s.model.z))
    assert (p["x"], p["y"]) == (s.model.x[i], s.model.y[i])


def test_keys_step_along_a_row(tmp_path):
    s = session(tmp_path, mock_values.triangle)
    m = s.model
    i = int(np.flatnonzero(m.row == 20)[3])
    c = read(s, [{"x": float(m.x[i]), "y": float(m.y[i]), "step": [1, 0]}], cuts=False)["cursors"][0]
    assert c["x"] == m.x[i + 1] and c["y"] == m.y[i]
    up = read(s, [{"x": float(m.x[i]), "y": float(m.y[i]), "step": [0, 1]}], cuts=False)["cursors"][0]
    assert up["y"] > m.y[i]


def test_steps_together_stop_at_the_edge(tmp_path):
    s = session(tmp_path, mock_values.curved_grid)
    m = s.model
    line = np.flatnonzero(m.row == 3)
    at = [{"x": float(m.x[i]), "y": float(m.y[i]), "step": [1, 0]} for i in (line[-2], line[-1])]
    c = read(s, at, cuts=False, together=True)["cursors"]
    assert [p["x"] for p in c] == [m.x[line[-2]], m.x[line[-1]]]


def test_a_preview_is_drawn(tmp_path):
    d = mock_values.adaptive_map(True)
    d.save(tmp_path / "x.lbd")
    s = ExploreSession(tmp_path / "x.lbd", "v", {}, lp.load_style(), 320, 240, 1.0, saved_view=False, summarise=False, bare=True)
    assert len(s.render(None, None)[0]) > 1000


def test_save_as_csv_has_every_point(tmp_path):
    from lbd_viewer import export

    s = session(tmp_path, mock_values.triangle)
    t = export.session_table(s)
    assert [c.name for c in t.columns()] == ["B", "A", "S"]
    assert len(t.x) == s.model.z.size
    (x0, x1), (y0, y1) = s.full
    t = export.session_table(s, view={"xlim": [x0, (x0 + x1) / 2], "ylim": [y0, y1]})
    assert len(t.x) < s.model.z.size


def test_cells_can_be_chosen(tmp_path):
    s = session(tmp_path, mock_values.triangle, {"options": {"cells": "nearest"}})
    assert s.model.cells == "nearest"
