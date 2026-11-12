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
