# MATLAB API reference — `lbd`

All functions live in the `lbd` package: `lbd.Dataset`, `lbd.load`, `lbd.info` and
`lbd.version`; to write a file while measuring, `lbd.Writer`, `lbd.writingStatus` and
`lbd.recover` (see [Writing while measuring](getting-started/writing-while-measuring.md)). Requires MATLAB R2021b or newer; no extra toolboxes are needed. To install, see
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
d = lbd.Dataset(title, description, Created=when)
```

All arguments are optional: `title` and `description` are strings (default `""`); `Created` is
when the data was created (see the `Created` property).

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
| `Created` | string, datetime or empty | When the data was created, ISO-8601 with a UTC offset (`"2026-10-13T16:09:00+08:00"`); a datetime without a time zone, or a text without an offset, is taken in this computer's time zone. Empty: `save` fills in the time of the first save. A loaded file keeps its `Created`, and saving again keeps it. |

These properties are read-only; they are set by the methods and by `lbd.load`:

| Property | Type | Meaning |
|---|---|---|
| `Axes` | struct | `Axes.<name>` is a struct with fields `Name`, `Data` (column vector), `Unit`, `Label`. |
| `Values` | struct | `Values.<name>` is a struct with fields `Name`, `Data`, `Axes` (string row), `Unit`, `Label`, `Shape` (row vector), `Dtype` (LBD type name). |
| `Writer` | string | Program that wrote the file, e.g. `"matlab lbd 1.0.0"`. |
| `Id` | string | The measurement's identity (a UUID, made at the first save; see `save`). `d.newId()` makes a new one. |
| `ParentId` | string | The `Id` of the file this one was made from. |
| `LbdVersion` | string | Format version of the file. |
| `Path` | string | Where it was last loaded from or saved to. |

Access data with `d.Values.S21.Data` and `d.Axes.freq.Data`, or with [`d.get("S21")`](#get).

### `addAxis`

<!-- no-check -->
```matlab
d.addAxis(name, data, Unit="", Label=name, Elements=[])
```

Adds a 1-D axis.

| Argument | Meaning |
|---|---|
| `name` | Axis name ([naming rules](getting-started/concepts.md#names)). |
| `data` | A real numeric vector, row or column. It is stored as a column. May be `[]` when `Elements` is given: the positions are then 0, 1, 2 … |
| `Unit` | Unit string. Prefer plain SI units (`"Hz"`, not `"GHz"`). |
| `Label` | Display text. Defaults to `name`. |
| `Elements` | A text for each position (format 1.2), e.g. `["ground" "excited"]`: the viewer shows them instead of the numbers. |

**Returns** the axis struct. **Errors** with `lbd:invalid` if the name is invalid or already
used, or if `data` is not a real numeric vector.

### `addValue`

<!-- no-check -->
```matlab
d.addValue(name, data, axes, Unit="", Label=name, Dtype="auto", Shape=[], Elements=[])
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
| `Shape` | The size of one data point (format 1.2): `3` for a vector of 3, `[2 2]` for a matrix. Empty: one number. `data`'s dimensions are the value's axes first, then the data point's. |
| `Elements` | A data point's position texts: a string array for a vector (`["x" "y" "z"]`), a cell with one string array per dimension for a matrix (`{["I" "Q"], ["I" "Q"]}`; `[]` leaves a dimension numbered). |

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
d.addAxis("state", [], Elements=["ground" "excited"]);                  % positions 0, 1
d.addValue("bloch", zeros(numel(v), 3), "t", Shape=3, Elements=["x" "y" "z"]);   % a vector per point
```

A value's `Axes` are what was swept (`"t"`); its data point is described by `PointShape` (`3`)
and `Elements`, and `Shape` is the data's size (`[numel(v) 3]`: the sweep, then the data point).
In the file, each dimension of a data point is an axis of its own (`bloch_dim1`, with
`role="point"`), so every reader reads it.

### `write`

Fills a value made with `addValue(name, [], axes, Dtype=...)` (every point `NaN`, or 0 with a
false `Measured` mask for integers and logicals): a point, a trace, a map, or several values at
once. Indices count from 1; a position can also be one of an axis's elements.

```matlab
d = lbd.Dataset("Power sweep");
d.addAxis("power", linspace(-60, 0, 7), Unit="dBm");
d.addAxis("freq", linspace(6.99e9, 7.01e9, 201), Unit="Hz");
d.addValue("S21", [], ["power" "freq"], Dtype="complex128");
d.addValue("n", [], "power", Dtype="int32");
for i = 1:3
    d.write(power=i, S21=ones(1, 201), n=10 * i);    % a trace, and n at power i
end
disp(d.Values.n.Measured')                            % 1 1 1 0 0 0 0
d.save("sweep.lbd");
```

`d.addAxis("time", [], Grows=true)` makes an axis whose points `write` adds
(`d.write(time=t, T=x)`). A name that isn't a valid MATLAB name goes as text:
`d.write("if", 3, "S21", z)`.

### Variable sweeps: `addGroup`

When the inner points depend on the outer one (B chosen per A), put the axes in an axis group
(format 2.0): only measured points are stored. See [Grid or group?](getting-started/concepts.md#grid-or-group).

```matlab
d = lbd.Dataset("Variable sweep");
d.addGroup("AB");                                  % its axes follow, outer to inner
d.addAxis("A", [], Group="AB", Unit="V");
d.addAxis("B", [], Group="AB", Unit="Hz");
d.addValue("f", [], ["A" "B"]);                    % one entry per (A, B) point
d.addValue("q", [], "A");                          % one per A
bs = {10, [10 20], [15 25 35]};
for a = 1:3
    d.write(A=a, B=bs{a}, f=100 * a + bs{a});      % coordinates, not indices
    d.write(A=a, q=1.5 * a);
end
disp(d.Axes.B.Data')       % 10 10 20 15 25 35: each (A, B) point's B
disp(d.Axes.B.Parent')     % 1 2 2 3 3 3: the A it belongs to (from 1)
disp(d.Values.f.Dims)      % {["A" "B"]}: stored as the (A, B) points
i = d.write(A=4);                                  % write returns the point's index ...
d.write(Parent=i, B=[5 6], f=[45 46]);             % ... to write under it without a lookup
m = d.toDense("f");                                % the full rectangle: gaps NaN
disp(size(m.Values.f.Data))                        % 4 7
r = d.rows("f", By="A");                           % {key, dataset; ...}
disp(r{3, 2}.Axes.B.Data')                         % 15 25 35
c = d.coords("f");                                 % each point's coordinates
disp([c.A c.B]')
d.save("variable.lbd");                            % format 2.0
```

- A group's axis takes a **coordinate**, outer axes first; the same coordinates are the same
  point. `Parent=` takes the index an earlier `write` returned (indices from 1; the file stores
  them from 0).
- A value lies on an outer part of a group (`"A"`, `["A" "B"]`, or the group's name), never on
  `"B"` alone.
- `d.toDense(name, Round=9)` or `RTol=1e-9` merges coordinates that differ only by rounding
  (`write` warns about them); `Limit=Inf` lifts the size limit (1e8 cells).
- `lbd.Writer` takes the same calls (`w.addGroup`, `w.addAxis(..., Group=)`, `w.write`).

### `save`

<!-- no-check -->
```matlab
path = d.save(path, Compression=false)
```

Writes the dataset and returns the path. It also sets `Writer` and `Path`, and `Created` if it
was empty (the time of this first save); a `Created` that is set is written unchanged.

It also sets the file's **id**: the measurement's identity, which LBD Viewer's Library uses to recognise
the same measurement in two places (a copy, a backup, a synced folder). It is made at the first
save (a UUID, from the time and random bits of the operating system: no setup, nothing to
coordinate between computers) and is read-only. Saving again to the same file keeps it;
saving to **another file** gives that file a new id, and the old one becomes its **parent
id** (a new measurement made from this one). A file copied by the file system keeps its id. `d.newId()` makes a loaded dataset a new
measurement on purpose.

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

## `lbd.open`

<!-- no-check -->
```matlab
d = lbd.open(path)
d = lbd.open(path, Mode="r+")
```

Reads the file's structure and leaves the value data in the file: each value's `Data` is an
`lbd.OnDisk`. `size` and `class` need no reading; `Data(4, :)` reads row 4 only, `Data.read()`
everything. `d.close()` closes the file; what was read stays usable.

| Argument | Meaning |
|---|---|
| `path` | File to read. A file being written (`.lbd.writing`) opens as it was at that moment. |
| `Mode` | `"r"` (default): read only; `write` and `save` are refused. `"r+"`: `write` puts data into the file at points that exist, `d.save()` writes the title, description, metadata and saved view into it, `d.save(other)` copies it piece by piece. |

```matlab
d = lbd.open("big.lbd");
row = d.Values.S21.Data(4, :);
d.close();
```

See [Large files](getting-started/large-files.md).

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
