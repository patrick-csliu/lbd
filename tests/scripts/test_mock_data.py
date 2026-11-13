"""scripts/make_mock_data.py: one command makes a whole folder of mock data, with every kind of
label (stars, nested projects, users and tags, comments, labels kept without a file) and, unless
small, the large files (engine tests); mock_live.py --variable writes a variable sweep.
scripts/dev_viewer.py is tested in test_dev_viewer.py."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import lbd

REPO = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_folder_of_mock_data_with_every_kind_of_label(tmp_path):
    pytest.importorskip("lbd_viewer")
    make = load("make_mock_data")
    made = make.make(tmp_path / "mock", files=30, small=True)
    root = tmp_path / "mock"
    assert {p.name for p in root.iterdir()} == {"Lab library", "Panels", "Examples", ".lbd-library.json"}
    assert sum(made["library"].values()) >= 25 and made["panels"] >= 5 and made["writer"] is None
    # the examples are written by examples/make_examples.py (18.6), in today's format: with an id
    assert lbd.info(root / "Examples" / "rabi.lbd").id
    assert (root / "Examples" / "2026" / "resonator" / "power_sweep.lbd").is_file()
    entries = [e for side in root.rglob(".lbd-library.json") for e in json.loads(side.read_text("utf-8"))["files"]]
    assert any(e["star"] for e in entries)
    assert any(e["project"] and e["project"].count("/") >= 1 for e in entries)              # nested projects
    assert any("/" in u for e in entries for u in e["users"])                                # users in groups
    assert any("/" in t for e in entries for t in e["tags"]) and any(t for e in entries for t in e["tags"] if "/" not in t)
    assert any("\n" in e["comment"] for e in entries)                                        # a comment of lines
    kept = json.loads((root / ".lbd-library.json").read_text("utf-8"))["labels"]            # kept without a file
    assert set(kept) == {"project", "users", "tags"}
    with pytest.raises(SystemExit):                                                          # never over files
        make.make(root, files=5, small=True)


def test_the_large_files_are_made_unless_small(tmp_path, monkeypatch):
    """Without --small the mock data has Large/ (the engine tests); with it, none. The large
    makers are swapped for the small one here, so the test stays quick."""
    pytest.importorskip("lbd_viewer")
    make = load("make_mock_data")                      # puts viewer/tests on sys.path
    import mock_large

    monkeypatch.setattr(mock_large, "MAKERS", {"4 small map.lbd": mock_large.small_map})
    made = make.make(tmp_path / "full", files=5, with_labels=False)
    assert made["large"] == 1 and (tmp_path / "full" / "Large" / "4 small map.lbd").is_file()
    assert any("Large: 1 large files" in line for line in make.report(tmp_path / "full", made))
    made = make.make(tmp_path / "small", files=5, with_labels=False, small=True)
    assert made["large"] == 0 and not (tmp_path / "small" / "Large").exists()


def test_the_engine_tests_numbers():
    """mock_large's generator is the engine test's: s = (1664525 s + 1013904223) mod 2^32,
    returning s / 2^32, the same as a step-by-step loop, also across its blocks of 65 536."""
    load("make_mock_data")
    import mock_large

    n, s, expected = 70_000, 1, []
    for _ in range(n):
        s = (1664525 * s + 1013904223) % 2 ** 32
        expected.append(s / 2 ** 32)
    assert np.array_equal(mock_large.rng(1, n), expected)
    assert mock_large.rng(1, 1)[0] == 1015568748 / 2 ** 32

    d = mock_large.small_map()                         # engine test 4: value = column + 5 x row
    assert list(d.axes["x"].data) == [1, 2, 4, 8, 16] and d.values["value"].data[3, 4] == 4 + 5 * 3
    assert list(mock_large.MAKERS) == ["1 accuracy.lbd", "2 traces.lbd", "3 map.lbd", "4 small map.lbd"]


def test_a_variable_sweep_written_live(tmp_path):
    """mock_live.py --variable: a variable sweep with lbd.Writer, a power a step."""
    load("make_mock_data")
    import mock_live

    path = mock_live.measure_variable(tmp_path, seconds=0)    # two powers, no waiting
    d = lbd.load(path)
    assert d.lbd_version == "2.0" and list(d.groups) == ["scan"]
    assert d.values["Q"].data.shape == (2,) and len(d.axes["freq"].data) == 46 + 40


def test_healthy_mock_data_has_nothing_broken_or_in_conflict(tmp_path):
    """18.5: --healthy, to play around with: every file reads and has an id; no copies, conflict,
    missing file or sync conflict copy; the labels are still there."""
    pytest.importorskip("lbd_viewer")
    make = load("make_mock_data")
    made = make.make(tmp_path / "mock", files=30, small=True, healthy=True)
    root = tmp_path / "mock"
    assert made["special"] == {} and made["healthy"]
    files = sorted(root.rglob("*.lbd"))
    assert len(files) >= 25
    for p in files:
        assert lbd.info(p).id, p                                      # reads, and has an id
    assert not list(root.rglob("*Conflict*")) and not (root / "Lab library" / "Shared" / "Backup").exists()
    sides = list(root.rglob(".lbd-library.json"))
    entries = [(side.parent, e) for side in sides for e in json.loads(side.read_text("utf-8"))["files"]]
    assert any(e["tags"] for _, e in entries)                         # labelled
    assert all((where / e["name"]).exists() for where, e in entries)  # no label without its file
    assert "healthy" in "\n".join(make.report(root, made))
    # the same folder made without --healthy has the problem cases
    plain = make.make(tmp_path / "plain", files=30, small=True)
    assert set(plain["special"]) >= {"copy", "conflict", "no_id", "missing"}
    assert (tmp_path / "plain" / "Lab library" / "Lab data" / "2026" / "03" / "14" / "broken.lbd").exists()


def test_a_live_measurement_without_the_stopped_one(tmp_path):
    """18.5: mock_live.py --no-stopped (what --healthy --live runs) leaves no stopped measurement."""
    import subprocess

    subprocess.run([sys.executable, str(REPO / "viewer" / "tests" / "mock_live.py"), str(tmp_path), "--seconds", "0",
                    "--no-stopped"], check=True, capture_output=True, timeout=120)
    assert not list(tmp_path.glob("stopped*")) and (tmp_path / "live sweep.lbd").exists()
