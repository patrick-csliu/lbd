"""Heat map: single-shot qubit readout with the two states marked

A 2-D histogram of many single-shot I/Q measurements. Annotations mark the centre of each state,
a 2σ circle around it, and the threshold between them.

Figure: a heat map of counts in the I/Q plane, with markers, labels, circles and a threshold line.
Code: annotations: an Axes method with args and kwargs, a patch, text at a fixed place in the plot.
Tasks: Plot data in memory (without a file); Mark points, lines and regions (annotations); Fix a unit prefix (MHz, mV, …)
Uses: lbd.Dataset, lbd.plot.plot, lbd.plot.save
"""

import numpy as np

import lbd
import lbd.plot as lp

# ---- mock data for the example: 4000 shots, half in |0>, half in |1> (in mV) ----
rng = np.random.default_rng(1)
c0, c1, sigma = np.array([0.6, 0.2]), np.array([-0.1, 0.55]), 0.12
shots = np.concatenate([c0 + sigma * rng.normal(size=(2000, 2)),
                        c1 + sigma * rng.normal(size=(2000, 2))])
counts, i_edges, q_edges = np.histogram2d(shots[:, 0], shots[:, 1], bins=80)
i_mv = (i_edges[:-1] + i_edges[1:]) / 2
q_mv = (q_edges[:-1] + q_edges[1:]) / 2

d = lbd.Dataset(title="Single-shot readout")
d.add_axis("I", i_mv * 1e-3, unit="V")              # stored in volts
d.add_axis("Q", q_mv * 1e-3, unit="V")
d.add_value("counts", counts.T, axes=["Q", "I"], label="Counts")   # rows: Q, columns: I

# ---- annotations: each is a matplotlib call, in the units shown on the axes (mV here) ----
middle = (c0 + c1) / 2
slope = -(c1[0] - c0[0]) / (c1[1] - c0[1])          # the threshold is perpendicular to c0 -> c1
annotations = [
    # ax.plot(x, y, ...): a cross at each centre
    {"method": "plot", "args": [[c0[0], c1[0]], [c0[1], c1[1]]],
     "kwargs": {"marker": "x", "ls": "", "color": "white"}},
    # ax.text(x, y, text, ...): the state labels
    {"method": "text", "args": [c0[0] + 0.05, c0[1] + 0.05, "$|0\\rangle$"], "kwargs": {"color": "white"}},
    {"method": "text", "args": [c1[0] + 0.05, c1[1] + 0.05, "$|1\\rangle$"], "kwargs": {"color": "white"}},
    # a patch is a shape from matplotlib.patches: Circle((x, y), radius, ...)
    {"patch": "Circle", "args": [list(c0), 2 * sigma], "kwargs": {"fill": False, "ec": "white", "ls": "--"}},
    {"patch": "Circle", "args": [list(c1), 2 * sigma], "kwargs": {"fill": False, "ec": "white", "ls": "--"}},
    # ax.axline((x, y), slope=...): the threshold, an endless line through the middle
    {"method": "axline", "args": [list(middle)], "kwargs": {"slope": slope, "color": "white", "lw": 0.8}},
    # "axes fraction": 0..1 across the plot, so the text stays in the corner whatever the data
    {"method": "annotate", "args": ["2000 shots per state"],
     "kwargs": {"xy": [0.03, 0.04], "xycoords": "axes fraction", "color": "white"}},
]

# Fix the prefix of both axes to mV: annotations are in mV, so the axes must not switch units.
style = {"quantities": {"I": {"prefix": "m"}, "Q": {"prefix": "m"}}}
fig = lp.plot(d, "heatmap", "counts", style=style, annotations=annotations)
lp.save(fig, "heatmap_single_shot.png", style=style)
