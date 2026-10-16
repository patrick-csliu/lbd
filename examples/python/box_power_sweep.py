"""A box around a region, saved with the file

A power sweep of a resonator: above about −20 dBm the resonance moves. A box and a label mark
that region. The view, its style and the box are stored in the .lbd file, so the file opens the
same way in LBD Viewer and with lp.plot(path).

Figure: a heat map with a rectangle and a label.
Code: store the plot with the file (lbd.set_plot); redraw it from the file; export PDF, SVG and PNG.
Tasks: Save data to a file; Mark points, lines and regions (annotations); Store the plot with the file (saved view); Plot a file like the viewer; Export PDF, SVG and PNG; Fix a unit prefix (MHz, mV, …)
Uses: lbd.Dataset, lbd.set_plot, lbd.load, lbd.plot.plot, lbd.plot.save
"""

import numpy as np

import lbd
import lbd.plot as lp

# ---- mock data for the example: |S21| of a resonator against power and frequency ----
power = np.linspace(-60, 0, 31)                                # dBm
freq = np.linspace(6.990e9, 7.010e9, 401)                      # Hz
f0 = 7.0e9 - 2e6 * np.clip((power[:, None] + 20) / 20, 0, None) ** 2
s21 = 1 - 0.9 / (1 + 2j * (freq - f0) / 1e6)

d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", power, unit="dBm", label="Power")
d.add_axis("freq", freq, unit="Hz", label="Frequency")
d.add_value("S21", s21, axes=["power", "freq"], label="$S_{21}$")
d.save("power_sweep.lbd")

# ---- store how the file should be plotted: what to draw, the style, and the annotations ----
lbd.set_plot(
    "power_sweep.lbd",
    spec={
        "kind": "heatmap", "values": ["S21"], "complex": "db",
        "annotations": [
            # Rectangle((x, y), width, height): from 6997.5 MHz and -21 dBm, 3 MHz wide, 22 dB high
            {"patch": "Rectangle", "args": [[6997.5, -21], 3.0, 22],
             "kwargs": {"fill": False, "ec": "white", "lw": 1.0}},
            {"method": "text", "args": [6997.6, -24, "frequency shift"],
             "kwargs": {"color": "white", "va": "top"}},
        ],
    },
    style={"quantities": {"freq": {"prefix": "M"}}},           # MHz, so the box stays in place
)

# ---- anyone can now redraw it from the file alone ----
fig = lp.plot("power_sweep.lbd")
for ext in ("pdf", "svg", "png"):                              # exact size, fonts embedded
    lp.save(fig, f"box_power_sweep.{ext}")

d = lbd.load("power_sweep.lbd")
print("saved view:", d.plot["kind"], d.plot["values"], f"with {len(d.plot['annotations'])} annotations")
print("saved style:", d.style)
print("written with matplotlib", d.matplotlib)
