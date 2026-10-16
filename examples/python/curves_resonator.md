1. **Mock data.** The arrays stand in for a measurement: `S21` has one row per power and one
   column per frequency. Frequencies are kept in **Hz**: files store base units, and the plot picks
   a readable prefix later.
2. **Save the data.** A [`lbd.Dataset`][lbd.Dataset] holds the axes and the values that depend
   on them. [`add_axis`][lbd.Dataset.add_axis] adds a coordinate with its unit and label;
   [`add_value`][lbd.Dataset.add_value] adds the data and names its axes in order (rows: power,
   columns: frequency). Complex data is stored as it is.
3. **Record the measurement settings.** `d.meta` is a dictionary that is saved with the data:
   text, numbers, `True`/`False`, lists and arrays, and nested dictionaries, which become groups,
   such as `meta["vna"]` here. `None` can't be stored; leave such a key out. See
   [metadata](../python/files.md) for every type.
4. **Write the file.** [`save`][lbd.Dataset.save] writes one `.lbd` file (plain HDF5). MATLAB,
   Julia and LBD Viewer read it the same way.
5. **Read it back.** [`lbd.info`][lbd.info] reads only the header: names, shapes, units and the
   metadata. It is fast even for big files. [`lbd.load`][lbd.load] reads the data too, and
   `lbd.load(path, values="S21")` reads only some values.
6. **Plot it.** [`lp.plot`][lbd.plot.plot] draws a file or a `Dataset` the way the viewer does:
   `"curve"` with `series="power"` gives one curve per power, and `complex="db"` shows
   20·log₁₀|S₂₁|. The legend names each curve.
7. **Override the style for this figure.** The `style` dict changes only what it names, on top of
   the default style. Here it fixes the frequency to **MHz**
   ([fixed unit prefixes](../styles/scales-and-units.md)) and moves the legend to the empty
   corner. [`lp.save`][lbd.plot.save] writes the figure at its exact size.

**Change it**

- Only one power: `series="none", index={"power": -1}` (the last one).
- The phase instead: `complex="phase_deg"`.
- The settings in the viewer: open `sweep.lbd`; the metadata is under **File contents**.
