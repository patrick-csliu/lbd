"""Histogram: counts how many numbers fall in each bin.

`count_bins` and `auto_bins` are the one way of counting: the plot type here, the operation
Histogram of LBD Viewer and the histograms beside a scatter plot all use them.
"""

from typing import Any, Optional, Tuple

import numpy as np

MOST_BINS = 10_000


def count_bins(values: Any, bins: Any = 50, range: Optional[Tuple[float, float]] = None) -> Tuple[np.ndarray, np.ndarray]:
    """(edges, counts) of the finite numbers in `values`. `bins`: how many, or the edges themselves
    (then `range` is ignored, and blocks counted with the same edges simply add up). `range`: (lo, hi);
    None: the numbers' own. lo == hi widens by 0.5 each way. As numpy: the last bin includes its
    right edge; numbers outside aren't counted. Counts are int64."""
    numbers = np.asarray(values).ravel()
    if np.iscomplexobj(numbers):
        raise ValueError("these numbers are complex: choose how to show complex values first")
    numbers = numbers.astype(float, copy=False)
    numbers = numbers[np.isfinite(numbers)]
    if np.ndim(bins) == 0:
        if isinstance(bins, (bool, np.bool_)) or int(bins) != bins or not 2 <= bins <= MOST_BINS:
            raise ValueError(f"a histogram needs 2 to {MOST_BINS} bins, not {bins!r}")
        if range is None:
            if not numbers.size:
                raise ValueError("no values to count")
            range = (float(numbers.min()), float(numbers.max()))
        lo, hi = float(range[0]), float(range[1])
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        counts, edges = np.histogram(numbers, int(bins), (lo, hi))
    else:
        counts, edges = np.histogram(numbers, np.asarray(bins, dtype=float))
    return edges, counts.astype(np.int64, copy=False)


def auto_bins(values: Any, most: int = 200, count: Optional[int] = None,
              span: Optional[Tuple[float, float]] = None) -> int:
    """How many bins suit these numbers: Freedman-Diaconis (width 2 IQR / n^(1/3)); Sturges when the
    IQR is 0. `values`: the numbers, or a sample of them; `count`: how many there are in all, when a
    sample; `span`: (lo, hi) when the sample's own ends aren't the real ones. At least 2, at most `most`."""
    numbers = np.asarray(values, dtype=float).ravel()
    numbers = numbers[np.isfinite(numbers)]
    n = int(count) if count is not None else numbers.size
    if n < 1 or not numbers.size:
        return 2
    lo, hi = span if span is not None else (float(numbers.min()), float(numbers.max()))
    q1, q3 = np.percentile(numbers, [25, 75])
    if q3 > q1 and hi > lo:
        wanted = (hi - lo) / (2 * (q3 - q1) / n ** (1 / 3))
    else:
        wanted = np.log2(n) + 1
    return int(min(max(np.ceil(wanted), 2), most))


KIND = None
