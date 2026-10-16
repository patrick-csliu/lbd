"""Log scale: a noise spectrum in your own matplotlib code

Your own figure, written with plain matplotlib, in the same style as the viewer's plots: a noise
power spectral density on log-log axes with guide lines for the 1/f and the white noise.

Figure: log-log axes, data and two guide lines, a legend and a fit result.
Code: lp.use for the style, lp.axis_label for "Name (unit)", lp.prefix for a readable number, lp.save.
Tasks: Your own matplotlib figure in the house style; Log axes
Uses: lbd.plot.use, lbd.plot.axis_label, lbd.plot.prefix, lbd.plot.save
"""

import matplotlib.pyplot as plt
import numpy as np

import lbd.plot as lp

# ---- mock data for the example: 1/f noise plus white noise ----
rng = np.random.default_rng(3)
f = np.logspace(0, 5, 300)                                     # Hz
a, white = 1e-14, 3.2e-18                                      # V²/Hz at 1 Hz, and the white level
psd = (a / f + white) * np.exp(rng.normal(0, 0.15, f.size))
corner = a / white                                             # where 1/f meets the white noise

with lp.use():                                                 # the default style, for everything below
    fig, ax = plt.subplots()
    ax.loglog(f, psd, label="measured")
    ax.loglog(f, a / f, "--", label="$1/f$")
    ax.loglog(f, np.full_like(f, white), ":", label="white")
    value, unit = lp.prefix(corner, "Hz")                      # 3125 Hz -> 3.1 kHz
    ax.text(0.05, 0.08, f"corner at {value:.1f} {unit}", transform=ax.transAxes)
    ax.set_xlabel(lp.axis_label("Frequency", "Hz"))
    ax.set_ylabel(lp.axis_label("$S_V$", "V²/Hz"))
    ax.legend(loc="upper right")
lp.save(fig, "logscale_noise.png")
