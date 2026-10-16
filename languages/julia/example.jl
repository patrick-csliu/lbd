using LBD

f = collect(range(4e9, 8e9, 401))
p = collect(-40.0:4:0)
s21 = exp.(1im .* (p * f') .* 1e-10)               # size (11, 401) = (power, freq)

d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", p; unit="dBm", label="Power")
add_axis!(d, "freq", f; unit="Hz", label="Frequency")
add_value!(d, "S21", s21, ["power", "freq"])
t = collect(range(0, 1e-6, 201))
add_axis!(d, "t", t; unit="s", label="Time")
add_value!(d, "trace", sin.(2e7 .* t), "t"; unit="V")
d.meta["T_mK"] = 12
d.meta["vna"] = Dict("ifbw_Hz" => 1000.0, "averages" => 4)
LBD.save("example.lbd", d)

d = LBD.load("example.lbd")
size(d["S21"].data)
