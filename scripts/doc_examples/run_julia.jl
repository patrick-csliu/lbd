# Run the Julia documentation blocks listed in ARGS[1] (see scripts/check_doc_examples.py).
using JSON3, LBD

const PRELUDE = """
using LBD
f = collect(range(4e9, 8e9, 401)); p = collect(-40.0:4:0)
s21 = exp.(1im .* (p * f') .* 1e-10)
t = collect(range(0, 1e-6, 201)); v = sin.(2e7 .* t); counts = collect(1:201)
d = LBD.Dataset("prelude")
add_axis!(d, "power", p; unit="dBm"); add_axis!(d, "freq", f; unit="Hz"); add_axis!(d, "t", t; unit="s")
WITHVALUES
LBD.save("sweep.lbd", d); LBD.save("run.lbd", d)
temperatures = [10, 20]; out = mkpath("out"); measure(T) = ones(401)
"""
const VALUES = """add_value!(d, "S21", s21, ["power", "freq"]); add_value!(d, "trace", v, "t")"""

blocks = JSON3.read(read(ARGS[1], String))
cd(mktempdir())
fails = 0
for b in blocks
    code = String(b.code)
    if occursin("->", code) || occursin("mutable struct", code) || occursin("::AbstractString", code)
        println("sig  ", b.where); continue
    end
    global fails
    err = nothing
    for prelude in (replace(PRELUDE, "WITHVALUES" => ""), replace(PRELUDE, "WITHVALUES" => VALUES))
        m = Module()
        try
            Base.include_string(m, prelude * "\n" * code)
            err = nothing; break
        catch e
            err = sprint(showerror, e)
        end
    end
    if err === nothing
        println("ok   ", b.where)
    else
        fails += 1; println("FAIL ", b.where, " ", first(split(err, "\n")))
    end
end
println("$(length(blocks) - fails)/$(length(blocks)) ok")
