"""Scatter: single-shot readout in the I/Q plane

Every single-shot measurement of a qubit is one point in the I/Q plane. Prepared in |0⟩ or in
|1⟩, the points form two clouds; colouring them by the prepared state shows how well they separate.

Figure: a scatter plot of I against Q, one colour per prepared state, named in the legend.
Code: plot a Dataset in memory; colour points by an axis (a legend for a short axis); override the style for one figure.
Tasks: Plot data in memory (without a file); Colour points by group with a legend; Fix a unit prefix (MHz, mV, …); Override the style for one figure
Uses: lbd.Dataset, lbd.plot.plot, lbd.plot.save
"""

import numpy as np

import lbd
import lbd.plot as lp

# ---- mock data for the example: 1000 shots for each prepared state ----
rng = np.random.default_rng(4)
centres = np.array([0.6e-3 + 0.2e-3j, -0.1e-3 + 0.55e-3j])            # V, for |0> and |1>
noise = rng.normal(size=(2, 1000)) + 1j * rng.normal(size=(2, 1000))
iq = centres[:, None] + 0.12e-3 * noise                                # shape (state, shot)

d = lbd.Dataset(title="Single-shot readout")
d.add_axis("state", [0, 1], label="Prepared state")
d.add_axis("shot", np.arange(1000), label="Shot")
d.add_value("IQ", iq, axes=["state", "shot"], unit="V", label="IQ")    # one complex value

# ---- plot: real part against imaginary part, coloured by the prepared state ----
# The state axis has 2 points, so each gets its own colour and a legend entry (a long axis, or
# a value, would get a colour bar instead).
style = {
    "quantities": {"IQ.iq": {"prefix": "m"}},                          # show mV, whatever the data
    "figure": {"axes": {"legend": {"location": "upper right"}}},       # the empty corner
}
fig = lp.plot(d, "scatter", "IQ", complex="iq", color="state", x_label="I", y_label="Q", style=style)
lp.save(fig, "scatter_iq_readout.png", style=style)
