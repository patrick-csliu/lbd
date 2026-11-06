"""The plot type Histogram: counting, the model and the drawing."""

import numpy as np
import pytest

from lbd.plot.histogram import auto_bins, count_bins


def test_count_bins_is_numpys_histogram():
    x = np.random.default_rng(1).normal(size=1000)
    edges, counts = count_bins(x, 17)
    want, want_edges = np.histogram(x, 17)
    assert np.array_equal(edges, want_edges) and np.array_equal(counts, want)
    assert counts.dtype == np.int64
    _, top = count_bins([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    assert top.tolist() == [1, 2]                      # the last bin includes its right edge


def test_count_bins_ignores_nan_and_infinity():
    _, counts = count_bins([1.0, 2.0, np.nan, np.inf, -np.inf], 2)
    assert counts.sum() == 2


def test_numbers_outside_a_range_are_not_counted():
    edges, counts = count_bins([0.0, 1.0, 5.0], 2, (0.0, 2.0))
    assert edges.tolist() == [0.0, 1.0, 2.0] and counts.tolist() == [1, 1]


def test_blocks_counted_with_the_same_edges_add_up():
    x = np.random.default_rng(2).normal(size=1000)
    edges, whole = count_bins(x, 30)
    parts = sum(count_bins(block, edges)[1] for block in np.array_split(x, 7))
    assert np.array_equal(parts, whole)


def test_one_number_widens_the_range():
    edges, counts = count_bins([3.0, 3.0], 2)
    assert edges[0] == 2.5 and edges[-1] == 3.5 and counts.sum() == 2


def test_no_values_says_so():
    with pytest.raises(ValueError, match="no values to count"):
        count_bins([np.nan], 5)
    edges, counts = count_bins([np.nan], 5, (0.0, 1.0))        # with a range there is something to show
    assert edges.size == 6 and counts.sum() == 0


def test_complex_is_refused():
    with pytest.raises(ValueError, match="complex"):
        count_bins(np.array([1 + 1j]), 5)


@pytest.mark.parametrize("bins", [1, 0, -3, 10_001, 2.5, True])
def test_bins_outside_the_limits_say_so(bins):
    with pytest.raises(ValueError, match="2 to 10000"):
        count_bins([1.0, 2.0], bins)


def test_auto_bins_grows_with_the_data_and_stays_in_limits():
    rng = np.random.default_rng(3)
    few, many = auto_bins(rng.normal(size=100)), auto_bins(rng.normal(size=100_000))
    assert 2 <= few < many <= 200
    assert auto_bins(rng.normal(size=100_000), most=20) == 20
    assert auto_bins([1.0]) == 2 and auto_bins([]) == 2


def test_auto_bins_from_a_sample():
    x = np.random.default_rng(4).normal(size=1_000_000)
    sample = x[::100]
    assert auto_bins(sample) < auto_bins(sample, count=x.size)
    wide = auto_bins(sample, count=x.size, span=(-100.0, 100.0), most=10_000)
    assert wide > auto_bins(sample, count=x.size, most=10_000)
    whole = auto_bins(x, most=10_000)
    assert abs(auto_bins(sample, count=x.size, span=(x.min(), x.max()), most=10_000) - whole) <= 0.05 * whole


def test_auto_bins_with_no_spread():
    assert auto_bins(np.ones(1024)) == 11              # Sturges: log2(n) + 1
    x = np.r_[np.zeros(1000), 1.0]                     # the middle half is one number
    assert auto_bins(x) == int(np.ceil(np.log2(x.size) + 1))
