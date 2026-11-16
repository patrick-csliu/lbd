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


def test_an_operation_not_offered_is_left_out_with_a_note(tmp_path):
    """16.50: Matrix offers Subtract the mean and Normalize; FFT (from a view made on another plot
    type) is left out, saying so, and the others run."""
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix"})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}, {"op": "fft", "along": "x"}, {"op": "normalize", "along": "x"}]})
    s.render(None, None)
    info = s.ops_info()
    assert info["notes"] == [None, "left out: FFT (not offered on Matrix)", None]
    assert info["offered"] == ["subtract_mean", "normalize"] and s.model.z.shape == (3, 3)


def test_a_saved_bars_view_with_smooth_says_it_is_left_out(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars"})
    s.apply({"ops": [{"op": "smooth", "along": "x", "n": 3}]})
    s.render(None, None)
    assert s.ops_info()["notes"] == ["left out: Smooth (not offered on Bars)"]


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


def test_the_table_has_the_row_sums(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "matrix", "options": {"row_sums": True}})
    t = export.session_table(s)
    t.to_csv(tmp_path / "t.csv", layout="matrix")
    grid = np.loadtxt(tmp_path / "t.csv", delimiter=",")
    assert np.isnan(grid[0, -1]) and grid[1:, -1] == pytest.approx(1.0)
    assert "each row's sum" in (tmp_path / "t.csv").read_text(encoding="utf-8")


def test_a_preview_has_only_the_cells(tmp_path):
    mock.assignment_matrix(False).save(tmp_path / "x.lbd")
    s = ExploreSession(tmp_path / "x.lbd", "v", {"kind": "matrix"}, lp.load_style(), 120, 90, 1.0, bare=True)
    s.apply({})
    body, meta = s.render(None, None)
    assert meta["plot"] == [0, 0, 120, 90]


def test_a_click_reads_the_bar(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population"]})
    assert s.kind == "bars" and s.spec["x"] == "state"
    c = read(s, 1.1, 0.05)
    got = items(c)
    assert got["x"]["text"] == "excited" and got["z"]["value"] == 0.24 and got["z"]["label"] == "Population"
    assert c["index"] == {"state": 1}
    assert c["cell"][1] == 0 and c["cell"][3] == pytest.approx(0.24)
    assert read(s, c["x"], c["y"])["at"] == c["at"]         # asked again at its own place: the same bar


def test_a_grouped_bar(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population", "error"]})
    m = s.model
    second = m.left[1, 2] + m.width / 2                     # 'error' in the third group
    c = read(s, second, 0.0)
    got = items(c)
    assert got["series"]["text"] == "Error" and got["z"]["value"] == 0.01 and got["x"]["text"] == "second"
    assert read(s, c["x"], c["y"], step=[-1, 0])["items"][-1]["value"] == 0.05      # the bar before it


def test_a_stacked_bar(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {"kind": "bars", "x": "prepared", "series": "measured",
                                                   "options": {"layout": "stacked"}})
    c = read(s, 0, 0.98)                                    # 'ground' row: 0.97, then 0.025, then 0.005
    assert items(c)["z"]["value"] == 0.025 and c["index"] == {"prepared": 0, "measured": 1}


def test_a_negative_bar(tmp_path):
    def down(small):
        d = lbd.Dataset(title="t")
        d.add_axis("a", [0.0, 1.0])
        d.add_value("v", [2.0, -3.0], axes="a")
        return d

    s = session(tmp_path, down, {"kind": "bars"})
    c = read(s, 1, -1)
    assert items(c)["z"]["value"] == -3.0 and c["cell"][1] == -3.0 and c["cell"][3] == 0.0


def test_a_horizontal_level(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population", "lifetime"]})
    c = read(s, 0.4, 0.355, "horizontal")
    assert c["y"] == 0.355 and c["items"][0]["value"] == 0.355
    assert c["items"][1]["unit"] == "s" and c["items"][1]["value"] == pytest.approx(20e-6)     # half the tallest


def test_the_bars_table(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population", "error"]})
    t = export.session_table(s)
    t.to_csv(tmp_path / "t.csv")
    rows = np.loadtxt(tmp_path / "t.csv", delimiter=",")
    assert rows.tolist() == [[0, 0.71, 0.02], [1, 0.24, 0.03], [2, 0.05, 0.01]]
    text = (tmp_path / "t.csv").read_text(encoding="utf-8")
    assert text.startswith("# state,population,error") and "State: 0 = ground, 1 = excited, 2 = second" in text


def test_single_numbers_table(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["fidelity", "visibility"]})
    assert s.spec["values"] == ["fidelity", "visibility"]
    t = export.session_table(s)
    t.to_csv(tmp_path / "t.csv")
    assert np.loadtxt(tmp_path / "t.csv", delimiter=",").tolist() == [0, 0.982, 0.91]
    assert (tmp_path / "t.csv").read_text(encoding="utf-8").startswith("# row,fidelity,visibility")


def test_a_click_on_a_single_number(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["fidelity", "visibility"]})
    got = items(read(s, 1, 0.5))
    assert got["x"]["text"] == "Visibility" and got["z"]["value"] == 0.91


def test_operations_on_bars(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population"]})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}]})
    s.render(None, None)
    assert s.view.kind == "bars" and np.nansum(s.model.bars.raw) == pytest.approx(0)
    assert read(s, 0, 0)["stored"]["value"] == 0.71


def test_operations_need_one_unit(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population", "lifetime"]})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}]})
    assert "one unit" in s.ops_info()["notes"][0]


def test_a_log_vertical_scale(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population"]})
    s.apply({"yscale": "log"})
    _, meta = s.render(None, None)
    assert meta["yscale"] == "log" and meta["ylim"][0] > 0


def test_bars_have_no_cuts_or_sync(tmp_path):
    s = session(tmp_path, mock.bars, {"kind": "bars", "values": ["population"]})
    _, meta = s.render(None, None)
    assert meta["strips"] is None and meta["sync"] == {}


def power_sweep(small):
    d = lbd.Dataset(title="t")
    d.add_axis("power", [-30.0, -20.0], label="Power", unit="dBm")
    d.add_axis("frequency", [4e9, 5e9, 6e9], label="Frequency", unit="Hz")
    d.add_value("v", [[1.0, 2.0, 6.0], [4.0, np.nan, 8.0]], axes=["power", "frequency"], label="Level", unit="V")
    return d


def test_all_of_an_axis_on_bars(tmp_path):
    s = session(tmp_path, power_sweep, {"kind": "bars", "x": "power", "series": "none", "all": ["frequency"],
                                        "options": {"stat": "mean", "errors": True}})
    assert s.spec["all"] == ["frequency"] and s.spec["slices"] == []
    got = items(read(s, 1, 1))
    assert got["z"]["value"] == 6.0 and got["z"]["label"] == "Mean of Level"      # 4 and 8: the empty point left out
    assert s.model.errors is not None and "errors" in s.model.artists
    t = export.session_table(s)
    t.to_csv(tmp_path / "t.csv")
    assert np.loadtxt(tmp_path / "t.csv", delimiter=",").tolist() == [[-30, 3.0], [-20, 6.0]]
    assert "Each bar: the mean of all Frequency (empty points left out)" in (tmp_path / "t.csv").read_text(encoding="utf-8")


def test_a_preview_of_bars(tmp_path):
    mock.bars(False).save(tmp_path / "x.lbd")
    s = ExploreSession(tmp_path / "x.lbd", "v", {"kind": "bars", "values": ["population", "error", "lifetime"]},
                       lp.load_style(), 120, 90, 1.0, bare=True)
    s.apply({})
    assert s.render(None, None)[1]["plot"] == [0, 0, 120, 90]
