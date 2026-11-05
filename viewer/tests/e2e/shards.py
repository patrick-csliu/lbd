"""Split the browser tests into shards that take about as long each, for CI jobs running side by
side (`scripts/test_all.py --shard 2/3`, or `LBD_SHARD=2/3 pytest viewer/tests/e2e`).

Whole test files go to a shard, the longest first to the least loaded one, by the times in
durations.json (seconds per file, from a full run: `scripts/test_all.py --record-durations`). A
file not listed there counts as the median of those that are, so a new test file is still run
(in exactly one shard).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DURATIONS = Path(__file__).with_name("durations.json")


def parse(text: Optional[str]) -> Optional[Tuple[int, int]]:
    """"2/3" → (2, 3); None or "" → None. ValueError for anything else."""
    if not text:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", text)
    if not m or not 1 <= int(m[1]) <= int(m[2]):
        raise ValueError(f"a shard is i/N with 1 <= i <= N, e.g. 2/3; not {text!r}")
    return int(m[1]), int(m[2])


def durations() -> Dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(DURATIONS.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def assign(files: Iterable[str], count: int, times: Optional[Dict[str, float]] = None) -> List[List[str]]:
    """The files in `count` shards of about equal time (file names as in durations.json)."""
    times = durations() if times is None else times
    files = sorted(set(files))
    known = sorted(times.values())
    median = known[len(known) // 2] if known else 1.0
    cost = {f: times.get(f, median) for f in files}
    shards: List[List[str]] = [[] for _ in range(count)]
    load = [0.0] * count
    for f in sorted(files, key=lambda f: (-cost[f], f)):         # the longest first
        i = min(range(count), key=lambda k: (load[k], k))
        shards[i].append(f)
        load[i] += cost[f]
    return [sorted(s) for s in shards]
