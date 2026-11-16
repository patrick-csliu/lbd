"""Large mock data files: the four engine tests, for trying LBD Viewer on big data by hand.

    uv run python viewer/tests/mock_large.py FOLDER

writes the `.lbd` files into FOLDER (about 214 MB, a few seconds). They are the engine tests the
Explore view was measured with, with the same numbers as the Labber logs made from the same
definitions (noise included: `rng` below is that test's random generator), so LBD and Labber can
be compared on identical data:

1. one curve of 1 000 000 points: a one-point spike, a three-point dip, a gap of 100 points;
2. 1000 traces x 10 000 points: one dip per trace, moving; trace 437 has a spike;
3. a 4001 x 4001 map: a bending resonance, one hot cell, a 16 x 16 checkerboard;
4. a 5 x 4 map with uneven x (1, 2, 4, 8, 16), value = column + 5 x row: small and exact.

Each file has a saved view. docs/developers/mock-data.md says what to look for in each.
"""

import sys
from pathlib import Path
from typing import List

import numpy as np

import lbd

# The linear congruential generator of the engine test: s = (A*s + C) mod 2^32, giving s / 2^32.
A, C, M = 1664525, 1013904223, 2 ** 32


def rng(seed: int, n: int) -> np.ndarray:
    """The first n numbers of the engine test's generator started at `seed`, in [0, 1).

    Computed a block at a time: step j of a block is s_j = a_j * s + c_j (mod M), with a_j and
    c_j worked out once, so numpy does the work instead of a Python loop of n steps."""
    block = 1 << 16
    a_pow, c_sum = np.empty(block, np.uint64), np.empty(block, np.uint64)
    ap, cs = 1, 0
    for j in range(block):
        ap, cs = ap * A % M, (cs * A + C) % M
        a_pow[j], c_sum[j] = ap, cs
    out, s = np.empty(n), seed % M
    for start in range(0, n, block):
        k = min(block, n - start)
        seq = (a_pow[:k] * np.uint64(s) + c_sum[:k]) % np.uint64(M)   # wraps mod 2^64, and 2^32 divides 2^64
        out[start:start + k] = seq / M
        s = int(seq[-1])
    return out


def accuracy() -> lbd.Dataset:
    """Engine test 1: one curve of 1 000 000 points with a one-point spike (at 731 234), a
    three-point dip (200 000-200 002) and a gap of 100 points (500 000-500 099). Nothing may be
    lost when the view is reduced to the screen's pixels."""
    n = 1_000_000
    x = np.arange(n) / (n - 1)
    y = np.sin(2 * np.pi * 3 * x) + 0.02 * (rng(1, n) - 0.5)
    y[731234] = 5
    y[200000:200003] = -3
    y[500000:500100] = np.nan
    d = lbd.Dataset(title="Engine test 1: accuracy, 1 trace x 1M points")
    d.add_axis("x", x)
    d.add_value("signal", y, axes="x")
    d.plot = {"kind": "curve"}
    return d


def traces() -> lbd.Dataset:
    """Engine test 2: 1000 traces x 10 000 points, one dip per trace moving from 4.5 to 5.5 GHz;
    trace 437 has a spike (+3 at point 7000)."""
    nt, n = 1000, 10000
    f = 4 + 2 * np.arange(n) / (n - 1)
    y = -20 / (1 + ((f[None, :] - (4.5 + np.arange(nt)[:, None] / (nt - 1))) / 0.01) ** 2) \
        + 0.3 * (rng(2, nt * n).reshape(nt, n) - 0.5)
    y[437, 7000] = 3
    d = lbd.Dataset(title="Engine test 2: 1000 traces x 10000 points")
    d.add_axis("trace", np.arange(float(nt)), label="Trace")
    d.add_axis("freq", f * 1e9, unit="Hz", label="Frequency")
    d.add_value("S21", y, axes=["trace", "freq"], unit="dB")
    d.plot = {"kind": "curve", "x": "freq", "series": "trace"}
    return d


def big_map() -> lbd.Dataset:
    """Engine test 3: a 4001 x 4001 map with a cosine-shaped resonance, one hot cell (+10) and a
    16 x 16 checkerboard of +5 and -15 near the top right corner."""
    n = 4001
    f = 4 + 2 * np.arange(n) / (n - 1)
    flux = -1 + 2 * np.arange(n) / (n - 1)
    z = -20 / (1 + ((f[None, :] - (5 + 0.5 * np.cos(np.pi * flux))[:, None]) / 0.02) ** 2) \
        + 0.5 * (rng(3, n * n).reshape(n, n) - 0.5)
    hi, hj, c0 = round(n * 0.3), round(n * 0.7), n - 60
    z[hj, hi] = 10
    jj, ii = np.mgrid[c0:c0 + 16, c0:c0 + 16]
    z[c0:c0 + 16, c0:c0 + 16] = np.where((ii + jj) % 2 == 1, 5.0, -15.0)
    d = lbd.Dataset(title="Engine test 3: map 4001 x 4001")
    d.add_axis("flux", flux * 1e-3, unit="A", label="Flux")
    d.add_axis("freq", f * 1e9, unit="Hz", label="Frequency")
    d.add_value("S21", z, axes=["flux", "freq"], unit="dB")
    d.plot = {"kind": "heatmap", "x": "freq", "y": "flux"}
    return d


def small_map() -> lbd.Dataset:
    """Engine test 4: a 5 x 4 map with uneven x (1, 2, 4, 8, 16); value = column + 5 x row, so
    every cell's value says where it is."""
    d = lbd.Dataset(title="Engine test 4: small map, uneven x")
    d.add_axis("x", np.array([1.0, 2, 4, 8, 16]))
    d.add_axis("y", np.array([10.0, 20, 30, 40]))
    d.add_value("value", np.arange(5.0)[None, :] + 5 * np.arange(4.0)[:, None], axes=["y", "x"])
    d.plot = {"kind": "heatmap", "x": "x", "y": "y"}
    return d


MAKERS = {"1 accuracy.lbd": accuracy, "2 traces.lbd": traces, "3 map.lbd": big_map, "4 small map.lbd": small_map}


def write_all(folder: Path) -> List[Path]:
    """Write the four engine tests into `folder`; returns their paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, make in MAKERS.items():
        make().save(folder / name)
        out.append(folder / name)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in write_all(Path(sys.argv[1])):
        print(p)
