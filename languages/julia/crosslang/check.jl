using LBD
using Test

function check(path)
    d = LBD.load(path)
    @test d.title == "Fixture – ünïcode"
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

root = ARGS[1]
failed = false
for lang in sort(readdir(root))
    p = joinpath(root, lang, "fixture.lbd")
    isfile(p) || continue
    ts = @testset "julia reads $lang" begin
        check(p)
    end
end
