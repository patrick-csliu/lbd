# lbd

Read and write **LBD** (`.lbd`) lab data files from Python. The same files read and write
identically in MATLAB and Julia, and open in LBD Viewer.

```python
import numpy as np
import lbd

f = np.linspace(4e9, 8e9, 401)
p = np.arange(-40, 1, 4.0)

d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", p, unit="dBm", label="Power")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", np.exp(1j * np.outer(p, f) * 1e-10), axes=["power", "freq"])
d.meta["T_mK"] = 12
d.save("sweep.lbd")

d = lbd.load("sweep.lbd")
d["S21"].data.shape     # (11, 401)
```

Requires Python 3.9 or newer, `numpy` and `h5py`. To look at the files, install LBD Viewer.

Guides: `docs/python/` in the LBD repository; the API reference is generated from the docstrings (both under **Help** in LBD Viewer). Format: `spec/LBD-v1.md`.
