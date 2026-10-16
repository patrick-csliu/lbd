"""PresetStore: names, files on disk, resolution order, the viewer's default preset."""

import json

import pytest

pytest.importorskip("matplotlib")

import lbd.plot as lp  # noqa: E402
from lbd.plot.presets import BUILTIN_PRESETS, PresetStore, check_name, config_dir, default_preset_name  # noqa: E402
from lbd.plot.style import StyleError, StyleWarning  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return PresetStore(tmp_path / "styles")


# ---- construction ------------------------------------------------------------------------------


def test_default_folder_follows_lbd_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path
    assert PresetStore().dir == tmp_path / "styles"


def test_directory_argument_checks():
    with pytest.raises(ValueError, match="empty"):
        PresetStore("")
    with pytest.raises(TypeError):
        PresetStore(5)


# ---- names -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["paper", "Paper 2", "a.b-c_d", "x" * 64])
def test_valid_names(name):
    assert check_name(name) == name


@pytest.mark.parametrize("name", ["", " x", "../x", "a/b", "a\\b", "x" * 65, "con", "NUL.json", "com3", "end.",
                                  "end ", "ä", 5, None])
def test_invalid_names(name):
    with pytest.raises(StyleError):
        check_name(name)


@pytest.mark.parametrize("method", ["preset", "style", "delete", "is_customized", "is_builtin"])
def test_every_method_checks_the_name(store, method):
    with pytest.raises(StyleError):
        getattr(store, method)("../escape")


def test_names_order_and_builtins(store):
    assert store.names() == ["default"]
    store.save("alpha", {})
    store.save("Zeta", {})
    assert store.names() == ["default", "alpha", "Zeta"]
    assert all(store.is_builtin(n) for n in BUILTIN_PRESETS) and not store.is_builtin("alpha")


def test_unusable_files_are_reported(store):
    store.dir.mkdir(parents=True)
    (store.dir / "con.lbd.json").write_text("{}")
    (store.dir / "old.json").write_text("{}")        # not <name>.lbd.json
    (store.dir / "folder.json").mkdir()
    with pytest.warns(StyleWarning, match="con.lbd.json, old.json"):
        names = store.names()
    assert "con" not in names and "old" not in names and "folder" not in names


def test_names_are_not_case_sensitive(store):
    store.save("paper", {})
    with pytest.raises(StyleError, match="not case-sensitive"):
        store.save("Paper", {})
    with pytest.raises(StyleError, match="already exists"):
        store.import_file("PAPER", {})
    store.import_file("PAPER", {"figure": {"width_mm": 50}}, overwrite=True)   # updates "paper"
    assert store.style("paper").figure.width_mm == 50


# ---- save / preset / style -------------------------------------------------------------------------


def test_save_stores_only_differences(store):
    stored = store.save("paper", {"figure": {"width_mm": 90, "height_mm": 64}})
    assert stored == {"lbd_style": 2, "name": "paper", "figure": {"width_mm": 90.0}}
    on_disk = json.loads((store.dir / "paper.lbd.json").read_text(encoding="utf-8"))
    assert on_disk == stored
    assert store.preset("paper") == {"lbd_style": 2, "figure": {"width_mm": 90.0}}
    assert store.style("paper").name == "paper"
    assert not list(store.dir.glob("*.tmp*"))


def test_save_rejects_bad_settings(store):
    with pytest.raises(StyleError, match="unknown style setting"):
        store.save("paper", {"figure": {"widht_mm": 90}})
    with pytest.raises(StyleError, match="dict"):
        store.save("paper", [1])
    assert not (store.dir / "paper.lbd.json").exists()


def test_preset_file_problems(store):
    store.dir.mkdir(parents=True)
    (store.dir / "broken.lbd.json").write_text("{nope")
    with pytest.raises(StyleError, match="not valid JSON"):
        store.preset("broken")
    (store.dir / "listy.lbd.json").write_text("[1, 2]")
    with pytest.raises(StyleError, match="JSON object"):
        store.preset("listy")
    (store.dir / "future.lbd.json").write_text(json.dumps({"figure": {"hologram": True}}))
    with pytest.warns(StyleWarning, match="hologram"):
        assert store.style("future").figure.width_mm == 85


def test_unknown_preset(store):
    with pytest.raises(KeyError, match="no style preset named 'nope'"):
        store.preset("nope")


# ---- delete --------------------------------------------------------------------------------------


def test_delete(store):
    store.save("paper", {})
    store.delete("paper")
    assert "paper" not in store.names()
    with pytest.raises(KeyError):
        store.delete("paper")
    with pytest.raises(StyleError, match="nothing to delete"):
        store.delete("default")
    store.save("default", {"figure": {"width_mm": 99}})
    assert store.is_customized("default")
    store.delete("default")                  # resets the built-in
    assert not store.is_customized("default") and store.style("default").figure.width_mm == 85


# ---- resolve --------------------------------------------------------------------------------------


def test_resolve_layers(store):
    store.save("paper", {"figure": {"width_mm": 90, "height_mm": 50}})
    s = store.resolve("paper", file_style={"figure": {"height_mm": 60}}, override={"figure": {"dpi": 300}})
    assert (s.figure.width_mm, s.figure.height_mm, s.figure.dpi) == (90, 60, 300)
    assert s.name == "paper"


def test_resolve_unknown_preset(store):
    with pytest.raises(StyleError, match="available"):
        store.resolve("nope")


def test_resolve_file_style_is_lenient_override_is_strict(store):
    with pytest.warns(StyleWarning, match="nonsense"):
        s = store.resolve("default", file_style={"figure": {"nonsense": 1, "width_mm": 70}})
    assert s.figure.width_mm == 70
    with pytest.raises(StyleError, match="unknown style setting"):
        store.resolve("default", override={"figure": {"nonsense": 1}})


# ---- default preset ---------------------------------------------------------------------------------


def test_default_preset_name(tmp_path):
    assert default_preset_name(tmp_path) == "default"          # no settings yet: silent
    PresetStore(tmp_path / "styles").save("paper", {})
    (tmp_path / "settings.json").write_text(json.dumps({"default_style": "paper"}))
    assert default_preset_name(tmp_path) == "paper"


@pytest.mark.parametrize("content, match", [
    ("{nope", "can't read"),
    ("[1]", "not a JSON object"),
    (json.dumps({"default_style": 5}), "must be text"),
    (json.dumps({"default_style": "gone"}), "no longer exists"),
])
def test_default_preset_problems_warn(tmp_path, content, match):
    (tmp_path / "settings.json").write_text(content)
    with pytest.warns(StyleWarning, match=match):
        assert default_preset_name(tmp_path) == "default"


def test_lp_functions_use_the_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path))
    PresetStore().save("paper", {"figure": {"width_mm": 91}})
    assert "paper" in lp.list_styles()
    assert lp.load_style("paper").figure.width_mm == 91
    (tmp_path / "settings.json").write_text(json.dumps({"default_style": "paper"}))
    assert lp.default_style().figure.width_mm == 91


def test_default_preset_has_a_description_and_otherwise_the_defaults(store):
    from lbd.plot.style import Style

    s = store.style("default")
    assert "APS and AIP" in s.description
    s.description, s.name = "", None
    assert s == Style()
