"""How much memory the viewer may use for data, and the parts of large values it has read
(plan 6d).

The rule (decided with the user): no fixed share of RAM. The viewer uses what the operating
system reports as available now, always leaving a **reserve** for the rest of the computer
(max(2 GB, 10% of RAM) unless set), and never more than an optional fixed **maximum**.

- `Memory.room()`: the bytes the viewer may still take now.
- A value whose data fits in the room is loaded whole, as before (no lag); a bigger one is read
  by part (`lbd.open(..., hold=False)`), and the parts read are kept in `PartCache`.
- `PartCache` keeps parts while there is room and drops the oldest when there isn't (checked
  before each read and by `trim()`, called every few seconds), giving the memory back.

The source of "available" and the clock are injectable, so tests decide how much memory there is.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np

GB = 1 << 30
RESERVE_MIN = 2 * GB          # the reserve is at least this …
RESERVE_SHARE = 0.10          # … or this share of RAM, whichever is larger
TRIM_EVERY = 5.0              # seconds between checks that the parts kept still leave the reserve


def _system() -> Tuple[int, int]:
    """(total, available) bytes of this computer's memory, as the operating system reports them."""
    import psutil

    vm = psutil.virtual_memory()
    return int(vm.total), int(vm.available)


class Memory:
    """The viewer's memory rule. `reserve`, `maximum`: bytes, or None for automatic / no maximum."""

    def __init__(self, reserve: Optional[int] = None, maximum: Optional[int] = None,
                 system: Callable[[], Tuple[int, int]] = _system):
        self.reserve_setting, self.maximum = reserve, maximum
        self._system = system
        self.cache: Optional["PartCache"] = None

    def reserve(self) -> int:
        if self.reserve_setting is not None:
            return int(self.reserve_setting)
        total, _ = self._system()
        return max(RESERVE_MIN, int(RESERVE_SHARE * total))

    def room(self) -> int:
        """The bytes the viewer may still take now (0 when none)."""
        _, available = self._system()
        room = available - self.reserve()
        if self.maximum is not None:
            used = self.cache.bytes if self.cache is not None else 0
            room = min(room, int(self.maximum) - used)
        return max(0, int(room))

    def fits(self, nbytes: int) -> bool:
        return nbytes <= self.room()


class PartCache:
    """Parts of large values read from their files, most recent last; dropped oldest first when
    the memory rule says there is no room. Keys: (path, version, where, index text)."""

    def __init__(self, memory: Memory, clock: Callable[[], float] = time.monotonic):
        self.memory = memory
        memory.cache = self
        self._parts: "OrderedDict[Any, np.ndarray]" = OrderedDict()
        self.bytes = 0
        self.lock = threading.Lock()
        self.hits = self.misses = 0
        self._clock = clock

    def get(self, key: Any) -> Optional[np.ndarray]:
        with self.lock:
            arr = self._parts.get(key)
            if arr is None:
                self.misses += 1
                return None
            self._parts.move_to_end(key)
            self.hits += 1
            return arr

    def put(self, key: Any, arr: np.ndarray) -> None:
        with self.lock:
            if key in self._parts:
                return
            self._parts[key] = arr
            self.bytes += arr.nbytes
        self.trim()

    def trim(self) -> None:
        """Drop the oldest parts while the memory rule leaves no room (keeps the newest one)."""
        with self.lock:
            while len(self._parts) > 1 and self.memory.room() <= 0:
                _, old = self._parts.popitem(last=False)
                self.bytes -= old.nbytes

    def clear(self) -> None:
        with self.lock:
            self._parts.clear()
            self.bytes = 0


class Cached:
    """A large value's data seen through the part cache: `x[key]` is read from the file once,
    then from memory while it is kept. `shape` and `dtype` as the value's."""

    def __init__(self, data: Any, cache: PartCache, ident: Tuple[str, str]):
        self._data, self._cache, self._ident = data, cache, ident
        self.shape, self.dtype = data.shape, data.dtype
        self._source = data._source                   # still "on disk" for lbd (Value._read)
        self._last: Optional[tuple] = None

    ndim = property(lambda self: len(self.shape))
    size = property(lambda self: int(np.prod(self.shape, dtype=np.int64)))
    nbytes = property(lambda self: self.size * self.dtype.itemsize)

    def __len__(self) -> int:
        return self.shape[0]

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        arr = self[...]
        return arr if dtype is None else arr.astype(dtype, copy=False)

    def __getitem__(self, key: Any) -> np.ndarray:
        if isinstance(key, tuple):
            self._last = key
        k = self._ident + (self._data._where, _key_text(key))
        arr = self._cache.get(k)
        if arr is None:
            arr = self._data[key]
            self._cache.put(k, arr)
        return arr

    def read_ahead(self) -> None:
        """Read the neighbours of the last part read (one step either way along each dimension it
        fixed: the slider positions next to the one shown), in the background, if there is room."""
        key = self._last
        if key is None:
            return
        for i, k in enumerate(key):
            if isinstance(k, (int, np.integer)):
                for step in (1, -1):
                    if 0 <= k + step < self.shape[i]:
                        self.ahead(key[:i] + (int(k) + step,) + key[i + 1:])

    def ahead(self, key: Any) -> None:
        """Read `key` in the background, if there is room (the next slider position)."""
        k = self._ident + (self._data._where, _key_text(key))
        if self._cache.get(k) is not None or not self._cache.memory.fits(_part_bytes(self, key)):
            return

        def read() -> None:
            try:
                self._cache.put(k, self._data[key])
            except Exception:                          # a guess that didn't work out costs nothing
                pass

        threading.Thread(target=read, name="lbd read ahead", daemon=True).start()


def _key_text(key: Any) -> str:
    if not isinstance(key, tuple):
        key = (key,)
    return repr(tuple(k.tolist() if isinstance(k, np.ndarray) else k for k in key))


def _part_bytes(x: Any, key: Any) -> int:
    """About how many bytes `x[key]` takes (integers drop a dimension, slices keep it)."""
    if not isinstance(key, tuple):
        key = (key,)
    n = 1
    for i, size in enumerate(x.shape):
        k = key[i] if i < len(key) else slice(None)
        if isinstance(k, (int, np.integer)):
            continue
        if isinstance(k, slice):
            n *= len(range(*k.indices(size)))
        else:
            n *= len(np.atleast_1d(k))
    return n * x.dtype.itemsize


def load_values(path: Any, names: Sequence[str], version: str, cache: Optional[PartCache] = None) -> Any:
    """The file with values `names` ready to draw: loaded whole when they fit in the memory
    available now (as `lbd.load(path, values=names)`), else opened (`lbd.open`, the file opened
    for each read, never held) with their data read by part through the part cache."""
    import lbd

    cache = cache or shared()
    header = lbd.info(path)
    need = sum(int(np.prod(header.values[n].shape, dtype=np.int64)) * np.dtype(header.values[n].dtype).itemsize
               for n in names)
    if cache.memory.fits(need):
        return lbd.load(path, values=list(names))
    d = lbd.open(path, hold=False)
    for name, v in d.values.items():
        if name in names:
            v.data = Cached(v.data, cache, (str(path), version))
        else:
            v.data = v.measured = None                 # as lbd.load(values=names)
    return d


_shared: Dict[str, Any] = {}


def shared() -> PartCache:
    """The viewer's one part cache (all Explore tabs share it: one server process)."""
    if "cache" not in _shared:
        _shared["cache"] = cache = PartCache(Memory())

        def trim_every_few_seconds() -> None:      # other programs may have taken memory meanwhile
            while True:
                time.sleep(TRIM_EVERY)
                try:
                    cache.trim()
                except Exception:                    # psutil failing once: try again next time
                    pass

        threading.Thread(target=trim_every_few_seconds, name="lbd part cache trim", daemon=True).start()
    return _shared["cache"]


def configure(reserve: Optional[int], maximum: Optional[int]) -> None:
    """Apply the settings (bytes, or None: automatic reserve / no maximum)."""
    c = shared()
    c.memory.reserve_setting, c.memory.maximum = reserve, maximum
    c.trim()
