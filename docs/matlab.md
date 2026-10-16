# MATLAB API reference — `lbd`

All functions live in the `lbd` package: `lbd.Dataset`, `lbd.load`, `lbd.info` and
`lbd.version`. Requires MATLAB R2021b or newer; no extra toolboxes are needed. To install, see
[Install → MATLAB](getting-started/install.md#matlab).

## Quick example

```matlab
f = linspace(4e9, 8e9, 401);
p = -40:4:0;
s21 = exp(1i * (p' * f) * 1e-10);                 % 11 x 401 = (power, freq)

d = lbd.Dataset("Resonator power sweep");
d.addAxis("power", p, Unit="dBm", Label="Power");
d.addAxis("freq", f, Unit="Hz", Label="Frequency");
d.addValue("S21", s21, ["power" "freq"]);
d.Meta.T_mK = 12;
d.Meta.vna = struct("ifbw_Hz", 1000, "averages", 4);
d.save("sweep.lbd");

d = lbd.load("sweep.lbd");
size(d.Values.S21.Data)     % [11 401]
d.Values.S21.Axes           % ["power" "freq"]
```

`lbd.Dataset` is a handle object, so methods change the object in place. You don't need
`d = d.addAxis(...)`.

---

## `lbd.Dataset`

<!-- no-check -->
```matlab
d = lbd.Dataset(title, description)
```

Both arguments are optional strings (default `""`).

### Properties

You can set these properties:

| Property | Type | Meaning |
|---|---|---|
| `Title` | string | Short title. |
| `Description` | string | Free text. |
| `Meta` | struct | Free metadata. Nested structs become groups. See [meta types](#meta-values). |
| `Plot` | struct, JSON text, or `[]` | Default plot for the viewer: a [plot spec](styles/plot-settings.md), e.g. `struct("kind","heatmap","complex","db")`. |
| `Style` | struct, JSON text, or `[]` | Per-file [style](styles/index.md) changes, e.g. `struct("figure", struct("width_mm", 120))`. |
| `StyleName` | string or empty | Name of a viewer style preset for this file. |
| `Matplotlib` | string or empty | matplotlib version that last wrote the saved view (set by Python and the viewer). MATLAB keeps it when saving. |

These properties are read-only; they are set by the methods and by `lbd.load`:

| Property | Type | Meaning |
|---|---|---|
| `Axes` | struct | `Axes.<name>` is a struct with fields `Name`, `Data` (column vector), `Unit`, `Label`. |
| `Values` | struct | `Values.<name>` is a struct with fields `Name`, `Data`, `Axes` (string row), `Unit`, `Label`, `Shape` (row vector), `Dtype` (LBD type name). |
| `Created` | string | ISO-8601 time the file was written. |
| `Writer` | string | Program that wrote the file, e.g. `"matlab lbd 1.0.0"`. |
| `LbdVersion` | string | Format version of the file. |
| `Path` | string | Where it was last loaded from or saved to. |

Access data with `d.Values.S21.Data` and `d.Axes.freq.Data`, or with [`d.get("S21")`](#get).

### `addAxis`

<!-- no-check -->
```matlab
d.addAxis(name, data, Unit="", Label=name)
```

Adds a 1-D axis.

| Argument | Meaning |
|---|---|
| `name` | Axis name ([naming rules](getting-started/concepts.md#names)). |
| `data` | A real numeric vector, row or column. It is stored as a column. |
| `Unit` | Unit string. Prefer plain SI units (`"Hz"`, not `"GHz"`). |
| `Label` | Display text. Defaults to `name`. |

**Returns** the axis struct. **Errors** with `lbd:invalid` if the name is invalid or already
used, or if `data` is not a real numeric vector.

### `addValue`

<!-- no-check -->
```matlab
d.addValue(name, data, axes, Unit="", Label=name, Dtype="auto")
```

Adds an N-D value.

| Argument | Meaning |
|---|---|
| `name` | Value name. |
| `data` | Numeric or logical array. A single number with no `axes` makes a scalar value. |
| `axes` | One axis name per dimension, as a string array (`["power" "freq"]`), a single name (`"freq"`), or comma-separated text (`"power,freq"`). Leave it out for a scalar. The axes must already exist. |
| `Unit` | Unit string. |
| `Label` | Display text. Defaults to `name`. |
| `Dtype` | `"auto"` keeps the class of `data`. Or force one of `"float64"`, `"float32"`, `"complex128"`, `"complex64"`, `"bool"`, `"int8"`…`"int64"`, `"uint8"`…`"uint64"`. |

- **Vectors:** a value with one axis accepts a row or a column vector and stores it as a column.
- **Matrices:** `size(data)` must equal the axis lengths in order. MATLAB drops trailing
  dimensions of length 1, and that is handled: a 5×1 value on axes `["a" "b"]` with `b` of
  length 1 is accepted.

**Returns** the value struct. **Errors** with `lbd:invalid` if:
- the name is invalid or used,
- the number of axes doesn't fit the data,
- an axis doesn't exist,
- a size doesn't match its axis length,
- the data isn't numeric or logical,
- `Dtype` is unknown,
- `Dtype` would drop the imaginary part of complex data.

```matlab
d.addValue("S21", s21, ["power" "freq"]);
d.addValue("trace", v, "t", Unit="V");
d.addValue("mask", v > 0.5, "t");                  % logical -> bool
d.addValue("raw", counts, "t", Dtype="float32");   % force a type
d.addValue("fit_Q", 12345.6);                      % scalar
```

### `save`

<!-- no-check -->
```matlab
path = d.save(path, Compression=false)
```

Writes the dataset and returns the path. It also sets `Created`, `Writer` and `Path`.

| Argument | Meaning |
|---|---|
| `path` | File path. Use `.lbd`; other extensions give the warning `lbd:extension`. An existing file is replaced. |
| `Compression` | `true` gzip-compresses arrays of 1024 elements or more. This is lossless and transparent to all readers. |

The file is written under a temporary name and then renamed, so other programs never see a
half-written file. If writing fails, an existing file at `path` is left untouched.

**Errors** with `lbd:invalid` if:
- meta contains something that can't be stored,
- a value was loaded without its data.

### `get`

<!-- no-check -->
```matlab
item = d.get(name)
```

Returns the value struct called `name`, or else the axis struct with that name. **Errors**
with `lbd:notFound` if neither exists.

### `disp`

Typing `d` (or calling `disp(d)`) prints the title and one line per axis and value.

---

## `lbd.load`

<!-- no-check -->
```matlab
d = lbd.load(path)
d = lbd.load(path, Values=names)
```

Reads an `.lbd` file and returns an `lbd.Dataset`.

| Argument | Meaning |
|---|---|
| `path` | File to read. |
| `Values` | String array of the values whose data to read. Values not listed are still described (`Shape`, `Dtype`, `Axes`, `Unit`), but their `Data` is `[]`. Axes and meta are always read. |

**Errors**:
- `lbd:notFound` if the file doesn't exist, or `Values` names a missing value.
- `lbd:invalid` if the file isn't LBD or breaks the format rules.
- `lbd:version` if the file's major format version is newer than supported.

**Warnings**:
- `lbd:newerVersion` if the minor format version is newer.
- `lbd:metaKey` if a meta key isn't a valid field name (it is renamed with `matlab.lang.makeValidName`).
- `lbd:json` if the stored plot JSON is invalid.

```matlab
d = lbd.load("sweep.lbd");
d = lbd.load("big.lbd", Values="S21");
```

## `lbd.info`

<!-- no-check -->
```matlab
d = lbd.info(path)
```

Reads everything except value data. It is fast, even for very large files.

```matlab
files = dir("data/**/*.lbd");
for k = 1:numel(files)
    i = lbd.info(fullfile(files(k).folder, files(k).name));
    fprintf("%s: %s\n", files(k).name, i.Title);
end
```

## `lbd.version`

```matlab
v = lbd.version()      % struct with fields package = "1.0.0", lbd_version = "1.0"
```

---

## Errors and warnings

| Identifier | Kind | When |
|---|---|---|
| `lbd:invalid` | error | Invalid name, shape, type or meta; file is not LBD or breaks the rules. |
| `lbd:notFound` | error | File missing; no value/axis with that name. |
| `lbd:version` | error | File's major format version is newer than supported. |
| `lbd:newerVersion` | warning | File's minor format version is newer; some content may be ignored. |
| `lbd:extension` | warning | Saving to a name that doesn't end in `.lbd`. |
| `lbd:metaKey` | warning | A meta key from another language isn't a valid MATLAB field name. |
| `lbd:json` | warning | Stored plot/style JSON can't be parsed; it is ignored. |

```matlab
file = "sweep.lbd";
try
    d = lbd.load(file);
catch err
    if err.identifier == "lbd:version"
        disp("This file needs a newer LBD module.");
    else
        rethrow(err);
    end
end
```

## Type conversion

### Values

| MATLAB class | Stored as | Read back as |
|---|---|---|
| `double` / `single` | float64 / float32 | same |
| complex `double` / `single` | complex128 / complex64 | complex, even if every imaginary part is 0 |
| `int8` … `uint64` | same | same |
| `logical` | bool | `logical` |

Arrays from Python and Julia arrive in the same logical shape (see
[dimension order](getting-started/concepts.md#dimension-order-is-the-same-in-every-language)). 1-D data always
arrives as a column vector.

### Meta values

| You put in `Meta` | Stored as | Read back as |
|---|---|---|
| string, char row | UTF-8 text | string |
| string array, cellstr (1-D) | text array | string row |
| `double`, `single`, integers | same class | same class |
| `logical` | int64 0/1 | `int64` |
| complex numbers | complex | complex |
| vectors | 1-D array | column vector |
| matrices, N-D arrays | array (logical order kept) | same size |
| `datetime` | ISO-8601 text | string |
| nested struct | sub-group | struct |
| `[]`, struct arrays, cells, objects | refused at `save` | — |

**Integers from other languages:** Python and Julia write whole numbers as 64-bit integers, so
`averages = 4` written in Python is `int64(4)` in MATLAB. Arithmetic with `double` then gives
`int64` results; convert with `double(d.Meta.averages)` when you need a double.

**Plot and Style** are read back as structs, through `jsondecode`. Lists of text become cell
arrays; use `string(d.Plot.values)` to get a string array.

## Recipes

### Add metadata to an existing file

```matlab
d = lbd.load("sweep.lbd");
d.Meta.note = "checked 2026-10-14";
d.save("sweep.lbd");
```

### Save the default plot and style

```matlab
d.Plot = struct("kind", "curve", "values", {{"trace"}}, "y_label", "Signal");
d.Style = struct("figure", struct("width_mm", 120, "height_mm", 70));
d.StyleName = "thesis";
d.save("run.lbd");
```

Note the double braces in `{{"trace"}}`: `struct` needs them to store a cell array in a field.

### Loop over measurements

```matlab
for k = 1:numel(T)
    d = lbd.Dataset(sprintf("Sweep at %g mK", T(k)));
    d.addAxis("freq", f, Unit="Hz", Label="Frequency");
    d.addValue("S21", measure(T(k)), "freq");
    d.Meta.T_mK = T(k);
    d.save(sprintf("out/sweep_%03d.lbd", k), Compression=true);
end
```
