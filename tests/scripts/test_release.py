"""Release scripts: bump_version.py, release_notes.py and smoke_test_app.py."""

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Everything bump_version.py reads or writes, copied so the tests never touch the repository.
FILES = ["CHANGELOG.md", "uv.lock", "viewer/pyproject.toml", "viewer/src/lbd_viewer/__init__.py",
         "viewer/web/package.json", "viewer/web/package-lock.json", "spec/LBD-v1.md"]


@pytest.fixture()
def repo(tmp_path):
    """A copy of the files that carry the version (the CHANGELOG's top section is unreleased)."""
    for rel in FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "languages", tmp_path / "languages",
                    ignore=shutil.ignore_patterns("__pycache__", "tests", "test", "crosslang"))
    changelog = tmp_path / "CHANGELOG.md"
    head, _, rest = changelog.read_text(encoding="utf-8").partition("\n## ")
    changelog.write_text(head + "\n## Unreleased\n\n- a change\n\n## " + rest, encoding="utf-8")
    return tmp_path


@pytest.fixture(scope="module")
def bump(load_module):
    return load_module("scripts/bump_version.py")


@pytest.fixture(scope="module")
def notes(load_module):
    return load_module("scripts/release_notes.py")


@pytest.fixture(scope="module")
def current(load_module):
    """The repository's version now, e.g. "0.1.0"."""
    return load_module("scripts/check_versions.py").release_version()


@pytest.fixture(scope="module")
def higher(current):
    """A version above the current one, e.g. "0.2.0"."""
    major, minor, _ = (int(n) for n in current.split("."))
    return f"{major}.{minor + 1}.0"


# ---- bump_version.py ----------------------------------------------------------------------------


def test_bump_sets_every_version_and_dates_the_changelog(bump, repo, capsys, higher):
    assert bump.main([higher], repo=repo, today="2026-11-03") == 0
    release, _ = bump.collect(repo)
    assert set(release.values()) == {higher} and len(release) >= 12   # every place, lock files too
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {higher} (2026-11-03)\n\n- a change" in changelog and "## Unreleased" not in changelog
    assert "git tag v" + higher in capsys.readouterr().out
    assert (REPO / "uv.lock").read_text(encoding="utf-8") != (repo / "uv.lock").read_text(encoding="utf-8")


def test_bump_to_the_same_version_releases_it(bump, repo, current):
    assert bump.main([current], repo=repo, today="2026-11-03") == 0
    assert f"## {current} (2026-11-03)" in (repo / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("version, message", [
    ("0.2", "X.Y.Z"),
    ("0.2.0rc1", "X.Y.Z"),
    ("v0.2.0", "X.Y.Z"),
    ("0.0.1", "lower than the current version"),
])
def test_bump_refuses_bad_versions_and_writes_nothing(bump, repo, capsys, version, message):
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert bump.main([version], repo=repo) == 1
    assert message in capsys.readouterr().err
    assert before == {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}


def test_bump_needs_changelog_notes(bump, repo, capsys, higher):
    changelog = repo / "CHANGELOG.md"
    head = changelog.read_text(encoding="utf-8").split("\n## ")[0]
    changelog.write_text(head + "\n## Unreleased\n\n## 0.0.1 (2020-01-01)\n\nold\n", encoding="utf-8")
    assert bump.main([higher], repo=repo) == 1
    assert "empty" in capsys.readouterr().err
    changelog.write_text(head + "\n## 0.0.1 (2020-01-01)\n\nold\n", encoding="utf-8")
    assert bump.main([higher], repo=repo) == 1
    assert "no \"## Unreleased\"" in capsys.readouterr().err


def test_bump_keeps_windows_line_endings(bump, repo, higher):
    path = repo / "viewer" / "pyproject.toml"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert bump.main([higher], repo=repo) == 0
    data = path.read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")


def test_bump_dry_run_writes_nothing(bump, repo, capsys, higher):
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert bump.main([higher, "--dry-run"], repo=repo) == 0
    out = capsys.readouterr().out
    assert "uv.lock" in out and "CHANGELOG.md" in out and "Nothing written" in out
    assert before == {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}


def test_bump_refuses_when_files_disagree(bump, repo, capsys, current, higher):
    init = repo / "viewer" / "src" / "lbd_viewer" / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace(current, "9.9.9"), encoding="utf-8")
    assert bump.main([higher], repo=repo) == 1
    assert "don't agree" in capsys.readouterr().err


# ---- release_notes.py ---------------------------------------------------------------------------

CHANGELOG = """# Changelog

## 0.3.0 (in development)

- next

## 0.2.0 (2026-11-03)

**Viewer**

- a thing ≥ 0.5 pt

## 0.1.0 (2026-10-01)

- first
"""


def test_release_notes_section(notes):
    assert notes.section(CHANGELOG, "0.2.0") == "**Viewer**\n\n- a thing ≥ 0.5 pt\n"
    assert notes.section(CHANGELOG, "0.1.0") == "- first\n"
    assert notes.section(CHANGELOG, "0.3.0", allow_unreleased=True) == "- next\n"


@pytest.mark.parametrize("version, message", [
    ("0.4.0", "no \"## 0.4.0"),
    ("0.3.0", "still in development"),
])
def test_release_notes_errors(notes, version, message):
    with pytest.raises(notes.NotesError, match=message):
        notes.section(CHANGELOG, version)


def test_release_notes_empty_section(notes):
    with pytest.raises(notes.NotesError, match="empty"):
        notes.section("## 0.2.0 (2026-11-03)\n\n## 0.1.0 (2026-10-01)\n- x\n", "0.2.0")


def test_release_notes_main_writes_utf8(notes, tmp_path, capfdbinary):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    assert notes.main(["0.2.0"], repo=tmp_path) == 0
    assert "≥".encode("utf-8") in capfdbinary.readouterr().out
    assert notes.main(["0.9.9"], repo=tmp_path) == 1


# ---- smoke_test_app.py --------------------------------------------------------------------------


def test_smoke_test_passes_on_the_source_viewer(load_module, capsys):
    smoke = load_module("scripts/smoke_test_app.py")
    assert smoke.run([sys.executable, "-m", "lbd_viewer"], REPO / "examples" / "data", release=False) == 0
    out = capsys.readouterr().out
    assert "ok    export PDF" in out and "SMOKE TEST PASSED" in out


def test_smoke_test_release_checks_catch_a_missing_sdk(load_module, capsys):
    """Run from source, the viewer has no bundled language modules: --release must fail on that."""
    smoke = load_module("scripts/smoke_test_app.py")
    assert smoke.run([sys.executable, "-m", "lbd_viewer"], REPO / "examples" / "data", release=True) == 1
    out = capsys.readouterr().out
    assert "FAIL  sdk" in out and "not bundled" in out and "SMOKE TEST FAILED" in out


def test_smoke_test_reports_a_viewer_that_does_not_start(load_module, capsys):
    smoke = load_module("scripts/smoke_test_app.py")
    assert smoke.run([sys.executable, "-c", "raise SystemExit(3)"], REPO / "examples" / "data", release=False) == 1
    assert "exited with code 3" in capsys.readouterr().out
