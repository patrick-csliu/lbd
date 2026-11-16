"""A measurement being written, for trying LBD Viewer by hand (plan 6b).

    uv run python viewer/tests/mock_live.py FOLDER [--kind map|curve|scatter|variable] [--name NAME]
                                                   [--seconds 120] [--stopped]

Writes `FOLDER/NAME.lbd` slowly with lbd.Writer, so the Library shows it as "measuring…" and Explore
shows it as it grows; it becomes an ordinary .lbd file at the end. Stop the script with Ctrl+C to
see a running measurement become "stopped before finishing". What is written (`--kind`):

- map (the default, `live sweep`): a power sweep, one trace of S21 against frequency a step, saved
  as a map; and a growing temperature log.
- curve (`live fridge log`): a fridge's cool-down log, the mixing-chamber, still and 4 K plate
  temperatures, a point a step; saved as a curve of the mixing chamber.
- scatter (`live single shot`): single-shot readout, a shot a step: the I/Q point of the qubit
  prepared in ground and in excited; saved as a scatter in the I/Q plane, coloured by the state.
- variable (`live variable sweep`; also `--variable`): a variable sweep (an axis group, format
  2.0), one power a step, each with its own frequencies (as mock_values.variable_sweep).

With `--stopped`, it first leaves `FOLDER/stopped sweep.lbd.writing`, a measurement that stopped
before finishing, to try Recover on.

With `--copy-to OTHER --as-computer LAB-PC`, the file being written and its heartbeat are also
copied into OTHER every few steps, as a sync tool would bring them from another computer (no lock
travels): open OTHER in the viewer to see "Measuring on LAB-PC", then "No sign …".
"""

import argparse
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

import lbd

FREQS = np.linspace(6.99e9, 7.01e9, 401)
KINDS = ("map", "curve", "scatter", "variable")
NAMES = {"map": "live sweep", "curve": "live fridge log", "scatter": "live single shot",
         "variable": "live variable sweep"}

Step = Callable[[lbd.Writer, int], None]          # called after each step (the copies of --copy-to)


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


def _steps(seconds: float) -> int:
    """One step a second, at least two."""
    return max(2, int(seconds))


def _progress(i: int, n: int, what: str) -> None:
    print(f"\r{i + 1} of {n} {what}", end="", flush=True)


def measure(folder: Path, seconds: float, step: Optional[Step] = None, name: str = NAMES["map"]) -> Path:
    """map: a power sweep, a trace a step, and a growing temperature log."""
    powers = np.linspace(-60, 0, _steps(seconds))
    w = start(folder / f"{name}.lbd", powers)
    t0 = time.monotonic()
    with w:
        for i, p in enumerate(powers):
            w.write(power=i, S21=trace(p))
            w.write(time=time.monotonic() - t0, T_mK=12 + np.random.default_rng().normal(scale=0.05))
            _progress(i, len(powers), "traces")
            if step:
                step(w, i)
            time.sleep(seconds / len(powers))
    print()
    return w.path


def measure_curve(folder: Path, seconds: float, step: Optional[Step] = None, name: str = NAMES["curve"]) -> Path:
    """curve: a fridge's cool-down log, a point a step (time grows): each stage cools towards its
    base temperature, the mixing chamber last and slowest."""
    rng = np.random.default_rng()
    n = _steps(seconds)
    w = lbd.Writer(folder / f"{name}.lbd", title=name, description="written by viewer/tests/mock_live.py --kind curve")
    w.add_axis("time", unit="s", grows=True, label="Time")
    w.add_value("T_MXC", axes="time", unit="mK", label="Mixing chamber")
    w.add_value("T_still", axes="time", unit="K", label="Still")
    w.add_value("T_4K", axes="time", unit="K", label="4 K plate")
    w.plot = {"kind": "curve", "values": ["T_MXC"]}
    t0 = time.monotonic()
    with w:
        for i in range(n):
            x = i / max(1, n - 1)                          # 0 … 1 through the cool-down
            w.write(time=time.monotonic() - t0,
                    T_MXC=10 + 790 * np.exp(-5 * x) + rng.normal(scale=0.3),
                    T_still=0.7 + 1.3 * np.exp(-4 * x) + rng.normal(scale=0.005),
                    T_4K=3.2 + 0.8 * np.exp(-6 * x) + rng.normal(scale=0.01))
            _progress(i, n, "points")
            if step:
                step(w, i)
            time.sleep(seconds / n)
    print()
    return w.path


def measure_scatter(folder: Path, seconds: float, step: Optional[Step] = None, name: str = NAMES["scatter"]) -> Path:
    """scatter: single-shot readout, a shot a step (shot grows): the I/Q point of the qubit prepared
    in ground and in excited; a few excited shots have decayed to ground before the readout."""
    rng = np.random.default_rng()
    n = _steps(seconds)
    ground, excited, sigma = np.array([-0.5, -0.2]), np.array([0.4, 0.3]), 0.15     # mV
    w = lbd.Writer(folder / f"{name}.lbd", title=name, description="written by viewer/tests/mock_live.py --kind scatter")
    w.add_axis("shot", grows=True, label="Shot")
    w.add_axis("state", [0.0, 1.0], label="Prepared state", elements=["ground", "excited"])
    w.add_value("IQ", axes=["shot", "state"], dtype="complex128", unit="V", label="I/Q")
    w.plot = {"kind": "scatter", "values": ["IQ"], "complex": "iq", "color": "state"}
    with w:
        for i in range(n):
            e = ground if rng.random() < 0.05 else excited          # T1 during the readout
            pts = np.stack([ground, e]) + rng.normal(0, sigma, (2, 2))
            w.write(shot=float(i), IQ=(pts[:, 0] + 1j * pts[:, 1]) * 1e-3)
            _progress(i, n, "shots")
            if step:
                step(w, i)
            time.sleep(seconds / n)
    print()
    return w.path


def measure_variable(folder: Path, seconds: float, step: Optional[Step] = None, name: str = NAMES["variable"]) -> Path:
    """variable: a variable sweep written live (format 2.0, as mock_values.variable_sweep): for each
    power, the frequencies are chosen around where the resonance is at that power, and Q is
    fitted once per power; one power a step."""
    rng = np.random.default_rng(13)
    powers = np.linspace(-60, 0, _steps(seconds))
    w = lbd.Writer(folder / f"{name}.lbd", title=name, description="written by viewer/tests/mock_live.py --kind variable")
    w.add_group("scan")
    w.add_axis("power", group="scan", unit="dBm", label="Power")
    w.add_axis("freq", group="scan", unit="Hz", label="Frequency")
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    w.add_value("Q", axes="power", label="Quality factor")
    with w:
        for i, p in enumerate(powers):
            f0 = 7e9 - 2e6 * 10 ** (p / 20)                  # the resonance moves down at high power
            n = 40 + int(-p / 10)                            # more points at low power
            f = np.linspace(f0 - 3e6, f0 + 3e6, n)
            w.write(power=p, freq=f, S21=1 - 0.8 / (1 + 2j * (f - f0) / 0.6e6) + 0.01 * rng.normal(size=n))
            w.write(power=p, Q=1e4 * (1 + 0.1 * rng.normal()))
            _progress(i, len(powers), "powers")
            if step:
                step(w, i)
            time.sleep(seconds / len(powers))
    print()
    return w.path


MEASURE = {"map": measure, "curve": measure_curve, "scatter": measure_scatter, "variable": measure_variable}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--kind", choices=KINDS, default="map", help="what is written (default: map)")
    ap.add_argument("--name", help="the file's name, without .lbd (default: by the kind, e.g. 'live sweep')")
    ap.add_argument("--seconds", type=float, default=120.0, help="how long the live measurement takes")
    ap.add_argument("--stopped", action="store_true",
                    help="first leave a measurement that stopped before finishing, to try Recover on")
    ap.add_argument("--copy-to", type=Path, help="also copy it there every few steps, as a sync tool would")
    ap.add_argument("--as-computer", default="OTHER-PC", help="the computer the copies' heartbeat names")
    ap.add_argument("--variable", action="store_true", help="the same as --kind variable")
    ap.add_argument("--no-stopped", action="store_true", help=argparse.SUPPRESS)   # the default now
    args = ap.parse_args()
    kind = "variable" if args.variable else args.kind
    name = args.name[:-4] if args.name and args.name.lower().endswith(".lbd") else args.name
    args.folder.mkdir(parents=True, exist_ok=True)
    if args.stopped:
        print("left", stopped(args.folder))
    copy = None
    if args.copy_to is not None:
        def copy(w: lbd.Writer, i: int) -> None:
            if i % 3 == 0:
                copy_as_synced(w, args.copy_to, args.as_computer)
    print("finished", MEASURE[kind](args.folder, args.seconds, copy, name or NAMES[kind]))
