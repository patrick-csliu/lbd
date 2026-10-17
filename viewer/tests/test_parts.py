"""The viewer's parts on their own: settings, folder scanning, images, language modules, command line."""

import io
import json
import os
import sys
import urllib.error
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lbd_viewer import cli, images, scan, sdk
from lbd_viewer.config import Config, ConfigError


# ---- config ---------------------------------------------------------------------------------


def test_config_settings_roundtrip(tmp_path):
    cfg = Config(tmp_path / "c")
    assert cfg.settings() == {"roots": [], "default_style": "default", "open_files_in": "viewer", "theme": "system"}
    assert cfg.problems() == []
    folder = tmp_path / "data"
    folder.mkdir()
    assert cfg.add_root(str(folder)) == [str(folder.resolve())]
    assert cfg.add_root(str(folder)) == [str(folder.resolve())]       # no duplicates
    with pytest.raises(ConfigError, match="not a folder"):
        cfg.add_root(str(tmp_path / "nope"))
    with pytest.raises(KeyError):
        cfg.remove_root(str(tmp_path / "nope"))
    assert cfg.remove_root(str(folder)) == []


@pytest.mark.parametrize("content, match", [
    ("{nope", "not valid JSON"),
    ("[1]", "JSON object"),
    (json.dumps({"roots": "C:/data"}), "'roots' must be a list"),
    (json.dumps({"roots": [1]}), "'roots' must be a list"),
    (json.dumps({"default_style": 3}), "'default_style' must be text"),
    (json.dumps({"open_files_in": "window"}), "'open_files_in' must be one of viewer, browser-tab"),
    (json.dumps({"theme": "blue"}), "'theme' must be one of system, light, dark"),
])
def test_config_broken_settings(tmp_path, content, match):
    cfg = Config(tmp_path / "c")
    cfg.settings_path.write_text(content)
    with pytest.raises(ConfigError, match=match):
        cfg.settings()


def test_config_open_files_in(tmp_path):
    cfg = Config(tmp_path / "c")
    cfg.set_open_files_in("browser-tab")
    assert cfg.settings()["open_files_in"] == "browser-tab"
    cfg.set_default_style("default")                     # other changes keep it
    assert Config(tmp_path / "c").settings()["open_files_in"] == "browser-tab"
    with pytest.raises(ConfigError, match="one of viewer, browser-tab"):
        cfg.set_open_files_in("popup")


def test_config_theme(tmp_path):
    cfg = Config(tmp_path / "c")
    cfg.set_theme("dark")
    cfg.set_open_files_in("browser-tab")                 # other changes keep it
    assert Config(tmp_path / "c").settings()["theme"] == "dark"
    with pytest.raises(ConfigError, match="one of system, light, dark"):
        cfg.set_theme("blue")


def test_config_default_style_and_problems(tmp_path):
    cfg = Config(tmp_path / "c")
    cfg.save_preset("paper", {})
    cfg.set_default_style("paper")
    assert cfg.settings()["default_style"] == "paper"
    with pytest.raises(ConfigError):
        cfg.set_default_style("nope")
    cfg.delete_preset("paper")                         # resets the default
    assert cfg.settings()["default_style"] == "default" and cfg.problems() == []
    cfg.settings_path.write_text(json.dumps({"default_style": "gone", "roots": [str(tmp_path / "x")]}))
    problems = cfg.problems()
    assert any("'gone'" in p for p in problems) and any("no longer exists" in p for p in problems)


def test_preset_for(tmp_path):
    cfg = Config(tmp_path / "c")
    cfg.save_preset("paper", {})
    notes = []
    assert cfg.preset_for("paper", None, notes) == "paper"
    assert cfg.preset_for(None, "paper", notes) == "paper"
    assert cfg.preset_for(None, "elsewhere", notes) == "default" and "elsewhere" in notes[0]
    with pytest.raises(ConfigError, match="no style named"):
        cfg.preset_for("nope", None)
    assert cfg.preset_for(None, None) == "default"


def test_config_uses_lbd_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path / "env"))
    assert Config().dir == tmp_path / "env"


# ---- scan ---------------------------------------------------------------------------------------


def make_tree(root):
    (root / "sub").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "node_modules").mkdir()
    for name in ("a.lbd", "b.LBD", "s.lbd.json", "p.png", "notes.txt", "sub/c.lbd"):
        (root / name).write_bytes(b"x")
    return root


def test_file_type_and_is_lbd():
    assert scan.file_type("x.LBD") == "lbd" and scan.file_type("x.lbd.json") == "style"
    assert scan.file_type("x.tiff") == "image" and scan.file_type("x.json") is None
    assert scan.is_lbd("a.lbd") and not scan.is_lbd("a.lbd.json")


def test_list_dir(tmp_path):
    root = make_tree(tmp_path / "r")
    listing = scan.list_dir(root)
    assert listing["dirs"] == ["sub"]
    assert [f["name"] for f in listing["files"]] == ["a.lbd", "b.LBD", "p.png", "s.lbd.json"]
    assert listing["errors"] == []


@pytest.mark.skipif(sys.platform == "win32" and not hasattr(os, "symlink"), reason="no symlinks")
def test_broken_link_is_reported(tmp_path):
    root = make_tree(tmp_path / "r")
    try:
        os.symlink(root / "missing.lbd", root / "link.lbd")
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs extra rights here")
    errors = scan.list_dir(root)["errors"]
    assert errors and errors[0]["name"] == "link.lbd" and "broken link" in errors[0]["error"]


def test_search(tmp_path):
    root = make_tree(tmp_path / "r")
    res = scan.search(root, "LBD")
    assert sorted(r["rel"].replace("\\", "/") for r in res["results"]) == ["a.lbd", "b.LBD", "s.lbd.json", "sub/c.lbd"]
    limited = scan.search(root, "", limit=2)
    assert limited["truncated"] is True and len(limited["results"]) == 2
    with pytest.raises(ValueError):
        scan.search(root, "", limit=0)


def test_walk_reports_unreadable_folders(tmp_path, monkeypatch):
    root = make_tree(tmp_path / "r")
    real_walk = os.walk

    def walk(top, onerror=None, **kw):
        onerror(PermissionError(13, "Permission denied", str(root / "locked")))
        yield from real_walk(top, **kw)

    monkeypatch.setattr(scan.os, "walk", walk)
    res = scan.search(root, "")
    assert res["errors"] and "locked" in res["errors"][0]["path"]


# ---- images -------------------------------------------------------------------------------------


def save_image(path, img, **kw):
    img.save(path, **kw)
    return path


def test_image_info_and_bytes(tmp_path):
    png = save_image(tmp_path / "a.png", Image.new("RGB", (20, 10)), dpi=(254, 254))
    info = images.info(png)
    assert (info["width"], info["height"], info["dpi"], info["size_mm"]) == (20, 10, [254.0, 254.0], [2.0, 1.0])
    data, media = images.browser_bytes(png)
    assert media == "image/png" and data.startswith(b"\x89PNG")


def test_image_bmp_palette_and_16bit(tmp_path):
    bmp = save_image(tmp_path / "a.bmp", Image.new("RGB", (4, 4)))
    data, media = images.browser_bytes(bmp)
    assert media == "image/png"
    pal = save_image(tmp_path / "p.tif", Image.new("P", (4, 4)))
    data, _ = images.browser_bytes(pal)
    assert Image.open(io.BytesIO(data)).mode == "RGBA"
    const16 = save_image(tmp_path / "c.tif", Image.fromarray(np.full((4, 4), 7, dtype=np.uint16)))
    assert images.info(const16)["note"].startswith("High bit-depth")
    data, _ = images.browser_bytes(const16)
    assert Image.open(io.BytesIO(data)).getextrema() == (0, 0)


def test_multi_frame_note(tmp_path):
    frames = [Image.new("L", (4, 4), c) for c in (0, 128)]
    gif = tmp_path / "a.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:])
    assert "2 frames" in images.info(gif)["note"]


def test_bad_dpi_becomes_a_note(tmp_path, monkeypatch):
    png = save_image(tmp_path / "a.png", Image.new("RGB", (2, 2)))
    real_open = Image.open

    def fake_open(path):
        img = real_open(path)
        img.info["dpi"] = ("x", "y")
        return img

    monkeypatch.setattr(Image, "open", fake_open)
    info = images.info(png)
    assert info["dpi"] is None and "resolution" in info["note"]


def test_corrupt_and_unsupported_images(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(images.ImageError, match="can't be read"):
        images.info(bad)
    other = tmp_path / "x.ico"
    other.write_bytes(b"")
    with pytest.raises(images.ImageError, match="not a supported"):
        images.browser_bytes(other)


@pytest.mark.parametrize("w, h, mm, note", [
    ("20mm", "10mm", [20.0, 10.0], None),
    ("2cm", "1in", [20.0, 25.4], None),
    ("72pt", "96px", [25.4, 25.4], None),
    ("100%", "50%", None, "can't convert"),
])
def test_svg_sizes(tmp_path, w, h, mm, note):
    p = tmp_path / "a.svg"
    p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 10 20"/>')
    info = images.info(p)
    assert info["size_mm"] == mm and (info["width"], info["height"]) == (10, 20)
    assert (note is None and info["note"] is None) or note in info["note"]


def test_svg_problems(tmp_path):
    p = tmp_path / "a.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 x"/>')
    assert "viewBox" in images.info(p)["note"]
    p.write_text("<svg")
    with pytest.raises(images.ImageError, match="not a valid SVG"):
        images.info(p)


# ---- sdk -------------------------------------------------------------------------------------------


def write_lang(folder, toml, example=None):
    folder.mkdir(parents=True)
    (folder / "language.toml").write_text(toml, encoding="utf-8")
    if example:
        (folder / example).write_text("print(1)")


def test_sdk_broken_languages_are_listed_with_their_error(tmp_path, monkeypatch):
    base = tmp_path / "sdk"
    write_lang(base / "good", 'id = "good"\nname = "Good"\nexample = "ex.py"\n'
                              '[[install]]\nsteps = [{ label = "a", code = "b {path}" }]\n', "ex.py")
    write_lang(base / "bad", "id = [")
    write_lang(base / "order", 'id = "order"\nname = "O"\norder = "x"\n')
    write_lang(base / "noexample", 'id = "noexample"\nname = "N"\nexample = "gone.py"\n'
                                   '[[install]]\nsteps = [{ label = "a", code = "b" }]\n')
    (base / "empty").mkdir()
    monkeypatch.setenv("LBD_SDK_DIR", str(base))
    monkeypatch.setattr(sdk.sys, "frozen", False, raising=False)
    langs = {lang["id"]: lang for lang in sdk.languages()}
    assert langs["good"]["error"] is None and langs["good"]["install"][0]["code"].startswith("b ")
    assert "can't be read" in langs["bad"]["error"]
    assert "order" in langs["order"]["error"]
    assert "example file" in langs["noexample"]["error"]
    assert "no language.toml" in langs["empty"]["error"]
    assert not langs["bad"]["available"]


def test_sdk_reveal_unknown(monkeypatch):
    with pytest.raises(KeyError):
        sdk.reveal("cobol")


# ---- cli -------------------------------------------------------------------------------------------


def test_viewer_url():
    assert cli.viewer_url(8765, "t") == "http://127.0.0.1:8765/?token=t"
    assert "open=C%3A%2Fx.lbd" in cli.viewer_url(1, "t", "C:/x.lbd")


def test_split_args(tmp_path, capsys):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    files, dirs = cli._split_args([str(f), str(tmp_path), str(tmp_path / "nope")])
    assert files == [str(f.resolve())] and dirs == [str(tmp_path.resolve())]
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--port", "70000"], ["--port", "-1"], ["--idle-exit", "-5"], ["--idle-exit", "nan"]])
def test_cli_rejects_bad_numbers(args):
    with pytest.raises(SystemExit) as e:
        cli.main(args)
    assert e.value.code == 2


def test_cli_all_paths_missing(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope.lbd")]) == 2
    assert "none of the given" in capsys.readouterr().err


def test_cli_hands_over_to_a_running_viewer(tmp_path, monkeypatch, capsys):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    calls = []

    def fake_api(port, token, method, path, body=None, timeout=5.0):
        calls.append((method, path, body))
        if path == "/api/roots":
            raise urllib.error.HTTPError(path, 400, "Bad", {}, io.BytesIO(b'{"detail": "not a folder"}'))
        return {}

    monkeypatch.setattr(cli, "_running_server", lambda: {"port": 1, "token": "t"})
    monkeypatch.setattr(cli, "_api", fake_api)
    assert cli.main([str(f), str(tmp_path), "--no-browser"]) == 0
    out = capsys.readouterr()
    assert "refused" in out.err and "not a folder" in out.err
    assert ("POST", "/api/open", {"path": str(f.resolve())}) in calls
    assert "token=t" in out.out


@pytest.fixture
def running_viewer(monkeypatch):
    """A fake running viewer for lbd-view's hand-over: records requests and opened browser tabs."""
    seen = {"calls": [], "tabs": [], "setting": "viewer", "deliver": None}

    def fake_api(port, token, method, path, body=None, timeout=5.0):
        seen["calls"].append(path)
        if path == "/api/state":
            return {"open_files_in": seen["setting"]}
        if path == "/api/deliver":
            return seen["deliver"]
        return {}

    monkeypatch.setattr(cli, "_running_server", lambda: {"port": 1, "token": "t"})
    monkeypatch.setattr(cli, "_api", fake_api)
    monkeypatch.setattr(cli.webbrowser, "open", seen["tabs"].append)
    return seen


def test_cli_delivers_to_the_open_page_without_a_new_tab(tmp_path, running_viewer):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    running_viewer["deliver"] = {"delivered": True, "shown": [], "busy": [], "unplaced": []}
    assert cli.main([str(f)]) == 0
    assert "/api/deliver" in running_viewer["calls"] and running_viewer["tabs"] == []


def test_cli_opens_tabs_for_files_no_page_took(tmp_path, running_viewer, capsys):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    running_viewer["deliver"] = {"delivered": False, "shown": [], "busy": ["b.lbd"], "unplaced": [str(f)]}
    assert cli.main([str(f)]) == 0
    assert len(running_viewer["tabs"]) == 1 and "open=" in running_viewer["tabs"][0]
    assert "being moved" in capsys.readouterr().err


def test_cli_setting_browser_tab_skips_delivery(tmp_path, running_viewer):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    running_viewer["setting"] = "browser-tab"
    assert cli.main([str(f)]) == 0
    assert "/api/deliver" not in running_viewer["calls"] and len(running_viewer["tabs"]) == 1


def test_cli_with_an_older_viewer_opens_tabs_as_before(tmp_path, running_viewer):
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    running_viewer["setting"] = None                     # its /api/state has no open_files_in
    assert cli.main([str(f)]) == 0
    assert "/api/deliver" not in running_viewer["calls"] and len(running_viewer["tabs"]) == 1


@pytest.mark.parametrize("folder", [False, True])
def test_cli_without_files_opens_a_browser_tab(tmp_path, running_viewer, folder):
    """The Start menu (or a folder): a page that is open can't be brought to the front, so a new
    browser tab shows the viewer."""
    args = [str(tmp_path)] if folder else []
    running_viewer["deliver"] = {"delivered": True, "shown": [], "busy": [], "unplaced": []}
    assert cli.main(args) == 0
    assert "/api/deliver" not in running_viewer["calls"]
    assert len(running_viewer["tabs"]) == 1 and "open=" not in running_viewer["tabs"][0]
    assert ("/api/roots" in running_viewer["calls"]) == folder


def test_lock_path_follows_lbd_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LBD_RUNTIME_DIR", str(tmp_path / "rt"))
    assert cli.lock_path() == tmp_path / "rt" / "server.json" and (tmp_path / "rt").is_dir()


def test_open_tabs_prints_urls(capsys):
    cli._open_tabs(5, "tok", ["C:/a.lbd"], no_browser=True)
    assert "open=" in capsys.readouterr().out


def test_free_port():
    assert 0 < cli._free_port() < 65536


# ---- cli: starting a server (uvicorn's run is replaced, so nothing listens) ----------------------


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    import time

    import uvicorn

    lock = tmp_path / "server.json"
    monkeypatch.setattr(cli, "lock_path", lambda: lock)
    monkeypatch.setattr(cli, "_running_server", lambda: None)
    seen = {}

    def run(self):
        seen["lock"] = json.loads(lock.read_text()) if lock.exists() else None
        seen["config"] = self.config
        self.started = True
        time.sleep(0.3)                      # let the start-up thread print the URL
        self.should_exit = True

    monkeypatch.setattr(uvicorn.Server, "run", run)
    return lock, seen


def test_cli_starts_a_server(tmp_path, fake_server, capsys):
    lock, seen = fake_server
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    assert cli.main([str(f), str(tmp_path), "--no-browser", "--port", "8123", "--new"]) == 0
    assert seen["lock"]["port"] == 8123 and seen["config"].port == 8123
    assert not lock.exists()                 # removed when the server stops
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8123/?token=" in out and "open=" in out
    assert str(tmp_path.resolve()) in Config().settings()["roots"]


def test_cli_start_then_run_in_a_thread(tmp_path, fake_server):
    """The macOS app starts the server like this: start(), then run() in a background thread."""
    import threading

    lock, seen = fake_server
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    started = []
    args = cli.build_parser().parse_args(["--port", "8124"])
    running = cli.start(args, [str(f)], [str(tmp_path)], on_started=started.append)
    assert running.port == 8124 and running.url().startswith("http://127.0.0.1:8124/?token=")
    running.state.check_allowed(str(f))                       # the file was opened
    thread = threading.Thread(target=running.run)
    thread.start()
    thread.join(5)
    assert started == [running] and running.stopped and not lock.exists()


def test_cli_dev_mode(fake_server, capsys):
    lock, seen = fake_server
    assert cli.main(["--dev"]) == 0
    assert seen["lock"] is None and seen["config"].port == 8765      # dev mode writes no lock file
    assert "token: dev" in capsys.readouterr().out


def test_running_server_with_a_stale_lock(tmp_path, monkeypatch):
    lock = tmp_path / "server.json"
    monkeypatch.setattr(cli, "lock_path", lambda: lock)
    assert cli._running_server() is None                 # no lock file
    lock.write_text("{broken")
    assert cli._running_server() is None
    lock.write_text(json.dumps({"port": cli._free_port(), "token": "t"}))
    assert cli._running_server() is None                 # nobody answers


def test_lock_path_is_in_the_runtime_folder():
    assert cli.lock_path().name == "server.json"


def test_module_entry_point():
    import subprocess

    r = subprocess.run([sys.executable, "-m", "lbd_viewer", "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("lbd-view ")


# ---- file actions -------------------------------------------------------------------------------


def test_show_in_file_manager_selects_the_file(tmp_path, monkeypatch):
    from lbd_viewer import files
    calls = []
    monkeypatch.setattr(files.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd))

    class Failed:          # what subprocess.run returns when dbus-send finds no file manager
        returncode = 1

    def run(cmd, *a, **k):
        calls.append(cmd)
        return Failed()

    monkeypatch.setattr(files.subprocess, "run", run)
    monkeypatch.setattr(files, "open_folder", lambda p: calls.append(("folder", p)))
    f = tmp_path / "a b.lbd"
    f.write_bytes(b"x")
    files.show_in_file_manager(tmp_path)
    assert calls[-1] == ("folder", str(tmp_path))  # a folder is opened itself
    files.show_in_file_manager(f)
    if os.name == "nt":
        assert calls[-1] == f'explorer /select,"{f}"'
    elif sys.platform == "darwin":
        assert calls[-1] == ["open", "-R", str(f)]
    else:
        # Linux: ask the file manager over D-Bus to select the file; if that fails, open the folder.
        assert calls[-1] == ("folder", str(tmp_path))
        if files.shutil.which("dbus-send"):
            assert calls[-2][0] == "dbus-send" and f.as_uri() in calls[-2][-2]


def test_rename_and_trash_wait_while_another_program_has_the_file_open(tmp_path, monkeypatch):
    """Windows refuses to rename or delete an open file. The viewer drawing it in another page
    opens it for a moment (found on GitHub's Windows runner): both retry for a while."""
    from lbd_viewer import files

    p = tmp_path / "a.lbd"
    p.write_bytes(b"x")
    busy = {"left": 2}

    def sometimes_busy(path):
        if busy["left"]:
            busy["left"] -= 1
            raise PermissionError(13, "The process cannot access the file")
        Path(path).unlink()

    monkeypatch.setattr(files.send2trash, "send2trash", sometimes_busy)
    files.trash(p)                                         # busy twice, then done
    assert not p.exists() and busy["left"] == 0

    p.write_bytes(b"x")
    monkeypatch.setattr(files, "IN_USE_WAIT", 0.3)
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(PermissionError(13, "in use")))
    with pytest.raises(files.FileActionError, match="it is open in another program; close it there"):
        files.rename(p, "b.lbd")                          # still busy after the wait: a clear message


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to rename an open file")
def test_rename_waits_for_a_real_open_file_on_windows(tmp_path):
    import threading

    from lbd_viewer import files

    p = tmp_path / "a.lbd"
    p.write_bytes(b"x")
    handle = open(p, "rb")                                 # another program reading it
    threading.Timer(0.4, handle.close).start()
    assert files.rename(p, "b.lbd") == tmp_path / "b.lbd"


def test_extension_kept_by_rename():
    from lbd_viewer.files import extension
    assert extension("paper.lbd.json") == ".lbd.json"
    assert extension("run.LBD") == ".LBD"
    assert extension("fig.tiff") == ".tiff"


# ---- macOS app: what it does with Finder's events (no Tk; runs on every system) -----------------


@pytest.fixture
def mac_app(tmp_path):
    from lbd_viewer import macapp
    from lbd_viewer.server import AppState

    class Server:
        started = False
        should_exit = False

    running = cli.Running(AppState(Config(tmp_path / "cfg"), token="tok"), Server(), 8125, lock=None)
    opened, alerts = [], []
    return macapp.MacApp(running, open_url=opened.append, alert=alerts.append), opened, alerts


def test_mac_app_waits_for_the_server_then_opens_documents(mac_app, tmp_path):
    app, opened, alerts = mac_app
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    app.open_documents(str(f))                 # Finder's document arrives before the server answers
    assert app.tick(0.0) and opened == []
    app.running.server.started = True
    assert app.tick(0.2)
    assert len(opened) == 1 and "open=" in opened[0] and "a.lbd" in opened[0]
    app.running.state.check_allowed(str(f))    # the file may be read now
    assert app.tick(5.0) and len(opened) == 1  # no extra main tab: a document was shown


def test_mac_app_opens_the_main_tab_when_started_without_a_document(mac_app):
    app, opened, _ = mac_app
    app.running.server.started = True
    assert app.tick(10.0) and opened == []      # waits a moment for a document from Finder
    assert app.tick(10.0 + 1.5) and opened == [app.running.url()]


def test_mac_app_folders_missing_files_reopen_and_quit(mac_app, tmp_path):
    app, opened, alerts = mac_app
    app.running.server.started = True
    app.open_documents(str(tmp_path), str(tmp_path / "gone.lbd"))
    app.tick(0.0)
    assert str(tmp_path.resolve()) in app.running.state.config.settings()["roots"]
    assert opened == [app.running.url()]
    assert alerts and "gone.lbd: not found" in alerts[0]
    app.reopen()                                # Dock icon clicked
    assert len(opened) == 2
    app.quit()                                  # ⌘Q
    assert app.running.stopped and app.tick(1.0) is False


def test_mac_app_delivers_to_an_open_page(mac_app, tmp_path):
    import threading

    app, opened, alerts = mac_app
    app.running.server.started = True
    pages = app.running.state.pages
    page = pages.register()
    pages.start_poll(page.id)                     # the page listens
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")

    def take():     # the open page receives the file and confirms (other commands: the page list)
        handled = 0
        while (command := pages.wait_for_command(page.id, pages.start_poll(page.id, handled), timeout=5)).kind != "open":
            handled = command.id
        pages.ack(page.id, command.id)

    t = threading.Thread(target=take)
    t.start()
    app.open_documents(str(f))
    app.tick(0.0)
    t.join()
    assert opened == [] and alerts == [] and pages.owner(str(f.resolve())).id == page.id


def test_mac_app_folder_with_a_page_open_still_opens_a_tab(mac_app, tmp_path):
    app, opened, _ = mac_app
    app.running.server.started = True
    pages = app.running.state.pages
    pages.start_poll(pages.register().id)         # a page is open, but it can't come forward
    app.open_documents(str(tmp_path))
    app.tick(0.0)
    assert opened == [app.running.url()]


def test_mac_app_setting_browser_tab(mac_app, tmp_path):
    app, opened, _ = mac_app
    app.running.server.started = True
    pages = app.running.state.pages
    pages.start_poll(pages.register().id)                # a page is open, but the setting says tabs
    app.running.state.config.set_open_files_in("browser-tab")
    f = tmp_path / "a.lbd"
    f.write_bytes(b"x")
    app.open_documents(str(f))
    app.tick(0.0)
    assert len(opened) == 1 and "open=" in opened[0]
