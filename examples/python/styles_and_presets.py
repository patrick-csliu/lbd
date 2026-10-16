"""Styles: make a preset once, use it everywhere

A style sets size, fonts, line widths, ticks and colours. Here a "talk" preset is made from the
default, stored (the viewer's Styles page sees it too), saved as a file to keep with a paper, and
exported for colleagues who use matplotlib without LBD.

Figure: a plot drawn with the new preset.
Code: list and load styles, change settings, store a preset, a .lbd.json style file, an .mplstyle file.
Tasks: Make and share a style (preset, style file, .mplstyle)
Uses: lbd.plot.list_styles, lbd.plot.load_style, lbd.plot.PresetStore, lbd.plot.Style, lbd.plot.use, lbd.plot.save
"""

import matplotlib.pyplot as plt
import numpy as np

import lbd.plot as lp

print("styles:", lp.list_styles())

# Start from the default and change what a talk needs: bigger, bolder.
style = lp.load_style("default")
style.figure.width_mm = 120
style.figure.height_mm = 80
style.figure.font.size_pt = 14
style.figure.axes.lines.width_pt = 2
style.description = "Slides and talks: 120 × 80 mm, 14 pt text, 2 pt lines"   # shown on the Styles page

# Store it as a preset: the viewer and every Python script can now use the name "talk".
lp.PresetStore().save("talk", style.diff())                    # only what differs from the default
print("stored:", lp.PresetStore().preset("talk"))

# Keep the complete style with the paper, and give matplotlib users an .mplstyle file.
style.save("talk.lbd.json")
with open("talk.mplstyle", "w", encoding="utf-8") as fh:
    fh.write(style.to_mplstyle())                               # for plt.style.use("talk.mplstyle")

# Use it by name, by file, or as the Style object itself.
x = np.linspace(0, 4 * np.pi, 200)
with lp.use("talk"):
    fig, ax = plt.subplots()
    ax.plot(x, np.sin(x), label="$\\sin\\theta$")
    ax.plot(x, np.cos(x), "--", label="$\\cos\\theta$")
    ax.set_xlabel(lp.axis_label("Phase θ", "rad"))
    ax.set_ylabel(lp.axis_label("Amplitude"))
    ax.set_ylim(-1.2, 1.6)
    ax.legend(loc="upper right", ncols=2)
lp.save(fig, "styles_and_presets.png", style="talk.lbd.json")
