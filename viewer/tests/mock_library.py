"""A mock library of .lbd files for the Library workspace (plan 8a) and its tests.

    uv run python viewer/tests/mock_library.py FOLDER [N] [--labels] [--many-labels]

writes about N files (default 300) into two folders under FOLDER, as two "open folders" of the
viewer would be: `Lab data/` sorted by date (`YYYY/MM/DD/`) and `Shared/` sorted by project.
Simulated measurements of a few kinds (resonator sweeps, Rabi, spectroscopy, T1, fridge logs),
created over two years in several time zones, with titles, descriptions and nested metadata to
search, plus the cases a list must handle: a damaged file, a file without a title, the same file
name in two folders, a file of single numbers only, and a measurement just before midnight.
Small arrays, so 10 000 files are written in a minute or so. A fixed random seed: the same
library every time.
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

import lbd

ZONES = [timezone(timedelta(hours=8)), timezone(timedelta(hours=1)), timezone(timedelta(hours=-5)), timezone.utc]
PROJECTS = ["Qubit A", "Qubit B", "Resonator chip 3", "Fridge"]
OPERATORS = ["Patrick", "Alice", "Bob"]
WORDS = ["after re-cooling", "flux bias 0.2", "punch-out check", "with the new amplifier",
         "repeat of yesterday", "calibration run"]

# The special files (relative to the folder given), for the tests.
SPECIAL = {
    "broken": "Lab data/2026/03/14/broken.lbd",               # damaged: not readable
    "untitled": "Lab data/2026/03/14/untitled.lbd",           # empty title
    "midnight": "Lab data/2026/03/14/late resonator.lbd",     # 2026-03-14T23:30:00+08:00
    "numbers": "Shared/Qubit A/T1 fit only.lbd",              # single numbers only
    "twin_lab": "Lab data/2025/06/02/calibration.lbd",        # the same name ...
    "twin_shared": "Shared/Fridge/calibration.lbd",           # ... in another folder
}


def _dataset(kind: str, k: int, rng: np.random.Generator, created: datetime) -> lbd.Dataset:
    project = PROJECTS[k % len(PROJECTS)]
    words = WORDS[k % len(WORDS)]
    if kind == "resonator":
        d = lbd.Dataset(title=f"Resonator sweep {k}", description=f"Power sweep of the resonator, {words}",
                        created=created)
        p, f = np.linspace(-60, 0, 5), np.linspace(6.99e9, 7.01e9, 11)
        d.add_axis("power", p, unit="dBm", label="Power")
        d.add_axis("freq", f, unit="Hz", label="Frequency")
        d.add_value("S21", 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 1e6) * np.ones((5, 1)), axes=["power", "freq"])
        d.meta = {"vna": {"power_dBm": -30.0, "ifbw_Hz": float(rng.choice([100, 1000])), "averages": 4}}
    elif kind == "rabi":
        d = lbd.Dataset(title=f"Rabi amplitude {k}", description=f"Rabi oscillation, {words}", created=created)
        a = np.linspace(0, 0.5, 21)
        p = 0.5 * (1 - np.cos(np.pi * a / 0.2))
        d.add_axis("amplitude", a, unit="V", label="Drive amplitude")
        d.add_value("I", 1e-3 * p, axes="amplitude", unit="V")
        d.add_value("Q", 3e-5 * (1 - p), axes="amplitude", unit="V")
        d.add_value("population", p, axes="amplitude", label="Population")
    elif kind == "spectroscopy":
        d = lbd.Dataset(title=f"Qubit spectroscopy {k}", description=f"Two-tone spectroscopy vs flux, {words}",
                        created=created)
        d.add_axis("qubit_power", [-30.0, -20.0, -10.0], unit="dBm")
        d.add_axis("flux", np.linspace(-0.5, 0.5, 4), unit="Φ0", label="Flux")
        d.add_axis("frequency", np.linspace(4.5e9, 5.5e9, 6), unit="Hz", label="Frequency")
        d.add_value("amplitude", rng.random((3, 4, 6)), axes=["qubit_power", "flux", "frequency"], unit="V")
    elif kind == "t1":
        d = lbd.Dataset(title=f"T1 {k}", description=f"Energy relaxation, {words}", created=created)
        t = np.linspace(0, 1e-4, 16)
        d.add_axis("delay", t, unit="s", label="Delay")
        d.add_value("P1", np.exp(-t / 2.1e-5), axes="delay", label="P(1)")
        d.add_value("T1", 2.1e-5, unit="s")
    else:  # fridge
        d = lbd.Dataset(title=f"Fridge log {k}", description=f"Cool-down monitor, {words}", created=created)
        t = np.linspace(0, 3600.0, 12)
        d.add_axis("time", t, unit="s", label="Time")
        d.add_value("T_mxc", 0.012 + np.exp(-t / 900), axes="time", unit="K")
        d.add_value("P_main", 1e-6 + np.exp(-t / 300), axes="time", unit="mbar")
    d.meta = {**d.meta, "project_hint": project, "operator": OPERATORS[k % len(OPERATORS)],
              "fridge": {"T_mK": float(rng.choice([10, 12, 15]))}}
    return d


KINDS = ["resonator", "rabi", "spectroscopy", "t1", "fridge"]


def write_library(folder: Path, n: int = 300) -> Dict[str, List[Path]]:
    """Write the mock library into `folder`: {"Lab data": [...], "Shared": [...]} (the paths
    written, per open folder). The special files are in SPECIAL."""
    folder = Path(folder)
    rng = np.random.default_rng(8)
    start = datetime(2024, 10, 1, 9, 0, tzinfo=timezone.utc)         # two years up to about 2026-10
    out: Dict[str, List[Path]] = {"Lab data": [], "Shared": []}
    for k in range(max(n - len(SPECIAL), 0)):
        zone = ZONES[k % len(ZONES)]
        created = (start + timedelta(minutes=int(rng.integers(0, 720 * 24 * 60)))).astimezone(zone)
        kind = KINDS[k % len(KINDS)]
        d = _dataset(kind, k, rng, created)
        if k % 3 == 2:                                     # a third in the shared, by-project folder
            path = folder / "Shared" / PROJECTS[k % len(PROJECTS)] / f"{d.title}.lbd"
            out["Shared"].append(path)
        else:                                              # the others by date, as written there
            path = folder / "Lab data" / created.strftime("%Y/%m/%d") / f"{d.title}.lbd"
            out["Lab data"].append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        d.save(path)
    # the special cases
    late = datetime(2026, 3, 14, 23, 30, tzinfo=ZONES[0])
    specials = {
        "midnight": _dataset("resonator", 9001, rng, late),
        "twin_lab": _dataset("t1", 9002, rng, datetime(2025, 6, 2, 10, 0, tzinfo=ZONES[1])),
        "twin_shared": _dataset("fridge", 9003, rng, datetime(2025, 6, 3, 10, 0, tzinfo=ZONES[1])),
    }
    specials["midnight"].title = "Late resonator sweep"
    untitled = _dataset("rabi", 9004, rng, datetime(2026, 3, 14, 12, 0, tzinfo=ZONES[0]))
    untitled.title = ""
    specials["untitled"] = untitled
    numbers = lbd.Dataset(title="T1 fit only", description="Only the fitted numbers", created="2025-09-01T15:00:00+08:00")
    numbers.add_value("T1", 2.1e-5, unit="s")
    numbers.add_value("T2", 1.4e-5, unit="s")
    specials["numbers"] = numbers
    for name, d in specials.items():
        path = folder / SPECIAL[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        d.save(path)
        out[SPECIAL[name].split("/")[0]].append(path)
    broken = folder / SPECIAL["broken"]
    broken.write_bytes((folder / SPECIAL["midnight"]).read_bytes()[:300])   # cut short: damaged
    out["Lab data"].append(broken)
    return out



# The labels the mock library is given (add_labels): nested 1-3 levels, flat and nested, a long one
# to try layouts with; and labels kept without any file (a new project before its first data).
LABEL_PROJECTS = ["Qubit A", "Qubit A/Device 1", "Qubit A/Device 3", "Qubit A/Device 3/Cooldown 7",
                  "Qubit B/Device 2", "Resonator chip 3", "Resonator chip 3/Wafer 12/Die 4", "Fridge"]
LABEL_USERS = ["Lab A/Qubit team/Patrick", "Lab A/Qubit team/Alice", "Lab A/Resonator team/Chen",
               "Lab B/Bob", "Guest"]
LABEL_TAGS = ["resonator", "calibration", "flux/bias", "flux/sweet spot", "quality/good", "quality/redo",
              "quality/redo/more averages", "punch-out", "two-tone", "noise", "after re-cooling",
              "a rather long tag to see how the lists and chips cope with it"]
LABEL_COMMENTS = ["", "", "", "punch-out at -20 dBm", "redo with more averages",
                  "flux bias 0.2 mA\nsweet spot found at 0.31 mA\nnext: T2 echo",
                  "The resonance moved by about 2 MHz after the amplifier was changed; compare with the run "
                  "of last week before drawing conclusions, and check the attenuation on line 3 first."]
KEPT = [("project", "Qubit C/Device 1"), ("users", "Lab B/New student"), ("tags", "to check")]


def many_labels() -> Dict[str, List[str]]:
    """A large vocabulary, to try long lists (--many-labels): 300 users in 4 labs and 20 teams,
    800 tags (some nested 4 deep), 60 projects, and a few names over 80 characters."""
    rng = random.Random(80)
    first = ["Alice", "Bob", "Chen", "Dana", "Eli", "Fatima", "Gil", "Hana", "Ivan", "Jun", "Kofi", "Lena", "Mateo",
             "Nora", "Omar", "Priya", "Quinn", "Rosa", "Sven", "Tara", "Uma", "Viktor", "Wen", "Xavi", "Yara", "Zoe"]
    teams = ["Qubit team", "Resonator team", "Fridge team", "Theory", "Readout"]
    users = sorted({f"Lab {lab}/{team}/{rng.choice(first)} {rng.choice('ABCDEFGHKLMNPRSTW')}."
                    for lab in "ABCD" for team in teams for _ in range(16)})[:300]
    words = ["flux", "bias", "sweet spot", "quality", "redo", "noise", "drift", "amplifier", "line", "attenuation",
             "cooldown", "warmup", "calibration", "readout", "pulse", "echo", "ramsey", "spectroscopy", "power",
             "frequency", "phase", "IQ", "mixer", "LO leakage", "TWPA", "HEMT", "filter", "magnet", "temperature"]
    tags = set()
    while len(tags) < 800:
        depth = rng.choice([1, 1, 2, 2, 3, 4])
        tags.add("/".join(rng.choice(words) + (f" {rng.randint(1, 40)}" if rng.random() < 0.5 else "") for _ in range(depth)))
    tags.add("a very long tag that describes the whole measurement setup, the line and the attenuators used here")
    tags.add("quality/redo/" + "with more averages and a longer wait between the pulses, " * 2)
    projects = sorted({f"Chip {c}/Wafer {w}/Die {d}" for c in range(1, 6) for w in range(1, 5) for d in range(1, 4)})
    projects.append("A project with a rather long name for the cooldown of the new dilution fridge in room 3")
    return {"project": projects, "users": users, "tags": sorted(tags)}


def random_labels(rng: random.Random, vocabulary: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """One file's labels: a star now and then, a project or none, 0-3 users, 0-4 tags, a comment."""
    v = vocabulary or {"project": LABEL_PROJECTS, "users": LABEL_USERS, "tags": LABEL_TAGS}
    return {"star": rng.random() < 0.15,
            "project": rng.choice(v["project"]) if rng.random() < 0.8 else None,
            "add_users": rng.sample(v["users"], rng.choice([0, 1, 1, 1, 2, 3])),
            "add_tags": rng.sample(v["tags"], rng.choice([0, 0, 1, 1, 2, 3, 4])),
            "comment": rng.choice(LABEL_COMMENTS)}


def add_labels(folder: Path, keep_in: Optional[Path] = None, many: bool = False) -> Dict[str, Path]:
    """Organise a mock library written by write_library (plan 8b): labels in the folders' label
    files (stars, projects nested 1-3 levels, users in groups, flat and nested tags, comments of
    one or several lines; LABEL_*), labels kept without a file (KEPT), an identical copy, a copy changed
    after copying (a conflict), a sync conflict copy of a label file, files without an id, and
    labels whose file is gone (missing). The labels kept without a file go into `keep_in`, an open
    folder of the viewer (default: `folder/Lab data`, as the tests open it). Returns the special
    files by name. `many`: a large vocabulary (many_labels), every label of it kept, so the lists
    are long."""
    import shutil

    import h5py

    from lbd_viewer import labels

    folder = Path(folder)
    rng = random.Random(8)
    vocabulary = many_labels() if many else None
    files = sorted(p for p in folder.rglob("*.lbd") if "broken" not in p.name)
    by_folder: Dict[Path, List[Path]] = {}
    for p in files:
        by_folder.setdefault(p.parent, []).append(p)
    for where, members in sorted(by_folder.items()):
        def change(doc, members=members):
            for p in members:
                if rng.random() < 0.3:                          # about a third without any label
                    continue
                info = lbd.info(p)
                e = labels.new_entry(info.id, p.name, info.created)
                labels.apply(e, random_labels(rng, vocabulary))
                doc["files"].append(e)
        labels.update(where, change)
    # labels kept although no file has them yet (made with + New in the Library), in an open folder
    keep_in = Path(keep_in) if keep_in else folder / "Lab data"
    if keep_in.is_dir():
        def keep(doc):
            for kind, label in KEPT:
                labels.keep(doc, kind, label)
            for kind, names in (vocabulary or {}).items():
                for label in names:
                    labels.keep(doc, kind, label)
        labels.update(keep_in, keep)
    special: Dict[str, Path] = {}
    backup = folder / "Shared" / "Backup"
    backup.mkdir(parents=True, exist_ok=True)
    original = files[0]
    special["copy"] = backup / original.name
    shutil.copy2(original, special["copy"])                         # an identical copy
    edited = files[1]
    special["conflict"] = backup / edited.name
    shutil.copy2(edited, special["conflict"])
    d = lbd.load(special["conflict"])
    d.description = d.description + " (edited after copying)"
    d.save(special["conflict"])                                     # same place: same id, other content
    for p in files[-3:]:                                            # written before format 1.1
        with h5py.File(p, "a") as f:
            if "id" in f.attrs:
                del f.attrs["id"]
            f.attrs["lbd_version"] = "1.0"
        special.setdefault("no_id", p)
    gone = files[2]                                                 # labelled, then deleted: missing
    def label_gone(doc):
        info = lbd.info(gone)
        e = labels.find(doc, info.id, gone.name) or labels.new_entry(info.id, gone.name, info.created)
        if e not in doc["files"]:
            doc["files"].append(e)
        labels.apply(e, {"add_tags": ["lost"], "comment": "this file was deleted outside LBD"})
    labels.update(gone.parent, label_gone)
    gone.unlink()
    special["missing"] = gone
    side = folder / "Shared" / PROJECTS[0] / labels.SIDECAR       # a sync tool's conflict copy
    if side.exists():
        doc = json.loads(side.read_text(encoding="utf-8"))
        for e in doc["files"][:1]:
            labels.apply(e, {"add_tags": ["from the laptop"]}, "2099-01-01T00:00:00.000Z", "LAPTOP")
        (side.parent / ".lbd-library_LAPTOP_Oct-29-140513-2026_Conflict.json").write_text(json.dumps(doc), encoding="utf-8")
    return special


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    written = write_library(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 300)
    for root, paths in written.items():
        print(f"{root}: {len(paths)} files")
    if "--labels" in sys.argv or "--many-labels" in sys.argv:
        for what, path in add_labels(Path(sys.argv[1]), many="--many-labels" in sys.argv).items():
            print(f"{what}: {path}")
