# Quick start

A ten-minute tour: write a file from your own code, look at it in LBD Viewer, save a view, and
make a matching figure in Python. You need [LBD Viewer and the module for your
language](install.md).

## 1. Write a file

A measurement is a set of **axes** (what you swept) and **values** (what you measured on
those axes). Here a resonator's transmission `S21` is measured against power and frequency.
Pick your language; the tabs on every page switch together.

=== "Python"

    ```python
    import numpy as np
    import lbd

    f = np.linspace(6.99e9, 7.01e9, 401)
    p = np.arange(-60, 1, 5.0)
    s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 0.6e6) * np.ones((len(p), 1))

    d = lbd.Dataset(title="Resonator power sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", s21, axes=["power", "freq"])    # shape (13, 401) = (power, freq)
    d.meta["T_mK"] = 12
    d.save("sweep.lbd")
    ```

=== "MATLAB"

    ```matlab
    f = linspace(6.99e9, 7.01e9, 401);
    p = -60:5:0;
    s21 = 1 - 0.8 ./ (1 + 2i * (f - 7e9) / 0.6e6) .* ones(numel(p), 1);

    d = lbd.Dataset("Resonator power sweep");
    d.addAxis("power", p, Unit="dBm", Label="Power");
    d.addAxis("freq", f, Unit="Hz", Label="Frequency");
    d.addValue("S21", s21, ["power" "freq"]);       % size 13 x 401 = (power, freq)
    d.Meta.T_mK = 12;
    d.save("sweep.lbd");
    ```

=== "Julia"

    ```julia
    using LBD

    f = collect(range(6.99e9, 7.01e9, 401))
    p = collect(-60.0:5:0)
    s21 = 1 .- 0.8 ./ (1 .+ 2im .* (f' .- 7e9) ./ 0.6e6) .* ones(length(p))

    d = Dataset("Resonator power sweep")
    add_axis!(d, "power", p; unit="dBm", label="Power")
    add_axis!(d, "freq", f; unit="Hz", label="Frequency")
    add_value!(d, "S21", s21, ["power", "freq"])    # size (13, 401) = (power, freq)
    d.meta["T_mK"] = 12
    LBD.save("sweep.lbd", d)
    ```

The axis order you give is the order of your array's dimensions in your language, so the same
file reads back with the same shape in all three. See [Concepts](concepts.md) for types, names
and units.

## 2. Look at it

**Double-click `sweep.lbd`.** LBD Viewer opens it in your browser and picks a plot for a 2-D
complex value: a heat map of the magnitude.

Try the controls on the left ([full guide](../viewer/plotting.md)):

- **Complex data as** → *magnitude (dB)*.
- **Plot type** → *Curves*, **One curve per** → *power*: one curve per power, coloured in
  order.
- **Plot type** → *Curves*, **One curve per** → *— (single curve)*: a slider picks the power.

Units are scaled automatically: the frequency axis reads *Frequency (GHz)*.

To see all files of a project, use **+ Add folder** in the folder panel; every `.lbd` file,
style file and image below it is listed ([Folders and files](../viewer/folders-and-files.md)).

## 3. Save the view and export

**Save this view to the file** stores your plot settings inside `sweep.lbd`. From now on it
opens like this for anyone, on any computer. The data is never changed.

**Export: PDF** saves the figure at its real size: 85 mm × 64 mm, 10 pt text, fonts embedded,
ready for a column of an APS or AIP journal ([Saving and exporting](../viewer/saving-and-exporting.md)).

## 4. Make every figure match

The size, fonts, frame, ticks and colours come from a **style**. Open **Styles** in the viewer's
top bar, create a preset (for example *thesis*) and make it the default. Every figure in the
viewer then uses it ([How styles work](../styles/index.md)).

The same style is available in Python, both for the viewer's plot types and for figures you
draw yourself:

```python
import matplotlib.pyplot as plt
import lbd
import lbd.plot as lp

d = lbd.load("sweep.lbd")
fig = lp.plot(d)                      # the saved view (or the automatic one), as in the viewer
lp.save(fig, "sweep.pdf")

with lp.use("default"):               # your own matplotlib figure, same style
    fig, ax = plt.subplots()
    f_ghz, f_unit = lp.prefix(d.axes["freq"].data, "Hz")
    ax.plot(f_ghz, abs(d["S21"].data[-1]))
    ax.set_xlabel(lp.axis_label("Frequency", f_unit))
    ax.set_ylabel(lp.axis_label("|S21|", ""))
    fig.savefig("my_figure.pdf")
```

Replace `"default"` with your preset's name, or with the path of a `.lbd.json` style file
kept next to a paper's data.

## Next

- [Concepts](concepts.md): what exactly a file holds.
- [LBD Viewer](../viewer/index.md): every control and page.
- [Styles and figures](../styles/index.md): every setting, fixed colour scales per quantity, SI
  prefixes.
- The reference for your language: [Python](../python/files.md) · [MATLAB](../matlab.md) ·
  [Julia](../julia.md).
