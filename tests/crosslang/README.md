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

- **write** creates `<out>/fixture.lbd` with exactly the content below. `<out>` is given as
  `{out}` / `LBD_OUT`.
- **check** finds every `<root>/*/fixture.lbd` (`{root}` / `LBD_ROOT`), compares each with the
  definition, prints one line per file (`<language> reads <writer> OK` or `FAILED: <reason>`),
  and exits non-zero if any check failed.

## Fixture definition (0-based indices i, j, k)

| Item | Definition |
|---|---|
| title | `Fixture – ünïcode` |
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
| meta | `sample="chip – é"`, `T_mK=12` (int), `names=["a","b"]`, `vec=[1,2,3]`, `mat=[[0,1,2],[3,4,5]]` (2×3), `vna.ifbw_Hz=1000.0`, `vna.averages=4` (int) |
| plot | `spec={"kind":"heatmap","values":["M"]}`, `style_name="thesis"`, `matplotlib` a non-empty version text (Python writes the installed matplotlib version; MATLAB and Julia write `"3.9.0"`) |

When the format gains a feature, extend this table and every language's `write`/`check`
script together.

<!-- --8<-- [end:fixture] -->
