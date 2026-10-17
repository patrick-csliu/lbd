import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

import lbd
from lbd.plot import render as rnd
from lbd_viewer.config import Config, ConfigError, Style, StyleError, deep_merge
from lbd_viewer.server import AppState, create_app


# ---- security --------------------------------------------------------------------


def test_token_required(cfg):
    c = TestClient(create_app(AppState(cfg, token="secret")), base_url="http://127.0.0.1:8000")
    assert c.get("/api/state").status_code == 403
    assert c.get("/api/state", headers={"X-LBD-Token": "nope"}).status_code == 403
    assert c.get("/api/state", headers={"X-LBD-Token": "secret"}).status_code == 200


def test_host_check_blocks_dns_rebinding(cfg):
    c = TestClient(create_app(AppState(cfg, token="t")), base_url="http://evil.example:8000")
    assert c.get("/api/state", headers={"X-LBD-Token": "t"}).status_code == 403


def test_paths_outside_roots_refused(client, tmp_path):
    outside = tmp_path / "outside.lbd"
    lbd.Dataset().save(outside)
    assert client.get("/api/file", params={"path": str(outside)}).status_code == 403
    assert client.get("/api/list", params={"path": str(tmp_path)}).status_code == 403
    # ... unless it was opened explicitly (double-click)
    client.post("/api/open", json={"path": str(outside)}).raise_for_status()
    assert client.get("/api/file", params={"path": str(outside)}).status_code == 200


# ---- folders ----------------------------------------------------------------------


def test_roots_and_listing(client, data_dir):
    s = client.get("/api/state").json()
    assert s["roots"] == [str(data_dir.resolve())]
    r = client.get("/api/list", params={"path": str(data_dir)}).json()
    assert r["dirs"] == ["sub"]  # .git and @eaDir hidden
    assert [f["name"] for f in r["files"]] == ["curve.lbd"]
    r = client.get("/api/list", params={"path": str(data_dir / "sub")}).json()
    assert r["dirs"] == ["deeper"]
    assert [f["name"] for f in r["files"]] == ["sweep.lbd"]  # notes.txt not listed
    r = client.get("/api/search", params={"root": str(data_dir), "q": "cu"}).json()
    assert sorted(x["rel"].replace("\\", "/") for x in r["results"]) == ["curve.lbd", "sub/deeper/cube.lbd"]
    client.request("DELETE", "/api/roots", params={"path": str(data_dir.resolve())}).raise_for_status()
    assert client.get("/api/state").json()["roots"] == []


def test_add_missing_root(client, tmp_path):
    r = client.post("/api/roots", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 400


# ---- files and rendering --------------------------------------------------------------


def test_file_summary(client, data_dir):
    r = client.get("/api/file", params={"path": str(data_dir / "sub" / "sweep.lbd")}).json()
    assert r["title"] == "sweep"
    assert [a["name"] for a in r["axes"]] == ["power", "freq"]
    assert r["values"][0]["complex"] is True
    assert r["values"][0]["shape"] == [7, 30]
    assert r["plot"]["kind"] == "heatmap"


@pytest.mark.parametrize("name, spec, kind", [
    ("curve.lbd", None, "curve"),
    ("curve.lbd", {"values": ["a", "b"]}, "curve"),
    ("sub/sweep.lbd", None, "heatmap"),
    ("sub/sweep.lbd", {"kind": "curve"}, "curve"),
    ("sub/sweep.lbd", {"kind": "curve", "series": "none", "index": {"power": 3}}, "curve"),
    ("sub/deeper/cube.lbd", {"values": ["T"]}, "heatmap"),
])
def test_render_kinds(client, data_dir, name, spec, kind):
    r = client.post("/api/render", json={"path": str(data_dir / name), "spec": spec})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["svg"].lstrip().startswith("<?xml")
    assert body["spec"]["kind"] == kind


def test_render_resolves_slices(client, data_dir):
    body = client.post("/api/render", json={"path": str(data_dir / "sub/deeper/cube.lbd"),
                                            "spec": {"values": ["T"], "index": {"a": -1}}}).json()
    assert body["spec"]["x"] == "c" and body["spec"]["y"] == "b"
    assert body["spec"]["slices"][0]["axis"] == "a"
    assert body["spec"]["slices"][0]["index"] == 1  # -1 counts from the end
    r = client.post("/api/render", json={"path": str(data_dir / "sub/deeper/cube.lbd"),
                                         "spec": {"values": ["T"], "index": {"a": 9}}})
    assert r.status_code == 400 and "out of range" in r.json()["detail"]


def test_render_errors(client, data_dir):
    r = client.post("/api/render", json={"path": str(data_dir / "curve.lbd"), "spec": {"kind": "heatmap"}})
    assert r.status_code == 400 and "2 dimensions" in r.json()["detail"]
    r = client.post("/api/render", json={"path": str(data_dir / "curve.lbd"), "spec": {"x": "nope"}})
    assert r.status_code == 400


@pytest.mark.parametrize("fmt, magic", [("pdf", b"%PDF"), ("png", b"\x89PNG"), ("svg", b"<?xml")])
def test_export(client, data_dir, fmt, magic):
    r = client.post("/api/export", json={"path": str(data_dir / "sub" / "sweep.lbd"), "format": fmt})
    assert r.status_code == 200, r.text
    assert r.content.startswith(magic)
    assert f'sweep_S21.{fmt}"' in r.headers["content-disposition"]


def test_png_export_has_physical_size(client, data_dir, cfg):
    from PIL import Image

    cfg.save_preset("tiny", {"figure": {"width_mm": 50.8, "height_mm": 25.4, "dpi": 100}})
    r = client.post("/api/export", json={"path": str(data_dir / "curve.lbd"), "format": "png", "preset": "tiny"})
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (200, 100)  # 2 in x 1 in at 100 dpi: no tight-bbox cropping


def test_save_override_into_file(client, data_dir):
    p = data_dir / "curve.lbd"
    r = client.put("/api/file/plot", json={"path": str(p), "style": {"figure": {"width_mm": 120}},
                                           "spec": {"values": ["b"]}})
    assert r.status_code == 200, r.text
    d = lbd.load(p)
    assert d.style == {"figure": {"width_mm": 120}}
    assert d.plot == {"values": ["b"]}
    np.testing.assert_allclose(d["a"].data[:3], np.sin(1e7 * np.linspace(0, 1e-6, 50))[:3])
    body = client.post("/api/render", json={"path": str(p)}).json()
    assert body["size_mm"][0] == 120
    assert body["spec"]["values"] == ["b"]
    # null removes an entry, missing keys are left alone
    client.put("/api/file/plot", json={"path": str(p), "style": None}).raise_for_status()
    d = lbd.load(p)
    assert d.style is None and d.plot == {"values": ["b"]}


# ---- styles -------------------------------------------------------------------------------


def test_style_presets_api(client, cfg):
    names = [s["name"] for s in client.get("/api/styles").json()]
    assert names == ["default"]
    r = client.put("/api/styles/My thesis", json={"preset": {"figure": {"font": {"family": "serif", "size_pt": 9}}}})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"]["figure"]["font"]["size_pt"] == 9
    assert r.json()["resolved"]["figure"]["width_mm"] == 85.0
    client.put("/api/settings", json={"default_style": "My thesis"}).raise_for_status()
    assert client.get("/api/state").json()["default_style"] == "My thesis"
    assert client.put("/api/styles/bad", json={"preset": {"figure": {"font": {"size_pt": -1}}}}).status_code == 400
    # path traversal in a preset name is refused (400 from the name check, or 404/405 from routing)
    assert client.put("/api/styles/..%2Fevil", json={"preset": {}}).status_code in (400, 404, 405)
    assert not (cfg.dir / "evil.json").exists()
    assert client.delete("/api/styles/default").status_code == 400
    client.delete("/api/styles/My thesis").raise_for_status()
    assert client.get("/api/state").json()["default_style"] == "default"


def test_style_resolution_order(cfg):
    cfg.save_preset("p1", {"figure": {"width_mm": 100, "font": {"size_pt": 10}}})
    cfg.save_preset("p2", {"figure": {"font": {"size_pt": 12}}})
    cfg.set_default_style("p1")
    assert cfg.resolve().figure.font.size_pt == 10
    # the file's style_name preset beats the app default
    assert cfg.resolve(preset=cfg.preset_for(None, "p2")).figure.font.size_pt == 12
    # a preset that doesn't exist here falls back to the default
    assert cfg.preset_for(None, "elsewhere") == "p1"
    # the UI choice beats the file's style_name
    assert cfg.preset_for("default", "p2") == "default"
    s = cfg.resolve(preset="p1", file_style={"figure": {"height_mm": 40}}, ui_override={"figure": {"width_mm": 70}})
    assert (s.figure.width_mm, s.figure.height_mm, s.figure.font.size_pt) == (70, 40, 10)


def test_deep_merge_does_not_mutate():
    base = {"a": {"b": 1, "c": 2}}
    out = deep_merge(base, {"a": {"b": 5}})
    assert out == {"a": {"b": 5, "c": 2}} and base == {"a": {"b": 1, "c": 2}}


def test_bad_preset_name(cfg):
    with pytest.raises(StyleError):
        cfg.save_preset("../x", {})


# ---- renderer details ------------------------------------------------------------------------


def test_unit_prefix():
    from lbd.plot.units import prefix_scale

    assert prefix_scale(np.array([6.99e9, 7.01e9]), "Hz") == (1e-9, "GHz")
    f, u = prefix_scale(np.array([1e-6, 5e-6]), "s")
    assert u == "µs" and f == pytest.approx(1e6)
    assert prefix_scale(np.array([-40.0]), "dBm", warn=False) == (1.0, "dBm")
    assert prefix_scale(np.array([7e9]), "Hz", to="") == (1.0, "Hz")
    assert prefix_scale(np.array([2.0]), "V") == (1.0, "V")


def test_axis_label_formats():
    assert rnd.axis_label("Frequency", "GHz", "paren") == "Frequency (GHz)"
    assert rnd.axis_label("Frequency", "GHz", "bracket") == "Frequency [GHz]"
    assert rnd.axis_label("Frequency", "GHz", "slash") == "Frequency / GHz"
    assert rnd.axis_label("Count", "", "paren") == "Count"


def test_quantity_fixed_limits(data_dir, cfg):
    style = cfg.resolve(ui_override={"quantities": {"S21.db": {"vmin": -20, "vmax": 0, "cmap": "magma"}}})
    d = lbd.load(data_dir / "sub" / "sweep.lbd")
    spec = rnd.resolve_spec(d, None)
    fig, _ = rnd.build_figure(d, spec, style)
    mesh = fig.axes[0].collections[0]
    assert mesh.norm.vmin == -20 and mesh.norm.vmax == 0
    assert mesh.cmap.name == "magma"


def test_sdk_info():
    from lbd_viewer import sdk

    info = sdk.sdk_info()
    assert info["bundled"] is False  # running from the source tree
    # discovered from languages/*/language.toml, in manifest order
    assert [lang["id"] for lang in info["languages"]] == ["python", "matlab", "julia"]
    for lang in info["languages"]:
        assert lang["available"] and lang["install"] and lang["check"] and lang["example"]
    by_id = {lang["id"]: lang for lang in info["languages"]}
    assert by_id["python"]["install"][0]["code"].startswith('pip install "')
    assert "addpath(" in by_id["matlab"]["install"][0]["code"]  # source variant, no .mltbx
    assert "{t.Name}" not in by_id["matlab"]["uninstall"]          # only known placeholders filled


def test_sdk_info_bundled(tmp_path, monkeypatch):
    """An installed app reads the staged sdk/<id>/language.toml and picks the 'sdk' variants."""
    from lbd_viewer import sdk

    src = sdk.REPO_ROOT / "languages"
    for lang_id in ("python", "matlab"):
        d = tmp_path / lang_id
        d.mkdir()
        (d / "language.toml").write_bytes((src / lang_id / "language.toml").read_bytes())
    (tmp_path / "python" / "lbd-9.9.9-py3-none-any.whl").write_bytes(b"")
    (tmp_path / "matlab" / "LBD.mltbx").write_bytes(b"")
    monkeypatch.setenv("LBD_SDK_DIR", str(tmp_path))
    info = sdk.sdk_info()
    assert info["bundled"] is True
    by_id = {lang["id"]: lang for lang in info["languages"]}
    assert by_id["python"]["install"][0]["code"].endswith('lbd-9.9.9-py3-none-any.whl[plot]"')
    assert by_id["python"]["install"][1]["code"].endswith('lbd-9.9.9-py3-none-any.whl"')
    assert "installToolbox" in by_id["matlab"]["install"][0]["code"]
    assert 'strcmp({t.Name}, "LBD")' in by_id["matlab"]["uninstall"]


# ---- style files: export / import / preview -----------------------------------------------


def test_style_export_import_roundtrip(client, data_dir, tmp_path):
    client.put("/api/styles/thesis", json={"preset": {"figure": {"width_mm": 140, "font": {"size_pt": 10}}}}) \
        .raise_for_status()
    r = client.get("/api/styles/thesis/export", params={"format": "lbd"})
    assert r.status_code == 200
    assert 'thesis.lbd.json"' in r.headers["content-disposition"]
    full = r.json()
    assert full["lbd_style"] == 2 and full["figure"]["width_mm"] == 140
    assert full["figure"]["axes"]["frame"]["linewidth_pt"] == 0.6      # complete, not only the changes
    # import it back under a new name
    r = client.post("/api/styles/import", json={"name": "thesis copy", "content": full})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"]["figure"]["font"]["size_pt"] == 10
    # refuses to overwrite silently, and refuses bad files
    assert client.post("/api/styles/import", json={"name": "thesis", "content": full}).status_code == 400
    assert client.post("/api/styles/import", json={"name": "x", "content": "{not json"}).status_code == 400
    assert client.post("/api/styles/import", json={"name": "x", "content": {"figure": {"dpi": -5}}}) \
        .status_code == 400


def test_style_export_mplstyle(client):
    client.put("/api/styles/talk", json={"preset": {"figure": {"font": {"size_pt": 14}}}}).raise_for_status()
    r = client.get("/api/styles/talk/export", params={"format": "mpl"})
    assert r.status_code == 200 and 'talk.mplstyle"' in r.headers["content-disposition"]
    assert "font.size: 14" in r.text and "axes.prop_cycle: cycler('color'" in r.text


def test_style_file_in_folder_listing_and_preview(client, data_dir):
    from lbd.plot.style import from_dict

    s = from_dict({"figure": {"width_mm": 120, "height_mm": 50}})
    s.name = "wide"
    s.save(data_dir / "wide.lbd.json")
    listing = client.get("/api/list", params={"path": str(data_dir)}).json()
    types = {f["name"]: f["type"] for f in listing["files"]}
    assert types["wide.lbd.json"] == "style" and types["curve.lbd"] == "lbd"
    info = client.get("/api/stylefile", params={"path": str(data_dir / "wide.lbd.json")}).json()
    assert info["name"] == "wide" and info["resolved"]["figure"]["width_mm"] == 120
    body = client.post("/api/render", json={"path": str(data_dir / "curve.lbd"),
                                            "style_file": str(data_dir / "wide.lbd.json")}).json()
    assert body["size_mm"] == [120, 50] and body["preset"] == "wide.lbd.json"


# ---- images ----------------------------------------------------------------------------------


def test_images_listing_info_and_bytes(client, data_dir):
    from PIL import Image

    # an LBD export (PNG with metadata), a JPEG, a 16-bit TIFF and an SVG
    png = client.post("/api/export", json={"path": str(data_dir / "curve.lbd"), "format": "png"}).content
    (data_dir / "fig.png").write_bytes(png)
    Image.new("RGB", (40, 20), "red").save(data_dir / "photo.jpg", dpi=(72, 72))
    Image.fromarray(np.arange(64 * 32, dtype=np.uint16).reshape(32, 64)).save(data_dir / "cam.tif")
    svg = client.post("/api/export", json={"path": str(data_dir / "curve.lbd"), "format": "svg"}).content
    (data_dir / "fig.svg").write_bytes(svg)
    (data_dir / "notes.txt").write_text("not shown")

    files = {f["name"]: f["type"] for f in client.get("/api/list", params={"path": str(data_dir)}).json()["files"]}
    assert {files["fig.png"], files["photo.jpg"], files["cam.tif"], files["fig.svg"]} == {"image"}
    assert "notes.txt" not in files
    found = client.get("/api/search", params={"root": str(data_dir), "q": "fig"}).json()["results"]
    assert {r["type"] for r in found} == {"image"}

    i = client.get("/api/image/info", params={"path": str(data_dir / "fig.png")}).json()
    assert i["format"] == "PNG" and i["width"] == 2007 and i["dpi"] == [600.0, 600.0]
    assert i["size_mm"][0] == pytest.approx(85, abs=0.1)              # physical size of the export
    assert i["text"]["Software"].startswith("LBD viewer") and i["text"]["Title"] == "curve"
    i = client.get("/api/image/info", params={"path": str(data_dir / "photo.jpg")}).json()
    assert (i["format"], i["width"], i["height"]) == ("JPEG", 40, 20)
    i = client.get("/api/image/info", params={"path": str(data_dir / "cam.tif")}).json()
    assert i["bit_depth"] == 16 and i["note"]
    i = client.get("/api/image/info", params={"path": str(data_dir / "fig.svg")}).json()
    assert i["format"] == "SVG" and i["size_mm"][0] == pytest.approx(85, abs=0.2)

    r = client.get("/api/image", params={"path": str(data_dir / "cam.tif")})
    assert r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")   # converted
    r = client.get("/api/image", params={"path": str(data_dir / "photo.jpg")})
    assert r.headers["content-type"] == "image/jpeg"
    r = client.get("/api/image", params={"path": str(data_dir / "fig.svg")})
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "script-src 'none'" in r.headers["content-security-policy"]


def test_image_paths_are_checked(client, tmp_path):
    from PIL import Image

    outside = tmp_path / "outside.png"
    Image.new("RGB", (4, 4)).save(outside)
    assert client.get("/api/image", params={"path": str(outside)}).status_code == 403
    assert client.get("/api/image/info", params={"path": str(outside)}).status_code == 403
    assert client.get("/api/stylefile", params={"path": str(outside)}).status_code == 403


def test_render_scatter_kinds(client, data_dir):
    p = str(data_dir / "sub" / "sweep.lbd")
    for spec in ({"kind": "scatter"}, {"kind": "scatter", "complex": "iq", "color": "power"},
                 {"kind": "scatter", "x": "freq", "color": "power"}):
        r = client.post("/api/render", json={"path": p, "spec": spec})
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["kind"] == "scatter"


def test_docs_served_without_token(cfg, tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "styles").mkdir(parents=True)
    (site / "index.html").write_text("<h1>LBD docs</h1>", encoding="utf-8")
    (site / "styles" / "settings.html").write_text("settings", encoding="utf-8")
    monkeypatch.setenv("LBD_DOCS_DIR", str(site))
    c = TestClient(create_app(AppState(cfg, token="secret")), base_url="http://127.0.0.1:8000")
    assert "LBD docs" in c.get("/docs/").text                       # no token needed
    assert c.get("/docs/styles/settings.html").text == "settings"
    r = c.get("/docs", follow_redirects=False)
    assert r.status_code in (301, 302, 307) and r.headers["location"] == "/docs/"
    assert c.get("/docs/../../secret.txt").status_code == 404
    evil = TestClient(create_app(AppState(cfg, token="secret")), base_url="http://evil.example:8000")
    assert evil.get("/docs/").status_code == 403                    # host check still applies


def test_docs_not_built(cfg, tmp_path, monkeypatch):
    from lbd_viewer import server

    monkeypatch.setenv("LBD_DOCS_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(server.sdk, "REPO_ROOT", tmp_path)          # no <repo>/site either
    monkeypatch.setattr(server.sdk, "PACKAGE_DIR", tmp_path)        # nor docs inside the package
    c = TestClient(create_app(AppState(cfg, token="t")), base_url="http://127.0.0.1:8000")
    r = c.get("/docs/")
    assert r.status_code == 404 and "mkdocs build" in r.text


def test_docs_and_sdk_inside_a_macos_app_bundle(tmp_path, monkeypatch):
    """LBD Viewer.app: the program is in Contents/MacOS, Help and modules in Contents/Resources."""
    from lbd_viewer import sdk, server

    contents = tmp_path / "LBD Viewer.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources" / "docs").mkdir(parents=True)
    (contents / "Resources" / "docs" / "index.html").write_text("help", encoding="utf-8")
    (contents / "Resources" / "sdk").mkdir()
    monkeypatch.delenv("LBD_DOCS_DIR", raising=False)
    monkeypatch.delenv("LBD_SDK_DIR", raising=False)
    monkeypatch.setattr(sdk.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sdk.sys, "executable", str(contents / "MacOS" / "lbd-view"))
    assert server.docs_dir() == contents / "Resources" / "docs"
    assert sdk.sdk_dir() == contents / "Resources" / "sdk"


def test_docs_and_sdk_inside_the_installed_package(tmp_path, monkeypatch):
    """The release wheel carries docs/ and sdk/ in the package folder (scripts/build_wheels.py)."""
    from lbd_viewer import sdk, server

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text("help", encoding="utf-8")
    (tmp_path / "sdk").mkdir()
    monkeypatch.delenv("LBD_DOCS_DIR", raising=False)
    monkeypatch.delenv("LBD_SDK_DIR", raising=False)
    monkeypatch.setattr(sdk, "PACKAGE_DIR", tmp_path)
    assert server.docs_dir() == tmp_path / "docs"
    assert sdk.sdk_dir() == tmp_path / "sdk"
    assert sdk.languages_dir() == (tmp_path / "sdk", "sdk")
