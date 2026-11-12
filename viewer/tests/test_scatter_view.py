"""The plot type Scatter in Explore: the picture, the cursor, large files, the histograms beside it."""

import json
import time

import numpy as np
import pytest

import lbd
import lbd.plot as lp
import mock_values
from lbd.plot import histogram as hist
from lbd.plot import render as rnd
from lbd.plot import scatter as sc
from lbd_viewer import crange, export, memory, reading
from lbd_viewer.explore import ExploreError, ExploreSession
from lbd_viewer.kinds import scatter as kind


@pytest.fixture(autouse=True)
def fresh():
    crange.forget()
    yield
    crange.forget()

IQ = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "state", "all": ["shot"], "index": {"readout_power": 1}}


@pytest.fixture()
def iq(tmp_path):
    path = tmp_path / "iq.lbd"
    mock_values.single_shot_iq(True).save(path)
    return path


@pytest.fixture()
def many(tmp_path, monkeypatch):
    """Points above the limit (lowered to 500), in two groups."""
    monkeypatch.setattr(sc, "DENSITY_ABOVE", 500)
    rng = np.random.default_rng(3)
    d = lbd.Dataset()
    d.add_axis("g", [0.0, 1.0], elements=["a", "b"])
    d.add_axis("t", np.arange(1000.0))
    d.add_value("x", rng.normal(size=(2, 1000)) + np.array([[-5.0], [5.0]]), axes=["g", "t"], unit="V")
    d.add_value("y", rng.normal(size=(2, 1000)), axes=["g", "t"], unit="V")
    d.save(tmp_path / "many.lbd")
    return tmp_path / "many.lbd"


MANY = {"kind": "scatter", "values": ["y"], "x": "x", "color": "g", "all": ["t"]}


def session(path, spec, version="v1", **kw):
    return ExploreSession(path, version, spec, lp.load_style(), 600, 400, 1.0, **kw)


def frame(s, xlim=None, ylim=None, settings=None, **kw):
    s.apply(settings or {})
    return s.render(xlim, ylim, **kw)[1]


def test_opens_and_zooms(iq):
    s = session(iq, IQ)
    assert s.kind == "scatter"
    meta = frame(s)
    assert meta["note"] == "every point shown" and not meta["reduced"]
    (x0, x1), (y0, y1) = s.full
    mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
    zoomed = frame(s, (x0, mid_x), (y0, mid_y))
    assert zoomed["xlim"][0] <= x0 + 1e-9 and zoomed["xlim"][1] >= mid_x - 1e-9 and zoomed["ylim"][1] >= mid_y - 1e-9
    assert zoomed["xlim"][1] - zoomed["xlim"][0] < frame(s)["xlim"][1] - frame(s)["xlim"][0]


def test_limits_are_the_data_with_a_margin(tmp_path):
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("x", np.array([0.0, 5.0, 10.0]), axes="t")
    d.add_value("y", np.array([1.0, 2.0, 3.0]), axes="t")
    d.save(tmp_path / "a.lbd")
    s = session(tmp_path / "a.lbd", {"kind": "scatter", "values": ["y"], "x": "x"})
    assert s.full[0] == pytest.approx((-0.5, 10.5)) and s.full[1] == pytest.approx((0.9, 3.1))


def test_equal_axes_report_the_limits_really_shown(iq):
    s = session(iq, {**IQ, "options": {"equal": True}})
    meta = frame(s)
    assert meta["equal"]
    ax = s.ax
    assert meta["xlim"] == pytest.approx(ax.get_xlim()) and meta["ylim"] == pytest.approx(ax.get_ylim())
    box = ax.get_window_extent()
    per_x = box.width / (meta["xlim"][1] - meta["xlim"][0])
    per_y = box.height / (meta["ylim"][1] - meta["ylim"][0])
    assert per_x == pytest.approx(per_y, rel=1e-3)


def test_above_the_limit_the_points_are_counted_per_pixel(many):
    s = session(many, MANY)
    meta = frame(s)
    assert meta["reduced"] and meta["note"] == "2,000 points: each pixel shows how many are there"
    w, h = meta["plot"][2:]
    assert s.view.image.get_array().shape[:2] == (h, w)
    assert [t.get_text() for t in s.ax.get_legend().get_texts()] == ["Prepared" if False else "g = a", "g = b"]


def test_zooming_counts_again_and_stays_sharp(many):
    s = session(many, MANY)
    frame(s)
    full = np.asarray(s.view.image.get_array()).copy()
    meta = frame(s, (-7.0, -3.0), (-1.0, 1.0))
    now = np.asarray(s.view.image.get_array())
    assert now.shape == full.shape and not np.array_equal(now, full)
    assert int(meta["note"].split()[0].replace(",", "")) < 2000


def test_a_draft_is_counted_at_half_size(many):
    s = session(many, MANY)
    meta = frame(s, draft=True)
    w, h = meta["plot"][2:]
    assert s.view.image.get_array().shape[:2] == (h // 2, w // 2)


def test_a_colour_bar_counts_points_without_colours(many):
    s = session(many, {**MANY, "color": "none", "all": ["t", "g"]})
    frame(s)
    assert s.fig.axes[1].get_ylabel() == "Points per pixel"
    assert s.view.bar.get_clim()[1] >= 2


def test_a_live_file_grows(tmp_path):
    path = tmp_path / "g.lbd"
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("x", np.arange(3.0), axes="t")
    d.add_value("y", np.arange(3.0), axes="t")
    d.save(path)
    s = session(path, {"kind": "scatter", "values": ["y"], "x": "x"})
    frame(s)
    assert s.model.series[0][0].size == 3
    d = lbd.Dataset()
    d.add_axis("t", np.arange(5.0))
    d.add_value("x", np.arange(5.0), axes="t")
    d.add_value("y", np.arange(5.0), axes="t")
    d.save(path)
    s = session(path, {"kind": "scatter", "values": ["y"], "x": "x"}, version="v2")      # (the page reopens it)
    frame(s)
    assert s.model.series[0][0].size == 5


def test_log_scales_say_what_they_hide(iq):
    s = session(iq, {"kind": "scatter", "values": ["Q"], "x": "I", "all": ["shot", "state", "readout_power"]})
    meta = frame(s, settings={"xscale": "log"})
    assert meta["xscale"] == "log" and "aren't shown on the log horizontal axis" in meta["hidden"][0]


def test_a_preview_has_only_the_data(iq):
    s = session(iq, {"kind": "scatter", "values": ["Q"], "x": "I", "color": "shot"}, bare=True)
    frame(s)
    assert len(s.fig.axes) == 1


# -- the cursor -------------------------------------------------------------------------------------

def read(s, points, **kw):
    meta = frame(s)
    return reading.cursors(s, [{"x": x, "y": y} for x, y in points], "cross", {"xlim": meta["xlim"], "ylim": meta["ylim"]},
                           meta["plot"][2:], **kw)


def uneven(tmp_path):
    """x in GHz and y in mV: units say nothing about the distance on the screen."""
    d = lbd.Dataset()
    d.add_axis("t", np.arange(3.0))
    d.add_value("f", np.array([1.0e9, 1.001e9, 2.0e9]), axes="t", unit="Hz")
    d.add_value("v", np.array([1.0e-3, 2.0e-3, 1.5e-3]), axes="t", unit="V")
    d.save(tmp_path / "u.lbd")
    return session(tmp_path / "u.lbd", {"kind": "scatter", "values": ["v"], "x": "f"})


def test_a_cursor_reads_the_nearest_point_in_pixels(tmp_path):
    s = uneven(tmp_path)
    # 1.05 GHz, 1.9 mV: nearest the second point on the plot
    c = read(s, [(1.05, 1.9)])["cursors"][0]
    assert c["index"] == {"t": 1}
    assert c["items"][0]["value"] == pytest.approx(1.001e9) and c["items"][0]["unit"] == "Hz"
    assert c["items"][1]["value"] == pytest.approx(2.0e-3) and c["items"][1]["unit"] == "V"
    assert "trace" not in c and "cell" not in c


def test_it_reads_the_stored_index(iq):
    s = session(iq, IQ)
    meta = frame(s)
    x, y = s.model.series[0][0][17], s.model.series[0][1][17]
    c = read(s, [(float(x), float(y))])["cursors"][0]
    want = {a: int(n[17]) for a, n in s.model.index[0].items()}
    assert c["index"] == want and c["index"]["readout_power"] == 1
    z = lbd.load(iq).values["IQ"].data[want["readout_power"], want["state"], want["shot"]]
    assert c["items"][0]["value"] == pytest.approx(z.real) and c["items"][1]["value"] == pytest.approx(z.imag)
    colour = c["items"][2]
    assert colour["role"] == "series" and colour["text"] == "ground" and "equal" not in meta   # off unless asked (16.32)


def test_a_colour_value_is_read_in_stored_units(iq):
    s = session(iq, {"kind": "scatter", "values": ["Q"], "x": "I", "color": "IQ", "complex": "abs", "all": ["shot", "state"],
                     "index": {"readout_power": 1}})
    c = read(s, [(float(s.model.series[0][0][3]), float(s.model.series[0][1][3]))])["cursors"][0]
    want = abs(lbd.load(iq).values["IQ"].data[1, 0, 3])
    assert c["items"][2]["role"] == "z" and c["items"][2]["value"] == pytest.approx(want)


def test_two_cursors_have_delta_and_mean(iq):
    s = session(iq, IQ)
    a, b = (float(s.model.series[0][0][1]), float(s.model.series[0][1][1])), (float(s.model.series[0][0][9]), float(s.model.series[0][1][9]))
    got = read(s, [a, b])
    one, two = got["cursors"]
    assert one["items"][0]["name"] == two["items"][0]["name"] and one["items"][0]["unit"] == two["items"][0]["unit"]
    assert "between" not in got                         # no counts: differences come from the two readings


def test_above_the_limit_it_still_reads_a_stored_point(many):
    s = session(many, MANY)
    c = read(s, [(5.0, 0.0)])["cursors"][0]
    d = lbd.load(many)
    assert d.values["x"].data[c["index"]["g"], c["index"]["t"]] == pytest.approx(c["items"][0]["value"])
    assert c["items"][2]["text"] == "b"


def test_a_cursor_keeps_to_the_points_in_view(iq):
    s = session(iq, IQ)
    frame(s)
    xs = s.model.series[0][0]
    lo, mid = float(xs.min()), float(np.median(xs))
    (y0, y1) = s.full[1]
    got = reading.cursors(s, [{"x": mid + 1e6, "y": 0.0}], "cross", {"xlim": [lo, mid], "ylim": [y0, y1]}, (500, 300))
    assert got["cursors"][0]["x"] <= mid


def test_table_has_every_shown_point(iq, tmp_path):
    s = session(iq, IQ)
    frame(s)
    t = export.session_table(s)
    assert export.column_names(t) == ["x", "IQ", "index_readout_power", "index_state", "index_shot"]
    out = t.to_csv(tmp_path / "s.csv")
    rows = np.loadtxt(out, delimiter=",", comments="#")
    assert rows.shape == (400, 5) and np.allclose(rows[:, 0], s.model.series[0][0] / s.model.xf)
    z = lbd.load(iq).values["IQ"].data
    i = rows[:, 2:].astype(int)
    assert np.allclose(z[i[:, 0], i[:, 1], i[:, 2]].imag, rows[:, 1])
    assert export.options(s)["stored"] and export.options(s)["zoomed"] is None


# -- a file that doesn't fit memory -------------------------------------------------------------------

@pytest.fixture()
def tight(tmp_path, monkeypatch):
    """Values read by part (fake memory), and 40 000 points: more than the room for them."""
    rng = np.random.default_rng(9)
    d = lbd.Dataset()
    d.add_axis("g", [0.0, 1.0], elements=["a", "b"])
    d.add_axis("t", np.arange(20_000.0))
    d.add_value("x", rng.normal(size=(2, 20_000)) + np.array([[-3.0], [3.0]]), axes=["g", "t"], unit="V")
    d.add_value("y", rng.normal(size=(2, 20_000)), axes=["g", "t"], unit="V")
    d.add_value("c", rng.normal(size=(2, 20_000)), axes=["g", "t"], unit="s")
    d.save(tmp_path / "tight.lbd")
    cache = memory.PartCache(memory.Memory(always_whole=0, system=lambda: (4 * memory.GB, 100_000)))
    monkeypatch.setitem(memory._shared, "cache", cache)
    monkeypatch.setattr(hist, "BLOCK", 3000)
    return tmp_path / "tight.lbd"


TIGHT = {"kind": "scatter", "values": ["y"], "x": "x", "color": "g", "all": ["t"]}


def done(s, **kw):
    for _ in range(1200):
        meta = frame(s, s.full[0], s.full[1], **kw)
        if not (meta.get("crange") or {}).get("state") == "working":
            return meta
        time.sleep(0.05)
    raise AssertionError("still counting")


def test_a_big_file_is_counted_by_parts(tight):
    s = session(tight, TIGHT)
    assert s.view._big() and s.model.series[0][0].size == 0
    meta = done(s)
    assert meta["note"] == "40,000 points: each pixel shows how many are there" and meta["crange"] is None
    assert s.full[0][0] < -3 < 3 < s.full[0][1]
    # the same counts as from the points in memory
    d = lbd.load(tight)
    spec = rnd.resolve_spec(d, TIGHT, warn_unused=False)
    m = sc.prepare_scatter(d, spec, s.style)
    w, h = meta["plot"][2:]
    pic = sc.density_image(m, sc.density(m, tuple(meta["xlim"]), tuple(meta["ylim"]), w, h, ("linear", "linear"), s.style.figure.axes.colors))
    assert np.array_equal(np.asarray(s.view.image.get_array()), pic)


def test_a_big_file_coloured_by_a_value(tight):
    s = session(tight, {**TIGHT, "color": "c"})
    done(s)
    assert s.model.c_text[1] == "s" and s.model.cnorm.vmin < 0 < s.model.cnorm.vmax


def test_a_big_view_is_kept_and_zooming_counts_again(tight):
    s = session(tight, TIGHT)
    done(s)
    full = s.full
    assert frame(s, full[0], full[1]).get("crange") is None
    zoomed = frame(s, (-4.0, -2.0), (-1.0, 1.0))
    assert zoomed["crange"]["state"] == "working" and zoomed["note"].startswith("counting")


def test_cursor_says_why(tight):
    s = session(tight, TIGHT)
    meta = done(s)
    assert "Cursors can't choose a point here" in meta["hidden"][0]
    got = reading.cursors(s, [{"x": 0.0, "y": 0.0}], "cross", {"xlim": meta["xlim"], "ylim": meta["ylim"]}, (300, 200))
    assert got["cursors"] == [None]
    with pytest.raises(ExploreError, match="too many to list"):
        export.session_table(s)


def test_a_slice_of_a_big_file_shows_markers(tight, monkeypatch):
    monkeypatch.setattr(kind, "BYTES_PER_POINT", 3)      # room for 33 000 points: not both groups
    assert session(tight, TIGHT).view._big()
    s = session(tight, {**TIGHT, "color": "none", "index": {"g": 0}})
    assert not s.view._big() and frame(s)["note"] == "every point shown"


# -- histograms of the points in view -----------------------------------------------------------------

def test_sides_count_only_points_in_view(many):
    s = session(many, MANY)
    meta = frame(s, (-8.0, 0.0), (-4.0, 4.0))
    sides = meta["sides"]
    x, y = (lbd.load(many).values[n].data for n in "xy")
    seen = (x >= -8) & (x <= 0) & (y >= -4) & (y <= 4)
    assert [sum(c) for c in sides["x"]["counts"]] == [int(seen[0].sum()), int(seen[1].sum())]
    assert sides["x"]["edges"][0] == pytest.approx(-8) and sides["x"]["edges"][-1] == pytest.approx(0, abs=1e-9)
    assert sum(sides["y"]["counts"][0]) == int(seen[0].sum())
    assert len(sides["x"]["edges"]) == len(sides["x"]["counts"][0]) + 1
    json.dumps(sides)


def test_sides_per_group(iq):
    s = session(iq, IQ)
    sides = frame(s)["sides"]
    assert sides["labels"] == ["Prepared state = ground", "Prepared state = excited"] and len(sides["colours"]) == 2
    assert sum(sides["x"]["counts"][0]) == 200 and sum(sides["x"]["counts"][1]) == 200
    assert sides["x"]["unit"] == "V" and sides["x"]["factor"] == s.model.xf
    one = frame(session(iq, {**IQ, "color": "none", "all": ["shot", "state"]}))["sides"]
    assert len(one["x"]["counts"]) == 1


def test_sides_above_the_limit_match(many):
    s = session(many, MANY)
    meta = frame(s)
    assert meta["reduced"] and sum(sum(c) for c in meta["sides"]["x"]["counts"]) == 2000


def test_sides_on_a_log_axis_have_log_bins(tmp_path):
    d = lbd.Dataset()
    d.add_axis("t", np.arange(1000.0))
    d.add_value("x", 10 ** np.linspace(0, 3, 1000), axes="t")
    d.add_value("y", np.ones(1000), axes="t")
    d.save(tmp_path / "l.lbd")
    s = session(tmp_path / "l.lbd", {"kind": "scatter", "values": ["y"], "x": "x"})
    sides = frame(s, settings={"xscale": "log"})["sides"]
    e = np.asarray(sides["x"]["edges"])
    assert np.allclose(e[1:] / e[:-1], e[1] / e[0]) and sum(sides["x"]["counts"][0]) == 1000


def test_sides_of_a_big_file_come_from_the_same_pass(tight):
    s = session(tight, TIGHT)
    meta = done(s)
    assert sum(sum(c) for c in meta["sides"]["x"]["counts"]) == 40_000
    assert len(meta["sides"]["x"]["counts"]) == 2 and meta["strips"] == "histograms"
