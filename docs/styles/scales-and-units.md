# Fixed scales and unit prefixes

## Fixed scales per quantity

`quantities` — to compare figures from different files or years, the same quantity must use
the same colour range (heat maps, colour-coded scatter) or the same vertical range (curves,
scatter), and the same unit prefix.

```json
{
  "quantities": {
    "temperature": {"vmin": 290, "vmax": 350, "cmap": "inferno"},
    "S21.db":      {"vmin": -30, "vmax": 0},
    "rate":        {"scale": "log"},
    "freq":        {"prefix": "M"}
  }
}
```

{{ style_table("QuantityStyle") }}

The limits are checked: `vmin` must be smaller than `vmax`, both must be finite numbers, and a
log scale needs `vmin > 0`.

**How a quantity name matches.** These names are tried in order, and the first one found is
used:

1. `<value name>.<complex mode>`, for complex values only, e.g. `S21.db`, `S21.phase`. This lets
   the dB view and the phase view have different ranges.
2. `<value name>`, e.g. `temperature`.
3. `<value label>`, e.g. `Temperature`.

Axes can be named too: `"freq": {"prefix": "M"}` shows every frequency axis in MHz, and a
scatter plot coloured by `power` uses the `power` entry. Limits are in the unit stored in the
file, without a prefix: K, dB, V.

When several values are plotted as curves, the first value's entry sets the vertical axis.
A quantity with `scale: "log"` makes that axis logarithmic even if the plot settings say
`linear`.

## Unit prefixes

LBD shows numbers with a unit prefix so they are readable: `7.0e9 Hz` → `7.0 GHz`, `2e-6 s` →
`2 µs`. It only **adds a prefix** to the unit the data is stored in; it never converts between
units (newtons to dynes, hertz to rad/s). Store the data in the unit you want to show.

### Automatic prefixes

With `axis.label.auto_prefix` on (the default), an axis or colour bar gets a prefix
automatically:

- The prefix is chosen from the largest absolute value shown, in steps of 1000: … n µ m (none)
  k M G T … (the full range from q, 10⁻³⁰, to Q, 10³⁰). c, d, da and h are never chosen
  automatically.
- It applies to these base units only: `Hz s V A W Ω Ohm F H T K m g J C S Pa N eV Wb`.
  The whole unit is compared with this list, exactly; every other unit is shown as stored (see
  [the table below](#which-units-get-a-prefix)).
- When a colour bar has fixed limits (`vmin`/`vmax`), it gets no automatic prefix, so the
  limits read exactly as entered.
- In the I/Q plane, both axes use the same prefix, so circles stay circles.

### Which units get a prefix

One rule holds for the axes and colour bars of every figure and for the numbers the viewer
writes (Explore's cursor read-outs, differences and means, tables, cuts and tooltips): a unit
gets a prefix only when the **whole unit** is on the list above. Nothing is guessed from the
unit's spelling, and nothing needs to be set.

| Stored | Shown | Why |
|---|---|---|
| 5120310000 Hz | 5.12031 GHz | on the list |
| 0.002 K | 2 mK | on the list |
| 0.5 C | 500 mC | on the list (coulomb); `°C` is not |
| 0.75 mm | 0.75 mm | already has a prefix |
| 5000 kHz | 5000 kHz | already has a prefix (not changed to 5 MHz) |
| 0.5 dB, 12 %, 0.5 rad, 3 ppm, 90 ° | as stored | not on the list |
| 0.5 a.u., 1500 counts, 0.5 min | as stored | not on the list |
| 0.02 V/cm, 3 m/s, 0.5 V*s, 2 A·s | as stored | a combined unit: no prefix on its first part |
| 2e-7 V/cm, 1.5e6 counts | 2e−7 V/cm, 1.5e6 counts | in the viewer's numbers, a unit without a prefix writes numbers below 0.001 or from 1 000 000 in scientific notation |

In a table, each column has one prefix, chosen from its largest number, so the digits line up
and the unit can go in the column's head.

To show another unit with a prefix, store the data in that unit, or give its quantity a fixed
prefix (below; for figures).

### A fixed prefix

Set `prefix` for a quantity to always use the same prefix, for **any** unit:

| `prefix` | Effect |
|---|---|
| empty (`null`) | automatic, as above |
| `""` | no prefix: the stored unit as it is |
| `"M"`, `"m"`, `"µ"` (or `"u"`), `"c"`, `"k"`, … | that prefix, e.g. MHz, mV, µs, cm, kOe |

All SI prefixes can be used: `q r y z a f p n µ m c d da h k M G T P E Z Y R Q`.

A fixed prefix is how you keep figures comparable: with `"freq": {"prefix": "M"}`, a sweep
around 7 GHz and one around 900 MHz are both shown in MHz.

### In your own Python figures

[`lbd.plot.prefix`][lbd.plot.prefix] does the same for your own figures:

```python
import numpy as np
import lbd.plot as lp

f = np.linspace(4e9, 8e9, 401)
f_ghz, unit = lp.prefix(f, "Hz")            # automatic: values in GHz, unit "GHz"
f_mhz, unit_m = lp.prefix(f, "Hz", to="M")  # fixed: values in MHz, unit "MHz"
field, field_unit = lp.prefix(np.array([2e-3, 5e-3]), "Oe", to="m")   # any unit: mOe
```

**Store data in base units** (Hz, not GHz), and the same quantity from different files gets
the same treatment.
