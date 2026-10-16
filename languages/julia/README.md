# LBD for Julia

Read and write LBD (`.lbd`) files from Julia 1.9 or newer.

```julia
using LBD
d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", -40.0:4:0; unit="dBm", label="Power")
add_axis!(d, "freq", range(4e9, 8e9, 401); unit="Hz", label="Frequency")
add_value!(d, "S21", s21, ["power", "freq"])        # size(s21) == (11, 401)
d.meta["T_mK"] = 12
LBD.save("sweep.lbd", d)

d = LBD.load("sweep.lbd")
d["S21"].data
```

Install with `using Pkg; Pkg.develop(path="<this folder>")`. Full API reference:
`docs/julia.md` in the LBD repository (also under **Help** in LBD Viewer).
