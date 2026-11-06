"""Matrix and Bars in an Explore session: reading a cell or bar, Save as CSV, operations."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values as mock
from lbd_viewer import export, reading
from lbd_viewer.explore import ExploreError, ExploreSession


def session(tmp_path, make, spec, name="x.lbd"):
    make(False).save(tmp_path / name)
    s = ExploreSession(tmp_path / name, "v", spec, lp.load_style(), 700, 500, 1.0)
    s.apply({})
    s.render(None, None)
    return s


def read(s, x, y, kind="cross", **more):
    size = s._plot_area()[2:]
    return reading.cursors(s, [{"x": x, "y": y, **more}], kind, {}, size)["cursors"][0]


def items(c):
    return {i["role"]: i for i in c["items"]}


def test_a_click_reads_the_cell(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    assert s.kind == "matrix" and s.spec["y"] == "prepared" and s.spec["x"] == "measured"
    c = read(s, 1.2, 1.9)                                   # row 0 is at the top: y = 2
    got = items(c)
    assert got["y"]["text"] == "ground" and got["x"]["text"] == "excited"
    assert got["z"]["value"] == 0.025 and got["z"]["label"] == "Probability"
    assert c["index"] == {"prepared": 0, "measured": 1}
    assert c["cell"] == [0.5, 1.5, 1.5, 2.5]


def test_a_pixel_picks_the_cell(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    px, py = s._to_px(np.array([2.0]), np.array([0.0]))
    p = s.pick(float(px[0]), float(py[0]))
    assert p["index"] == {"prepared": 2, "measured": 2} and p["kind"] == "cell"
    assert s.pick(1.0, 1.0) is None                         # beside the cells
    left, top, w, h = s._plot_area()
    assert left <= p["rect"][0] <= left + w and top <= p["rect"][1] <= top + h


def test_keys_step_through_the_cells(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    assert read(s, 0, 2, step=[1, 0])["index"] == {"prepared": 0, "measured": 1}
    assert read(s, 0, 2, step=[0, -1])["index"] == {"prepared": 1, "measured": 0}        # down
    assert read(s, 0, 2, step=[0, 1])["index"] == {"prepared": 0, "measured": 0}         # stops at the edge


def test_the_im_block_reads_im(tmp_path):
    s = session(tmp_path, mock.density_matrix, {"kind": "matrix", "index": {"amp": 5}})
    assert s.spec["complex"] == "re_im"
    rho = lbd.load(tmp_path / "x.lbd").values["rho"].data[5]
    re, im = read(s, 3, 3), read(s, 8, 3)                   # Re ends at column 3; the gap is 4; Im starts at 5
    assert re["block"] == "Re" and items(re)["z"]["value"] == pytest.approx(rho[0, 3].real)
    assert im["block"] == "Im" and items(im)["z"]["value"] == pytest.approx(rho[0, 3].imag)
    assert items(im)["z"]["label"] == "Im ρ" and im["index"] == {"row": 0, "col": 3}
    gap = read(s, 4.2, 3)                                   # the gap: the nearest cell
    assert gap["block"] == "Im" and gap["index"]["col"] == 0


def test_a_slider_changes_the_matrix(tmp_path):
    s = session(tmp_path, mock.tomography, {"kind": "matrix", "values": ["cov"]})
    cov = lbd.load(tmp_path / "x.lbd").values["cov"].data
    assert items(read(s, 1, 1))["z"]["value"] == pytest.approx(cov[0, 0, 1])
    s.set_spec({"kind": "matrix", "values": ["cov"], "index": {"amp": 3}})
    s.apply({})
    s.render(None, None)
    c = items(read(s, 1, 1))
    assert c["z"]["value"] == pytest.approx(cov[3, 0, 1]) and c["y"]["text"] == "I" and c["x"]["text"] == "Q"


def test_the_table_is_the_grid(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    t = export.session_table(s)
    t.to_csv(tmp_path / "t.csv", layout="matrix")
    grid = np.loadtxt(tmp_path / "t.csv", delimiter=",")
    assert grid[1:, 1:] == pytest.approx(lbd.load(tmp_path / "x.lbd").values["probability"].data)
    text = (tmp_path / "t.csv").read_text(encoding="utf-8")
    assert "Prepared: 0 = ground, 1 = excited, 2 = second" in text
    assert t.estimate("rows")["rows"] == 9


def test_re_and_im_save_both_blocks(tmp_path):
    s = session(tmp_path, mock.density_matrix, {"kind": "matrix"})
    t = export.session_table(s)
    assert [c.name for c, _ in t.values] == ["rho_re", "rho_im"]
    assert [c.label for c, _ in t.values] == ["Re ρ", "Im ρ"]
    with pytest.raises(ValueError, match="holds one value"):
        t.check_matrix()


def test_the_table_of_a_zoomed_view(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    t = export.session_table(s, view={"xlim": [0.5, 2.5], "ylim": [1.5, 2.5]})
    t.to_csv(tmp_path / "t.csv", layout="matrix")
    grid = np.loadtxt(tmp_path / "t.csv", delimiter=",")
    assert grid[1] == pytest.approx(np.array([0, 0.025, 0.005]))


def test_stored_numbers_of_a_complex_mode(tmp_path):
    s = session(tmp_path, mock.density_matrix, {"kind": "matrix", "complex": "abs"})
    t = export.session_table(s, "both")
    assert [c.name for c, _ in t.values] == ["rho", "rho_re", "rho_im"]


def test_an_operation_that_keeps_the_shape(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}]})
    s.render(None, None)
    assert s.view.kind == "matrix" and s.model.z.shape == (3, 3)
    assert np.nansum(s.model.grid.blocks[0].raw, axis=1) == pytest.approx(0)
    info = s.ops_info()
    assert info["notes"] == [None] and info["applied"] == 1
    c = read(s, 0, 2)
    assert c["stored"]["value"] == 0.97 and items(c)["z"]["value"] == pytest.approx(0.97 - 1 / 3)
    s.apply({})
    assert s.model is s.base_model


def test_an_operation_that_changes_the_shape_is_refused(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}, {"op": "fft", "along": "x"}, {"op": "normalize", "along": "x"}]})
    s.render(None, None)
    notes = s.ops_info()["notes"]
    assert notes[0] is None and "changes the shape" in notes[1] and "above" in notes[2]
    assert s.model.z.shape == (3, 3)


def test_operations_need_one_number_per_cell(tmp_path):
    s = session(tmp_path, mock.density_matrix, {"kind": "matrix"})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}]})
    assert "another complex mode" in s.render(None, None)[1]["ops"]["notes"][0]


def test_equations_are_refused(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    with pytest.raises(ExploreError, match="Equations aren't available"):
        s.apply({"equations": {"z": "z*2"}})


def test_a_large_matrix_says_why_there_are_no_numbers(tmp_path):
    def big(small):
        d = lbd.Dataset(title="t")
        d.add_axis("a", np.arange(40.0))
        d.add_axis("b", np.arange(40.0))
        d.add_value("v", np.ones((40, 40)), axes=["a", "b"])
        return d

    s = session(tmp_path, big, {"kind": "matrix"})
    assert s.take_notes() == ["Numbers are shown up to 32 × 32; this has 40 × 40 cells."]
    assert s.render(None, None)[1]["note"] == "every cell shown"


def test_a_matrix_has_no_cuts_or_sync(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    _, meta = s.render(None, None)
    assert meta["strips"] is None and meta["sync"] == {}
    assert "cuts" not in reading.cursors(s, [{"x": 0, "y": 0}], "cross", {}, (300, 300))


def test_a_preview_has_only_the_cells(tmp_path):
    mock.assignment_matrix(False).save(tmp_path / "x.lbd")
    s = ExploreSession(tmp_path / "x.lbd", "v", {"kind": "matrix"}, lp.load_style(), 120, 90, 1.0, bare=True)
    s.apply({})
    body, meta = s.render(None, None)
    assert meta["plot"] == [0, 0, 120, 90]
