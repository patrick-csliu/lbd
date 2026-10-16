"""Every HTTP endpoint of the viewer, with its error statuses and the warnings it passes on."""

import json

import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient

import lbd
from lbd_viewer import server
from lbd_viewer.server import AppState, collect_warnings, create_app, jsonable


# ---- app ------------------------------------------------------------------------------------


def test_ping_and_heartbeat(client):
    pong = client.get("/api/ping").json()
    assert pong["app"] == "lbd-viewer" and isinstance(pong["pid"], int)
    state = client.app.state.lbd
    assert state.last_heartbeat is None
    assert client.post("/api/heartbeat").json() == {"ok": True}
    assert state.last_heartbeat is not None


def test_state_reports_problems(client, cfg, tmp_path):
    body = client.get("/api/state").json()
    assert body["warnings"] == [] and body["default_style"] == "default"
    gone = tmp_path / "gone"
    gone.mkdir()
    client.post("/api/roots", json={"path": str(gone)}).raise_for_status()
    gone.rmdir()
    settings = json.loads(cfg.settings_path.read_text())
    settings["default_style"] = "deleted-style"
    cfg.settings_path.write_text(json.dumps(settings))
    warnings = client.get("/api/state").json()["warnings"]
    assert any("no longer exists" in w and "gone" in w for w in warnings)
    assert any("deleted-style" in w for w in warnings)


def test_broken_settings_file_is_an_error_not_a_reset(client, cfg):
    cfg.settings_path.write_text("{broken")
    r = client.get("/api/state")
    assert r.status_code == 400 and "settings.json" in r.json()["detail"]
    assert cfg.settings_path.read_text() == "{broken"          # not overwritten


def test_auto_token():
    assert len(AppState(config=None).token) > 20


def test_host_check_can_be_disabled(cfg):
    c = TestClient(create_app(AppState(cfg, token="t", check_host=False)), base_url="http://anything:1")
    assert c.get("/api/ping", headers={"X-LBD-Token": "t"}).status_code == 200


def test_unknown_body_fields_are_rejected(client, data_dir):
    r = client.post("/api/render", json={"path": str(data_dir / "curve.lbd"), "styleFile": "x"})
    assert r.status_code == 422
    r = client.post("/api/open", json={"path": str(data_dir / "curve.lbd"), "extra": 1})
    assert r.status_code == 422


# ---- folders ----------------------------------------------------------------------------------


def test_open_missing_file(client, tmp_path):
    assert client.post("/api/open", json={"path": str(tmp_path / "nope.lbd")}).status_code == 404


def test_remove_unknown_root(client, tmp_path):
    r = client.delete("/api/roots", params={"path": str(tmp_path / "never-added")})
    assert r.status_code == 404


def test_list_and_search_errors(client, data_dir):
    assert client.get("/api/list", params={"path": ""}).status_code == 400
    assert client.get("/api/list", params={"path": str(data_dir / "curve.lbd")}).status_code == 404
    assert client.get("/api/search", params={"root": str(data_dir / "curve.lbd"), "q": "x"}).status_code == 404
    body = client.get("/api/search", params={"root": str(data_dir), "q": ""}).json()
    assert body["truncated"] is False and body["errors"] == [] and len(body["results"]) == 3


def test_pick_folder_without_tkinter(client, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_tk(name, *a, **k):
        if name == "tkinter":
            raise ImportError("no tk")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_tk)
    assert client.post("/api/pick-folder").status_code == 501


def test_pick_folder_busy(client):
    assert server._DIALOG_LOCK.acquire(blocking=False)
    try:
        assert client.post("/api/pick-folder").status_code in (409, 501)
    finally:
        server._DIALOG_LOCK.release()


# ---- files --------------------------------------------------------------------------------------


def test_file_errors_and_warnings(client, data_dir):
    assert client.get("/api/file", params={"path": str(data_dir / "missing.lbd")}).status_code == 404
    (data_dir / "fake.lbd").write_text("not hdf5")
    r = client.get("/api/file", params={"path": str(data_dir / "fake.lbd")})
    assert r.status_code == 400 and "not an LBD file" in r.json()["detail"]
    p = data_dir / "curve.lbd"
    with h5py.File(p, "r+") as f:
        f["meta"].create_dataset("table", data=[1, 2])
    body = client.get("/api/file", params={"path": str(p)}).json()
    assert any("/meta/table" in w for w in body["warnings"])


def test_file_summary_details(client, data_dir):
    d = lbd.load(data_dir / "curve.lbd")
    d.meta = {"c": 1 + 2j, "big": np.arange(100.0), "nan": float("nan"), "n": {"x": np.int32(3)}}
    d.save(data_dir / "curve.lbd")
    body = client.get("/api/file", params={"path": str(data_dir / "curve.lbd")}).json()
    assert body["meta"]["c"] == "1+2j" and body["meta"]["nan"] is None and body["meta"]["n"]["x"] == 3
    assert body["meta"]["big"]["array"] is True and body["meta"]["big"]["shape"] == [100]
    t = next(a for a in body["axes"] if a["name"] == "t")
    assert t["min"] == 0.0 and t["max"] == pytest.approx(1e-6)


def test_put_file_plot_checks(client, data_dir):
    p = str(data_dir / "curve.lbd")
    assert client.put("/api/file/plot", json={"path": p}).status_code == 400
    r = client.put("/api/file/plot", json={"path": p, "spec": {"knd": "curve"}})
    assert r.status_code == 400 and "unknown plot setting" in r.json()["detail"]
    r = client.put("/api/file/plot", json={"path": p, "style_name": "thesis"})
    assert r.status_code == 200 and r.json()["style_name"] == "thesis"


# ---- render / export --------------------------------------------------------------------------


def test_render_returns_warnings(client, data_dir):
    p = data_dir / "sub" / "sweep.lbd"
    lbd.set_plot(p, style_name="from-elsewhere")
    body = client.post("/api/render", json={"path": str(p)}).json()
    assert any("from-elsewhere" in w for w in body["warnings"])
    assert body["preset"] == "default"


def test_render_ignores_leftover_ui_settings_quietly(client, data_dir):
    body = client.post("/api/render", json={"path": str(data_dir / "sub" / "sweep.lbd"),
                                            "spec": {"kind": "heatmap", "series": "power", "color": "freq"}}).json()
    assert body["warnings"] == []


def test_render_errors_are_400(client, data_dir):
    p = str(data_dir / "sub" / "sweep.lbd")
    for spec in ({"values": ["S12"]}, {"kind": "pie"}, {"knd": 1}, {"kind": "curve", "series": "none", "index": {"power": 99}}):
        r = client.post("/api/render", json={"path": p, "spec": spec})
        assert r.status_code == 400, spec
    r = client.post("/api/render", json={"path": p, "preset": "no-such-style"})
    assert r.status_code == 400 and "no style named" in r.json()["detail"]
    r = client.post("/api/render", json={"path": p, "style": {"figure": {"widht_mm": 5}}})
    assert r.status_code == 400 and "did you mean" in r.json()["detail"]
    r = client.post("/api/render", json={"path": p, "format": "png"})
    assert r.status_code == 400 and "/api/export" in r.json()["detail"]
    r = client.post("/api/render", json={"path": p, "style": {"figure": {"font": {"family": "NoSuchFont123"}}}})
    assert r.status_code == 400 and "not installed" in r.json()["detail"] and "DejaVu Sans" in r.json()["detail"]


def test_render_and_save_annotations(client, data_dir):
    p = str(data_dir / "sub" / "sweep.lbd")
    ann = [{"method": "axhline", "args": [-10], "kwargs": {"ls": ":"}},
           {"patch": "Rectangle", "args": [[0, -20], 1, 5], "kwargs": {"fill": False}}]
    body = client.post("/api/render", json={"path": p, "spec": {"kind": "curve", "annotations": ann}}).json()
    assert body["spec"]["annotations"] == ann and body["svg"].startswith("<?xml")
    r = client.post("/api/render", json={"path": p, "spec": {"annotations": [{"method": "axvlin"}]}})
    assert r.status_code == 400 and "annotations[0]" in r.json()["detail"] and "axvline" in r.json()["detail"]
    r = client.post("/api/render", json={"path": p, "spec": {"annotations": [{"method": "axhline",
                                                                               "kwargs": {"nope": 1}}]}})
    assert r.status_code == 400 and "annotations[0] (axhline)" in r.json()["detail"]
    client.put("/api/file/plot", json={"path": p, "spec": {"kind": "curve", "annotations": ann}}).raise_for_status()
    d = lbd.load(p)
    assert d.plot["annotations"] == ann and d.matplotlib


def test_render_with_preset_and_ui_style(client, data_dir):
    client.put("/api/styles/talk", json={"preset": {"figure": {"width_mm": 160}}}).raise_for_status()
    body = client.post("/api/render", json={"path": str(data_dir / "curve.lbd"), "preset": "talk",
                                            "style": {"figure": {"height_mm": 70}}}).json()
    assert body["preset"] == "talk" and body["size_mm"] == [160, 70]


def test_export_errors_and_warning_header(client, data_dir):
    p = data_dir / "sub" / "sweep.lbd"
    assert client.post("/api/export", json={"path": str(p), "format": "gif"}).status_code == 400
    lbd.set_plot(p, style_name="elsewhere")
    r = client.post("/api/export", json={"path": str(p), "format": "PDF"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert "elsewhere" in json.loads(r.headers["X-LBD-Warnings"])[0]


# ---- styles -------------------------------------------------------------------------------------


def test_style_endpoints_statuses(client):
    assert client.get("/api/styles/nope").status_code == 404
    assert client.get("/api/styles/nope/export").status_code == 404
    assert client.get("/api/styles/default/export", params={"format": "pdf"}).status_code == 400
    assert client.delete("/api/styles/nope").status_code == 404
    r = client.put("/api/styles/paper", json={"preset": {"figure": {"widht_mm": 9}}})
    assert r.status_code == 400 and "widht_mm" in r.json()["detail"]
    r = client.put("/api/styles/paper", json={"preset": {"figure": {"width_mm": 90}}})
    assert r.status_code == 200 and r.json()["warnings"] == []
    assert client.put("/api/settings", json={"default_style": "nope"}).status_code == 400


def test_style_defaults_endpoint(client):
    body = client.get("/api/style-defaults").json()
    assert body["defaults"]["figure"]["width_mm"] == 85
    q = body["schema"]["$defs"]["QuantityStyle"]["properties"]
    assert "prefix" in q
    label = body["schema"]["$defs"]["LabelStyle"]["properties"]
    assert "auto_prefix" in label and "si_prefix" not in label


def test_import_variants(client):
    r = client.post("/api/styles/import", json={"name": "a", "content": "[1, 2]"})
    assert r.status_code == 400 and "JSON object" in r.json()["detail"]
    r = client.post("/api/styles/import", json={"name": "a", "content": '{"figure": {"width_mm": 70}}'})
    assert r.status_code == 200
    r = client.post("/api/styles/import", json={"name": "A", "content": {}})
    assert r.status_code == 400                                   # names ignore case
    r = client.post("/api/styles/import", json={"name": "a", "content": {"figure": {"width_mm": 71}},
                                                "overwrite": True})
    assert r.status_code == 200 and r.json()["resolved"]["figure"]["width_mm"] == 71
    r = client.post("/api/styles/import", json={"name": "../evil", "content": {}})
    assert r.status_code == 400


def test_style_file_preview_warns_about_unknown_keys(client, data_dir):
    p = data_dir / "future.lbd.json"
    p.write_text(json.dumps({"figure": {"width_mm": 99, "hologram": True}}))
    body = client.get("/api/stylefile", params={"path": str(p)}).json()
    assert body["resolved"]["figure"]["width_mm"] == 99 and any("hologram" in w for w in body["warnings"])
    (data_dir / "bad.lbd.json").write_text("{nope")
    assert client.get("/api/stylefile", params={"path": str(data_dir / "bad.lbd.json")}).status_code == 400


# ---- sdk / reveal -------------------------------------------------------------------------------


def test_sdk_endpoints(client, data_dir, monkeypatch):
    opened = []
    monkeypatch.setattr(server.sdk, "open_folder", lambda p: opened.append(p))
    body = client.get("/api/sdk").json()
    ids = [lang["id"] for lang in body["languages"]]
    assert ids[:3] == ["python", "matlab", "julia"]
    assert all(lang["error"] is None for lang in body["languages"])
    assert client.post("/api/sdk/reveal", params={"lang": "python"}).status_code == 200
    assert client.post("/api/sdk/reveal", params={"lang": "cobol"}).status_code == 404
    shown = []
    monkeypatch.setattr(server.files, "show_in_file_manager", lambda p: shown.append(p))
    assert client.post("/api/reveal", json={"path": str(data_dir / "curve.lbd")}).json() == {"ok": True}
    assert shown[-1] == data_dir / "curve.lbd"  # the file itself, so it is selected
    assert client.post("/api/reveal", json={"path": "C:/Windows"}).status_code == 403


# ---- rename and trash ----------------------------------------------------------------------------


def test_rename_file(client, data_dir):
    r = client.post("/api/file/rename", json={"path": str(data_dir / "curve.lbd"), "name": "renamed.lbd"})
    assert r.status_code == 200
    assert r.json()["path"] == str(data_dir / "renamed.lbd")
    assert (data_dir / "renamed.lbd").is_file() and not (data_dir / "curve.lbd").exists()
    # only the letter case changes: the same file, allowed
    r = client.post("/api/file/rename", json={"path": str(data_dir / "renamed.lbd"), "name": "Renamed.lbd"})
    assert r.status_code == 200


@pytest.mark.parametrize("name, status", [
    ("curve.h5", 400),           # the file type would change
    ("curve", 400),
    (".lbd", 400),               # no name before the extension
    ("", 400),
    ("sub/curve.lbd", 400),      # renaming can't move it
    (r"..\curve.lbd", 400),
])
def test_rename_refuses_bad_names(client, data_dir, name, status):
    r = client.post("/api/file/rename", json={"path": str(data_dir / "curve.lbd"), "name": name})
    assert r.status_code == status, r.text
    assert (data_dir / "curve.lbd").is_file()


def test_rename_refuses_existing_folders_and_other_files(client, data_dir, tmp_path):
    (data_dir / "other.lbd").write_bytes(b"x")
    r = client.post("/api/file/rename", json={"path": str(data_dir / "curve.lbd"), "name": "other.lbd"})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    r = client.post("/api/file/rename", json={"path": str(data_dir / "sub"), "name": "sub2"})
    assert r.status_code == 400 and "folder" in r.json()["detail"]
    r = client.post("/api/file/rename", json={"path": str(data_dir / "sub" / "notes.txt"), "name": "n.txt"})
    assert r.status_code == 400
    r = client.post("/api/file/rename", json={"path": str(data_dir / "gone.lbd"), "name": "x.lbd"})
    assert r.status_code == 404
    (tmp_path / "outside.lbd").write_bytes(b"x")
    r = client.post("/api/file/rename", json={"path": str(tmp_path / "outside.lbd"), "name": "y.lbd"})
    assert r.status_code == 403


def test_renamed_opened_file_stays_readable(client, data_dir, tmp_path):
    f = tmp_path / "single.lbd"
    (data_dir / "curve.lbd").rename(f)
    client.post("/api/open", json={"path": str(f)}).raise_for_status()
    new = client.post("/api/file/rename", json={"path": str(f), "name": "single2.lbd"}).json()["path"]
    assert client.get("/api/file", params={"path": new}).status_code == 200


def test_trash_file(client, data_dir, monkeypatch):
    trashed = []
    monkeypatch.setattr(server.files.send2trash, "send2trash", lambda p: trashed.append(p))
    assert client.post("/api/file/trash", json={"path": str(data_dir / "curve.lbd")}).json() == {"ok": True}
    assert trashed == [str(data_dir / "curve.lbd")]
    assert client.post("/api/file/trash", json={"path": str(data_dir / "sub")}).status_code == 400
    assert client.post("/api/file/trash", json={"path": str(data_dir / "sub" / "notes.txt")}).status_code == 400
    assert client.post("/api/file/trash", json={"path": str(data_dir / "gone.lbd")}).status_code == 404
    assert client.post("/api/file/trash", json={"path": "C:/Windows/win.ini"}).status_code == 403
    assert len(trashed) == 1


def test_trash_failure_keeps_the_file(client, data_dir, monkeypatch):
    def no_trash(p):
        raise OSError("no recycle bin on this drive")
    monkeypatch.setattr(server.files.send2trash, "send2trash", no_trash)
    r = client.post("/api/file/trash", json={"path": str(data_dir / "curve.lbd")})
    assert r.status_code == 500 and "not deleted" in r.json()["detail"]
    assert (data_dir / "curve.lbd").is_file()


# ---- web UI and helpers --------------------------------------------------------------------------


def test_root_page(client, monkeypatch, cfg, tmp_path):
    r = client.get("/")
    assert r.status_code == 200
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "no-ui")
    c = TestClient(create_app(AppState(cfg, token="t")), base_url="http://127.0.0.1:8000")
    assert "npm run build" in c.get("/").text


def test_collect_warnings_only_lbd_warnings():
    import warnings

    with collect_warnings() as found:
        warnings.warn("a", lbd.LBDWarning)
        warnings.warn("a", lbd.LBDWarning)         # duplicates are shown once
        warnings.warn("other", DeprecationWarning)
    assert found == ["a"]


def test_jsonable():
    assert jsonable({"a": np.float32(1.5), "b": (1, 2), "c": float("inf")}) == {"a": 1.5, "b": [1, 2], "c": None}


def test_fonts_lists_installed_families(client):
    body = client.get("/api/fonts").json()
    assert "DejaVu Sans" in body["installed"] and body["generic"] == ["sans-serif", "serif", "monospace"]
    assert body["installed"] == sorted(set(body["installed"]), key=str.lower)


def test_export_jpg(client, data_dir):
    r = client.post("/api/export", json={"path": str(data_dir / "curve.lbd"), "format": "jpg"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8" and r.headers["content-disposition"].endswith('.jpg"')


def test_export_save_uses_the_save_dialog(client, data_dir, tmp_path, monkeypatch):
    asked = []

    def dialog(folder, name, fmt):
        asked.append((folder, name, fmt))
        return str(tmp_path / "chosen.pdf")

    monkeypatch.setattr(server, "native_save_dialog", dialog)
    r = client.post("/api/export/save", json={"path": str(data_dir / "curve.lbd"), "format": "pdf"})
    assert r.json() == {"path": str(tmp_path / "chosen.pdf"), "warnings": []}
    assert (tmp_path / "chosen.pdf").read_bytes()[:4] == b"%PDF"
    # starts in the data file's folder, with the default name filled in
    assert asked == [(data_dir, "curve_a.pdf", "pdf")]


def test_export_save_cancel_and_wrong_extension(client, data_dir, tmp_path, monkeypatch):
    body = {"path": str(data_dir / "curve.lbd"), "format": "png"}
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: None)
    assert client.post("/api/export/save", json=body).json()["path"] is None
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(tmp_path / "fig.pdf"))
    r = client.post("/api/export/save", json=body)
    assert r.status_code == 400 and "must end in .png" in r.json()["detail"]
    assert not (tmp_path / "fig.pdf").exists()
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(tmp_path / "fig.PNG"))
    assert client.post("/api/export/save", json=body).status_code == 200


def test_export_save_render_errors_come_before_the_dialog(client, data_dir, monkeypatch):
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: pytest.fail("dialog shown for a broken plot"))
    r = client.post("/api/export/save", json={"path": str(data_dir / "curve.lbd"), "format": "pdf",
                                              "spec": {"values": ["nope"]}})
    assert r.status_code == 400


def test_export_save_without_a_dialog(client, data_dir, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_tk(name, *a, **k):
        if name == "tkinter":
            raise ImportError("no tk")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_tk)
    r = client.post("/api/export/save", json={"path": str(data_dir / "curve.lbd"), "format": "pdf"})
    assert r.status_code == 501 and "download folder" in r.json()["detail"]


def test_file_summary_has_the_matplotlib_version(client, data_dir):
    p = str(data_dir / "curve.lbd")
    assert client.get("/api/file", params={"path": p}).json()["matplotlib"] is None
    client.put("/api/file/plot", json={"path": p, "spec": {"kind": "curve"}}).raise_for_status()
    assert client.get("/api/file", params={"path": p}).json()["matplotlib"]
