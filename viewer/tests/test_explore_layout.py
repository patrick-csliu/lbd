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
