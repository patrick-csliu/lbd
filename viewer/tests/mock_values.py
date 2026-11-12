"""Mock data files with several values, for the Explore view's panels (plan 4) and its tests.

    uv run python viewer/tests/mock_values.py FOLDER [--small]

writes the `.lbd` files into FOLDER. Each is made for a part of the panels: several recorded
values against one axis, 3-D maps with a slider, values over different axes, many values, one
value (nothing changes), single-shot I/Q readout, data points with a shape, and variable sweeps
(axis groups, format 2.0: frequencies chosen per power, a triangle, an adaptive map), and grids
with uneven steps (a map uneven on both axes, a map on a log-spaced axis, a curve with uneven x).
The tests use `small=True`: the same structure with few points. Simulated data, with a fixed random seed, so the files are always the
same.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

import lbd

NAMES = ["6 rabi.lbd", "7 spectroscopy 3d.lbd", "8 mixed axes.lbd", "9 many values.lbd",
         "10 one value.lbd", "11 single shot iq.lbd", "12 tomography.lbd", "13 variable sweep.lbd",
         "14 triangle.lbd", "15 adaptive map.lbd", "16 density matrix.lbd", "17 assignment matrix.lbd",
         "18 bars.lbd", "19 curved grid.lbd", "20 uneven map.lbd", "21 log axis map.lbd", "22 uneven curve.lbd"]


def rabi(small: bool) -> lbd.Dataset:
    """A Rabi measurement: one swept axis, four recorded values in three units (V, none, rad)."""
    rng = np.random.default_rng(6)
    a = np.linspace(0, 0.5, 21 if small else 101)
    p = 0.5 * (1 - np.cos(np.pi * a / 0.2) * np.exp(-a / 0.6))          # excited population
    i = 0.2e-3 + 1.0e-3 * p + rng.normal(0, 20e-6, a.size)              # V, about a mV
    q = 30e-6 - 20e-6 * p + rng.normal(0, 1e-6, a.size)                 # V, about 30 µV
    d = lbd.Dataset(title="Rabi amplitude", description="Mock data: I, Q, population and phase vs drive amplitude")
    d.add_axis("amplitude", a, unit="V", label="Drive amplitude")
    d.add_value("I", i, axes="amplitude", unit="V", label="Digitizer I")
    d.add_value("Q", q, axes="amplitude", unit="V", label="Digitizer Q")
    d.add_value("population", np.clip(p + rng.normal(0, 0.02, a.size), 0, 1), axes="amplitude", label="Population")
    d.add_value("phase", np.arctan2(q, i), axes="amplitude", unit="rad", label="Phase")
    return d


def spectroscopy_3d(small: bool) -> lbd.Dataset:
    """Qubit spectroscopy against flux and frequency, at three drive powers: two 3-D values."""
    rng = np.random.default_rng(7)
    flux = np.linspace(-0.5, 0.5, 9 if small else 41)
    power = np.array([-30.0, -20.0, -10.0])
    f = np.linspace(4.5e9, 5.5e9, 31 if small else 201)
    fq = 4.6e9 + 0.8e9 * np.sqrt(np.abs(np.cos(np.pi * flux)))         # the qubit's frequency
    width = 5e6 * 10 ** ((power + 30) / 20)                             # broader at higher power
    det = (f[None, None, :] - fq[None, :, None]) / width[:, None, None]
    resp = 1 / (1 + 1j * det)
    noise = rng.normal(0, 0.02, resp.shape) + 1j * rng.normal(0, 0.02, resp.shape)
    z = 1e-3 * (0.2 + 0.8 * resp + noise)
    d = lbd.Dataset(title="Qubit spectroscopy vs flux and power", description="Mock data: two 3-D values")
    d.add_axis("qubit_power", power, unit="dBm", label="Qubit power")
    d.add_axis("flux", flux, unit="Φ0", label="Flux")
    d.add_axis("frequency", f, unit="Hz", label="Frequency")
    d.add_value("amplitude", np.abs(z), axes=["qubit_power", "flux", "frequency"], unit="V", label="Amplitude")
    d.add_value("phase", np.angle(z), axes=["qubit_power", "flux", "frequency"], unit="rad", label="Phase")
    d.plot = {"kind": "heatmap", "values": ["amplitude"], "x": "frequency", "y": "flux"}
    return d


def mixed_axes(small: bool) -> lbd.Dataset:
    """A resonator power sweep with its fit results: values over different axes, and a single number."""
    rng = np.random.default_rng(8)
    p = np.linspace(-60, 0, 6 if small else 31)
    f = np.linspace(6.99e9, 7.01e9, 41 if small else 401)
    f0 = 7.0e9 - 2e6 * 10 ** (p / 20)                                   # shifts down at high power
    qi = 2e5 / (1 + 10 ** ((p + 30) / 20))
    kappa = f0 / qi + 0.2e6
    s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - f0[:, None]) / kappa[:, None])
    s21 = s21 * np.exp(-2j * np.pi * f[None, :] * 50e-9)
    s21 += rng.normal(0, 0.01, s21.shape) + 1j * rng.normal(0, 0.01, s21.shape)
    ref = np.exp(-2j * np.pi * f * 50e-9) * (1 + rng.normal(0, 0.005, f.size))
    d = lbd.Dataset(title="Resonator power sweep with fits", description="Mock data: values over different axes")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("frequency", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "frequency"], label="S21")
    d.add_value("S21_ref", ref, axes="frequency", label="S21 reference")
    d.add_value("f0", f0, axes="power", unit="Hz", label="Resonance frequency")
    d.add_value("Q_i", qi, axes="power", label="Internal Q")
    d.add_value("temperature", 0.012, unit="K", label="Mixing chamber temperature")
    return d


def many_values(small: bool) -> lbd.Dataset:
    """A fridge log: eight values against time, in four units (K, mbar, W, none)."""
    rng = np.random.default_rng(9)
    t = np.linspace(0, 3600 * 10, 50 if small else 2000)
    cool = np.exp(-t / 9000)
    d = lbd.Dataset(title="Fridge log", description="Mock data: many values against time")
    d.add_axis("time", t, unit="s", label="Time")
    for name, base, top in (("T_50K", 45, 300), ("T_4K", 3.2, 300), ("T_still", 0.8, 300), ("T_mxc", 0.012, 300)):
        d.add_value(name, base + (top - base) * cool * (1 + rng.normal(0, 0.002, t.size)), axes="time", unit="K",
                    label=name.replace("_", " "))
    d.add_value("P_main", 1e-6 + 1e3 * cool ** 3, axes="time", unit="mbar", label="Main pressure")
    d.add_value("P_still", 1e-3 + 0.5 * cool, axes="time", unit="mbar", label="Still pressure")
    d.add_value("heater", np.where(t > 20000, 2e-3, 0.0), axes="time", unit="W", label="Still heater")
    d.add_value("flow", 40 * (1 - cool) + rng.normal(0, 0.5, t.size), axes="time", label="Flow")
    return d


def one_value(small: bool) -> lbd.Dataset:
    """One value: Explore shows it as it did before panels."""
    p = np.linspace(-60, 0, 3 if small else 11)
    f = np.linspace(6.99e9, 7.01e9, 21 if small else 201)
    s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 1e6) * np.ones((p.size, 1))
    d = lbd.Dataset(title="One value")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("frequency", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "frequency"], label="S21")
    d.plot = {"kind": "curve", "x": "frequency", "series": "power", "complex": "db"}
    return d


def single_shot_iq(small: bool) -> lbd.Dataset:
    """Single-shot readout: shots of I/Q for the qubit prepared in ground (0) and excited (1), at
    five readout powers. The two blobs separate more at higher power; a few excited shots have
    decayed to ground before the readout."""
    rng = np.random.default_rng(11)
    power = np.linspace(-40, -20, 2 if small else 5)
    shots = 200 if small else 5000
    amp = 10 ** ((power + 20) / 20)                                     # relative readout amplitude
    ground, excited = np.array([-0.5, -0.2]), np.array([0.4, 0.3])      # mV at the highest power
    sigma = 0.15
    iq = np.empty((power.size, 2, shots), dtype=complex)
    fidelity = np.empty(power.size)
    for k, a in enumerate(amp):
        g, e = ground * a, excited * a
        centre = np.stack([np.tile(g, (shots, 1)), np.tile(e, (shots, 1))])
        decayed = rng.random(shots) < 0.05                              # T1 during the readout
        centre[1, decayed] = g
        pts = centre + rng.normal(0, sigma, centre.shape)
        iq[k] = (pts[..., 0] + 1j * pts[..., 1]) * 1e-3
        # assigned to the nearer centre (the line halfway between them)
        mid, axis = (g + e) / 2, (e - g) / np.linalg.norm(e - g)
        excited_called = ((pts - mid) @ axis) > 0
        fidelity[k] = 1 - (excited_called[0].mean() + (1 - excited_called[1].mean())) / 2
    d = lbd.Dataset(title="Single-shot readout", description="Mock data: I/Q shots, ground (0) and excited (1)")
    d.add_axis("readout_power", power, unit="dBm", label="Readout power")
    d.add_axis("state", [0.0, 1.0], label="Prepared state", elements=["ground", "excited"])
    d.add_axis("shot", np.arange(float(shots)), label="Shot")
    d.add_value("IQ", iq, axes=["readout_power", "state", "shot"], unit="V", label="I/Q")
    d.add_value("I", iq.real, axes=["readout_power", "state", "shot"], unit="V", label="I")
    d.add_value("Q", iq.imag, axes=["readout_power", "state", "shot"], unit="V", label="Q")
    d.add_value("fidelity", fidelity, axes="readout_power", label="Assignment fidelity")
    d.add_value("amplitude", 0.05, unit="V", label="Readout amplitude")
    return d


def tomography(small: bool) -> lbd.Dataset:
    """State tomography against drive amplitude (format 1.2): each data point is a Bloch vector
    (x, y, z) and a 2×2 I/Q covariance matrix."""
    rng = np.random.default_rng(12)
    amp = np.linspace(0, 0.5, 6 if small else 41)
    theta = np.pi * amp / 0.25                                          # a π pulse at 0.25 V
    bloch = np.stack([np.sin(theta), 0.02 * rng.normal(size=amp.size), np.cos(theta)], axis=1)
    bloch *= np.exp(-amp / 2)[:, None]                                  # a little decay
    cov = np.empty((amp.size, 2, 2))
    for k, a in enumerate(amp):
        sii, sqq, siq = 1 + 0.2 * a, 1 - 0.1 * a, 0.3 * np.sin(theta[k])
        cov[k] = np.array([[sii, siq], [siq, sqq]]) * 1e-8
    d = lbd.Dataset(title="Tomography", description="Mock data: a Bloch vector and an I/Q covariance per amplitude")
    d.add_axis("amp", amp, unit="V", label="Drive amplitude")
    d.add_value("bloch", bloch, axes="amp", shape=(3,), elements=["x", "y", "z"], label="Bloch vector")
    d.add_value("cov", cov, axes="amp", shape=(2, 2), elements=[["I", "Q"], ["I", "Q"]], unit="V^2",
                label="Covariance")
    return d


def variable_sweep(small: bool) -> lbd.Dataset:
    """A resonator measured around its resonance (format 2.0): for each power, the frequencies
    are chosen around where the resonance is at that power (a window that moves, with more
    points at low power); Q is fitted once per power."""
    rng = np.random.default_rng(13)
    powers = np.linspace(-60, 0, 5 if small else 21)
    d = lbd.Dataset(title="Variable sweep", description="Mock data: frequencies chosen per power (an axis group)")
    d.add_group("scan")
    d.add_axis("power", group="scan", unit="dBm", label="Power")
    d.add_axis("freq", group="scan", unit="Hz", label="Frequency")
    d.add_value("S21", axes=["power", "freq"], dtype="complex128")
    d.add_value("Q", axes="power", label="Quality factor")
    for p in powers:
        f0 = 7e9 - 2e6 * 10 ** (p / 20)                                  # the resonance moves down at high power
        n = (6 if small else 40) + int(-p / 10)                          # more points at low power
        f = np.linspace(f0 - 3e6, f0 + 3e6, n)
        s21 = 1 - 0.8 / (1 + 2j * (f - f0) / 0.6e6) + 0.01 * rng.normal(size=n)
        d.write(power=p, freq=f, S21=s21)
        d.write(power=p, Q=1e4 * (1 + 0.1 * rng.normal()))
    return d


def triangle(small: bool) -> lbd.Dataset:
    """A triangle (format 2.0): A = 1 … n, and for each A, B = 1 … A."""
    n = 5 if small else 40
    d = lbd.Dataset(title="Triangle", description="Mock data: B = 1 … A (an axis group)")
    d.add_group("tri")
    d.add_axis("A", group="tri")
    d.add_axis("B", group="tri")
    d.add_value("S", axes=["A", "B"])
    for a in range(1, n + 1):
        b = np.arange(1, a + 1)
        d.write(A=a, B=b, S=np.sin(a / 5) * np.cos(b / 5))
    return d


def adaptive_map(small: bool) -> lbd.Dataset:
    """Points placed anywhere in a plane (format 2.0): adaptive sampling, denser near a peak."""
    rng = np.random.default_rng(15)
    n = 30 if small else 600
    x = np.round(np.concatenate([rng.uniform(-1, 1, n // 2), rng.normal(0.3, 0.1, n - n // 2)]), 4)
    y = np.round(np.concatenate([rng.uniform(-1, 1, n // 2), rng.normal(-0.2, 0.1, n - n // 2)]), 4)
    d = lbd.Dataset(title="Adaptive map", description="Mock data: points anywhere (an axis group)")
    d.add_group("xy")
    d.add_axis("x", group="xy", unit="V")
    d.add_axis("y", group="xy", unit="V")
    d.add_value("z", axes=["x", "y"])
    d.write(x=x, y=y, z=np.exp(-((x - 0.3) ** 2 + (y + 0.2) ** 2) / 0.05))
    return d


def density_matrix(small: bool) -> lbd.Dataset:
    """A complex 4 × 4 density matrix per drive amplitude: rows and columns named by the basis states."""
    amps = np.linspace(0, 1, 3 if small else 11)
    basis = ["00", "01", "10", "11"]
    rho = np.zeros((amps.size, 4, 4), dtype=complex)
    for k, a in enumerate(amps):
        psi = np.array([np.cos(a * np.pi / 4), 0, 0, np.sin(a * np.pi / 4) * np.exp(0.4j)])
        rho[k] = 0.95 * np.outer(psi, psi.conj()) + 0.05 * np.eye(4) / 4
    d = lbd.Dataset(title="Density matrix", description="Mock data: a matrix per step, complex, with named rows and columns")
    d.add_axis("amp", amps, unit="V", label="Drive amplitude")
    d.add_axis("row", np.arange(4.0), label="State", elements=basis)
    d.add_axis("col", np.arange(4.0), label="State", elements=basis)
    d.add_value("rho", rho, axes=["amp", "row", "col"], label="ρ")
    return d


def assignment_matrix(small: bool) -> lbd.Dataset:
    """Prepared against measured state: real, each row sums to 1."""
    states = ["ground", "excited", "second"]
    m = np.array([[0.97, 0.025, 0.005], [0.06, 0.92, 0.02], [0.03, 0.09, 0.88]])
    d = lbd.Dataset(title="Assignment matrix", description="Mock data: prepared against measured state")
    d.add_axis("prepared", np.arange(3.0), label="Prepared", elements=states)
    d.add_axis("measured", np.arange(3.0), label="Measured", elements=states)
    d.add_value("probability", m, axes=["prepared", "measured"], label="Probability")
    return d


def bars(small: bool) -> lbd.Dataset:
    """Few named positions: a value and two more on them, and single numbers."""
    states = ["ground", "excited", "second"]
    d = lbd.Dataset(title="Bars", description="Mock data: values on named positions, and single numbers")
    d.add_axis("state", np.arange(3.0), label="State", elements=states)
    d.add_value("population", [0.71, 0.24, 0.05], axes="state", label="Population")
    d.add_value("error", [0.02, 0.03, 0.01], axes="state", label="Error")
    d.add_value("lifetime", [40e-6, 22e-6, 9e-6], axes="state", unit="s", label="Lifetime")
    d.add_value("fidelity", 0.982, label="Fidelity")
    d.add_value("visibility", 0.91, label="Visibility")
    return d


def curved_grid(small: bool) -> lbd.Dataset:
    """A group with the same number of points in every row, moving from row to row: a bent grid."""
    rows = np.linspace(0, 1, 6 if small else 20)
    n = 5 if small else 30
    d = lbd.Dataset(title="Curved grid", description="Mock data: every row has its own x, the same number of them")
    d.add_group("grid")
    d.add_axis("y", group="grid", unit="V", label="Gate")
    d.add_axis("x", group="grid", unit="V", label="Bias")
    d.add_value("g", axes=["y", "x"], label="Conductance")
    for y in rows:
        x = np.linspace(-1, 1, n) + 0.5 * y ** 2
        d.write(y=y, x=x, g=np.exp(-((x - y) / 0.4) ** 2))
    return d


def uneven_map(small: bool) -> lbd.Dataset:
    """A map whose x and y steps both grow: cells get wider to the right and taller to the top,
    each edge halfway between two stored values. value = column + 10 x row, so a cell's value
    says where it is."""
    x = np.array([0.0, 0.1, 0.3, 0.7, 1.5, 3.1] if small else [0.0, 0.1, 0.3, 0.7, 1.5, 3.1, 6.3, 12.7])
    y = np.array([0.0, 1, 3, 7] if small else [0.0, 1, 3, 7, 15, 31])
    d = lbd.Dataset(title="Uneven map", description="Mock data: a map with uneven steps on both axes")
    d.add_axis("y", y, unit="V", label="Gate")
    d.add_axis("x", x, unit="V", label="Bias")
    d.add_value("value", np.arange(float(x.size))[None, :] + 10 * np.arange(float(y.size))[:, None], axes=["y", "x"])
    d.plot = {"kind": "heatmap", "x": "x", "y": "y"}
    return d


def log_axis_map(small: bool) -> lbd.Dataset:
    """A map against a log-spaced axis (six decades, ten points per decade; two when small) and an even one,
    saved with a log x scale, on which its cells have the same width."""
    f = np.logspace(1, 7, 13 if small else 61)
    a = np.linspace(0, 1, 5 if small else 21)
    roll = 1 / (1 + (f[None, :] / (1e3 * 10 ** (3 * a[:, None]))) ** 2)     # a corner that moves up with a
    d = lbd.Dataset(title="Log axis map", description="Mock data: a map against a log-spaced axis")
    d.add_axis("a", a, label="Setting")
    d.add_axis("f", f, unit="Hz", label="Frequency")
    d.add_value("gain", 10 * np.log10(roll), axes=["a", "f"], unit="dB", label="Gain")
    d.plot = {"kind": "heatmap", "x": "f", "y": "a", "x_scale": "log"}
    return d


def uneven_curve(small: bool) -> lbd.Dataset:
    """A curve whose points are dense near a peak and sparse away from it (uneven x)."""
    rng = np.random.default_rng(22)
    u = np.linspace(-1, 1, 21 if small else 201)
    x = 0.5 + 0.5 * u ** 3                                                    # dense around 0.5
    d = lbd.Dataset(title="Uneven curve", description="Mock data: a curve with uneven x steps")
    d.add_axis("x", x, unit="V", label="Bias")
    d.add_value("signal", 1 / (1 + ((x - 0.5) / 0.02) ** 2) + rng.normal(0, 0.01, x.size), axes="x", label="Signal")
    return d


MAKERS = dict(zip(NAMES, [rabi, spectroscopy_3d, mixed_axes, many_values, one_value, single_shot_iq, tomography,
                          variable_sweep, triangle, adaptive_map, density_matrix, assignment_matrix, bars, curved_grid,
                          uneven_map, log_axis_map, uneven_curve]))


def write_all(folder: Path, small: bool = False) -> List[Path]:
    """Write every mock file into `folder`; returns their paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, make in MAKERS.items():
        make(small).save(folder / name)
        out.append(folder / name)
    return out


def old_record() -> Dict[str, Any]:
    """An Explore view remembered by LBD 1.3.0-dev before panels (one plot per file): the shape
    that must still open, upgraded to one panel."""
    return {
        "spec": {"values": ["S21"], "kind": "curve", "x": "frequency", "series": "power", "complex": "db"},
        "settings": {"yscale": "linear", "ops": [{"op": "subtract_mean", "on": True}]},
        "stat": "max",
        "view": None,
        "cursors": {"type": "cross", "at": [], "active": 0, "cuts": True, "on": True},
        "listOpen": True,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in write_all(Path(sys.argv[1]), small="--small" in sys.argv[2:]):
        print(p)
