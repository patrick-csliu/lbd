# LBD for MATLAB

Read and write LBD (`.lbd`) files from MATLAB R2021b or newer. No toolboxes are needed.

```matlab
d = lbd.Dataset("Resonator power sweep");
d.addAxis("power", -40:4:0, Unit="dBm", Label="Power");
d.addAxis("freq", linspace(4e9, 8e9, 401), Unit="Hz", Label="Frequency");
d.addValue("S21", s21, ["power" "freq"]);          % size(s21) == [11 401]
d.Meta.T_mK = 12;
d.save("sweep.lbd");

d = lbd.load("sweep.lbd");
d.Values.S21.Data
```

Install: double-click `LBD.mltbx`, or add this folder to the path with `addpath`. Full API
reference: `docs/matlab.md` in the LBD repository (also under **Help** in LBD Viewer).

| Path | Contents |
|---|---|
| `+lbd/` | the package: `lbd.Dataset`, `lbd.load`, `lbd.info`, `lbd.version` |
| `tests/` | unit tests: `runtests('tests')` |
| `crosslang/` | cross-language fixture writer and checker |
| `build_mltbx.m` | packages `+lbd` as `LBD.mltbx` (needs R2023a+ to build) |
