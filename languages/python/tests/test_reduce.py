"""lbd.plot.reduce: what large maps and curves look like on a screen with fewer pixels than data.

The traps are the ones the plot-engine comparison used: a single hot cell, a checkerboard, uneven
cells, a one-point spike, a gap. A slow brute-force reduction checks the fast one.
"""

import numpy as np
import pytest

from lbd.plot.reduce import MapPyramid, ReduceError, cell_edges, curve_minmax, nearest_point


def pixels(lo, hi, n):
    return np.linspace(lo, hi, n + 1)


def noisy_map(n, seed=0):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (n, n))


# ---- maps ---------------------------------------------------------------------------------------


def test_a_single_hot_cell_survives_max_at_the_full_view():
    z = noisy_map(1001)
    z[700, 300] = 10                                     # row = y index, column = x index
    e = cell_edges(np.arange(1001.0))
    pyr = MapPyramid(z, e, e)
    r = pyr.raster(pixels(e[0], e[-1], 200), pixels(e[0], e[-1], 150), "max")
    assert r.reduced and r.level >= 1
    assert np.nanmax(r.image) == 10
    j, i = np.unravel_index(np.nanargmax(r.image), r.image.shape)
    assert abs(i - 300 / 1001 * 200) <= 1.5 and abs(j - 700 / 1001 * 150) <= 1.5
    assert "max of" in r.note()
    # The mean is a different question ("what does it look like overall"): the cell is diluted.
    assert np.nanmax(pyr.raster(pixels(e[0], e[-1], 200), pixels(e[0], e[-1], 150), "mean").image) < 2


def test_a_checkerboard_makes_no_pattern_that_is_not_in_the_data():
    z = np.zeros((512, 512))
    z[100:132, 100:132] = np.where((np.add.outer(np.arange(32), np.arange(32)) % 2) == 1, 5.0, -15.0)
    e = cell_edges(np.arange(512.0))
    pyr = MapPyramid(z, e, e)
    view = (pixels(e[0], e[-1], 64), pixels(e[0], e[-1], 64))       # 8 cells per pixel
    inside = (slice(13, 16), slice(13, 16))                         # pixels fully over the board
    assert np.all(pyr.raster(*view, "max").image[inside] == 5)
    assert np.all(pyr.raster(*view, "min").image[inside] == -15)
    assert np.allclose(pyr.raster(*view, "mean").image[inside], -5)


def test_uneven_cells_keep_their_widths():
    x = np.array([1.0, 2, 4, 8, 16])
    y = np.array([10.0, 20, 30, 40])
    z = np.arange(5.0)[None, :] + 5 * np.arange(4.0)[:, None]
    xe, ye = cell_edges(x), cell_edges(y)                           # 0.5 1.5 3 6 12 20
    pyr = MapPyramid(z, xe, ye)
    px, py = pixels(0.5, 20, 390), pixels(5, 45, 400)
    r = pyr.raster(px, py, "max")
    assert not r.reduced and r.note() == "every cell shown"
    centres_x, centres_y = (px[:-1] + px[1:]) / 2, (py[:-1] + py[1:]) / 2
    col = np.searchsorted(xe, centres_x, side="right") - 1
    row = np.searchsorted(ye, centres_y, side="right") - 1
    assert np.array_equal(r.image, z[row][:, col])                  # each pixel: the cell under it
    assert r.image[np.searchsorted(centres_y, 30), np.searchsorted(centres_x, 10)] == 13


def test_zoomed_in_every_pixel_shows_the_exact_cell():
    z = noisy_map(300, seed=4)
    e = cell_edges(np.linspace(-1, 1, 300))
    pyr = MapPyramid(z, e, e)
    px, py = pixels(e[100], e[110], 500), pixels(e[50], e[53], 400)
    r = pyr.raster(px, py, "mean")
    cx = np.searchsorted(e, (px[:-1] + px[1:]) / 2, side="right") - 1
    cy = np.searchsorted(e, (py[:-1] + py[1:]) / 2, side="right") - 1
    assert r.level == 0 and np.array_equal(r.image, z[cy][:, cx])


def test_decreasing_axes_give_the_same_picture():
    z = noisy_map(200, seed=2)
    e = cell_edges(np.arange(200.0))
    up = MapPyramid(z, e, e).raster(pixels(0, 150, 40), pixels(20, 199, 30), "max").image
    down = MapPyramid(z[::-1, ::-1], e[::-1], e[::-1]).raster(pixels(0, 150, 40), pixels(20, 199, 30), "max").image
    assert np.array_equal(up, down)


def test_outside_the_map_is_empty():
    e = cell_edges(np.arange(10.0))
    r = MapPyramid(noisy_map(10), e, e).raster(pixels(100, 200, 5), pixels(0, 9, 5), "max")
    assert np.all(np.isnan(r.image))


def test_an_unsorted_axis_is_refused_with_a_reason():
    with pytest.raises(ReduceError, match="not sorted"):
        MapPyramid(np.zeros((2, 3)), np.array([0.0, 2, 1, 3]), np.array([0.0, 1, 2]))


def _brute(z, xe, ye, px, py, stat, level):
    """The pyramid's rule written out with loops: blocks of 2**level cells; a pixel narrower than
    the block under its centre shows that block (none when its centre is off the map), a wider one
    every block it overlaps."""
    s = 2 ** level
    ny, nx = z.shape
    bx = xe[np.minimum(np.arange(-(-nx // s) + 1) * s, nx)]
    by = ye[np.minimum(np.arange(-(-ny // s) + 1) * s, ny)]

    def blocks(be, lo, hi):
        c = (lo + hi) / 2
        k = np.searchsorted(be, c, side="right") - 1
        kc = min(max(k, 0), len(be) - 2)
        if hi - lo < be[kc + 1] - be[kc]:
            return [k] if 0 <= k < len(be) - 1 else []
        return [k for k in range(len(be) - 1) if be[k] < hi and be[k + 1] > lo]

    out = np.full((len(py) - 1, len(px) - 1), np.nan)
    for j in range(len(py) - 1):
        for i in range(len(px) - 1):
            vals = [z[b * s:(b + 1) * s, a * s:(a + 1) * s].ravel()
                    for b in blocks(by, py[j], py[j + 1]) for a in blocks(bx, px[i], px[i + 1])]
            v = np.concatenate(vals) if vals else np.array([])
            v = v[np.isfinite(v)]
            if v.size:
                out[j, i] = {"max": v.max, "min": v.min, "mean": v.mean}[stat]()
    return out


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("stat", ["max", "min", "mean"])
def test_the_fast_reduction_equals_brute_force(seed, stat):
    rng = np.random.default_rng(seed)
    ny, nx = rng.integers(70, 160, 2)
    z = rng.normal(size=(ny, nx))
    z[rng.random(z.shape) < 0.1] = np.nan                # missing cells are left out
    xe = np.cumsum(rng.uniform(0.2, 3, nx + 1))          # uneven cells
    ye = np.cumsum(rng.uniform(0.2, 3, ny + 1))
    pyr = MapPyramid(z, xe, ye, smallest=8)
    for _ in range(4):
        x0, x1 = np.sort(rng.uniform(xe[0] - 5, xe[-1] + 5, 2))
        y0, y1 = np.sort(rng.uniform(ye[0] - 5, ye[-1] + 5, 2))
        px, py = pixels(x0, x1, int(rng.integers(5, 40))), pixels(y0, y1, int(rng.integers(5, 40)))
        r = pyr.raster(px, py, stat)
        expected = _brute(z, xe, ye, px, py, stat, r.level)
        # max and min of the stored cells are exact; higher levels keep them as float32, and a
        # mean is added up in another order: equal up to rounding.
        exact = r.level == 0 and stat != "mean"
        assert np.allclose(r.image, expected, equal_nan=True, rtol=0 if exact else 1e-6, atol=0 if exact else 1e-6)


# ---- curves -------------------------------------------------------------------------------------


def accuracy_curve():
    n = 1_000_000
    x = np.arange(n) / (n - 1)
    y = np.sin(2 * np.pi * 3 * x) + 0.02 * (np.random.default_rng(1).random(n) - 0.5)
    y[731234] = 5
    y[200000:200003] = -3
    y[500000:500100] = np.nan
    return x, y


def test_a_one_point_spike_and_a_short_dip_survive():
    x, y = accuracy_curve()
    [(xr, yr)], reduced = curve_minmax(x, [y], pixels(0, 1, 900))
    assert reduced and len(yr) <= 2 * 902
    assert np.nanmax(yr) == 5 and np.nanmin(yr) == -3
    assert abs(xr[np.nanargmax(yr)] - x[731234]) < 1 / 900          # in the right pixel column


def test_zoomed_in_the_stored_points_are_drawn_unchanged():
    x, y = accuracy_curve()
    lo, hi = x[500000 - 300], x[500100 + 300]
    [(xr, yr)], reduced = curve_minmax(x, [y], pixels(lo, hi, 900))
    assert not reduced
    assert np.array_equal(xr, x[500000 - 301:500100 + 302])
    assert np.isnan(yr).sum() == 100                                # the gap is still a gap


def test_a_column_of_missing_points_breaks_the_line():
    x = np.arange(10000.0)
    y = np.ones(10000)
    y[5000:5600] = np.nan
    [(xr, yr)], _ = curve_minmax(x, [y], pixels(0, 9999, 100))
    assert np.isnan(yr).any()


def test_many_curves_share_the_columns():
    x = np.linspace(4, 6, 10000)
    ys = [np.sin(x * k) for k in range(50)]
    ys[37][7000] = 3
    out, reduced = curve_minmax(x, ys, pixels(4, 6, 300))
    assert reduced and len(out) == 50
    assert np.nanmax(out[37][1]) == 3 and all(np.nanmax(o[1]) <= 1 for k, o in enumerate(out) if k != 37)


def test_decreasing_x_is_reduced_too():
    x = np.linspace(1, 0, 100000)
    y = np.zeros(100000)
    y[123] = 7
    [(xr, yr)], reduced = curve_minmax(x, [y], pixels(0, 1, 200))
    assert reduced and np.nanmax(yr) == 7 and np.all(np.diff(xr) >= 0)


def test_the_nearest_point_is_found_in_pixels():
    x = np.linspace(0, 10, 11)
    ys = [np.zeros(11), np.ones(11)]
    to_px = lambda xx, yy: (xx * 10, 100 - yy * 50)                 # noqa: E731 (a tiny mapping)
    assert nearest_point(x, ys, to_px, (31, 52)) == (1, 3)
    assert nearest_point(x, ys, to_px, (31, 99)) == (0, 3)
    assert nearest_point(x, ys, to_px, (500, 500)) is None


def test_an_unsorted_curve_is_thinned_in_stored_order_keeping_extremes():
    from lbd.plot.reduce import thin_in_order

    t = np.linspace(0, 40 * np.pi, 1_000_000)
    x, y = np.cos(t), np.sin(t) * np.linspace(0, 1, t.size)           # a spiral: x goes back and forth
    y[777_777] = 3
    xs, ys = thin_in_order(x, y, 2000)
    assert len(ys) <= 2002 and np.max(ys) == 3                       # the spike stays
    assert np.min(ys) == np.min(y)
    small_x, small_y = thin_in_order(x[:500], y[:500], 2000)
    assert np.array_equal(small_y, y[:500])                          # few points: unchanged


def test_lines_are_rastered_with_later_lines_on_top():
    from lbd.plot.reduce import raster_lines

    flat = (np.array([0.0, 99.0]), np.array([10.0, 10.0]))          # a horizontal line at row 10
    rising = (np.array([0.0, 99.0]), np.array([49.0, 0.0]))         # from bottom-left to top-right
    spike = (np.array([50.0, 50.5, 51.0]), np.array([30.0, 2.0, 30.0]))
    owner = raster_lines([flat, rising, spike], 100, 50)
    assert (owner[10, :] >= 0).all()                                 # no gaps along the flat line
    assert owner[10, 20] == 0 and owner[2, 50] == 2                  # the spike's tip is drawn
    col_hits = [(owner[:, c] == 1).any() for c in range(100) if c not in (50, 51)]
    assert all(col_hits)                                             # the slope is continuous (the spike, on top, hides it at 50-51)
    assert owner[49, 99] == -1 and owner[0, 0] == -1                 # elsewhere: nothing
    crossing = np.argwhere((owner == 1) & (np.abs(np.arange(50)[:, None] - 10) == 0))
    assert crossing.size                                             # 'rising' drawn over 'flat' where they cross


def test_rastered_lines_leave_gaps_and_ignore_what_is_outside():
    from lbd.plot.reduce import raster_lines

    gap = (np.array([0.0, 40.0, np.nan, 60.0, 99.0]), np.array([5.0, 5.0, np.nan, 5.0, 5.0]))
    far = (np.array([-1e6, 1e6]), np.array([1e6, 1e6]))            # entirely below the picture
    owner = raster_lines([gap, far], 100, 20)
    assert (owner[5, 45:55] == -1).all() and (owner[5, :40] == 0).all()
    assert not (owner == 1).any()


@pytest.mark.parametrize("n", [40, 3000])                            # fewer and more points than columns
def test_curves_sharing_x_raster_like_any_polyline(n):
    from lbd.plot.reduce import raster_columns, raster_lines

    rng = np.random.default_rng(n)
    x = np.sort(rng.uniform(-5, 105, n))
    ys = np.cumsum(rng.normal(0, 2, (6, n)), axis=1) + 25
    ys[2, n // 2: n // 2 + 3] = np.nan                               # a gap in one curve
    fast = raster_columns(x, ys, 100, 50, 1.3)
    slow = raster_lines([(x, y) for y in ys], 100, 50, 1.3)
    # the same pixels drawn; the owner may differ by a pixel where the two methods round a slope
    assert np.mean((fast >= 0) == (slow >= 0)) > 0.97
    assert np.mean(fast[(fast >= 0) & (slow >= 0)] == slow[(fast >= 0) & (slow >= 0)]) > 0.9
