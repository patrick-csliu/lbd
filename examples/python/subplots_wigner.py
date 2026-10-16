"""Two panels with a shared axis: a Wigner function and its projection

A cat state's Wigner function W(x, p) as a heat map, and above it the probability P(x) of the
position, the projection of W onto the x axis. Both panels share the x axis.

Figure: two stacked panels, (a) a curve, (b) a heat map with a diverging colour map.
Code: lp.subplots with a shared axis; lp.plot into one panel (ax=), your own matplotlib code in the other.
Tasks: Combine panels with a shared axis; Plot data in memory (without a file); Your own matplotlib figure in the house style; Override the style for one figure
Uses: lbd.Dataset, lbd.plot.subplots, lbd.plot.plot, lbd.plot.use, lbd.plot.save
"""

import numpy as np

import lbd
import lbd.plot as lp

# ---- mock data for the example: Wigner function of an even cat state ----
x = np.linspace(-4, 4, 201)
p = np.linspace(-4, 4, 201)
X, P = np.meshgrid(x, p)                                       # rows: p, columns: x
p0 = 2.0                                                       # the two parts sit at p = ±p0
W = (np.exp(-X**2 - (P - p0)**2) + np.exp(-X**2 - (P + p0)**2)
     + 2 * np.exp(-X**2 - P**2) * np.cos(2 * p0 * X)) / (2 * np.pi)
P_x = W.sum(axis=0) * (p[1] - p[0])                            # projection: integrate over p

d = lbd.Dataset(title="Cat state")
d.add_axis("x", x, label="$x$")
d.add_axis("p", p, label="$p$")
d.add_value("W", W, axes=["p", "x"], label="$W(x, p)$")

# A diverging colour map centred on zero shows where W is negative (the quantum part).
w = np.abs(W).max()
style = {"quantities": {"W": {"vmin": -w, "vmax": w, "cmap": "RdBu_r"}}}

with lp.use(style):
    fig, (top, bottom) = lp.subplots(2, 1, style=style, height_mm=90, sharex=True,
                                     gridspec_kw={"height_ratios": [1, 2]})
    top.plot(x, P_x)                                           # your own plot ...
    top.set_ylabel("$P(x)$")
    lp.plot(d, "heatmap", "W", style=style, ax=bottom)         # ... and the tool's heat map
    top.set_title("(a)", loc="left")
    bottom.set_title("(b)", loc="left")
lp.save(fig, "subplots_wigner.png", style=style)
