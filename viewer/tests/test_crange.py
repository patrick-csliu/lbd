"""A map's colour range from every slider position (plan 11, view setting `crange`): the same
colours at every position, worked out in the background, with operations and complex modes."""

import time

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import render as rnd
from lbd_viewer import crange
from lbd_viewer.explore import ExploreSession


@pytest.fixture(autouse=True)
def fresh():
    crange.forget()
    yield
    crange.forget()


@pytest.fixture
def stack(tmp_path):
    """Three slices along `power`; slice k holds k*10 … k*10 + 5 (so each has its own range)."""
    d = lbd.Dataset(title="Stack")
    d.add_axis("power", [-30.0, -20.0, -10.0], unit="dBm")
    d.add_axis("flux", np.linspace(-0.5, 0.5, 4))
    d.add_axis("f", np.linspace(5e9, 6e9, 6), unit="Hz")
    z = np.arange(3)[:, None, None] * 10.0 + np.linspace(0, 5, 24).reshape(4, 6)[None]
    d.add_value("S21", z * np.exp(0.3j), axes=["power", "flux", "f"], unit="V")
    p = tmp_path / "stack.lbd"
    d.save(p)
    return p


def session(path, index=0):
    spec = {"kind": "heatmap", "values": ["S21"], "x": "f", "y": "flux", "index": {"power": index}, "complex": "abs"}
    return ExploreSession(path, "v1", spec, lp.load_style(), 300, 200, 1)


def norm_of(s):
    n = s.image.norm
    return n.vmin / s.model.zf, n.vmax / s.model.zf


def wait(s, settings):
    for _ in range(1200):                                            # up to 60 s (a busy computer)
        s.apply(settings)
        if not (s.crange_state() or {}).get("state"):
            return
        time.sleep(0.05)
    raise AssertionError(f"the range of every slice never came: {s.crange_state()}")


def test_every_slice_has_the_same_colours_with_all(stack):
    s = session(stack, 0)
    s.apply({})
    assert norm_of(s) == pytest.approx((0, 5))                      # this slice's own (as before)
    wait(s, {"crange": "all"})
    assert norm_of(s) == pytest.approx((0, 25))
    assert s.crange_state() == {"from": "all"}
    s.set_spec({**{k: v for k, v in s.spec.items() if k in rnd.SPEC_KEYS}, "index": {"power": 2}})
    s.settings = {}
    s.apply({"crange": "all"})                                       # kept: no new work
    assert norm_of(s) == pytest.approx((0, 25))
    s.settings = {}
    s.apply({"crange": "slice"})
    assert norm_of(s) == pytest.approx((20, 25))


def test_while_worked_out_the_slice_is_used_and_the_page_is_told(stack, monkeypatch):
    gate = []
    real = crange._work

    def slow(*a):
        while not gate:
            time.sleep(0.01)
        real(*a)

    monkeypatch.setattr(crange, "_work", slow)
    s = session(stack, 1)
    s.apply({"crange": "all"})
    assert s.crange_state()["state"] == "working" and s.crange_state()["slices"] == 3
    assert norm_of(s) == pytest.approx((10, 15))
    gate.append(1)
    wait(s, {"crange": "all"})
    assert norm_of(s) == pytest.approx((0, 25))


def test_typed_limits_win(stack):
    s = session(stack, 0)
    wait(s, {"crange": "all"})
    s.apply({"crange": "all", "clim": [1.0, 2.0]})
    assert (s.image.norm.vmin, s.image.norm.vmax) == (1.0, 2.0)
    s.apply({"crange": "all", "clim": [None, 2.0]})                  # one end typed: the other from every slice
    assert s.image.norm.vmin / s.model.zf == pytest.approx(0) and s.image.norm.vmax == 2.0


def test_operations_run_on_every_slice(stack):
    """The user's choice: with operations, the range of every slice after them."""
    s = session(stack, 0)
    settings = {"crange": "all", "ops": [{"op": "subtract_mean", "along": "x"}]}
    wait(s, settings)
    lo, hi = norm_of(s)
    # each row minus its mean: about ±0.54 in every slice (the slices only differ by a constant)
    assert lo == pytest.approx(-hi, rel=1e-6) and hi == pytest.approx(5 / 23 * 2.5)


def test_a_map_without_slider_has_no_choice(tmp_path):
    d = lbd.Dataset(title="Flat")
    d.add_axis("x", np.arange(4.0))
    d.add_axis("y", np.arange(3.0))
    d.add_value("z", np.arange(12.0).reshape(3, 4), axes=["y", "x"])
    d.save(tmp_path / "flat.lbd")
    s = ExploreSession(tmp_path / "flat.lbd", "v", {"kind": "heatmap"}, lp.load_style(), 300, 200, 1)
    s.apply({"crange": "all"})
    assert s.crange_state() is None and norm_of(s) == pytest.approx((0, 11))


def test_an_unknown_choice_is_refused(stack):
    from lbd_viewer.explore import ExploreError

    with pytest.raises(ExploreError, match="crange"):
        session(stack).apply({"crange": "everything"})


def test_the_colour_bar_keeps_its_unit_prefix_across_slices(tmp_path):
    """Slices of mV and of V: with All slices the colour bar's prefix comes from every slice, so it
    doesn't jump between mV and V while the slider moves."""
    d = lbd.Dataset(title="Scales")
    d.add_axis("power", [0.0, 1.0])
    d.add_axis("y", np.arange(3.0))
    d.add_axis("x", np.arange(4.0))
    d.add_value("v", np.stack([np.full((3, 4), 2e-3), np.full((3, 4), 2.0)]) + np.arange(12).reshape(3, 4) * 1e-4,
                axes=["power", "y", "x"], unit="V")
    d.save(tmp_path / "scales.lbd")
    spec = {"kind": "heatmap", "values": ["v"], "x": "x", "y": "y", "index": {"power": 0}}
    s = ExploreSession(tmp_path / "scales.lbd", "v", spec, lp.load_style(), 300, 200, 1)
    s.apply({"crange": "slice"})
    assert s.model.zf == 1000                                         # this slice alone: mV
    wait(s, {"crange": "all"})
    zf = s.model.zf
    s.set_spec({**spec, "index": {"power": 1}})
    s.settings = {}
    s.apply({"crange": "all"})
    assert s.model.zf == zf == 1                                       # V at both steps
