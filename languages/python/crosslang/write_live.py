"""A Python measurement written slowly, for every language to read while it is written
(tests/crosslang/README.md, "Reading while measuring"). Starts when every reader is ready."""

import sys
import time
from pathlib import Path

import numpy as np

import lbd

path, rows, readers = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
end = time.monotonic() + 180
while not all((path.parent / f"ready-{r}").exists() for r in readers):
    if time.monotonic() > end:
        sys.exit(f"  the readers {readers} weren't ready after 180 s")
    time.sleep(0.1)
with lbd.Writer(path, title="Read while measuring", flush_every=0.1) as w:
    w.add_axis("power", np.arange(1.0, rows + 1))
    w.add_axis("freq", np.linspace(0, 1, 5))
    w.add_axis("time", grows=True)
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    w.add_value("T", axes="time")
    w.add_group("G")                                     # a variable sweep: i % 3 + 1 points per row
    w.add_axis("gi", group="G")
    w.add_axis("gj", group="G")
    w.add_value("gv", axes=["gi", "gj"])
    for i in range(rows):
        w.write(power=i, S21=np.full(5, (i + 1) * (1 + 1j)))
        w.write(time=float(i), T=10.0 * i)
        j = np.arange(i % 3 + 1)
        w.write(gi=i, gj=j, gv=10.0 * i + j)
        time.sleep(0.05)
print(f"  python wrote {rows} rows while they were read")
