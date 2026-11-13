"""The plot box of an Explore view comes from the picture's size and the style only (plan 16,
16.37): the same size gives the same layout whatever came before (another size, another value),
for every kind; a label too long for its room is shortened with "…", never cut off."""

import lbd.plot as lp
import pytest
from lbd_viewer.explore import ExploreSession

KINDS = [
    ("6 rabi.lbd", {}),                                   # curves
    ("7 spectroscopy 3d.lbd", {}),                        # a map with its colour bar
    ("16 density matrix.lbd", {"kind": "matrix"}),        # equal cells, a colour bar inside its axes
    ("11 single shot iq.lbd", {"kind": "scatter"}),
    ("9 many values.lbd", {"kind": "histogram"}),
    ("18 bars.lbd", {"kind": "bars"}),
]


def layout(s):
    """Where the plot box and every other axes (colour bar) are, in pixels."""
    s.render(None, None)
    return [tuple(round(v, 1) for v in a.get_position().bounds) for a in s.fig.axes]


@pytest.mark.parametrize("name, spec", KINDS)
def test_the_same_size_gives_the_same_layout_whatever_came_before(values_files, data_dir, name, spec):
    style = lp.load_style()
    fresh = ExploreSession(data_dir / name, "v", spec, style, 404, 429, 1)
    resized = ExploreSession(data_dir / name, "v", spec, style, 930, 429, 1)
    resized.render(None, None)
    resized.resize(404, 429, 1)
    assert layout(resized) == layout(fresh)
    assert resized.render(None, None)[1]["plot"] == fresh.render(None, None)[1]["plot"]
    fresh.close()
    resized.close()


def test_two_values_with_labels_of_other_lengths_get_the_same_box(values_files, data_dir):
    style = lp.load_style()
    a = ExploreSession(data_dir / "9 many values.lbd", "v", {}, style, 404, 429, 1)
    names = list(a.data.values)
    b = ExploreSession(data_dir / "9 many values.lbd", "v", {"values": [names[-1]]}, style, 404, 429, 1)
    assert a.render(None, None)[1]["plot"] == b.render(None, None)[1]["plot"]
    a.close()
    b.close()


def test_a_label_too_long_for_its_room_is_shortened_not_cut_off(values_files, data_dir):
    s = ExploreSession(data_dir / "6 rabi.lbd", "v", {"x_label": "A very long label " * 12}, lp.load_style(), 300, 300, 1)
    s.render(None, None)
    label = s.ax.xaxis.label
    assert label.get_text().endswith("…")
    box = label.get_window_extent(s.fig.canvas.get_renderer())
    assert box.x0 >= 0 and box.x1 <= s.fig.bbox.width
    s.close()


def test_a_slider_keeps_the_frame_unit_and_limits(values_files, data_dir):
    """16.49: stepping a slider (I/Q plane, all shots, equal axes): the same unit prefix, the same
    limits while not zoomed (every step's points fit, so they compare), the same plot box; and the
    view asked for comes back as asked, not widened by equal axes (it doesn't grow step by step)."""
    base = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "state", "all": ["shot"],
            "options": {"equal": True}}
    s = ExploreSession(data_dir / "11 single shot iq.lbd", "v", dict(base, index={"readout_power": 0}),
                       lp.load_style(), 600, 500, 1)
    seen = []
    for k in (0, 1, 0):
        s.set_spec(dict(base, index={"readout_power": k}))
        meta = s.render(*s.full)[1]
        full = [[float(v) for v in lim] for lim in s.full]
        seen.append((s.model.x_label, full, meta["plot"], [[float(v) for v in lim] for lim in meta["asked"]]))
    assert all(x == seen[0] for x in seen), seen
    assert seen[0][3] == seen[0][1]                                     # asked, not widened
    s.close()


def test_curves_with_a_slider_keep_their_prefix_and_limits(values_files, data_dir):
    s = ExploreSession(data_dir / "7 spectroscopy 3d.lbd", "v", {"kind": "curve"}, lp.load_style(), 600, 400, 1)
    slider = [a for a in s.spec["index"] if a not in (s.spec.get("x"), s.spec.get("series"))]
    if not slider:
        pytest.skip("no slider in this file's curves")
    a = slider[0]
    labels, fulls = [], []
    for k in range(min(3, len(s.data.axes[a].data))):
        s.set_spec({"kind": "curve", "index": {**s.spec["index"], a: k}})
        labels.append(s.model.y_label)
        fulls.append(s.full)
    assert len(set(labels)) == 1 and all(f == fulls[0] for f in fulls)
    s.close()


def test_a_label_shortened_at_a_small_size_is_whole_again_at_a_larger_one(values_files, data_dir):
    s = ExploreSession(data_dir / "6 rabi.lbd", "v", {}, lp.load_style(), 120, 300, 1)
    s.render(None, None)
    whole = s.sync_keys()["x"]
    assert s.ax.xaxis.label.get_text().endswith("…") and not whole.endswith("…")
    s.resize(800, 400, 1)
    s.render(None, None)
    assert s.ax.xaxis.label.get_text() == whole == s.sync_keys()["x"]
    s.close()


def test_a_right_hand_axis_fills_the_height_on_a_linear_scale(tmp_path):
    """16.52: two units, the second on a right-hand axis: on a linear scale each side fits its own
    range (temperatures of at most 300 K no longer use 2 % of the height beside a pressure of
    1000 mbar); on a log scale the middles line up as before."""
    import numpy as np
    import lbd

    t = np.linspace(0, 10, 200)
    d = lbd.Dataset("fridge")
    d.add_axis("time", t, unit="s")
    d.add_value("P", 1000 * np.exp(-t), axes="time", unit="Pa")
    d.add_value("T", 50 + 250 * np.exp(-t / 3), axes="time", unit="K")
    p = d.save(tmp_path / "fridge.lbd")
    s = ExploreSession(p, "v", {"kind": "curve", "values": ["P", "T"]}, lp.load_style(), 600, 400, 1)

    def right_share():
        apart = s.model.units_apart
        right = np.concatenate([s.model.lines[k][0] for k in apart["right"]])
        (_, _), (y0, y1) = s.full
        return (right.max() - right.min()) / (y1 - y0)
    assert right_share() > 0.8                                        # linear: it fills the height
    s.apply({"yscale": "log"})
    assert s.model.units_apart["log"] and s.ax.get_yscale() == "log"
    s.apply({"yscale": "linear"})
    assert not s.model.units_apart["log"] and right_share() > 0.8
    s.close()


def test_equal_curves_widen_the_view_in_stored_units(tmp_path):
    """16.32: Explore's curves with Equal axes: the view asked for is kept (meta asked), the view
    shown is widened so one stored unit has as many pixels both ways."""
    import lbd
    import numpy as np

    t = np.linspace(0, 2e-3, 50)
    d = lbd.Dataset("ramp")
    d.add_axis("t", t, unit="s")
    d.add_value("v", t * 1e3, axes="t", unit="V")
    p = d.save(tmp_path / "ramp.lbd")
    s = ExploreSession(p, "v", {"kind": "curve", "options": {"equal": True}}, lp.load_style(), 600, 400, 1)
    asked = s.full
    meta = s.render(*asked)[1]
    assert meta["equal"] and [list(v) for v in meta["asked"]] == [list(asked[0]), list(asked[1])]
    box = s.ax.get_window_extent()
    m = s.model
    per_x = box.width / ((meta["xlim"][1] - meta["xlim"][0]) / m.xf)
    per_y = box.height / ((meta["ylim"][1] - meta["ylim"][0]) / m.yf)
    assert per_x == pytest.approx(per_y, rel=1e-3) and m.xf != m.yf
    s.close()


def test_new_plots_start_with_the_looks_the_settings_turn_on(values_files, data_dir):
    """18.2: Settings → Explore → New plots start with: a look that is on there starts on; one that
    is off is left to the plot (Grid: the style; Show points: off); a tick in Display wins."""
    looks = {"curve": {"grid": True, "points": True}, "scatter": {"grid": False}}
    style = lp.load_style()
    s = ExploreSession(data_dir / "6 rabi.lbd", "v", {}, style, 400, 300, 1, looks=lambda: looks)
    assert s.spec["options"]["grid"] is True and s.spec["options"]["points"] is True
    assert any(line.get_visible() for line in s.ax.xaxis.get_gridlines())
    s.set_spec({"options": {"grid": False}})                            # unticked in Display: off
    assert s.spec["options"]["grid"] is False and not any(line.get_visible() for line in s.ax.xaxis.get_gridlines())
    s.close()
    plain = ExploreSession(data_dir / "11 single shot iq.lbd", "v", {"kind": "scatter", "values": ["IQ"], "complex": "iq"},
                           style, 400, 300, 1, looks=lambda: looks)
    assert "grid" not in (plain.spec.get("options") or {})              # off in the settings: the style's
    plain.close()
    previews = ExploreSession(data_dir / "6 rabi.lbd", "v", {}, style, 400, 300, 1)   # no settings (previews): nothing added
    assert "grid" not in (previews.spec.get("options") or {})
    previews.close()
