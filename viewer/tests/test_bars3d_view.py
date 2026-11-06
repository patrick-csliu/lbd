"""3D bars in an Explore session: the angle, a click reading a bar, Save as CSV."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values as mock
from lbd.plot import render as rnd
from lbd_viewer import export
from lbd_viewer.explore import ExploreError, ExploreSession
from mpl_toolkits.mplot3d import proj3d


def session(tmp_path, make, spec, **more):
    make(False).save(tmp_path / "x.lbd")
    s = ExploreSession(tmp_path / "x.lbd", "v", {"kind": "bars3d", **spec}, lp.load_style(), 800, 600, 1.0, **more)
    s.apply({})
    s.render(None, None)
    return s


def top_of(s, panel, row, column):
    """Where a bar's top is in the picture."""
    m = s.model
    ax = m.axes[panel]
    x, y, _ = proj3d.proj_transform(m.x[column], m.y[row], m.panels[panel].height[row, column], ax.get_proj())
    px, py = ax.transData.transform((x, y))
    return float(px), float(s.fig.bbox.height - py)


def test_a_session_opens_on_a_3d_axes_and_draws(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    assert s.kind == "bars3d" and hasattr(s.ax, "get_proj")
    body, meta = s.render(None, None)
    assert len(body) == meta["width"] * meta["height"] * 4
    assert meta["sync"] == {} and meta["strips"] is None and meta["note"] == "3 × 3 bars"
    assert meta["angle"] == {"elev": 35.0, "azim": -50.0, "zoom": 1.0}


def test_the_angle_is_drawn_and_reported(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    before, _ = s.render(None, None)
    s.view.turn({"elev": 10, "azim": 200})
    after, meta = s.render(None, None)
    assert meta["angle"] == {"elev": 10.0, "azim": -160.0, "zoom": 1.0}
    assert s.ax.elev == 10 and s.ax.azim == -160
    assert before != after


def test_a_bad_angle_says_what_is_wrong(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    with pytest.raises(ExploreError, match="elev must be from -90 to 90, not 120"):
        s.view.turn({"elev": 120})
    with pytest.raises(ExploreError, match="zoom must be from 0.5 to 3"):
        s.view.turn({"zoom": 9})
    with pytest.raises(ExploreError, match="azim must be a number"):
        s.view.turn({"azim": "left"})


def test_a_click_on_a_bar_top_reads_it(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    p = s.pick(*top_of(s, 0, 2, 1))
    assert p["row"] == "second" and p["column"] == "excited" and p["value"] == 0.09
    assert p["index"] == {"prepared": 2, "measured": 1} and p["label"] == "Probability"


def test_the_nearest_to_the_viewer_wins_where_tops_overlap(tmp_path):
    def flat(small):
        d = lbd.Dataset(title="t")
        d.add_axis("a", [0.0, 1.0])
        d.add_axis("b", [0.0, 1.0])
        d.add_value("v", [[1.0, 2.0], [3.0, 4.0]], axes=["a", "b"])
        return d

    s = session(tmp_path, flat, {})
    s.view.turn({"elev": 0, "azim": -90})                   # from the front: rows hide each other
    s.render(None, None)
    near, far = top_of(s, 0, 1, 0), top_of(s, 0, 0, 0)
    assert s.pick((near[0] + far[0]) / 2, near[1])["row"] == "1"        # row 1 is in front


def test_a_click_beside_the_bars_reads_nothing(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    assert s.pick(3.0, 3.0) is None


def test_the_two_panels_pick_their_own_numbers(tmp_path):
    s = session(tmp_path, mock.density_matrix, {"index": {"amp": 5}})
    rho = lbd.load(tmp_path / "x.lbd").values["rho"].data[5]
    re, im = s.pick(*top_of(s, 0, 0, 3)), s.pick(*top_of(s, 1, 0, 3))
    assert re["panel"] == "Re" and re["value"] == pytest.approx(rho[0, 3].real)
    assert im["panel"] == "Im" and im["value"] == pytest.approx(rho[0, 3].imag)


def test_a_slider_changes_the_bars(tmp_path):
    s = session(tmp_path, mock.tomography, {"values": ["cov"]})
    cov = lbd.load(tmp_path / "x.lbd").values["cov"].data
    s.set_spec({"kind": "bars3d", "values": ["cov"], "index": {"amp": 3}})
    s.apply({})
    s.render(None, None)
    assert s.model.panels[0].raw == pytest.approx(cov[3])


def test_more_than_64_is_refused(tmp_path):
    def big(small):
        d = lbd.Dataset(title="t")
        d.add_axis("a", np.arange(70.0))
        d.add_axis("b", np.arange(3.0))
        d.add_value("v", np.ones((70, 3)), axes=["a", "b"])
        return d

    with pytest.raises(rnd.RenderError, match="at most 64 × 64"):
        session(tmp_path, big, {})


def test_the_table_is_the_grid(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    t = export.session_table(s, view={"xlim": [0, 1], "ylim": [0, 1]})
    t.to_csv(tmp_path / "t.csv", layout="matrix")
    grid = np.loadtxt(tmp_path / "t.csv", delimiter=",")
    assert grid[1:, 1:] == pytest.approx(lbd.load(tmp_path / "x.lbd").values["probability"].data)


def test_operations_keep_the_shape(tmp_path):
    s = session(tmp_path, mock.assignment_matrix, {})
    s.apply({"ops": [{"op": "subtract_mean", "along": "x"}]})
    s.render(None, None)
    assert s.kind == "bars3d" and s.model.z.shape == (3, 3)
    assert np.nansum(s.model.panels[0].raw, axis=1) == pytest.approx(0)


def test_a_preview_of_a_3d_view_is_drawn(tmp_path):
    s = session(tmp_path, mock.density_matrix, {}, bare=True)
    body, meta = s.render(None, None)
    assert len(s.fig.axes) == 2 and not s.fig.axes[0].axison
    assert meta["width"] == 800
