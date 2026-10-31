"""Mock data files with several values, for the Explore view's panels (plan 4) and its tests.

    uv run python viewer/tests/mock_values.py FOLDER [--small]

writes the `.lbd` files into FOLDER. Each is made for a part of the panels: several recorded
values against one axis, 3-D maps with a slider, values over different axes, many values, one
value (nothing changes), single-shot I/Q readout, data points with a shape, and variable sweeps
(axis groups, format 2.0: frequencies chosen per power, a triangle, an adaptive map). The tests use `small=True`: the same
structure with few points. Simulated data, with a fixed random seed, so the files are always the
same.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

import lbd

NAMES = ["6 rabi.lbd", "7 spectroscopy 3d.lbd", "8 mixed axes.lbd", "9 many values.lbd",
         "10 one value.lbd", "11 single shot iq.lbd", "12 tomography.lbd", "13 variable sweep.lbd",
         "14 triangle.lbd", "15 adaptive map.lbd"]


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


MAKERS = dict(zip(NAMES, [rabi, spectroscopy_3d, mixed_axes, many_values, one_value, single_shot_iq, tomography,
                          variable_sweep, triangle, adaptive_map]))


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
