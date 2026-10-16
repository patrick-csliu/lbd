import sys
from pathlib import Path

import numpy as np

import lbd

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

i3, j4, k2 = np.arange(3)[:, None, None], np.arange(4)[None, :, None], np.arange(2)[None, None, :]
d = lbd.Dataset(title="Fixture – ünïcode")
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
