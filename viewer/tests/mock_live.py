"""Files being written, for trying LBD Viewer by hand (plan 6b).

    uv run python viewer/tests/mock_live.py FOLDER [--seconds 120]

Writes `FOLDER/live sweep.lbd` slowly with lbd.Writer (a power sweep, one trace every second,
and a growing temperature log), so the Library shows it as "measuring…" and Explore shows it as
it grows; it becomes an ordinary .lbd file at the end. First it leaves `FOLDER/stopped
sweep.lbd.writing`, a measurement that stopped before finishing, to try Recover on. Stop the
script with Ctrl+C to see a running measurement become "stopped before finishing".

With `--copy-to OTHER --as-computer LAB-PC`, the file being written and its heartbeat are also
copied into OTHER every few traces, as a sync tool would bring them from another computer (no
lock travels): open OTHER in the viewer to see "Measuring on LAB-PC", then "No sign …".
"""

import argparse
import time
from pathlib import Path
from typing import Optional

import numpy as np

import lbd

FREQS = np.linspace(6.99e9, 7.01e9, 401)


def trace(power: float) -> np.ndarray:
    f0 = 7e9 - 2e6 * 10 ** (power / 20)                  # the resonance moves down at high power
    noise = 0.01 * (np.random.default_rng().normal(size=FREQS.size) + 1j * np.random.default_rng().normal(size=FREQS.size))
    return 1 - 0.8 / (1 + 2j * (FREQS - f0) / 0.6e6) + noise


def start(path: Path, powers: np.ndarray) -> lbd.Writer:
    w = lbd.Writer(path, title=path.stem, description="written by viewer/tests/mock_live.py")
    w.add_axis("power", powers, unit="dBm", label="Power")
    w.add_axis("freq", FREQS, unit="Hz", label="Frequency")
    w.add_axis("time", unit="s", grows=True)
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    w.add_value("T_mK", axes="time", unit="mK", label="Temperature")
    w.plot = {"kind": "heatmap", "values": ["S21"], "complex": "db"}
    return w


def stopped(folder: Path) -> Path:
    """A measurement that stopped before finishing: half its traces, then the script "crashed"."""
    path = folder / "stopped sweep.lbd"
    w = start(path, np.linspace(-60, 0, 13))
    for i in range(6):
        w.write(power=i, S21=trace(-60 + 5 * i))
        w.write(time=float(i), T_mK=12 + 0.1 * i)
    w._abandon()                                          # as a crash leaves it: the guard released
    return w.writing_path


def copy_as_synced(w: lbd.Writer, to: Path, computer: str) -> None:
    """What a sync tool brings to another computer: the file being written and its heartbeat,
    copied (no lock travels), the heartbeat naming the measuring computer `computer`."""
    import json
    import shutil

    to.mkdir(parents=True, exist_ok=True)
    beat = lbd.live.live_path(w.writing_path)
    try:
        w.flush()
        shutil.copyfile(w.writing_path, to / w.writing_path.name)
        content = json.loads(beat.read_text(encoding="utf-8"))
        content["computer"] = computer
        (to / beat.name).write_text(json.dumps(content), encoding="utf-8")
    except (OSError, ValueError):            # caught mid-write: the next copy brings it
        pass


def measure(folder: Path, seconds: float, copy_to: Optional[Path] = None, computer: str = "OTHER-PC") -> Path:
    powers = np.linspace(-60, 0, max(2, int(seconds)))
    w = start(folder / "live sweep.lbd", powers)
    t0 = time.monotonic()
    with w:
        for i, p in enumerate(powers):
            w.write(power=i, S21=trace(p))
            w.write(time=time.monotonic() - t0, T_mK=12 + np.random.default_rng().normal(scale=0.05))
            print(f"\r{i + 1} of {len(powers)} traces", end="", flush=True)
            if copy_to is not None and i % 3 == 0:
                copy_as_synced(w, copy_to, computer)
            time.sleep(seconds / len(powers))
    print()
    return w.path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--seconds", type=float, default=120.0, help="how long the live measurement takes")
    ap.add_argument("--copy-to", type=Path, help="also copy it there every few traces, as a sync tool would")
    ap.add_argument("--as-computer", default="OTHER-PC", help="the computer the copies' heartbeat names")
    args = ap.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    print("left", stopped(args.folder))
    print("finished", measure(args.folder, args.seconds, args.copy_to, args.as_computer))
