"""scripts/make_mock_data.py: one command makes a whole folder of mock data, with every kind of
label (stars, nested projects, users and tags, comments, labels kept without a file); and
scripts/dev_viewer.py refuses to start without a built UI or with a folder that isn't one."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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


def test_the_dev_viewer_checks_first(tmp_path, monkeypatch):
    dev = load("dev_viewer")
    monkeypatch.setattr(dev, "STATIC", tmp_path / "missing.html")
    assert dev.main([str(tmp_path)]) == 2                                                    # the UI isn't built
    monkeypatch.setattr(dev, "STATIC", Path(__file__))
    assert dev.main([str(tmp_path / "nowhere")]) == 2                                        # not a folder
