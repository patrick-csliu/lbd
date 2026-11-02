"""The heartbeat check (tests/crosslang/README.md, "The heartbeat"): in folder OUT, `stopped.lbd`
written 3 of 4 rows and left without finishing, and `finished.lbd` written to the end."""

import sys
import time
from pathlib import Path

import numpy as np

import lbd

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, rows in (("stopped", 3), ("finished", 4)):
    w = lbd.Writer(out / f"{name}.lbd", flush_every=0.05)
    w.add_axis("power", np.arange(4.0), unit="dBm")
    w.add_axis("freq", np.linspace(1, 2, 7), unit="Hz")
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    for i in range(rows):
        w.write(power=i, S21=np.ones(7))
    if name == "stopped":
        time.sleep(11)                        # the heartbeat is rewritten with all three rows
        w._abandon()                          # as a crash: no finish
    else:
        w.close()
