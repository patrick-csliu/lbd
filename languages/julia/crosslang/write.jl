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

# The live fixture: written while "measuring" with LBD.Writer, stopped early.
w = LBD.Writer(joinpath(out, "live.lbd"); title="Live – ü")
add_axis!(w, "power", [1.0, 2.0, 3.0]; unit="dBm")
add_axis!(w, "freq", [0.0, 0.5, 1.0]; unit="Hz")
add_axis!(w, "state"; elements=["ground", "excited"])
add_axis!(w, "time"; unit="s", grows=true)
add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)
add_value!(w, "T"; axes="time")
add_value!(w, "n"; axes=["state", "power"], dtype=Int32)
for i in 1:2                                           # power 3 is never measured
    write!(w; power=i, S21=[ComplexF64(i, j) for j in 1:3])
end
write!(w; time=0.0, T=0.0)
write!(w; time=[1.0, 2.0], T=[10.0, 20.0])
write!(w; time=3.0, T=30.0)
write!(w; state="excited", power=1, n=7)
write!(w; state="ground", power=2, n=3)
close(w; stopped=true)

# The groups fixture (format 2.0): variable sweeps, the same in every language.
g = LBD.Dataset("Groups")
add_group!(g, "AB")
add_axis!(g, "A"; group="AB", unit="V")
add_axis!(g, "B"; group="AB", unit="Hz")
add_axis!(g, "C", [0.1, 0.2, 0.3])
add_value!(g, "f"; axes=["A", "B"])
add_value!(g, "q"; axes="A")
add_value!(g, "h"; axes=["A", "B", "C"])
add_value!(g, "cov"; axes=["A", "B"], shape=(2, 2))
add_value!(g, "n"; axes=["A", "B"], dtype=Int16)
add_group!(g, "PQR")
for a in ("P", "Q", "R")
    add_axis!(g, a; group="PQR")
end
add_value!(g, "u"; axes=["P", "Q"])
add_value!(g, "w"; axes="PQR")
for (a, bs) in (1 => [10], 2 => [10, 20], 3 => [15, 25, 35])          # by coordinates
    for b in bs
        write!(g; A=a, B=b, f=100a + b, h=Float64[a, b, a + b], cov=Float64[a b; b -a])
    end
    write!(g; A=a, q=1.5a)
end
write!(g; A=1, B=10, n=1)
write!(g; A=3, B=25, n=2)
for p in 1:3                                                           # by parent=
    i = write!(g; P=p)
    for q in 0:p-1
        k = write!(g; parent=i, Q=q, u=10p + q)
        r = collect(0:q-1)
        write!(g; parent=k, R=r, w=100p .+ 10q .+ r)
    end
end
LBD.save(joinpath(out, "groups.lbd"), g)

# The r+ fixture (plan 6d): saved, then opened with mode="r+" and changed in place.
r = LBD.Dataset("R plus")
add_axis!(r, "x", collect(0.0:4))
add_value!(r, "y", zeros(5), "x")
LBD.save(joinpath(out, "rplus.lbd"), r)
LBD.open(joinpath(out, "rplus.lbd"); mode="r+") do o
    write!(o; x=3, y=7.0)
    o.meta["edited"] = 1
    LBD.save(o)
end
