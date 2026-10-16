# Style examples

## A thesis preset

```json
{
  "figure": {
    "width_mm": 140, "height_mm": 90,
    "font": {"family": "DejaVu Serif", "size_pt": 10, "math": "dejavuserif"},
    "axes": {"axis": {"label": {"unit_format": "bracket"}}}
  },
  "quantities": {"S21.db": {"vmin": -30, "vmax": 0}}
}
```

Paste it into **Edit as JSON** on the Styles page, or save it as `thesis.lbd.json` and import it.
Then make it the default, or name it in a file:

```python
d.style_name = "thesis"
```

## An open frame with outward ticks

```json
{"figure": {"axes": {
  "frame": {"top": false, "right": false},
  "axis": {"ticks": {"direction": "out", "mirror": false}, "minor": {"visible": false}}
}}}
```

## Store a default view in a file (Python)

```python
d.plot = {"kind": "curve", "values": ["S21"], "complex": "phase_deg", "series": "power",
          "y_label": "Phase of S21"}
d.style = {"figure": {"width_mm": 120}}
d.save("sweep.lbd")
```

## One slice of a 3-D value

A value `T(a, b, c)` as a heat map of `b` (vertical) against `c` (horizontal), at the third
point of `a`:

```json
{"kind": "heatmap", "values": ["T"], "x": "c", "y": "b", "index": {"a": 2}}
```
