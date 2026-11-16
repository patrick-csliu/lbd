"""Operations in the Explore view (operations.py): each against numbers worked out by hand, their
units, the order they run in, a chain that stops with its reason; and through /render, the
picture, its axis label and the cursors' read-outs."""

import json

import numpy as np
import pytest

import lbd
from lbd_viewer import operations as ops
from lbd_viewer.operations import Grid, Quantity


def grid(a, x=None, t=None, unit="V", xunit="s"):
    a = np.asarray(a, dtype=float)
    return Grid(a=a, x=np.arange(a.shape[1], dtype=float) if x is None else np.asarray(x, dtype=float),
                t=None if t is None else np.asarray(t, dtype=float), value=Quantity("v", unit),
                xq=Quantity("time", xunit), tq=Quantity("power", "dBm") if t is not None else None)


def run(g, *steps):
    return ops.run(g, ops.check([{"op": s[0], **(s[1] if len(s) > 1 else {})} for s in steps]))


def test_subtract_the_mean_and_normalize_per_trace():
    g = grid([[1, 2, 3], [10, 10, np.nan]])
    out = run(g, ("subtract_mean",)).grid
    assert out.a[0].tolist() == [-1, 0, 1] and out.a[1, :2].tolist() == [0, 0] and np.isnan(out.a[1, 2])
    assert out.value == Quantity("v − mean", "V") and out.one_to_one
    n = run(g, ("normalize",)).grid
    assert n.a[0] == pytest.approx([-1.2247449, 0, 1.2247449]) and n.value.unit == ""
    assert np.isnan(n.a[1]).all()                          # no spread: nothing to normalize by


def test_the_derivative_uses_the_real_uneven_steps():
    x = np.array([0.0, 1, 3, 6])
    g = grid([2 * x + 1], x=x)
    d = run(g, ("derivative",)).grid
    assert d.a[0] == pytest.approx([2, 2, 2, 2]) and d.value == Quantity("dv/dtime", "")    # another unit: none


def test_smoothing_skips_gaps_and_shrinks_at_the_ends():
    g = grid([[0, 3, np.nan, 3, 6]])
    s = run(g, ("smooth", {"n": 3})).grid
    assert s.a[0, 0] == pytest.approx(1.5)                 # (0 + 3) / 2 at the edge
    assert s.a[0, 1] == pytest.approx(1.5) and np.isnan(s.a[0, 2])   # the gap is skipped, and stays
    assert s.a[0, 3] == pytest.approx(4.5) and s.a[0, 4] == pytest.approx(4.5)


def test_between_traces():
    g = grid([[1, 1], [np.nan, np.nan], [3, 5], [4, 9]], t=[-30, -20, -10, 0])   # trace 2 left out
    assert run(g, ("subtract_first",)).grid.a[3].tolist() == [3, 8]
    prev = run(g, ("subtract_previous",)).grid.a
    assert np.isnan(prev[0]).all() and prev[2].tolist() == [2, 4] and prev[3].tolist() == [1, 4]
    avg = run(g, ("average",)).grid
    assert avg.a.tolist() == [[pytest.approx(8 / 3), 5]] and not avg.one_to_one and avg.labels == ["average of 3 traces"]
    assert run(g, ("std",)).grid.a[0, 0] == pytest.approx(np.std([1, 3, 4]))


def test_across_traces_along_a_maps_vertical_axis_removes_a_background():
    rows = np.array([[0.0, 1, 2]]).T * 10                  # a background that depends on the row
    g = grid(np.tile([5.0, 6, 7], (3, 1)) + rows, t=[0, 1, 2])
    out = run(g, ("subtract_mean", {"along": "traces"})).grid
    assert out.a == pytest.approx(np.full((3, 3), -0.0) + np.array([[-10.0], [0], [10]]))
    out = run(g, ("subtract_mean", {"along": "x"})).grid
    assert out.a == pytest.approx(np.tile([-1.0, 0, 1], (3, 1)))


def test_the_fft_finds_a_sine_and_its_amplitude():
    t = np.arange(1000) * 1e-6                             # 1 µs steps
    g = grid([0.5 + 2 * np.sin(2 * np.pi * 50e3 * t)], x=t)
    f = run(g, ("fft",)).grid
    peak = int(np.argmax(f.a[0, 1:])) + 1
    assert f.x[peak] == pytest.approx(50e3) and f.a[0, peak] == pytest.approx(2, rel=1e-3)
    assert f.a[0, 0] == pytest.approx(0.5) and f.xq == Quantity("Frequency", "") and not f.one_to_one
    uneven = run(grid([[1, 2, 3, 4, 5]], x=[0, 1, 2, 4, 5]), ("fft",))
    assert uneven.applied == 0 and "evenly spaced" in uneven.notes[0]


def test_the_histogram_counts_values():
    h = run(grid([[0, 0, 1, 2, 2, 2]]), ("histogram", {"bins": 3})).grid
    assert h.a.tolist() == [[2, 1, 3]] and h.xq == Quantity("v", "V") and h.value.label == "Counts"


def test_order_matters_and_a_chain_stops_with_its_reason():
    x = np.linspace(0, 1, 50)
    g = grid([x ** 2], x=x)
    a = run(g, ("smooth", {"n": 5}), ("derivative",)).grid.a
    b = run(g, ("derivative",), ("smooth", {"n": 5})).grid.a
    assert not np.allclose(a, b)                            # different results at the ends
    r = run(g, ("subtract_mean",), ("average",), ("derivative",))   # one trace: nothing to average
    assert r.applied == 1 and "several traces" in r.notes[1] and "not applied" in r.notes[2]
    assert r.grid.value.label == "v − mean"                 # the result before the one that can't apply


def test_a_bad_list_is_refused_with_the_choices():
    for bad, match in (([{"op": "integrate"}], "unknown"), ([{"op": "smooth", "n": "five"}], "whole number"),
                       ([{"op": "average", "along": "x"}], "along must be")):
        with pytest.raises(ops.BadOps, match=match):
            ops.check(bad)


def test_units_are_kept_or_left_out():
    assert ops.shown(np.array([2e-3]), Quantity("v", "V"), "paren")[1:] == ("mV", "v (mV)")
    assert ops.shown(np.array([3e-9]), Quantity("dv/dtime", ""), "paren") == (1.0, "", "dv/dtime")


# ---- through the viewer ---------------------------------------------------------------------------

def open_view(client, path, spec=None):
    r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": 640, "height": 420, "dpr": 1})
    r.raise_for_status()
    return r.json()


def render(client, o, settings):
    r = client.post(f"/api/explore/{o['session']}/render", json={"settings": settings})
    assert r.status_code == 200, r.text
    return json.loads(r.headers["X-LBD-Frame"])


@pytest.fixture()
def sweep(data_dir):
    """|S21| in dB of 3 traces over 5 GHz, each a line of slope 2 dB/GHz plus 10 dB per trace."""
    f = np.linspace(4e9, 6e9, 201)
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", np.array([-30.0, -20.0, -10.0]), unit="dBm", label="Power")
    d.add_axis("f", f, unit="Hz", label="Frequency")
    d.add_value("S21", 10 * np.arange(3.0)[:, None] + 2e-9 * (f[None, :] - 4e9), axes=["power", "f"], unit="dB")
    path = data_dir / "sweep_ops.lbd"
    d.save(path)
    return path


SPEC = {"kind": "curve", "x": "f", "series": "power"}


def test_a_derivative_is_drawn_with_its_unit_and_read_with_the_stored_value(client, sweep):
    o = open_view(client, sweep, SPEC)
    meta = render(client, o, {"ops": [{"op": "derivative"}]})
    assert meta["ops"]["notes"] == [None] and meta["ops"]["unit"] == ""
    sess = client.app.state.lbd.explore.get(o["session"])
    assert sess.ax.get_ylabel() == "dS21/dFrequency"                   # the unit changed: none shown
    c = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": [{"x": 5.0, "y": 2.0, "trace": 1}], "xlim": meta["xlim"], "ylim": meta["ylim"],
                          "width": 500, "height": 300}).json()["cursors"][0]
    shown = next(i for i in c["items"] if i["role"] == "y")
    assert shown["value"] == pytest.approx(2e-9) and shown["unit"] == ""          # dB per Hz, as stored
    assert c["stored"]["value"] == pytest.approx(12) and c["stored"]["unit"] == "dB" and c["index"] == {"f": 100, "power": 1}


def test_an_average_of_the_chosen_traces_is_one_curve_without_stored_points(client, sweep):
    o = open_view(client, sweep, SPEC)
    render(client, o, {"select": {"power": [0, 2]}, "ops": [{"op": "average"}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert len(sess.model.lines) == 1 and sess.model.lines[0][0][0] == pytest.approx(10)   # (0 + 20) / 2
    c = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": [{"x": 4.0, "y": 10}], "xlim": [4, 6], "ylim": [0, 20], "width": 500, "height": 300}
                    ).json()["cursors"][0]
    assert "stored" not in c and c["index"] == {}
    r = client.post(f"/api/explore/{o['session']}/save-cut", json={"which": "trace", "index": {}, "trace": 0})
    assert r.status_code == 400 and "turn the operations off" in r.json()["detail"]


def test_operations_off_show_the_stored_data_again(client, sweep):
    o = open_view(client, sweep, SPEC)
    render(client, o, {"ops": [{"op": "subtract_mean"}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert sess.model is not sess.base_model
    meta = render(client, o, {"ops": [{"op": "subtract_mean", "on": False}]})
    assert sess.model is sess.base_model and meta["ops"]["notes"] == ["off"]
    assert render(client, o, {})["ops"]["notes"] == []                 # no operations; the names are there


def test_a_bad_operation_is_a_clear_error(client, sweep):
    o = open_view(client, sweep, SPEC)
    r = client.post(f"/api/explore/{o['session']}/render", json={"settings": {"ops": [{"op": "integrate"}]}})
    assert r.status_code == 400 and "unknown" in r.json()["detail"]


def test_a_maps_background_is_removed_along_its_vertical_axis(client, data_dir):
    rows = np.arange(4.0)[:, None] * 100                  # each row a different offset
    d = lbd.Dataset(title="map")
    d.add_axis("y", np.arange(4.0), unit="A")
    d.add_axis("x", np.arange(5.0), unit="Hz")
    d.add_value("z", rows + np.arange(5.0)[None, :], axes=["y", "x"], unit="V")
    d.save(data_dir / "bg.lbd")
    o = open_view(client, data_dir / "bg.lbd", {"kind": "heatmap", "x": "x", "y": "y"})
    render(client, o, {"ops": [{"op": "subtract_mean", "along": "x"}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert sess.kind == "heatmap" and sess.model.z / sess.model.zf == pytest.approx(np.tile([-2.0, -1, 0, 1, 2], (4, 1)))
    render(client, o, {"ops": [{"op": "fft", "along": "x"}]})
    assert sess.ax.get_xlabel() == "Time" and sess.ops_shown.x_changed               # FFT of Hz: time, no unit


# ---- complex values: delay, rotation, auto-rotate, Calculate; the I/Q histogram ---------------------

@pytest.fixture()
def vna(data_dir):
    """S21 of 2 traces with a 60 ns cable delay and a phase offset of 30°, magnitude 0.5 and 1."""
    f = np.linspace(4e9, 4.1e9, 401)
    s21 = np.array([[0.5], [1.0]]) * np.exp(-2j * np.pi * f[None, :] * 60e-9 + 1j * np.radians(30))
    d = lbd.Dataset(title="vna")
    d.add_axis("power", np.array([-20.0, -10.0]), unit="dBm")
    d.add_axis("f", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "f"])
    path = data_dir / "vna.lbd"
    d.save(path)
    return path


VNA = {"kind": "curve", "x": "f", "series": "power", "complex": "phase_deg"}


def calculate(client, o, what, index, xlim, trace=None):
    r = client.post(f"/api/explore/{o['session']}/calculate", json={"what": what, "index": index, "xlim": xlim, "trace": trace})
    assert r.status_code == 200, r.text
    return r.json()


def test_calculate_finds_the_delay_and_removing_it_flattens_the_phase(client, vna):
    o = open_view(client, vna, VNA)
    render(client, o, {"ops": [{"op": "delay", "tau": 0}]})
    tau = calculate(client, o, "delay", 0, [4.0, 4.1])            # x in plot units (GHz)
    assert tau["value"] == pytest.approx(60e-9, rel=1e-6) and tau["unit"] == "s"
    render(client, o, {"ops": [{"op": "delay", "tau": tau["value"]}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    phase = sess.model.lines[0][0] / sess.model.yf
    assert np.ptp(phase) < 1e-6 and phase[0] == pytest.approx(30, abs=1e-4)   # flat, at the offset
    c = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": [{"x": 4.05, "y": 30, "trace": 1}], "xlim": [4, 4.1], "ylim": [0, 60],
                          "width": 500, "height": 300}).json()["cursors"][0]
    assert "stored" in c                                           # the file's phase, before the correction


def test_calculate_finds_the_rotation_that_puts_the_spread_on_re(client, data_dir):
    rng = np.random.default_rng(0)
    z = (rng.normal(0, 1, 500) + 1j * rng.normal(0, 0.05, 500) + 2) * np.exp(1j * np.radians(40))
    d = lbd.Dataset(title="iq")
    d.add_axis("n", np.arange(500.0))
    d.add_value("v", z, axes="n")
    d.save(data_dir / "iq.lbd")
    o = open_view(client, data_dir / "iq.lbd", {"kind": "curve", "x": "n", "complex": "imag"})
    render(client, o, {"ops": [{"op": "rotation", "phi": 0}]})
    phi = calculate(client, o, "rotation", 0, [0, 500])
    assert phi["value"] == pytest.approx(-40, abs=1) and phi["unit"] == "°"
    render(client, o, {"ops": [{"op": "rotation", "phi": phi["value"]}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert np.std(sess.model.lines[0][0] / sess.model.yf) < 0.1      # the imaginary part: only the narrow spread


def test_auto_rotate_lines_up_each_trace(client, data_dir):
    angles = np.radians([10.0, 70.0, -50.0])
    t = np.linspace(-1, 1, 200)
    z = (t[None, :] + 3) * np.exp(1j * angles[:, None])
    d = lbd.Dataset(title="rot")
    d.add_axis("k", np.arange(3.0))
    d.add_axis("t", t)
    d.add_value("v", z, axes=["k", "t"])
    d.save(data_dir / "rot.lbd")
    o = open_view(client, data_dir / "rot.lbd", {"kind": "curve", "x": "t", "series": "k", "complex": "imag"})
    render(client, o, {"ops": [{"op": "auto_rotate"}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert all(np.max(np.abs(y)) < 1e-9 for y, _ in sess.model.lines)   # every trace on the real axis


def test_the_iq_histogram_turns_curves_into_a_map_of_counts(client, data_dir):
    rng = np.random.default_rng(1)
    shots = np.where(rng.random((4, 2000)) < 0.5, 1 + 1j, -1 - 1j) + 0.1 * (rng.normal(size=(4, 2000)) + 1j * rng.normal(size=(4, 2000)))
    d = lbd.Dataset(title="shots")
    d.add_axis("rep", np.arange(4.0))
    d.add_axis("shot", np.arange(2000.0))
    d.add_value("v", shots, axes=["rep", "shot"], unit="V")
    d.save(data_dir / "shots.lbd")
    o = open_view(client, data_dir / "shots.lbd", {"kind": "curve", "x": "shot", "series": "rep"})
    meta = render(client, o, {"ops": [{"op": "iq_histogram", "bins": 40}, {"op": "derivative"}]})
    sess = client.app.state.lbd.explore.get(o["session"])
    assert sess.kind == "heatmap" and meta["ops"]["notes"][0] is None and "last operation" in meta["ops"]["notes"][1]
    counts = np.nan_to_num(sess.model.z / sess.model.zf)
    assert counts.sum() == 4 * 2000 and sess.ax.get_xlabel().startswith("Re v (I)")
    top = np.unravel_index(np.argsort(counts, axis=None)[-2:], counts.shape)   # the two blobs
    assert {np.sign(sess.model.x[top[1][0]]), np.sign(sess.model.x[top[1][1]])} == {-1.0, 1.0}
    c = client.post(f"/api/explore/{o['session']}/cursors",
                    json={"cursors": [{"x": 1, "y": 1}], "xlim": [-1.5, 1.5], "ylim": [-1.5, 1.5],
                          "width": 400, "height": 400}).json()["cursors"][0]
    assert c["index"] == {} and next(i for i in c["items"] if i["role"] == "z")["label"] == "Counts"
    meta = render(client, o, {"select": {"rep": [0]}, "ops": [{"op": "iq_histogram", "bins": 40}]})
    assert np.nansum(sess.model.z / sess.model.zf) == 2000          # only the chosen trace counted


def test_complex_operations_come_first(client, vna):
    o = open_view(client, vna, VNA)
    r = client.post(f"/api/explore/{o['session']}/render",
                    json={"settings": {"ops": [{"op": "smooth"}, {"op": "delay", "tau": 1e-9}]}})
    assert r.status_code == 400 and "before the operations on the values as shown" in r.json()["detail"]


def test_a_gaussian_smooths_symmetrically_and_skips_gaps():
    step = grid([[0.0] * 10 + [1.0] * 10])
    out = run(step, ("smooth", {"method": "gaussian", "sigma": 2.0})).grid.a[0]
    assert out[9] + out[10] == pytest.approx(1.0) and out[0] == pytest.approx(0) and out[-1] == pytest.approx(1)
    assert np.all(np.diff(out) >= -1e-12)                       # still a rising step
    gap = run(grid([[1.0, 1, np.nan, 1, 1]]), ("smooth", {"method": "gaussian", "sigma": 1.0})).grid.a[0]
    assert np.isnan(gap[2]) and gap[[0, 1, 3, 4]] == pytest.approx([1, 1, 1, 1])
    assert run(step, ("smooth", {"method": "gaussian", "sigma": 2.0})).grid.value == Quantity("v (Gaussian, σ = 2 points)", "V")


def test_a_median_removes_a_spike_the_mean_spreads():
    spike = grid([[0, 0, 0, 9, 0, 0, 0]])
    med = run(spike, ("smooth", {"method": "median", "n": 3})).grid.a[0]
    mean = run(spike, ("smooth", {"method": "mean", "n": 3})).grid.a[0]
    assert med.tolist() == [0] * 7 and mean[2] == pytest.approx(3) and mean[3] == pytest.approx(3)
    even = run(spike, ("smooth", {"method": "median", "n": 4}))
    assert even.applied == 0 and "odd number" in even.notes[0]
    with pytest.raises(ops.BadOps, match="one of mean, gaussian, median"):
        ops.check([{"op": "smooth", "method": "boxcar"}])
