import sys
from pathlib import Path

import numpy as np

import lbd

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

i3, j4, k2 = np.arange(3)[:, None, None], np.arange(4)[None, :, None], np.arange(2)[None, None, :]
d = lbd.Dataset(title="Fixture – ünïcode", created="2025-03-01T23:30:00+08:00")
d.add_axis("x", np.arange(10.0), unit="s")
d.add_axis("a", [1.0, 2.0, 3.0], unit="V")
d.add_axis("b", [1.0, 2.0, 3.0, 4.0], unit="A")
d.add_axis("c", [1.0, 2.0], unit="Hz")
d.add_value("y", np.arange(10.0) ** 2, axes="x", unit="s^2")
d.add_value("k", np.array([(i + 1) * (-1) ** i for i in range(10)], dtype=np.int32), axes="x")
d.add_value("mask", np.arange(10) % 2 == 0, axes="x")
d.add_value("M", (10 * i3 + j4)[:, :, 0].astype(float), axes=["a", "b"])
d.add_value("Z", ((i3 + 1) + 1j * (j4 + 1))[:, :, 0], axes=["a", "b"])
d.add_value("T", (100 * i3 + 10 * j4 + k2).astype(float), axes=["a", "b", "c"])
d.add_value("q", 42.5)
d.add_axis("state", elements=["ground", "état 1", "量子"])
d.add_value("S", [0.5, 1.5, 2.5], axes="state")
r2, c2 = np.arange(2)[None, :, None], np.arange(2)[None, None, :]
d.add_value("C", (100 * i3[:, :1, :1] + 10 * r2 + c2).astype(float), axes="a", shape=(2, 2),
            elements=[["I", "Q"], None])
d.meta = {
    "sample": "chip – é",
    "T_mK": 12,
    "names": ["a", "b"],
    "vec": [1.0, 2.0, 3.0],
    "mat": np.array([[0.0, 1, 2], [3, 4, 5]]),
    "vna": {"ifbw_Hz": 1000.0, "averages": 4},
}
d.plot = {"kind": "heatmap", "values": ["M"]}
d.style_name = "thesis"
d.save(out / "fixture.lbd")

# The live fixture: written while "measuring" with lbd.Writer, stopped early.
with lbd.Writer(out / "live.lbd", title="Live – ü") as w:
    w.add_axis("power", [1.0, 2.0, 3.0], unit="dBm")
    w.add_axis("freq", [0.0, 0.5, 1.0], unit="Hz")
    w.add_axis("state", elements=["ground", "excited"])
    w.add_axis("time", unit="s", grows=True)
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    w.add_value("T", axes="time")
    w.add_value("n", axes=["state", "power"], dtype="int32")
    for i in range(2):                                   # power 3 is never measured
        w.write(power=i, S21=(i + 1) + 1j * np.arange(1, 4))
    w.write(time=0.0, T=0.0)
    w.write(time=[1.0, 2.0], T=[10.0, 20.0])
    w.write(time=3.0, T=30.0)
    w.write(state="excited", power=0, n=7)
    w.write(state="ground", power=1, n=3)
    w.close(stopped=True)

# The groups fixture (format 2.0): variable sweeps, the same in every language.
g = lbd.Dataset(title="Groups")
g.add_group("AB")
g.add_axis("A", group="AB", unit="V")
g.add_axis("B", group="AB", unit="Hz")
g.add_axis("C", [0.1, 0.2, 0.3])
g.add_value("f", axes=["A", "B"])
g.add_value("q", axes="A")
g.add_value("h", axes=["A", "B", "C"])
g.add_value("cov", axes=["A", "B"], shape=(2, 2))
g.add_value("n", axes=["A", "B"], dtype="int16")
g.add_group("PQR")
for a in "PQR":
    g.add_axis(a, group="PQR")
g.add_value("u", axes=["P", "Q"])
g.add_value("w", axes="PQR")
for a, bs in ((1, [10]), (2, [10, 20]), (3, [15, 25, 35])):          # by coordinates
    for b in bs:
        g.write(A=a, B=b, f=100 * a + b, h=[a, b, a + b], cov=[[a, b], [b, -a]])
    g.write(A=a, q=1.5 * a)
g.write(A=1, B=10, n=1)
g.write(A=3, B=25, n=2)
for p in range(1, 4):                                                 # by parent=
    i = g.write(P=p)
    for q in range(p):
        k = g.write(parent=i, Q=q, u=10 * p + q)
        r = np.arange(q)
        g.write(parent=k, R=r, w=100 * p + 10 * q + r)
g.save(out / "groups.lbd")
