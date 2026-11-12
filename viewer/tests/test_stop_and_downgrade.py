"""Installing over a running viewer, and going back to an older version (plan 16.26).

- `POST /api/stop` and `lbd-view --stop`: the installers stop a running viewer gently first.
- An older viewer after a newer one: it keeps the newer one's settings, and says so (the macOS
  app at its first start); LBD's databases of a newer version are rebuilt or put aside, saying so.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from lbd_viewer import VERSION, cli, updates
from lbd_viewer.catalog import Catalog
from lbd_viewer.config import Config
from lbd_viewer.library import LibraryIndex
from lbd_viewer.server import AppState, create_app


def stop_client(cfg, client_host="127.0.0.1"):
    state = AppState(cfg, token="t0k")
    c = TestClient(create_app(state), base_url="http://127.0.0.1:8000", client=(client_host, 50000))
    c.headers["X-LBD-Token"] = "t0k"
    return state, c


# ---- POST /api/stop


def test_stop_asks_the_server_to_stop(cfg):
    state, c = stop_client(cfg)
    stopped = []
    state.on_stop = lambda: stopped.append(True)
    r = c.post("/api/stop")
    assert r.status_code == 200 and r.json() == {"stopping": True, "pid": os.getpid()} and stopped == [True]


def test_stop_needs_the_token_and_this_computer(cfg):
    state, c = stop_client(cfg)
    state.on_stop = lambda: pytest.fail("must not stop")
    assert c.post("/api/stop", headers={"X-LBD-Token": "wrong"}).status_code == 403
    state, c = stop_client(cfg, client_host="192.168.1.20")
    state.on_stop = lambda: pytest.fail("must not stop")
    r = c.post("/api/stop")
    assert r.status_code == 403 and "this computer" in r.json()["detail"]


def test_stop_of_a_viewer_not_started_by_lbd_view_says_so(cfg):
    _, c = stop_client(cfg)                               # on_stop is never set
    r = c.post("/api/stop")
    assert r.status_code == 409 and "stop it where it was started" in r.json()["detail"]


# ---- lbd-view --stop


def test_stop_without_a_running_viewer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_running_server", lambda: None)
    assert cli.main(["--stop"]) == 0
    assert "no viewer is running" in capsys.readouterr().out


def test_stop_of_an_older_viewer_fails_so_the_installer_forces_it(monkeypatch, capsys):
    """A viewer before 1.3.0 has no /api/stop (404)."""
    import urllib.error

    monkeypatch.setattr(cli, "_running_server", lambda: {"port": 1, "token": "t", "pid": 4242})

    def api(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:1/api/stop", 404, "Not Found", {}, None)

    monkeypatch.setattr(cli, "_api", api)
    assert cli.main(["--stop"]) == 1
    assert "older than 1.3.0" in capsys.readouterr().err


def test_stop_that_doesnt_end_in_time(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_running_server", lambda: {"port": 1, "token": "t", "pid": 4242})
    monkeypatch.setattr(cli, "_api", lambda *a, **k: {"stopping": True})
    monkeypatch.setattr(cli, "_alive", lambda pid: True)
    assert cli.stop_running(wait=0.3) == 1
    assert "still running" in capsys.readouterr().err


def test_a_real_viewer_stops_gently(tmp_path):
    """Start a viewer in its own process, then `lbd-view --stop`: it ends within 10 s, with its
    "running viewer" record removed (Running.run's normal end, after AppState.close)."""
    env = {**os.environ, "LBD_RUNTIME_DIR": str(tmp_path / "rt"), "LBD_CONFIG_DIR": str(tmp_path / "cfg"),
           "LBD_NO_UPDATE_CHECK": "1"}
    viewer = subprocess.Popen([sys.executable, "-m", "lbd_viewer", "--no-browser", "--new", "--idle-exit", "0"],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        lock = tmp_path / "rt" / "server.json"
        for _ in range(300):
            if viewer.stdout.readline().startswith("http://"):     # serving
                break
        assert lock.exists()
        r = subprocess.run([sys.executable, "-m", "lbd_viewer", "--stop"], env=env,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "the viewer stopped" in r.stdout
        viewer.wait(timeout=5)
        assert not lock.exists()
        assert "Traceback" not in viewer.stderr.read()
    finally:
        if viewer.poll() is None:
            viewer.kill()


# ---- versions


@pytest.mark.parametrize("a, b, newer", [
    ("1.3.0", "1.2.0", True), ("1.3.0", "1.3.0-dev", True), ("1.3.0-dev", "1.2.9", True),
    ("1.10.0", "1.9.0", True), ("2.0.0", "1.99.99", True),
    ("1.2.0", "1.3.0", False), ("1.3.0", "1.3.0", False), ("1.3.0-dev", "1.3.0", False),
    ("", "1.0.0", False), (None, "1.0.0", False), ("v1.4.0", "1.0.0", False), ("1.4", "1.0.0", False),
])
def test_versions_compare(a, b, newer):
    assert updates.is_newer(a, b) == newer


# ---- an older viewer after a newer one


def test_settings_of_a_newer_viewer_are_kept(tmp_path):
    cfg = Config(tmp_path)
    cfg.settings_path.write_text(json.dumps({
        "roots": [], "theme": "dark", "from_the_future": {"x": 1},
        "library": {"read_headers": False, "future_library_key": "kept"},
    }), encoding="utf-8")
    assert cfg.settings()["theme"] == "dark" and cfg.settings()["library"]["read_headers"] is False
    cfg.set_theme("light")                                  # a save by this (older) version
    data = json.loads(cfg.settings_path.read_text(encoding="utf-8"))
    assert data["theme"] == "light" and data["from_the_future"] == {"x": 1}
    assert data["library"]["future_library_key"] == "kept" and data["library"]["read_headers"] is False


def test_the_version_used_last_is_recorded(tmp_path):
    cfg = Config(tmp_path)
    assert cfg.note_version("1.3.0") is None
    assert cfg.note_version("1.3.0") == "1.3.0"
    assert cfg.note_version("1.2.5") == "1.3.0"
    assert json.loads(cfg.settings_path.read_text(encoding="utf-8"))["last_version"] == "1.2.5"


def test_an_older_viewer_says_so_once(tmp_path, monkeypatch, capsys):
    cfg = Config(tmp_path)
    newer = "99.0.0"
    cfg.note_version(newer)
    notice = cli._note_version(cfg)
    assert notice and f"({VERSION})" in notice and f"({newer})" in notice and updates.RELEASES_URL in notice
    assert "is older than the one used before" in capsys.readouterr().err
    assert cli._note_version(cfg) is None                  # once: now this version is the one used last


def test_the_start_records_the_version_but_dev_doesnt(tmp_path, monkeypatch):
    import uvicorn

    monkeypatch.setattr(cli, "lock_path", lambda: tmp_path / "server.json")
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    Config().note_version("99.0.0")
    dev = cli.start(cli.build_parser().parse_args(["--dev"]), [], [], on_started=lambda r: None)
    dev.stop()
    assert dev.notice is None and Config().settings()["last_version"] == "99.0.0"
    real = cli.start(cli.build_parser().parse_args(["--port", "8126"]), [], [], on_started=lambda r: None)
    real.stop()
    assert "99.0.0" in real.notice and Config().settings()["last_version"] == VERSION
    assert real.state.on_stop == real.stop


def test_a_catalog_of_a_newer_version_is_put_aside_and_said_so(tmp_path):
    db = sqlite3.connect(tmp_path / "catalog.sqlite")
    db.execute("PRAGMA user_version = 99")
    db.commit()
    db.close()
    c = Catalog(tmp_path)
    assert c.view("a.lbd") is None                        # works, with a new database
    assert "newer LBD" in c.problem and "catalog.broken-" in c.problem
    c.close()


def test_a_library_index_of_a_newer_version_is_built_again(tmp_path):
    (tmp_path / "db").mkdir()
    db = sqlite3.connect(tmp_path / "db" / "library.sqlite")
    db.execute("CREATE TABLE files (path TEXT, only_in_a_newer_version TEXT)")
    db.execute("PRAGMA user_version = 99")
    db.commit()
    db.close()
    (tmp_path / "data").mkdir()
    ix = LibraryIndex(tmp_path / "db", lambda: [str(tmp_path / "data")], lambda: True)
    ix.scan()
    assert ix.list()["total"] == 0
    ix.close()
    db = sqlite3.connect(tmp_path / "db" / "library.sqlite")
    assert db.execute("PRAGMA user_version").fetchone()[0] != 99
    db.close()
