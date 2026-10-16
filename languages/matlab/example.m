f = linspace(4e9, 8e9, 401);
p = -40:4:0;
s21 = exp(1i * (p' * f) * 1e-10);                  % 11 x 401 = (power, freq)

d = lbd.Dataset("Resonator power sweep");
d.addAxis("power", p, Unit="dBm", Label="Power");
d.addAxis("freq", f, Unit="Hz", Label="Frequency");
d.addValue("S21", s21, ["power" "freq"]);
t = linspace(0, 1e-6, 201);
d.addAxis("t", t, Unit="s", Label="Time");
d.addValue("trace", sin(2e7 * t), "t", Unit="V");
d.Meta.T_mK = 12;
d.Meta.vna = struct("ifbw_Hz", 1000, "averages", 4);
d.save("example.lbd");

d = lbd.load("example.lbd")
size(d.Values.S21.Data)
