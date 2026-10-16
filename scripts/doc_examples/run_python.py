"""Run the Python documentation blocks listed in $LBD_DOC_BLOCKS (see check_doc_examples.py).

Each block runs in a fresh namespace after PRELUDE, in the current (temporary) folder. A block
that fails is retried without the empty `d` the prelude ends with, for blocks that use the
prelude's sample dataset.
"""

import json
import os
import sys
import traceback
import warnings

PRELUDE = '''
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, lbd
import lbd.plot as lp
lp.PresetStore().save("thesis", {"figure": {"width_mm": 120, "font": {"family": "DejaVu Serif"}}})
lp.PresetStore().save("paper", {"figure": {"width_mm": 90}})
Path("figs").mkdir(exist_ok=True); lp.load_style("thesis").save("figs/thesis.lbd.json"); lp.load_style("thesis").save("thesis.lbd.json")
Path("thesis.mplstyle").write_text(lp.load_style("thesis").to_mplstyle())
x = np.linspace(0, 1, 20); y = x ** 2; dy = 0.05 * np.ones_like(x)
i, q = np.random.default_rng(0).normal(size=(2, 300)); power = np.linspace(-60, 0, 300)
v_fit = np.sin(2e7 * np.linspace(0, 1e-6, 201)); t1 = np.linspace(1e-5, 2e-5, 401)
Z = np.ones((11, 401))
f = np.linspace(4e9, 8e9, 401); p = np.arange(-40, 1, 4.0)
s21 = np.exp(1j * np.outer(p, f) * 1e-10)
t = np.linspace(0, 1e-6, 201); v = np.sin(2e7 * t); counts = np.arange(201)
d = lbd.Dataset(title="prelude")
d.add_axis("power", p, unit="dBm"); d.add_axis("freq", f, unit="Hz"); d.add_axis("t", t, unit="s")
d.add_value("S21", s21, axes=["power", "freq"]); d.add_value("trace", v, axes="t")
d.save("sweep.lbd"); d.save("run.lbd"); d.save("big.lbd"); d.save("huge.lbd")
Path("data").mkdir(exist_ok=True); d.save("data/a.lbd")
temperatures = [10, 20]; out = Path("out"); out.mkdir(exist_ok=True)
measure = lambda T: np.ones(401)
d = lbd.Dataset(title="fresh")
'''


def is_signature(code: str) -> bool:
    try:
        compile(code, "<doc>", "exec")
        return False
    except SyntaxError:
        return "->" in code or ": str" in code or "=..." in code


def main() -> int:
    blocks = json.load(open(os.environ["LBD_DOC_BLOCKS"], encoding="utf-8"))
    import lbd

    warnings.simplefilter("ignore")                    # third-party noise (e.g. deprecations)
    warnings.simplefilter("error", lbd.LBDWarning)     # an LBD warning in an example is a doc bug
    fails = 0
    for b in blocks:
        if is_signature(b["code"]):
            print("sig  ", b["where"])
            continue
        last = None
        for prelude in (PRELUDE, PRELUDE.replace('d = lbd.Dataset(title="fresh")', "")):
            try:
                ns = {}
                exec(prelude, ns)
                exec(compile(b["code"], b["where"], "exec"), ns)
                last = None
                break
            except Exception:
                last = traceback.format_exc().strip().splitlines()[-1]
            finally:
                __import__("matplotlib.pyplot").pyplot.close("all")
        if last:
            fails += 1
            print("FAIL", b["where"], last)
        else:
            print("ok  ", b["where"])
    print(f"{len(blocks) - fails}/{len(blocks)} ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
