# Cross-language round-trip tests

Every language writes the same logical content to `<root>/<language id>/fixture.lbd`. Then
every language reads **every** fixture and checks it against the definition below. With N
languages, that is N × N checks.

```bash
uv run python tests/crosslang/run_all.py               # all languages
uv run python tests/crosslang/run_all.py --only python julia
uv run python tests/crosslang/run_all.py --keep out/   # keep the fixture files
```

Languages are discovered from `languages/*/language.toml`. The `[crosslang]` section gives
each language's `write` and `check` commands, and their scripts live in
`languages/<id>/crosslang/`. A language whose `requires` program is not on `PATH` is skipped
with a notice. See [languages/README.md](../../languages/README.md) for adding one.

<!-- --8<-- [start:fixture] -->
## What the scripts must do

- **write** creates `<out>/fixture.lbd` with exactly the content below, `<out>/live.lbd`
  with the language's Writer (the live fixture), `<out>/groups.lbd` (the groups fixture) and
  `<out>/rplus.lbd` (changed in place with the language's `open` in mode r+).
  `<out>` is given as `{out}` / `LBD_OUT`.
- **check** finds every `<root>/*/fixture.lbd`, `<root>/*/live.lbd`, `<root>/*/groups.lbd` and
  `<root>/*/rplus.lbd`, also opens every fixture and groups file with the language's `open` (read
  lazily: the same values as a full load, read whole and by part) (`{root}` /
  `LBD_ROOT`), compares each with its definition, prints one line per file (`<language> reads
  <writer> OK` or `FAILED: <reason>`), and exits non-zero if any check failed.
- **read_live** (optional) reads a measurement while Python writes it: see "Reading while
  measuring" below.

## Fixture definition (0-based indices i, j, k)

| Item | Definition |
|---|---|
| title | `Fixture – ünïcode` |
| created | `2025-03-01T23:30:00+08:00` (given by the writer, not the time of saving); **check** also loads each fixture, saves it to a scratch file and reads it again: `created` is unchanged |
| id | made by the writer: a valid UUID version 7 (lower case; version 7, variant 10). **check** also: a copy of the fixture (copied as a file), loaded and saved to the *same* place, keeps the `id`; the fixture loaded and saved to *another* file gets a new `id` with `parent_id` = the fixture's `id` |
| axis `x` | float64 `0..9`, unit `s` |
| axis `a` | float64 `[1, 2, 3]`, unit `V` |
| axis `b` | float64 `[1, 2, 3, 4]`, unit `A` |
| axis `c` | float64 `[1, 2]`, unit `Hz` |
| value `y(x)` | float64 `x²`, unit `s^2` |
| value `k(x)` | int32 `(i+1)·(-1)^i` → `1, -2, 3, …, -10` |
| value `mask(x)` | bool `i even` |
| value `M(a,b)` | float64 `10·i + j` |
| value `Z(a,b)` | complex128 `(i+1) + (j+1)·1j` |
| value `T(a,b,c)` | float64 `100·i + 10·j + k` |
| value `q` | scalar float64 `42.5` |
| axis `state` | positions `0, 1, 2` with elements `["ground", "état 1", "量子"]` (format 1.2), made from the elements alone |
| value `S(state)` | float64 `[0.5, 1.5, 2.5]` |
| value `C(a)` | each data point a 2×2 matrix (shape `(2, 2)`, format 1.2): `C[i, r, c] = 100·i + 10·r + c`; elements `["I", "Q"]` for the first dimension, the second numbered; **check**: axes `a, C_dim1, C_dim2`, `C_dim1` and `C_dim2` have `role="point"`, `a` none |
| meta | `sample="chip – é"`, `T_mK=12` (int), `names=["a","b"]`, `vec=[1,2,3]`, `mat=[[0,1,2],[3,4,5]]` (2×3), `vna.ifbw_Hz=1000.0`, `vna.averages=4` (int) |
| plot | `spec={"kind":"heatmap","values":["M"]}`, `style_name="thesis"`, `matplotlib` a non-empty version text (Python writes the installed matplotlib version; MATLAB and Julia write `"3.9.0"`) |

## Live fixture definition (written with the Writer; 0-based indices)

| Item | Definition |
|---|---|
| file | `<out>/live.lbd`, finished: no `live.lbd.writing` is left |
| title | `Live – ü` |
| axes | `power` `[1, 2, 3]` dBm; `freq` `[0, 0.5, 1]` Hz; `state` elements `["ground", "excited"]`; `time` growing, s |
| value `S21(power, freq)` | complex128, written a trace at a time for powers 0 and 1: `S21[i, j] = (i+1) + (j+1)·1j`; power 2 never measured (`NaN`); no mask |
| value `T(time)` | float64; written as `time=0, T=0`, then `time=[1, 2], T=[10, 20]`, then `time=3, T=30`: `time = [0, 1, 2, 3]`, `T = [0, 10, 20, 30]`; no mask |
| value `n(state, power)` | int32, written at `state="excited", power 0` (7) and `state="ground", power 1` (3): data `[[0, 3, 0], [7, 0, 0]]`, mask `/measured/n` `[[0, 1, 0], [1, 0, 0]]` |
| finish | closed as stopped on purpose (`close(stopped=True)` and its equivalents) |

## Groups fixture definition (format 2.0; indices from 0 as in the file)

| Item | Definition |
|---|---|
| file | `<out>/groups.lbd`, title `Groups`, `lbd_version` `"2.0"` |
| group `AB` | order `A, B`; `A` unit V, `B` unit Hz; written by coordinates: A=1: B=10; A=2: B=10, 20; A=3: B=15, 25, 35. Levels: `A = [1, 2, 3]`, `B = [10, 10, 20, 15, 25, 35]`, `B._parent = [0, 1, 1, 2, 2, 2]` |
| axis `C` | fixed, `[0.1, 0.2, 0.3]` |
| value `f(A, B)` | float64, `100·A + B` per (A, B) point: `[110, 210, 220, 315, 325, 335]` |
| value `q(A)` | float64, `1.5·A`: `[1.5, 3, 4.5]` |
| value `h(A, B, C)` | float64, per (A, B) point the row `[A, B, A+B]`: shape (6, 3) |
| value `cov(A, B)` | float64, a 2 × 2 matrix per point `[[A, B], [B, −A]]`: shape (6, 2, 2) |
| value `n(A, B)` | int16, written only at (1, 10) = 1 and (3, 25) = 2: data `[1, 0, 0, 0, 2, 0]`, mask `[1, 0, 0, 0, 1, 0]` |
| group `PQR` | order `P, Q, R`, written with `parent=`: for P in 1…3 a point, under it Q in 0…P−1, under each R in 0…Q−1. `Q = [0, 0, 1, 0, 1, 2]`, `R = [0, 0, 0, 1]`, `R._parent = [2, 4, 5, 5]` |
| values `u(P, Q)`, `w(P, Q, R)` | `u = 10·P + Q`: `[10, 20, 21, 30, 31, 32]`; `w = 100·P + 10·Q + R`: `[210, 310, 320, 321]` |
| check also | `to_dense(f)`: B ticks `[10, 15, 20, 25, 35]`, NaN where not measured |

## R+ fixture definition (plan 6d)

| Item | Definition |
|---|---|
| file | `<out>/rplus.lbd`, title `R plus` |
| written | axis `x` `[0, 1, 2, 3, 4]`, value `y(x)` float64 zeros, saved; then opened with mode r+: `y` at x index 2 (from 0) set to 7, meta `edited = 1`, saved in place |
| check | `y = [0, 0, 7, 0, 0]`, `meta.edited = 1`, title `R plus` |

## Reading while measuring

`run_all.py` then starts every language's `read_live` command (`{file}` / `LBD_FILE`: a
`measuring.lbd` path) and a Python Writer that writes `measuring.lbd.writing` slowly: 200 rows,
row `i` (0-based) of `S21(power, freq)` (5 frequencies) all `(i+1)·(1+1j)`, a growing `time`
with `T = 10·time`, and a group `G` (`gi → gj`): at row `i` the points `gi = i`,
`gj = 0 … i mod 3`, with `gv = 10·gi + gj`. A reader:

1. creates `ready-<language id>` next to the file once it is running (the writer waits for all);
2. reads the `.writing` file again and again until it is renamed: every read must show the
   measured rows as a run from the first, each one right, `T = 10·time`, and every point of
   `gv` right or not measured yet (`NaN`);
3. reads the finished `measuring.lbd` (every row measured), and fails unless at least two reads
   saw the measurement part-way.

When the format gains a feature, extend these tables and every language's `write`/`check`
script together.

<!-- --8<-- [end:fixture] -->
