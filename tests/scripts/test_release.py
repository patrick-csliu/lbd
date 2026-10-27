"""Release scripts: bump_version, release_notes, smoke_test_app and build_wheels."""

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Everything bump_version.py reads or writes, copied so the tests never touch the repository.
FILES = ["CHANGELOG.md", "uv.lock", "viewer/pyproject.toml", "viewer/src/lbd_viewer/__init__.py",
         "viewer/web/package.json", "viewer/web/package-lock.json", "spec/LBD-v1.md"]


# The copy's version, whatever the repository's is right now (a release or X.Y.Z-dev).
CURRENT = "1.1.0"
HIGHER = "1.2.0"


@pytest.fixture()
def repo(tmp_path, bump):
    """A copy of the files that carry the version, all set to CURRENT (the CHANGELOG's top section
    is unreleased)."""
    for rel in FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "languages", tmp_path / "languages",
                    ignore=shutil.ignore_patterns("__pycache__", "tests", "test", "crosslang"))
    for where, path, pattern in bump.version_locations(tmp_path):
        bump.write(path, bump.set_version(bump.read(path), pattern, CURRENT, where))
    # A CHANGELOG of its own, so the tests don't depend on what the real one says right now.
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n- a change\n\n## 0.9.0 (2026-01-01)\n\n- older\n", encoding="utf-8")
    return tmp_path


@pytest.fixture(scope="module")
def bump(load_module):
    return load_module("scripts/bump_version.py")


@pytest.fixture(scope="module")
def notes(load_module):
    return load_module("scripts/release_notes.py")


@pytest.fixture(scope="module")
def versions(load_module):
    return load_module("scripts/check_versions.py")


@pytest.fixture()
def current():
    return CURRENT


@pytest.fixture()
def higher():
    return HIGHER


# ---- check_versions.py --------------------------------------------------------------------------


@pytest.mark.parametrize("text, form, expected", [
    ("1.2.0", "python", (1, 2, 0, False)),
    ("1.2.0.dev0", "python", (1, 2, 0, True)),
    ("1.2.0-dev.0", "npm", (1, 2, 0, True)),
    ("1.2.0-dev", "text", (1, 2, 0, True)),
    ("1.2.0-dev", "python", None),        # each file must use its own spelling
    ("1.2.0.dev0", "text", None),
    ("1.2.0rc1", "python", None),
    ("1.2", "text", None),
])
def test_parse_version_forms(versions, text, form, expected):
    v = versions.parse_version(text, form)
    assert (tuple(v) if v else None) == expected


def test_version_spellings_and_order(versions):
    dev = versions.Version(1, 2, 0, True)
    assert [dev.spell(f) for f in ("python", "npm", "text", "number")] == ["1.2.0.dev0", "1.2.0-dev.0", "1.2.0-dev", "1.2.0"]
    assert str(dev) == "1.2.0-dev"
    assert versions.Version(1, 1, 0).order() < dev.order() < versions.Version(1, 2, 0).order()


def test_check_versions_names_a_file_with_the_wrong_spelling(versions, bump, repo):
    init = repo / "viewer" / "src" / "lbd_viewer" / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace(f'"{CURRENT}"', f'"{CURRENT}-dev"'), encoding="utf-8")
    with pytest.raises(versions.VersionError, match=r"lbd_viewer/__init__.py  \(not a version as python files write it\)"):
        bump.the_version(repo)


# ---- bump_version.py ----------------------------------------------------------------------------


def test_bump_sets_every_version_and_dates_the_changelog(bump, versions, repo, capsys, higher):
    real_lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    assert bump.main([higher], repo=repo, today="2026-11-03") == 0
    release, _ = versions.collect(repo)
    assert set(release.values()) == {higher} and len(release) >= 12   # every place, lock files too
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {higher} (2026-11-03)\n\n- a change" in changelog and "## Unreleased" not in changelog
    assert "git tag -a v" + higher in capsys.readouterr().out
    assert (REPO / "uv.lock").read_text(encoding="utf-8") == real_lock   # the repository is untouched


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


def test_bump_dev_writes_each_spelling_and_starts_the_changelog(bump, versions, repo, capsys, higher):
    assert bump.main([higher, "--dev"], repo=repo) == 0
    assert str(bump.the_version(repo)) == f"{higher}-dev"
    release, _ = versions.collect(repo)
    assert release["uv.lock (lbd)"] == f"{higher}.dev0"
    assert release["viewer/web/package.json"] == f"{higher}-dev.0"
    assert release["languages/julia/Project.toml"] == f"{higher}-dev"
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.startswith(f"# Changelog\n\n## {higher} (in development)\n\n- a change")   # "Unreleased" renamed
    assert "can't be released" in capsys.readouterr().out


def test_bump_dev_then_release(bump, repo, capsys, higher):
    changelog = repo / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 0.9.0 (2026-01-01)\n\n- older\n", encoding="utf-8")
    assert bump.main([higher, "--dev"], repo=repo) == 0
    assert bump.main([higher, "--dev"], repo=repo) == 0        # again: the section is kept, not doubled
    text = changelog.read_text(encoding="utf-8")
    assert text.count(f"## {higher} (in development)") == 1
    changelog.write_text(text.replace("(in development)\n", "(in development)\n\n- a change\n"), encoding="utf-8")
    assert bump.main([higher], repo=repo, today="2026-11-03") == 0
    assert str(bump.the_version(repo)) == higher
    assert f"## {higher} (2026-11-03)\n\n- a change" in changelog.read_text(encoding="utf-8")
    # A released version can't go back to development.
    assert bump.main([higher, "--dev"], repo=repo) == 1
    assert "lower than the current version" in capsys.readouterr().err


def test_bump_refuses_a_dev_spelling_as_the_argument(bump, repo, capsys, higher):
    assert bump.main([f"{higher}-dev"], repo=repo) == 1
    assert "add --dev" in capsys.readouterr().err


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


def test_release_notes_of_a_dev_version(notes, tmp_path, capfdbinary):
    """A trial build of 0.3.0-dev shows the section in development; a release of it is refused."""
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    assert notes.main(["0.3.0-dev", "--allow-unreleased"], repo=tmp_path) == 0
    out = capfdbinary.readouterr()
    assert out.out == b"- next\n"
    assert notes.main(["0.3.0-dev"], repo=tmp_path) == 1
    assert b"development version; it can't be released" in capfdbinary.readouterr().err


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


# ---- build_wheels.py ----------------------------------------------------------------------------


def test_build_wheels_always_removes_the_staged_folders(load_module, tmp_path, monkeypatch):
    bw = load_module("scripts/build_wheels.py")
    package = tmp_path / "lbd_viewer"
    monkeypatch.setattr(bw, "PACKAGE", package)
    monkeypatch.setattr(bw, "STAGED", [package / "docs", package / "sdk"])
    steps = []

    def run(cmd, cwd=None):
        steps.append(cmd[:2])
        (package / "docs").mkdir(parents=True, exist_ok=True)   # as if mkdocs had written it
        if "stage_sdk.py" in " ".join(cmd):
            raise SystemExit("stage_sdk failed")

    monkeypatch.setattr(bw, "run", run)
    with pytest.raises(SystemExit, match="stage_sdk failed"):
        bw.build(tmp_path / "out", [])
    assert not (package / "docs").exists() and not (package / "sdk").exists()
    assert ["npm", "ci"] in steps


def test_build_wheels_checks_the_viewer_wheel(load_module, tmp_path, monkeypatch, versions):
    import zipfile

    current = versions.release_version("python")     # wheel names: 1.2.0.dev0 for 1.2.0-dev
    bw = load_module("scripts/build_wheels.py")
    monkeypatch.setattr(bw, "STAGED", [])
    out = tmp_path / "out"

    def run(cmd, cwd=None):           # "build" wheels without the Help inside
        if cmd[:2] == ["uv", "build"]:
            name = "lbd" if cmd[3] == "lbd" else "lbd_viewer"
            with zipfile.ZipFile(out / f"{name}-{current}-py3-none-any.whl", "w") as z:
                z.writestr("lbd_viewer/static/index.html", "ui")

    monkeypatch.setattr(bw, "run", run)
    with pytest.raises(SystemExit, match="lacks.*docs/index.html"):
        bw.build(out, [])


# ---- macos_min_version.py -----------------------------------------------------------------------

OTOOL = """Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 11.0
      sdk 14.2
Load command 10
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.13
      sdk 10.15
Load command 11
      cmd LC_BUILD_VERSION
 platform 1
    minos 13.3
"""


def test_macos_min_version_reads_both_load_commands(load_module):
    mm = load_module("scripts/macos_min_version.py")
    assert sorted(mm.parse_versions(OTOOL)) == [(10, 13), (11, 0), (13, 3)]
    assert mm.as_text(max(mm.parse_versions(OTOOL))) == "13.3"
    assert mm.parse_versions("not an object file") == []
