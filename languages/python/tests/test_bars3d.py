"""3D bars (lbd.plot.bars3d): the data of Matrix, a bar per cell."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import bars3d, matrix, render
from matplotlib.backends.backend_agg import FigureCanvasAgg
from mpl_toolkits.mplot3d import proj3d


def grid(values, name="v", elements=None):
    values = np.asarray(values)
    d = lbd.Dataset(title="t")
    d.add_axis("a", np.arange(float(values.shape[0])), elements=elements)
    d.add_axis("b", np.arange(float(values.shape[1])), elements=elements)
    d.add_value(name, values, axes=["a", "b"])
    return d


def model_of(d, **spec):
    resolved = render.resolve_spec(d, {"kind": "bars3d", **spec})
    return bars3d.prepare(d, resolved, lp.load_style()), resolved


def drawn(d, **spec):
    fig = lp.plot(d, "bars3d", **spec)
    fig.canvas.draw()
    return fig, fig.axes[0]


def test_a_matrix_gives_one_bar_per_cell():
    d = grid(np.arange(6.0).reshape(2, 3))
    m, spec = model_of(d, x="b", y="a")
    assert np.array_equal(m.z, matrix.read_grid(d, spec, lp.load_style()).blocks[0].z)
    points = lbd.Dataset(title="t")
    points.add_axis("s", [0.0, 1.0])
    points.add_value("c", np.arange(8.0).reshape(2, 2, 2), axes="s", shape=(2, 2), elements=[["I", "Q"], ["I", "Q"]])
    m2, _ = model_of(points, values="c", index={"s": 1})
    assert m2.z.tolist() == [[4.0, 5.0], [6.0, 7.0]]
    fig = lp.plot(d, "bars3d", x="b", y="a")
    assert len(fig.axes[0].collections) >= 6


def test_labels_are_the_elements_at_the_bar_centres():
    _, ax = drawn(grid(np.ones((3, 3)), elements=["g", "e", "f"]), x="b", y="a")
    assert ax.get_xticks().tolist() == [0.0, 1.0, 2.0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["g", "e", "f"]
    labels = dict(zip(ax.get_yticks(), (t.get_text() for t in ax.get_yticklabels())))
    assert labels[2.0] == "g"                               # row 0 at the back: far along y


def test_negative_bars_go_down_and_zero_is_in_the_limits():
    m, _ = model_of(grid([[1.0, 2.0], [3.0, 4.0]]))
    assert m.zlim[0] == 0.0
    m, _ = model_of(grid([[-1.0, -2.0], [-3.0, -4.0]]))
    assert m.zlim == (-4.0, 0.0)
    _, ax = drawn(grid([[-1.0, 2.0], [3.0, 4.0]]))
    assert ax.get_zlim()[0] < 0 < ax.get_zlim()[1]


def test_empty_cells_have_no_bar():
    d = grid([[1.0, np.nan], [np.nan, np.nan]])
    with pytest.warns(render.RenderWarning, match="3 cells are empty"):
        fig = lp.plot(d, "bars3d")
    m, _ = model_of(d)
    assert m.note == "3 cells are empty"
    assert len(fig.axes[0].collections) == 1


def test_above_64_is_refused_with_the_reason():
    d = grid(np.ones((65, 2)))
    text = "3D bars show at most 64 × 64 cells; this has 65 × 2. Use Matrix."
    assert bars3d.fits(render.flat(d), "v") == text
    with pytest.raises(render.RenderError, match="at most 64 × 64"):
        render.resolve_spec(d, {"kind": "bars3d"})
    assert bars3d.fits(render.flat(grid(np.ones((64, 64)))), "v") is None


ANGLES = [(35, -50), (35, 130), (20, 40), (60, -140)]


def drawn_model(d, **spec):
    resolved = render.resolve_spec(d, {"kind": "bars3d", **spec})
    style = lp.load_style()
    m = bars3d.prepare(d, resolved, style)
    fig = render.new_figure(style)
    FigureCanvasAgg(fig)
    bars3d.draw(fig, bars3d.make_axes(fig, m), m, d, resolved, style)
    fig.canvas.draw()
    return fig, m


@pytest.mark.parametrize("elev,azim", ANGLES)
def test_bars_are_drawn_far_to_near(elev, azim):
    _, m = drawn_model(grid(np.arange(16.0).reshape(4, 4) + 1), options={"elev": elev, "azim": azim})
    a = m.axes[0]
    x, y = (v.ravel() for v in np.meshgrid(m.x, m.y))
    depth = proj3d.proj_transform(x, y, np.zeros(16), a.get_proj())[2]
    ranks = [bar.get_zorder() for bar in m.bars[0]]
    assert sorted(ranks) == list(range(1, 17))
    assert [depth[k] for k in np.argsort(ranks)] == sorted(depth, reverse=True)


def test_the_order_follows_a_new_angle():
    fig, m = drawn_model(grid(np.ones((3, 3))))
    before = [bar.get_zorder() for bar in m.bars[0]]
    bars3d.set_angle(fig, 35, 130, 1.0)
    fig.canvas.draw()
    assert [bar.get_zorder() for bar in m.bars[0]] != before


def test_a_near_tall_bar_hides_a_far_one():
    """Seen from the front, a tall bar near the viewer covers the low bar behind it."""
    fig, m = drawn_model(grid([[1.0, 1.0], [10.0, 1.0]]), options={"elev": 15, "azim": -90})
    a = m.axes[0]
    picture = np.asarray(fig.canvas.buffer_rgba())
    x, y, _ = proj3d.proj_transform(0.0, 1.0, 1.0, a.get_proj())       # the far bar's top
    px, py = a.transData.transform((x, y))
    got = picture[picture.shape[0] - 1 - int(py), int(px), :3] / 255
    tall, low = (m.bars[0][k].get_facecolor()[0][:3] for k in (2, 0))
    assert np.abs(got - tall).sum() < np.abs(got - low).sum()


def test_the_quick_picture_is_the_same_bars():
    _, m = drawn_model(grid(np.arange(33.0 * 33).reshape(33, 33)))
    a = m.axes[0]
    assert m.quick[0] is not None and not m.quick[0].get_visible()
    limits = a.get_xlim(), a.get_ylim(), a.get_zlim()
    bars3d.set_draft(m, True)
    assert m.quick[0].get_visible() and not m.bars[0][0].get_visible()
    assert (a.get_xlim(), a.get_ylim(), a.get_zlim()) == limits
    bars3d.set_draft(m, False)
    assert m.bars[0][0].get_visible()
    assert drawn_model(grid(np.ones((4, 4))))[1].quick == [None]        # few bars are quick anyway


def test_a_wrong_angle_says_what_is_wrong():
    with pytest.raises(render.RenderError, match="elev must be a number from -90 to 90"):
        render.resolve_spec(grid(np.ones((2, 2))), {"kind": "bars3d", "options": {"elev": 120}})
