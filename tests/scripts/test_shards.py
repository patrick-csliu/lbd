"""The browser tests split into shards (viewer/tests/e2e/shards.py) for CI jobs side by side: every
test file in exactly one shard, the shards about equally long, a new file still run."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "viewer" / "tests" / "e2e"))
import shards  # noqa: E402


def test_every_file_in_exactly_one_shard_and_the_shards_balanced():
    files = sorted(p.name for p in (REPO / "viewer" / "tests" / "e2e").glob("test_*.py"))
    parts = shards.assign(files, 3)
    together = [f for part in parts for f in part]
    assert sorted(together) == files and len(together) == len(set(together))
    times = shards.durations()
    if times:                                                    # balanced by the recorded times
        loads = [sum(times.get(f, 0) for f in part) for part in parts]
        assert max(loads) - min(loads) <= max(times.values()) + 1


def test_a_new_file_counts_as_the_median_and_the_shard_is_checked():
    parts = shards.assign(["a.py", "b.py", "c.py", "new.py"], 2, {"a.py": 100.0, "b.py": 10.0, "c.py": 20.0})
    assert parts == [["a.py"], ["b.py", "c.py", "new.py"]]                    # new.py: the median, 20 s
    assert shards.parse("2/3") == (2, 3) and shards.parse(None) is None
    for bad in ("0/3", "4/3", "two"):
        with pytest.raises(ValueError):
            shards.parse(bad)
