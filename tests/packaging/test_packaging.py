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


def test_stage_sdk_prebuilt(load_module, tmp_path, monkeypatch):
    stage = load_module("packaging/stage_sdk.py")
    built = tmp_path / "mltbx"
    built.mkdir()
    (built / "LBD.mltbx").write_bytes(b"toolbox")
    for lang in stage.discover():   # no real builds: python would build a wheel
        monkeypatch.setattr(type(lang), "run", lambda self, cmd, **kw: type("R", (), {"returncode": 0})())
    dest = tmp_path / "sdk"
    assert stage.main(["--dest", str(dest), "--prebuilt", f"matlab={built}"]) == 0
    assert (dest / "matlab" / "LBD.mltbx").read_bytes() == b"toolbox"
    assert (dest / "matlab" / "LICENSE").is_file()          # the extras are still copied
    assert not (dest / "matlab" / "+lbd").exists()           # not the fallback


@pytest.mark.parametrize("arg, message", [
    ("matlab", "write ID=DIR"),
    ("cobol={tmp}", "unknown language"),
    ("matlab={tmp}/missing", "missing or empty"),
    ("matlab={tmp}/empty", "missing or empty"),
])
def test_stage_sdk_prebuilt_errors(load_module, tmp_path, arg, message):
    stage = load_module("packaging/stage_sdk.py")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit, match=message):
        stage.main(["--dest", str(tmp_path / "sdk"), "--prebuilt", arg.format(tmp=tmp_path)])


def test_stage_sdk_prebuilt_and_skip(load_module, tmp_path):
    stage = load_module("packaging/stage_sdk.py")
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "LBD.mltbx").write_bytes(b"x")
    with pytest.raises(SystemExit, match="both --skip and --prebuilt"):
        stage.main(["--dest", str(tmp_path / "sdk"), "--skip", "matlab", "--prebuilt", f"matlab={tmp_path / 'm'}"])


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
    assert {p.suffix for p in tmp_path.iterdir()} >= {".png", ".ico", ".icns", ".svg"}


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


@pytest.mark.parametrize("platform, frozen, argv, expected", [
    ("darwin", True, ["LBD Viewer"], True),                       # double-clicked in Finder
    ("darwin", True, ["LBD Viewer", "-psn_0_12345"], True),       # older macOS adds this
    ("darwin", True, ["lbd-view", "--no-browser"], False),        # Terminal / smoke test: the CLI
    ("darwin", False, ["lbd-view"], False),                       # uv tool install: the CLI
    ("win32", True, ["lbd-view.exe"], False),
])
def test_entry_finder_launch(load_module, monkeypatch, platform, frozen, argv, expected):
    entry = load_module("packaging/entry.py")
    monkeypatch.setattr(entry.sys, "platform", platform)
    monkeypatch.setattr(entry.sys, "argv", argv)
    monkeypatch.setattr(entry.sys, "frozen", frozen, raising=False)
    assert entry.finder_launch() is expected


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


def test_ensure_examples_writes_a_missing_folder_only(load_module, tmp_path, monkeypatch):
    """18.6: ensure_examples writes the files when the folder is missing and leaves a folder that
    exists alone; when this Python can't write them, it says how to make them."""
    mk = load_module("examples/make_examples.py")
    out = mk.ensure_examples(tmp_path / "ex")
    assert out == tmp_path / "ex" and lbd.info(out / "rabi.lbd").id
    (out / "rabi.lbd").unlink()
    assert mk.ensure_examples(out) == out and not (out / "rabi.lbd").exists()   # not written again
    monkeypatch.setitem(sys.modules, "lbd", None)                               # as in a bare Python
    with pytest.raises(SystemExit, match="examples/make_examples.py"):
        mk.ensure_examples(tmp_path / "missing")


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


def test_windows_installer_asks_for_shortcuts():
    """Start menu shortcut: yes by default; desktop shortcut: no by default."""
    from pathlib import Path

    iss = (Path(__file__).resolve().parents[2] / "packaging" / "windows" / "LBDViewer.iss").read_text(encoding="utf-8")
    tasks = {line.split('"')[1]: line for line in iss.splitlines() if line.startswith('Name: "') and "Description:" in line}
    assert set(tasks) == {"startmenu", "desktopicon"}
    assert "unchecked" not in tasks["startmenu"] and "Flags: unchecked" in tasks["desktopicon"]
    assert '{autoprograms}\\LBD Viewer"; Filename: "{app}\\lbd-view.exe"; Comment: "View LBD data files"; Tasks: startmenu' in iss
    assert '{autodesktop}\\LBD Viewer"; Filename: "{app}\\lbd-view.exe"; Comment: "View LBD data files"; Tasks: desktopicon' in iss


def _posix_shell():
    import shutil

    sh = shutil.which("sh") or shutil.which("bash")
    if not sh:
        pytest.skip("no POSIX shell here")
    return sh


def linux_package(folder, version):
    """An unpacked Linux package as build_linux.sh makes it, with a fake `lbd-view` that notes
    `--stop` in the home folder (how install.sh stops a running viewer)."""
    import shutil
    from pathlib import Path

    linux = Path(__file__).resolve().parents[2] / "packaging" / "linux"
    (folder / "LBDViewer").mkdir(parents=True)
    for f in ("install.sh", "uninstall.sh", "lbd-viewer.desktop", "lbd-mime.xml"):
        shutil.copy(linux / f, folder / f)
    for f in ("lbd.png", "lbd.svg"):
        shutil.copy(linux.parent / "icons" / f, folder / f)
    exe = folder / "LBDViewer" / "lbd-view"
    exe.write_text(f'#!/bin/sh\n[ "$1" = --stop ] && echo "{version}" >> "$HOME/stopped"\necho viewer {version}\n',
                   newline="\n")
    exe.chmod(0o755)
    (folder / "LBDViewer" / "VERSION").write_text(version + "\n", newline="\n")
    return folder


def linux_home(tmp_path):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "XDG_DATA_HOME": str(home / "data"), "XDG_CONFIG_HOME": str(home / "config"),
           "PATH": __import__("os").environ["PATH"]}
    return home, env


def run_sh(script, env, *args, ok=True):
    import subprocess

    r = subprocess.run([_posix_shell(), str(script), *args], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    return r


def test_linux_install_without_a_terminal_uses_the_shortcut_defaults(tmp_path):
    """Run install.sh (and uninstall.sh) into a temporary home, unattended: a menu entry, no
    desktop shortcut; uninstall removes everything it made."""
    _posix_shell()
    unpacked = linux_package(tmp_path / "unpacked", "1.3.0")
    home, env = linux_home(tmp_path)

    out = run_sh(unpacked / "install.sh", env, "--no-fonts").stdout
    entry = home / "data" / "applications" / "lbd-viewer.desktop"
    assert entry.is_file() and "NoDisplay" not in entry.read_text()        # in the menu
    assert not (home / "Desktop" / "lbd-viewer.desktop").exists()           # no desktop shortcut
    assert "applications menu" in out
    run_sh(unpacked / "uninstall.sh", env)
    assert not entry.exists() and not (home / "data" / "lbd-viewer").exists()


def test_linux_upgrade_keeps_settings_and_refuses_an_older_version(tmp_path):
    """Plan 16.26's upgrade test, locally: an installation from before 1.3.0 (no VERSION file),
    settings and labels; the new version replaces it (stopping the old viewer first) and keeps
    them; then an older package is refused, leaving the new one as it was."""
    _posix_shell()
    home, env = linux_home(tmp_path)
    app = home / "data" / "lbd-viewer"
    (app / "_internal").mkdir(parents=True)                       # "1.2.0", installed before
    (app / "_internal" / "old-only.py").write_text("old")
    (app / "lbd-view").write_text('#!/bin/sh\necho "old" >> "$HOME/stopped"\n', newline="\n")
    (app / "lbd-view").chmod(0o755)
    settings = home / "config" / "lbd" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"roots": ["/data"], "theme": "dark"}')
    labels = home / "measurements" / "lbd-labels.json"
    labels.parent.mkdir()
    labels.write_text('{"a.lbd": {"tags": ["x"]}}')

    new = linux_package(tmp_path / "new", "1.3.0")
    out = run_sh(new / "install.sh", env, "--no-fonts").stdout
    assert "Replacing the earlier LBD Viewer with 1.3.0" in out
    assert (home / "stopped").read_text().split() == ["old"]                 # the old viewer was asked to stop
    assert not (app / "_internal" / "old-only.py").exists()                  # the old program folder is gone
    assert (app / "VERSION").read_text().strip() == "1.3.0" and (app / "uninstall.sh").is_file()
    assert settings.read_text() == '{"roots": ["/data"], "theme": "dark"}' and labels.is_file()

    older = linux_package(tmp_path / "older", "1.2.9")
    r = run_sh(older / "install.sh", env, "--no-fonts", ok=False)
    assert "LBD Viewer 1.3.0 is installed, newer than this installer (1.2.9)" in r.stderr
    assert "uninstall.sh first" in r.stderr and "settings and Library are kept" in r.stderr
    assert (app / "VERSION").read_text().strip() == "1.3.0"                  # untouched

    same = run_sh(new / "install.sh", env, "--no-fonts").stdout                # the same again: fine
    assert "Replacing LBD Viewer 1.3.0 with 1.3.0" in same
    assert (home / "stopped").read_text().split() == ["old", "1.3.0"]
    run_sh(app / "uninstall.sh", env)                                        # the copy kept next to the app
    assert not app.exists() and settings.is_file()


@pytest.mark.parametrize("installed, package, refused", [
    ("1.3.0", "1.2.0", True), ("1.3.0", "1.3.0-dev", True), ("1.10.0", "1.9.0", True),
    ("1.3.0-dev", "1.3.0", False), ("1.2.0", "1.3.0", False), ("1.3.0", "1.3.0", False), ("garbage", "1.0.0", False),
])
def test_linux_installer_compares_versions(tmp_path, installed, package, refused):
    _posix_shell()
    home, env = linux_home(tmp_path)
    (home / "data" / "lbd-viewer").mkdir(parents=True)
    (home / "data" / "lbd-viewer" / "VERSION").write_text(installed)
    run_sh(linux_package(tmp_path / "pkg", package) / "install.sh", env, "--no-fonts", ok=not refused)


def test_linux_package_without_a_version_is_refused(tmp_path):
    _posix_shell()
    home, env = linux_home(tmp_path)
    pkg = linux_package(tmp_path / "pkg", "1.3.0")
    (pkg / "LBDViewer" / "VERSION").unlink()
    assert "VERSION is missing" in run_sh(pkg / "install.sh", env, ok=False).stderr


def test_windows_installer_refuses_an_older_version_and_stops_gently():
    """The Inno Setup script's logic (it is compiled and run in release.yml's Windows job)."""
    import re
    from pathlib import Path

    iss = (Path(__file__).resolve().parents[2] / "packaging" / "windows" / "LBDViewer.iss").read_text(encoding="utf-8")
    app_id = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", iss, re.M)[1]
    assert f'#define UninstallKey "{{{app_id}}}_is1"' in iss                  # the entry Windows keeps for AppId
    assert "function InitializeSetup(): Boolean;" in iss and "IsNewerVersion(Installed, '{#AppVersion}')" in iss
    assert "newer than this installer ({#AppVersion})" in iss and "uninstall ' + Installed + ' first" in iss
    assert "Your settings and Library are kept." in iss
    stop = iss[iss.index("procedure StopViewer"):]
    assert stop.index("'--stop'") < stop.index("Stop-Process -Force")        # gently first, then by force


def test_linux_installer_asks_for_shortcuts():
    from pathlib import Path

    sh = (Path(__file__).resolve().parents[2] / "packaging" / "linux" / "install.sh").read_text(encoding="utf-8")
    assert 'ask "Show LBD Viewer in the applications menu?" y' in sh
    assert 'ask "Add a shortcut to the desktop?" n' in sh
    assert "NoDisplay=true" in sh and "metadata::trusted" in sh


def test_every_language_has_the_same_license(load_module):
    """Each language folder can be installed on its own, so each carries the top LICENSE."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    top = (root / "LICENSE").read_text(encoding="utf-8")
    for lang in load_module("scripts/languages.py").discover():
        copy = lang.dir / "LICENSE"
        assert copy.is_file(), f"copy LICENSE into {lang.dir.relative_to(root)}"
        assert copy.read_text(encoding="utf-8") == top, f"{copy.relative_to(root)} differs from the top LICENSE"


def test_macos_app_opens_lbd_files():
    """The app bundle declares the .lbd file type and opens it (packaging/lbd-view.spec)."""
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[2] / "packaging" / "lbd-view.spec").read_text(encoding="utf-8")
    assert 'name="LBD Viewer.app"' in spec and "lbd.icns" in spec
    assert '"CFBundleDocumentTypes"' in spec and '"UTExportedTypeDeclarations"' in spec
    assert '"public.filename-extension": ["lbd"]' in spec and '"LSMinimumSystemVersion"' in spec


def test_shell_scripts_have_unix_line_endings():
    """A shell script with Windows line endings (CRLF) fails on Linux with confusing errors."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    scripts = sorted(root.glob("packaging/**/*.sh")) + sorted(root.glob("scripts/*.sh"))
    assert scripts
    crlf = [str(p.relative_to(root)) for p in scripts if b"\r\n" in p.read_bytes()]
    assert not crlf, f"convert to LF line endings: {crlf}"


def test_uninstaller_keeps_settings_by_default():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "packaging"
    iss = (root / "windows" / "LBDViewer.iss").read_text(encoding="utf-8")
    # The question is "Keep…?" with Yes (= keep) the default; a silent uninstall never asks.
    assert "Keep your LBD presets" in iss and "MB_DEFBUTTON1) = IDNO" in iss and "not UninstallSilent" in iss
    # asked before anything is removed, and never deleted permanently: to the Recycle Bin
    assert "CurUninstallStep = usUninstall" in iss and "SendToRecycleBin" in iss
    assert "DelTree(ExpandConstant('{userappdata}" not in iss
    sh = (root / "linux" / "uninstall.sh").read_text(encoding="utf-8")
    assert "keep=y" in sh and "[Y/n]" in sh


def test_the_upgrade_test_script_loads(load_module):
    """scripts/upgrade_test.py runs only in release.yml (it installs into the real user folders);
    here it must at least load and know its arguments."""
    up = load_module("scripts/upgrade_test.py")
    with pytest.raises(SystemExit):
        up.main(["--help"])


# ---- install scripts from the web (plan 16.27) -------------------------------------------------


def fake_release(folder, files):
    """A local folder that looks like a release: the files and their SHA256SUMS."""
    import hashlib

    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, content in files.items():
        (folder / name).write_bytes(content)
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
    (folder / "SHA256SUMS").write_text("".join(lines), newline="\n")
    return folder


@pytest.mark.parametrize("script", ["install.sh", "install-macos.sh"])
def test_web_install_scripts_parse(script):
    import subprocess
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "packaging" / script
    r = subprocess.run([_posix_shell(), "-n", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _powershell():
    import shutil

    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("no PowerShell here")
    return ps


def test_install_ps1_parses():
    import subprocess
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "packaging" / "install.ps1"
    command = (f"$e = $null; [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$e) "
               "| Out-Null; if ($e) { $e | ForEach-Object { $_.ToString() }; exit 1 }")
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert all(ord(c) < 128 for c in path.read_text(encoding="utf-8")), "Windows PowerShell 5.1 reads it as ANSI"


def _web_install(tmp_path, script, release, check_only=True, *args):
    import os
    import subprocess
    from pathlib import Path

    home, env = linux_home(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir(exist_ok=True)
    env = {**env, "LBD_RELEASE_BASE": str(release), "TMPDIR": str(tmp),
           "LBD_INSTALL_CHECK_ONLY": "1" if check_only else ""}
    if os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    path = Path(__file__).resolve().parents[2] / "packaging" / script
    r = subprocess.run([_posix_shell(), str(path), *args], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    assert not list(tmp.iterdir()), "the download was left behind"
    return r, home


def _arch():
    import platform

    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "aarch64"}.get(machine, machine)


def test_web_install_sh_checks_the_checksum(tmp_path):
    _posix_shell()
    name = f"lbd-viewer-1.3.0-linux-{_arch()}.tar.gz"
    release = fake_release(tmp_path / "release", {name: b"the package", "install.ps1": b"x"})
    r, _ = _web_install(tmp_path, "install.sh", release)
    assert r.returncode == 0 and "ok: " in r.stdout and "not installing" in r.stdout, r.stdout + r.stderr

    (release / name).write_bytes(b"the package, changed")          # not the published file
    r, _ = _web_install(tmp_path, "install.sh", release)
    assert r.returncode == 1 and "doesn't match SHA256SUMS" in r.stderr, r.stdout + r.stderr


def test_web_install_sh_says_why_it_fails(tmp_path):
    _posix_shell()
    r, _ = _web_install(tmp_path, "install.sh", tmp_path / "nothing-here")
    assert r.returncode == 1 and "couldn't download SHA256SUMS" in r.stderr
    release = fake_release(tmp_path / "release", {"lbd-viewer-1.3.0-linux-sparc.tar.gz": b"x"})
    r, _ = _web_install(tmp_path, "install.sh", release)
    assert r.returncode == 1 and "no Linux package for" in r.stderr
    r, _ = _web_install(tmp_path, "install.sh", release, True, "--colour")
    assert r.returncode == 1 and "unknown option --colour" in r.stderr


def test_web_install_sh_installs_with_the_options(tmp_path):
    """The whole way: download, check, unpack, and the package's install.sh with --desktop."""
    import io
    import tarfile

    _posix_shell()
    base = f"lbd-viewer-1.3.0-linux-{_arch()}"
    pkg = linux_package(tmp_path / "build" / base, "1.3.0")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(pkg, arcname=base)
    release = fake_release(tmp_path / "release", {f"{base}.tar.gz": buf.getvalue()})
    r, home = _web_install(tmp_path, "install.sh", release, False, "--desktop", "--no-fonts")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "data" / "lbd-viewer" / "VERSION").read_text().strip() == "1.3.0"
    assert (home / "Desktop" / "lbd-viewer.desktop").is_file()        # --desktop reached install.sh


def test_install_macos_sh_checks_the_checksum(tmp_path):
    _posix_shell()
    arch = {"x86_64": "x86_64", "arm64": "arm64"}.get(_arch())
    if not arch:
        pytest.skip("the macOS script knows only arm64 and x86_64")
    name = f"LBD-Viewer-1.3.0-macos-{arch}.dmg"
    release = fake_release(tmp_path / "release", {name: b"a disk image"})
    r, _ = _web_install(tmp_path, "install-macos.sh", release)
    assert r.returncode == 0 and "not installing" in r.stdout, r.stdout + r.stderr
    (release / name).write_bytes(b"another disk image")
    r, _ = _web_install(tmp_path, "install-macos.sh", release)
    assert r.returncode == 1 and "doesn't match SHA256SUMS" in r.stderr


def test_install_ps1_checks_the_checksum(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    ps = _powershell()
    name = "LBD-Viewer-1.3.0-windows-x64-setup.exe"
    release = fake_release(tmp_path / "release", {name: b"a setup program", "install.sh": b"x"})
    script = Path(__file__).resolve().parents[2] / "packaging" / "install.ps1"
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    env = {**os.environ, "LBD_RELEASE_BASE": str(release), "LBD_INSTALL_CHECK_ONLY": "1", "TEMP": str(tmp),
           "TMP": str(tmp), "TMPDIR": str(tmp)}

    def run():
        return subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                              env=env, capture_output=True, text=True)

    r = run()
    assert r.returncode == 0 and "not installing" in r.stdout, r.stdout + r.stderr
    (release / name).write_bytes(b"a changed setup program")
    r = run()
    assert r.returncode == 1 and "doesn't match SHA256SUMS" in r.stdout, r.stdout + r.stderr
    assert not list(tmp.iterdir()), "the download was left behind"
    env["LBD_RELEASE_BASE"] = str(tmp_path / "nothing-here")
    r = run()
    assert r.returncode == 1 and "couldn't download SHA256SUMS" in r.stdout


def test_the_release_publishes_the_install_scripts_and_checksums():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    wf = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "sha256sum -- * > ../SHA256SUMS" in wf
    assert "source/packaging/install.ps1 source/packaging/install.sh source/packaging/install-macos.sh release/" in wf
    assert "release/*" in wf.split("gh release create", 1)[1]
