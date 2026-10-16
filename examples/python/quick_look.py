"""Quick look: plot numpy arrays in one call

For a fast look at arrays, for example right after a fit, lp.quick draws them in the same style
as the viewer, without a Dataset or a file. Here: a Rabi oscillation with its fit.

Figure: measured points and a fitted curve, with a legend.
Code: lp.quick with named curves (a dict), labels and units; base units get readable prefixes.
Tasks: Plot numpy arrays quickly
Uses: lbd.plot.quick, lbd.plot.save
"""

import numpy as np

import lbd.plot as lp

# ---- mock data for the example: a Rabi oscillation and a fit ----
rng = np.random.default_rng(5)
t = np.linspace(0, 400e-9, 81)                                         # s
fit = 0.5 * (1 - np.cos(2 * np.pi * 7.5e6 * t) * np.exp(-t / 900e-9))
data = fit + rng.normal(0, 0.03, t.size)

# A dict gives named curves: the names go into the legend. The time axis becomes ns by itself.
fig = lp.quick(t, {"data": data, "fit": fit}, x_label="Pulse length", x_unit="s",
               y_label="$P_{|1\\rangle}$")
lp.save(fig, "quick_look.png")
