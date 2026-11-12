"""Show points in Explore (16.39): one real stored point per occupied pixel, drawn as a small dot."""

import numpy as np
import pytest

import lbd
from lbd_viewer import explore
from mock_large import accuracy
from test_explore import open_view, render


@pytest.fixture(scope="module")
def engine_data():
    return accuracy()


@pytest.fixture()
def engine_test_1(engine_data, data_dir):
    path = data_dir / "engine test 1.lbd"
    engine_data.save(path)
    return path


def drawn_dots(client, sid, **view):
    """The dots of the one curve as drawn (data units), the picture's meta and the session."""
    meta, _ = render(client, sid, **view)
    sess = client.app.state.lbd.explore.get(sid)
    [artist] = sess.dot_artists
    assert artist.get_visible()
    fx, fy = (np.asarray(v, dtype=float) for v in artist.get_data())
    (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
    return x0 + fx * (x1 - x0), y0 + fy * (y1 - y0), meta, sess


def test_every_dot_is_a_stored_point_one_per_occupied_pixel(client, engine_test_1):
    o = open_view(client, engine_test_1, spec={"kind": "curve", "options": {"points": True}})
    assert o["spec"]["options"] == {"points": True}
    d = lbd.load(engine_test_1)
    x, y = d.axes["x"].data, d.values["signal"].data
    for view in ({}, {"xlim": [0.2995, 0.3005]}):                   # all million points; about a thousand
        xd, yd, meta, sess = drawn_dots(client, o["session"], **view)
        # every dot sits on a stored point, at its exact x and y (up to the pixel round trip)
        i = np.clip(np.searchsorted(x, xd), 1, x.size - 1)
        i = np.where(np.abs(x[i - 1] - xd) < np.abs(x[i] - xd), i - 1, i)
        assert np.allclose(x[i], xd, rtol=0, atol=1e-12) and np.allclose(y[i], yd, rtol=0, atol=1e-9)
        # one dot per occupied pixel, and every occupied pixel has its dot
        (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
        w, h = meta["plot"][2:]

        def pixels(xs, ys):
            c, r = (xs - x0) * (w / (x1 - x0)), (ys - y0) * (h / (y1 - y0))      # as occupied_points
            ok = (c >= 0) & (c < w) & (r >= 0) & (r < h)
            return set(zip(c[ok].astype(int), r[ok].astype(int)))

        assert len(pixels(x[i], y[i])) == len(xd) == len(pixels(x, y))
        assert len(xd) < 5000                                           # not a million


def test_the_spike_and_dip_of_engine_test_1_have_dots(client, engine_test_1):
    o = open_view(client, engine_test_1, spec={"kind": "curve", "options": {"points": True}})
    xd, yd, meta, _ = drawn_dots(client, o["session"])
    d = lbd.load(engine_test_1)
    x = d.axes["x"].data
    for i, value in ((731234, 5.0), (200000, -3.0)):                  # the spike, the dip's first point
        assert np.any(np.isclose(xd, x[i], rtol=0, atol=1e-12) & np.isclose(yd, value, rtol=0, atol=1e-9)), i


def test_dots_shrink_to_the_line_where_the_curve_is_dense(client, engine_test_1):
    o = open_view(client, engine_test_1, spec={"kind": "curve", "options": {"points": True}})
    _, _, _, sess = drawn_dots(client, o["session"])                  # a million points in 600 columns
    dense = sess.dot_artists[0].get_markersize()
    _, _, _, sess = drawn_dots(client, o["session"], xlim=[0.3, 0.3001])   # 100 points
    sparse = sess.dot_artists[0].get_markersize()
    assert dense == pytest.approx(1 * 72 / 96) and sparse == pytest.approx(3 * 72 / 96)
    assert sess.lines[0].get_marker() == "None"                      # the reduced line has no markers itself


def test_too_many_points_in_view_leave_the_dots_out_with_a_note(client, engine_test_1, monkeypatch):
    monkeypatch.setattr(explore, "DOTS_LIMIT", 100_000)
    o = open_view(client, engine_test_1, spec={"kind": "curve", "options": {"points": True}})
    meta, _ = render(client, o["session"])
    sess = client.app.state.lbd.explore.get(o["session"])
    assert "points not shown: 1.0 million stored points in view, more than 0.1 million; zoom in" in meta["note"]
    assert not sess.dot_artists[0].get_visible()
    meta, _ = render(client, o["session"], xlim=[0.3, 0.31])         # 10 000 points: shown again
    assert "points not shown" not in meta["note"] and sess.dot_artists[0].get_visible()


def test_many_curves_get_their_dots_painted_into_their_picture(client, data_dir):
    d = lbd.Dataset(title="many")
    d.add_axis("k", np.arange(40.0))
    d.add_axis("t", np.arange(100.0))
    d.add_value("v", np.add.outer(np.arange(40.0), np.sin(np.arange(100.0))), axes=["k", "t"])
    d.save(data_dir / "many.lbd")
    painted = []
    for points in (False, True):
        o = open_view(client, data_dir / "many.lbd", spec={"kind": "curve", "x": "t", "series": "k",
                                                           "options": {"points": points}})
        render(client, o["session"])
        sess = client.app.state.lbd.explore.get(o["session"])
        assert sess.line_image.get_visible() and not any(a.get_visible() for a in sess.lines + sess.dot_artists)
        painted.append(np.count_nonzero(np.asarray(sess.line_image.get_array())[..., 3]))
    assert painted[1] > painted[0] * 1.2                              # 4000 dots on the lines


def test_painted_dots_are_squares_in_their_line_colour_later_lines_on_top():
    red, blue = [255, 0, 0, 255], [0, 0, 255, 255]
    nothing = (np.empty(0), np.empty(0))
    dots = [(np.array([10.3, 0.2]), np.array([5.6, 0.2])), (np.array([12.0]), np.array([5.0]))]
    img = explore.paint_lines([nothing, nothing], np.array([red, blue]), 20, 10, 1, dots, 3)
    assert list(img[5, 9]) == red and list(img[4, 9]) == red          # 9 … 11 by 4 … 6 around (10.3, 5.6)
    assert list(img[6, 11]) == blue                                   # where blue's square covers red's
    assert list(img[0, 0]) == red and list(img[0, 2]) == [0, 0, 0, 0]   # cut at the picture's edge
    assert img[9, 19, 3] == 0
