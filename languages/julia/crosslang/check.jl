using LBD
using Test

function check(path)
    d = LBD.load(path)
    @test d.title == "Fixture – ünïcode"
    @test d.created == "2025-03-01T23:30:00+08:00"
    again = joinpath(mktempdir(), "again.lbd")              # loaded and saved again: created kept
    LBD.save(again, LBD.load(path))
    @test LBD.load(again).created == "2025-03-01T23:30:00+08:00"
    # the id: a UUID version 7; saved to another file: a new one, made from this one
    @test d.id !== nothing && occursin(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", d.id)
    @test LBD.load(again).id != d.id && LBD.load(again).parent_id == d.id
    # a copy made by the file system, loaded and saved at its own place: the same id
    copied = joinpath(mktempdir(), "copied.lbd")
    cp(path, copied)
    LBD.save(copied, LBD.load(copied))
    @test LBD.load(copied).id == d.id
    @test d["x"].data == collect(0.0:9.0)
    @test (d["x"].unit, d["a"].unit, d["b"].unit, d["c"].unit) == ("s", "V", "A", "Hz")
    @test d["y"].data == collect(0.0:9.0) .^ 2
    @test d["y"].unit == "s^2"
    @test eltype(d["k"].data) == Int32
    @test d["k"].data == [(i + 1) * (-1)^i for i in 0:9]
    @test d["mask"].data == [iseven(i) for i in 0:9]
    @test d["M"].axes == ["a", "b"] && size(d["M"].data) == (3, 4)
    @test d["M"].data == [10.0 * i + j for i in 0:2, j in 0:3]
    @test eltype(d["Z"].data) == ComplexF64
    @test d["Z"].data == [ComplexF64(i + 1, j + 1) for i in 0:2, j in 0:3]
    @test d["T"].data == [100.0 * i + 10j + k for i in 0:2, j in 0:3, k in 0:1]
    @test isempty(d["q"].axes) && d["q"].data == 42.5
    @test d["state"].elements == ["ground", "état 1", "量子"]
    @test d["state"].data == [0, 1, 2]
    @test d["S"].data == [0.5, 1.5, 2.5]
    @test d["C"].axes == ["a"] && LBD.point_shape(d["C"]) == (2, 2)
    @test d["C"].elements == Any[["I", "Q"], nothing]
    @test !haskey(d.axes, "C_dim1") && d["a"].role === nothing
    @test d["C"].data == [100.0 * i + 10r + c for i in 0:2, r in 0:1, c in 0:1]
    m = d.meta
    @test m["sample"] == "chip – é"
    @test m["T_mK"] == 12
    @test m["names"] == ["a", "b"]
    @test vec(m["vec"]) == [1.0, 2.0, 3.0]
    @test m["mat"] == [0.0 1 2; 3 4 5]
    @test m["vna"]["ifbw_Hz"] == 1000.0 && m["vna"]["averages"] == 4
    @test d.plot["kind"] == "heatmap" && d.plot["values"] == ["M"]
    @test d.style_name == "thesis"
    @test d.matplotlib isa String && !isempty(d.matplotlib)
end

function check_live(path)
    @test !isfile(path * ".writing")
    d = LBD.load(path)
    @test d.title == "Live – ü"
    s = d["S21"].data
    @test eltype(s) == ComplexF64 && size(s) == (3, 3)
    @test s[1:2, :] == [ComplexF64(i, j) for i in 1:2, j in 1:3]
    @test all(isnan, s[3, :])
    @test d["time"].data == [0, 1, 2, 3]
    @test d["T"].data == [0, 10, 20, 30]
    @test d["T"].measured === nothing && d["S21"].measured === nothing
    @test eltype(d["n"].data) == Int32
    @test d["n"].data == [0 3 0; 7 0 0]
    @test d["n"].measured == [false true false; true false false]
    @test d["state"].elements == ["ground", "excited"]
end

root = ARGS[1]
failed = false
for lang in sort(readdir(root))
    p = joinpath(root, lang, "fixture.lbd")
    isfile(p) || continue
    ts = @testset "julia reads $lang" begin
        check(p)
    end
    p = joinpath(root, lang, "live.lbd")
    isfile(p) || continue
    @testset "julia reads $lang live.lbd" begin
        check_live(p)
    end
end
