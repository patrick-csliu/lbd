using LBD
using OrderedCollections: OrderedDict

out = ARGS[1]
mkpath(out)

d = LBD.Dataset("Fixture – ünïcode"; created="2025-03-01T23:30:00+08:00")
add_axis!(d, "x", collect(0.0:9.0); unit="s")
add_axis!(d, "a", [1.0, 2.0, 3.0]; unit="V")
add_axis!(d, "b", [1.0, 2.0, 3.0, 4.0]; unit="A")
add_axis!(d, "c", [1.0, 2.0]; unit="Hz")
add_value!(d, "y", collect(0.0:9.0) .^ 2, "x"; unit="s^2")
add_value!(d, "k", Int32[(i + 1) * (-1)^i for i in 0:9], "x")
add_value!(d, "mask", [iseven(i) for i in 0:9], "x")
add_value!(d, "M", [10.0 * i + j for i in 0:2, j in 0:3], ["a", "b"])
add_value!(d, "Z", [ComplexF64(i + 1, j + 1) for i in 0:2, j in 0:3], ["a", "b"])
add_value!(d, "T", [100.0 * i + 10j + k for i in 0:2, j in 0:3, k in 0:1], ["a", "b", "c"])
add_value!(d, "q", 42.5)
add_axis!(d, "state"; elements=["ground", "état 1", "量子"])
add_value!(d, "S", [0.5, 1.5, 2.5], "state")
add_value!(d, "C", [100.0 * i + 10r + c for i in 0:2, r in 0:1, c in 0:1], "a"; shape=(2, 2),
           elements=[["I", "Q"], nothing])
d.meta["sample"] = "chip – é"
d.meta["T_mK"] = 12
d.meta["names"] = ["a", "b"]
d.meta["vec"] = [1.0, 2.0, 3.0]
d.meta["mat"] = [0.0 1 2; 3 4 5]
d.meta["vna"] = OrderedDict("ifbw_Hz" => 1000.0, "averages" => 4)
d.plot = Dict{String,Any}("kind" => "heatmap", "values" => ["M"])
d.style_name = "thesis"
d.matplotlib = "3.9.0"   # Julia has no matplotlib: a fixed version for the test
LBD.save(joinpath(out, "fixture.lbd"), d)
