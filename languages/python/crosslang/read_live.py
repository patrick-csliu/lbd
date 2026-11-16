"""Read a measurement while it is written (tests/crosslang/README.md, "Reading while measuring")."""

import sys
import time
import warnings
from pathlib import Path

import numpy as np

import lbd

path = Path(sys.argv[1])
writing = Path(str(path) + ".writing")
(path.parent / "ready-python").touch()
end = time.monotonic() + 120
while not writing.exists() and not path.exists():
    if time.monotonic() > end:
        sys.exit(f"  python: {writing.name} never appeared")
    time.sleep(0.05)


def check(d, final):
    s = d["S21"].data
    measured = [not np.all(np.isnan(row)) for row in s]
    assert measured == sorted(measured, reverse=True), "measured rows are not a run from the start"
    for i in np.flatnonzero(measured):
        assert np.all(s[i] == (i + 1) * (1 + 1j)), f"row {i} is wrong"
    np.testing.assert_array_equal(d["T"].data, 10.0 * np.arange(len(d["time"])))
    c, gv = d.coords("gv"), d["gv"].data                  # the group: each point right, or not yet measured
    assert np.all(np.isnan(gv) | (gv == 10 * c["gi"] + c["gj"])), "a point of the group is wrong"
    if final:
        assert all(measured), "not every row in the finished file"
        assert len(gv) == sum(i % 3 + 1 for i in range(len(s))) and not np.isnan(gv).any(), "group points missing"
    return len(d["time"])


rows, failures = [], 0
while writing.exists():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", lbd.LBDWarning)
            d = lbd.load(writing)
    except (OSError, lbd.LBDError):         # opened before SWMR started, or renamed meanwhile
        failures += 1
        if failures > 50 and writing.exists():
            raise
        time.sleep(0.05)
        continue
    failures = 0
    rows.append(check(d, False))
    time.sleep(0.1)
n = check(lbd.load(path), True)
growing = [r for r in rows if 0 < r < n]
assert len(growing) >= 2, f"only {len(rows)} live reads ({rows}); the measurement wasn't seen while it grew"
print(f"  python read a Python measurement live: {len(rows)} reads, {min(growing)} ... {max(growing)} rows, then {n}: OK")
