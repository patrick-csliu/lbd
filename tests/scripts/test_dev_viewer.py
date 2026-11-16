"""scripts/dev_viewer.py: it refuses to start without a built UI or with a folder that isn't one,
says when Help (site/) is older than the docs, and deletes its scratch folders: its own when the
viewer stops, old ones whose dev_viewer.py has stopped, never one still running or a folder the
user named. No viewer is started here."""

import importlib.util
import os
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def dev():
    spec = importlib.util.spec_from_file_location("dev_viewer", REPO / "scripts" / "dev_viewer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scratch(root: Path, name: str, pid=None, age: float = 3600) -> Path:
    """A scratch folder as dev_viewer.py makes it, with a marker holding `pid` (none when None),
    last changed `age` seconds ago."""
    d = root / f"lbd-dev-viewer-{name}"
    (d / "settings").mkdir(parents=True)
    if pid is not None:
        (d / "dev_viewer.pid").write_text(str(pid), encoding="utf-8")
    t = time.time() - age
    os.utime(d, (t, t))
    return d


def test_the_dev_viewer_checks_first_and_leaves_no_scratch_folder(dev, tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "SCRATCH_ROOT", tmp_path)
    monkeypatch.setattr(dev, "STATIC", tmp_path / "missing.html")
    assert dev.main([str(tmp_path)]) == 2                                   # the UI isn't built
    monkeypatch.setattr(dev, "STATIC", Path(__file__))
    assert dev.main([str(tmp_path / "nowhere")]) == 2                       # not a folder
    assert not list(tmp_path.glob("lbd-dev-viewer-*"))                      # its scratch folder is gone


def test_old_scratch_folders_of_stopped_runs_are_deleted_running_ones_kept(dev, tmp_path):
    alive = {111}
    running = scratch(tmp_path, "running", pid=111)
    stopped = scratch(tmp_path, "stopped", pid=222)
    no_marker = scratch(tmp_path, "old-no-marker")
    bad_marker = scratch(tmp_path, "bad-marker", pid="not a number")
    just_made = scratch(tmp_path, "just-made", age=0)                       # its marker may come any moment
    other = tmp_path / "someone-else"                                       # not made by dev_viewer.py
    other.mkdir()
    removed = dev.remove_old_scratch(tmp_path, pid_alive=lambda pid: pid in alive)
    assert set(removed) == {stopped, no_marker, bad_marker}
    assert running.is_dir() and just_made.is_dir() and other.is_dir()
    assert not stopped.exists() and not no_marker.exists()


def test_folders_the_user_named_are_never_deleted(dev, tmp_path):
    settings = scratch(tmp_path, "kept-settings")                           # --keep-settings, no marker
    data = scratch(tmp_path, "data", pid=222)                               # FOLDER, its run stopped
    holder = scratch(tmp_path, "holder", pid=222)                           # holds a named folder
    named = holder / "settings"
    removed = dev.remove_old_scratch(tmp_path, keep=[settings, data, named], pid_alive=lambda pid: False)
    assert removed == []
    assert settings.is_dir() and data.is_dir() and named.is_dir()


def test_a_scratch_folder_has_a_marker_with_this_pid(dev, tmp_path):
    d = dev.make_scratch(tmp_path)
    assert d.name.startswith("lbd-dev-viewer-") and dev.marker_pid(d) == os.getpid()
    assert dev.old_scratch_folders(tmp_path) == []                          # this process runs
    assert dev.remove_folder(d) and not d.exists()


def test_a_line_says_when_help_is_older_than_the_docs(dev, tmp_path):
    docs = tmp_path / "docs"
    (docs / "developers").mkdir(parents=True)
    page = docs / "developers" / "index.md"
    page.write_text("# Page", encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog", encoding="utf-8")
    site = tmp_path / "site" / "index.html"
    sources = [docs, changelog, tmp_path / "spec"]                          # spec/ missing: fine

    assert "isn't built" in dev.docs_out_of_date(site, sources)            # no site/ at all
    site.parent.mkdir()
    site.write_text("<html>", encoding="utf-8")
    t = time.time()
    os.utime(site, (t, t))
    for f in (page, changelog):
        os.utime(f, (t - 100, t - 100))
    assert dev.docs_out_of_date(site, sources) is None                     # built after the last change
    os.utime(page, (t + 10, t + 10))
    line = dev.docs_out_of_date(site, sources)
    assert "older than the docs" in line and "dev_viewer.py --build" in line


def test_build_stops_when_the_docs_build_fails(dev, tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "SCRATCH_ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(dev, "build_ui", lambda: calls.append("ui") or 0)
    monkeypatch.setattr(dev, "build_docs", lambda: calls.append("docs") or 1)
    monkeypatch.setattr(dev, "run_viewer", lambda *a: pytest.fail("the viewer must not start"))
    assert dev.main(["--build", str(tmp_path)]) == 1
    assert calls == ["ui", "docs"]
