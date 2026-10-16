"""Packaging helpers and the example generator."""

import sys

import pytest

import lbd


# ---- stage_sdk.py --------------------------------------------------------------------------------


def test_stage_sdk_with_fallbacks(load_module, tmp_path, monkeypatch, capsys):
    stage = load_module("packaging/stage_sdk.py")
    langs = stage.discover()
    # No real builds: python's build is skipped via --skip only if it has a fallback, so fake the runs.
    calls = []

    class R:
        returncode = 0

    for lang in langs:
        monkeypatch.setattr(type(lang), "run", lambda self, cmd, **kw: (calls.append((self.id, kw)), R())[1])
    monkeypatch.setattr(type(langs[0]), "missing_tool", lambda self, section: None)
    dest = tmp_path / "sdk"
    (dest / "stale").mkdir(parents=True)
    assert stage.main(["--dest", str(dest), "--skip", "matlab"]) == 0
    assert not (dest / "stale").exists()
    assert (dest / "LBD-v1.md").is_file() and "Language modules" in (dest / "README.txt").read_text()
    assert (dest / "LICENSE").is_file()
    for lang in langs:
        assert (dest / lang.id / "language.toml").is_file()
        assert (dest / lang.id / "LICENSE").is_file()
    assert (dest / "matlab" / "+lbd").is_dir()                # fallback_copy
    assert ("python", ) == tuple(c[0] for c in calls if c[0] == "python")[:1]
    assert all(kw.get("version") for _, kw in calls)


def test_stage_sdk_unknown_skip(load_module, tmp_path):
    stage = load_module("packaging/stage_sdk.py")
    with pytest.raises(SystemExit, match="unknown language"):
        stage.main(["--dest", str(tmp_path / "sdk"), "--skip", "cobol"])


def test_stage_sdk_version_mismatch(load_module, tmp_path, monkeypatch):
    stage = load_module("packaging/stage_sdk.py")

    def mismatch():
        raise stage.VersionError("release versions differ")

    monkeypatch.setattr(stage, "release_version", mismatch)
    with pytest.raises(SystemExit, match="differ"):
        stage.main(["--dest", str(tmp_path / "sdk")])


def test_copy_items_missing(load_module, tmp_path):
    stage = load_module("packaging/stage_sdk.py")
    lang = stage.discover()[0]
    with pytest.raises(SystemExit, match="does not exist"):
        stage.copy_items(lang, ["nope.txt"], tmp_path)


# ---- make_icons.py --------------------------------------------------------------------------------


def test_icon_drawing(load_module, tmp_path, monkeypatch):
    icons = load_module("packaging/make_icons.py")
    img = icons.draw(64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    monkeypatch.setattr(icons, "OUT", tmp_path)
    icons.main()
    assert {p.suffix for p in tmp_path.iterdir()} >= {".png", ".ico", ".svg"}


# ---- entry.py ---------------------------------------------------------------------------------------


def test_entry_log_rotation(load_module, tmp_path, monkeypatch):
    entry = load_module("packaging/entry.py")
    import platformdirs

    monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **k: str(tmp_path))
    log = entry._log_file()
    log.write_bytes(b"x" * 2_000_000)
    rotated = entry._log_file()
    assert rotated == log
    assert any(p.name != log.name for p in tmp_path.iterdir())     # the old log was kept aside


# ---- examples/make_examples.py -----------------------------------------------------------------------


def test_make_examples(load_module, tmp_path):
    mk = load_module("examples/make_examples.py")
    out = mk.main(tmp_path / "ex")
    names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert "rabi.lbd" in names and "2026/resonator/power_sweep.lbd" in names and "thesis.lbd.json" in names
    for p in out.rglob("*.lbd"):
        lbd.load(p)


def test_make_examples_keeps_a_saved_view(load_module, tmp_path, capsys):
    mk = load_module("examples/make_examples.py")
    out = mk.main(tmp_path / "ex")
    lbd.set_plot(out / "temperature_map.lbd", spec={"kind": "curve", "title": "mine"}, style_name="thesis")
    mk.main(out)
    d = lbd.info(out / "temperature_map.lbd")
    assert d.plot == {"kind": "curve", "title": "mine"} and d.style_name == "thesis"
    assert "kept the saved view of temperature_map.lbd" in capsys.readouterr().out


def test_python_version():
    assert sys.version_info >= (3, 9)


@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_linux_scripts_parse(script):
    """`sh -n`: the Linux install scripts have no syntax errors (needs a POSIX shell)."""
    import shutil
    import subprocess
    from pathlib import Path

    sh = shutil.which("sh") or shutil.which("bash")
    if not sh:
        pytest.skip("no POSIX shell here")
    path = Path(__file__).resolve().parents[2] / "packaging" / "linux" / script
    r = subprocess.run([sh, "-n", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_every_language_has_the_same_license(load_module):
    """Each language folder can be installed on its own, so each carries the top LICENSE."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    top = (root / "LICENSE").read_text(encoding="utf-8")
    for lang in load_module("scripts/languages.py").discover():
        copy = lang.dir / "LICENSE"
        assert copy.is_file(), f"copy LICENSE into {lang.dir.relative_to(root)}"
        assert copy.read_text(encoding="utf-8") == top, f"{copy.relative_to(root)} differs from the top LICENSE"


def test_shell_scripts_have_unix_line_endings():
    """A shell script with Windows line endings (CRLF) fails on Linux with confusing errors."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    scripts = sorted(root.glob("packaging/linux/*.sh")) + sorted(root.glob("scripts/*.sh"))
    assert scripts
    crlf = [str(p.relative_to(root)) for p in scripts if b"\r\n" in p.read_bytes()]
    assert not crlf, f"convert to LF line endings: {crlf}"


def test_uninstaller_keeps_settings_by_default():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "packaging"
    iss = (root / "windows" / "LBDViewer.iss").read_text(encoding="utf-8")
    assert "MB_DEFBUTTON2" in iss and "not UninstallSilent" in iss       # "No" is the default
    # asked before anything is removed, and never deleted permanently: to the Recycle Bin
    assert "CurUninstallStep = usUninstall" in iss and "SendToRecycleBin" in iss
    assert "DelTree(ExpandConstant('{userappdata}" not in iss
    sh = (root / "linux" / "uninstall.sh").read_text(encoding="utf-8")
    assert "answer=n" in sh and "[y/N]" in sh
