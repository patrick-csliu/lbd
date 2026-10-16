"""Write a few sample .lbd files into examples/data/ (curve, heatmap, complex sweep, I/Q scatter).

    uv run python examples/make_examples.py [OUTDIR]

When a file already exists and has a saved view (e.g. one saved in LBD Viewer), that view is
kept: the script rewrites the data but never throws away a view someone chose.
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np

import lbd

DEFAULT_OUT = Path(__file__).resolve().parent / "data"


def _save(d: "lbd.Dataset", path: Path, **kwargs) -> None:
    """Save `d`, keeping the saved view of an existing file at `path`."""
    if path.exists():
        old = lbd.info(path)
        if old.plot is not None or old.style is not None or old.style_name is not None:
            d.plot, d.style, d.style_name = old.plot, old.style, old.style_name
            print(f"kept the saved view of {path.name}")
    d.save(path, **kwargs)


def main(out: Optional[Path] = None) -> Path:
    out = Path(out) if out is not None else DEFAULT_OUT
    (out / "2026" / "resonator").mkdir(parents=True, exist_ok=True)

    # 1-D curves: two traces against one axis
    t = np.linspace(0, 10e-6, 501)
    d = lbd.Dataset(title="Rabi oscillation", description="Simulated, two drive amplitudes")
    d.add_axis("t", t, unit="s", label="Pulse length")
    d.add_value("P1_a", 0.5 * (1 - np.cos(2 * np.pi * 0.8e6 * t) * np.exp(-t / 6e-6)), axes="t", label="P(1), amp 0.2")
    d.add_value("P1_b", 0.5 * (1 - np.cos(2 * np.pi * 1.6e6 * t) * np.exp(-t / 6e-6)), axes="t", label="P(1), amp 0.4")
    d.meta = {"qubit": "Q1", "T_mK": 12, "amplitudes": [0.2, 0.4]}
    d.plot = {"kind": "curve", "values": ["P1_a", "P1_b"]}
    _save(d, out / "rabi.lbd")

    # 2-D real heat map
    x = np.linspace(-1, 1, 121)
    y = np.linspace(-1, 1, 81)
    X, Y = np.meshgrid(x, y)
    d = lbd.Dataset(title="Temperature map")
    d.add_axis("y", y * 5, unit="mm", label="y")
    d.add_axis("x", x * 5, unit="mm", label="x")
    d.add_value("temperature", 300 + 40 * np.exp(-(X**2 + Y**2) / 0.2), axes=["y", "x"], unit="K",
                label="Temperature")
    _save(d, out / "temperature_map.lbd")

    # Complex 2-D: resonator power sweep
    f = np.linspace(6.99e9, 7.01e9, 401)
    p = np.arange(-60, 1, 5.0)
    f0 = 7.0e9 - 0.5e6 * (p + 60) / 60
    kappa = 0.6e6
    s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - f0[:, None]) / kappa)
    d = lbd.Dataset(title="Resonator power sweep", description="Simulated notch resonator")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "freq"], label="S21")
    d.meta = {"sample": "R7", "T_mK": 12, "vna": {"ifbw_Hz": 1000.0, "averages": 4}}
    d.plot = {"kind": "heatmap", "values": ["S21"], "complex": "db"}
    _save(d, out / "2026" / "resonator" / "power_sweep.lbd", compression="gzip")

    # Complex scatter data: qubit readout I/Q blobs for the two prepared states
    rng = np.random.default_rng(7)
    shots = 1500
    centers = np.array([0.6 + 0.2j, -0.1 + 0.55j])
    iq = centers[:, None] + 0.12 * (rng.normal(size=(2, shots)) + 1j * rng.normal(size=(2, shots)))
    d = lbd.Dataset(title="Readout I/Q", description="Simulated single-shot readout for |0> and |1>")
    d.add_axis("prep", [0.0, 1.0], label="Prepared state")
    d.add_axis("shot", np.arange(shots, dtype=float), label="Shot")
    d.add_value("IQ", iq * 1e-3, axes=["prep", "shot"], unit="V", label="Readout")
    d.plot = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "prep"}
    _save(d, out / "2026" / "readout_iq.lbd", compression="gzip")
    print(f"wrote examples to {out}")

    # A style file and a figure made with lbd.plot (needs lbd[plot])
    try:
        import matplotlib

        matplotlib.use("Agg")
        import lbd.plot as lp
    except ImportError:
        print("lbd.plot not installed; skipping the style file and figure examples")
        return out
    style = lp.load_style({
        "name": "thesis",
        "description": "Example: thesis figures, serif text, 120 mm wide",
        "figure": {"width_mm": 120, "height_mm": 80, "dpi": 300,
                   "font": {"family": "DejaVu Serif", "size_pt": 10, "math": "dejavuserif"},
                   "axes": {"axis": {"label": {"unit_format": "bracket"}}}},
        "quantities": {"S21.db": {"vmin": -15, "vmax": 0}},
    })
    style.save(out / "thesis.lbd.json")
    (out / "figures").mkdir(exist_ok=True)
    sweep = lbd.load(out / "2026" / "resonator" / "power_sweep.lbd")
    fig = lp.plot(sweep, kind="heatmap", values="S21", complex="db", style=style)
    lp.save(fig, out / "figures" / "power_sweep_thesis.png", style=style, title=sweep.title)
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
