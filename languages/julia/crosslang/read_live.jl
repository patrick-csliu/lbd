# Read a measurement while it is written (tests/crosslang/README.md, "Reading while measuring").
using LBD
using Logging

path = ARGS[1]
writing = path * ".writing"
# Julia compiles a function at its first call: read a small file once before saying "ready", so
# the first read of the measurement isn't seconds late (on a busy computer it could miss it).
let warm = joinpath(mktempdir(), "warm.lbd"), d = LBD.Dataset("warm")
    add_axis!(d, "x", [1.0, 2.0])
    add_value!(d, "y"; axes="x", dtype=ComplexF64)
    LBD.save(warm, d)
    LBD.load(warm)
end
touch(joinpath(dirname(path), "ready-julia"))
deadline = time() + 120
while !isfile(writing) && !isfile(path)
    time() > deadline && error("julia: $(basename(writing)) never appeared")
    sleep(0.05)
end

function check(d, final)
    s = d["S21"].data
    measured = [!all(isnan, s[i, :]) for i in axes(s, 1)]
    issorted(measured; rev=true) || error("measured rows are not a run from the start")
    for i in findall(measured)
        all(==(ComplexF64(i, i)), s[i, :]) || error("row $i is wrong")
    end
    d["T"].data == 10.0 .* (0:length(d["time"].data)-1) || error("T is wrong")
    c, gv = coords(d, "gv"), d["gv"].data              # the group: each point right, or not yet measured
    all(@. isnan(gv) | (gv == 10 * c["gi"] + c["gj"])) || error("a point of the group is wrong")
    final && !all(measured) && error("not every row in the finished file")
    final && (length(gv) != sum(i % 3 + 1 for i in 0:size(s, 1)-1) || any(isnan, gv)) && error("group points missing")
    return length(d["time"].data)
end

rows, failures = Int[], 0
while isfile(writing)
    d = try
        with_logger(NullLogger()) do
            LBD.load(writing)
        end
    catch e                               # opened before SWMR started, or renamed meanwhile
        global failures += 1
        (failures > 50 && isfile(writing)) && rethrow()
        sleep(0.05)
        continue
    end
    global failures = 0
    push!(rows, check(d, false))
    sleep(0.1)
end
n = check(LBD.load(path), true)
growing = filter(r -> 0 < r < n, rows)
length(growing) >= 2 || error("only $(length(rows)) live reads ($rows); the measurement wasn't seen while it grew")
println("  julia read a Python measurement live: $(length(rows)) reads, $(minimum(growing)) ... $(maximum(growing)) rows, then $n: OK")
