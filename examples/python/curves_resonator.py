"""Curves: a resonator measured at several powers

Save a measurement together with its settings, read it back, and plot one curve per drive power.

Figure: |S21| in dB against frequency, one curve per power.
Code: save data and metadata (instrument settings) in an .lbd file, read the header back, plot curves.
Tasks: Save data to a file; Record measurement settings (metadata); Read a file back (all of it, or only the header); Plot a file like the viewer; Fix a unit prefix (MHz, mV, …); Override the style for one figure
Uses: lbd.Dataset, lbd.info, lbd.load, lbd.plot.plot, lbd.plot.save
"""

import numpy as np

import lbd
import lbd.plot as lp

# ---- mock data for the example: S21(power, freq) of a resonator ----
power = np.arange(-60.0, 1.0, 20.0)                     # dBm
freq = np.linspace(6.984e9, 7.006e9, 441)               # Hz: store base units, prefixes come later
f0 = 7.0e9 - 2e6 * ((power[:, None] + 60) / 60) ** 2    # the resonance shifts at high power
s21 = 1 - 0.9 / (1 + 2j * (freq - f0) / 1e6)

# ---- save the data ----
d = lbd.Dataset(title="Resonator R7 power sweep")
d.add_axis("power", power, unit="dBm", label="Power")
d.add_axis("freq", freq, unit="Hz", label="Frequency")
d.add_value("S21", s21, axes=["power", "freq"], label="$S_{21}$")   # complex data is fine

# Measurement settings go into meta: numbers, text, True/False, lists, and nested groups.
d.meta["sample"] = "R7"
d.meta["T_mK"] = 12
d.meta["calibrated"] = True
d.meta["vna"] = {"model": "ZNB20", "ifbw_Hz": 1000.0, "averages": 4, "ports": [1, 2]}
d.save("sweep.lbd")

# ---- read it back ----
header = lbd.info("sweep.lbd")          # fast: names, shapes, units and meta, no data
print(header.title)
print("values:", list(header.values), " axes:", list(header.axes))
print("VNA settings:", header.meta["vna"])

d = lbd.load("sweep.lbd")               # everything, including the data
print("S21 shape:", d.values["S21"].data.shape)

# ---- plot: one curve per power, |S21| in dB ----
# Style changes for this figure: frequency always in MHz, and the legend where the plot is empty.
style = {
    "quantities": {"freq": {"prefix": "M"}},
    "figure": {"axes": {"legend": {"location": "lower left"}}},
}
fig = lp.plot("sweep.lbd", "curve", "S21", complex="db", series="power", style=style)
lp.save(fig, "curves_resonator.png", style=style)
