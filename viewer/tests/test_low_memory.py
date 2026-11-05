"""A computer short of memory (plan 10): every ordinary file still opens in Explore and gives a
Library preview; data larger than the always-whole size is summarised, and the user is told why.

Found on a lab computer with 0.55 GB of 15 GB free: the old reserve (2 GB) left no room, so even
11 × 201 points were "too big" and refused ("small enough to show without a summary")."""

import warnings
from pathlib import Path

import numpy as np
import pytest

import lbd
from lbd.plot.style import Style
from lbd_viewer import memory, summaries
from lbd_viewer.explore import ExploreError, ExploreSession
from lbd_viewer.memory import GB, Memory, PartCache

from mock_values import write_all

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "data"


def no_free_memory(monkeypatch, tmp_path, always_whole=memory.ALWAYS_WHOLE, total=16 * GB):
    """The operating system reports nothing available; summaries kept in `tmp_path`."""
    m = Memory(system=lambda: (total, 0), always_whole=always_whole)
    monkeypatch.setitem(memory._shared, "cache", PartCache(m))
    monkeypatch.setitem(summaries._shared, "cache", summaries.SummaryCache(tmp_path / "summaries", lambda: GB))
    return m


def files(tmp_path):
    return write_all(tmp_path / "mock") + sorted(EXAMPLES.rglob("*.lbd"))


def open_quietly(path, spec=None, **kw):
    with warnings.catch_warnings():                     # notes about variable sweeps are not the point here
        warnings.simplefilter("ignore")
        return ExploreSession(path, "v", spec or {}, Style(), 400, 300, 1, **kw)


def test_every_file_opens_and_previews_with_no_free_memory(monkeypatch, tmp_path):
    paths = files(tmp_path)
    no_free_memory(monkeypatch, tmp_path)
    for p in paths:
        try:
            s = open_quietly(p)
        except ExploreError as e:                       # a saved scatter view goes to Figure (on purpose)
            assert "scatter" in str(e), (p, e)
            s = open_quietly(p, saved_view=False)
        assert not s.summarised, p
        assert s.take_notes() == [], p                 # nothing to tell about small files
        heatmaps = [n for n, v in lbd.info(p).values.items() if len(v.shape) >= 2]
        if heatmaps:
            open_quietly(p, {"values": [heatmaps[0]], "kind": "heatmap"})
        open_quietly(p, saved_view=False, summarise=False, bare=True)     # the Library's preview


def test_several_values_as_curves_open_with_no_free_memory(monkeypatch, tmp_path):
    no_free_memory(monkeypatch, tmp_path)               # rabi: two values in one curve plot
    s = open_quietly(EXAMPLES / "rabi.lbd")
    assert len(s.spec["values"]) == 2 and not s.summarised


def test_nothing_to_shrink_draws_the_data_whole(monkeypatch, tmp_path):
    """Even counted as too big (always-whole off), curves a summary can't shrink are drawn whole."""
    d = lbd.Dataset(title="one value")
    d.add_axis("power", np.arange(11.0))
    d.add_axis("freq", np.linspace(1e9, 2e9, 201), unit="Hz")
    d.add_value("S21", np.random.default_rng(0).normal(size=(11, 201)), axes=["power", "freq"])
    d.save(tmp_path / "one.lbd")
    no_free_memory(monkeypatch, tmp_path, always_whole=0)
    s = open_quietly(tmp_path / "one.lbd", {"kind": "curve", "values": ["S21"], "x": "freq", "series": "power"})
    assert s.kind == "curve"
    assert not s.summarised and s.ops_info()["names"]


def test_a_map_summarised_for_lack_of_memory_says_so(monkeypatch, tmp_path):
    d = lbd.Dataset(title="map")
    d.add_axis("y", np.linspace(0, 1, 300))
    d.add_axis("x", np.linspace(0, 1, 400))
    d.add_value("z", np.random.default_rng(1).normal(size=(300, 400)), axes=["y", "x"])
    d.save(tmp_path / "map.lbd")
    no_free_memory(monkeypatch, tmp_path, always_whole=0)
    s = open_quietly(tmp_path / "map.lbd", {"kind": "heatmap"})
    assert s.summarised
    notes = s.take_notes()
    assert len(notes) == 1 and "little free memory (0.0 GB free)" in notes[0] and "every cell" in notes[0]
    assert s.take_notes() == []                         # told once
    info = s.ops_info()
    assert info["names"] is None and "Equations need the full data" in info["names_note"]


def test_data_larger_than_the_computer_is_summarised_without_the_note(monkeypatch, tmp_path):
    d = lbd.Dataset(title="map")
    d.add_axis("y", np.linspace(0, 1, 300))
    d.add_axis("x", np.linspace(0, 1, 400))
    d.add_value("z", np.zeros((300, 400)), axes=["y", "x"])
    d.save(tmp_path / "map.lbd")
    no_free_memory(monkeypatch, tmp_path, always_whole=0, total=1 << 20)     # a 1 MB "computer"
    s = open_quietly(tmp_path / "map.lbd", {"kind": "heatmap"})
    assert s.summarised and s.take_notes() == []


@pytest.mark.parametrize("reserve", [None, 0])
def test_the_default_reserve_is_zero(reserve):
    m = Memory(reserve=reserve, system=lambda: (16 * GB, 3 * GB))
    assert m.reserve() == 0 and m.room() == 3 * GB
