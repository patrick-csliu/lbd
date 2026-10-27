"""The repository's scripts: language manifests, version check, test runner, docs hooks, doc examples."""

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def languages(load_module):
    return load_module("scripts/languages.py")


# ---- languages.py ----------------------------------------------------------------------------


GOOD = '''id = "{id}"
name = "Lang"
order = 5
requirements = "nothing"
example = "ex.txt"
check = "ok"
notes = ["n"]

[[version]]
file = "VERSION"
pattern = '^v(\\\\S+)'

[test]
requires = "python"
command = ["{{python}}", "-c", "import sys; print(sys.argv[1])", "{{lang_dir}}"]

[crosslang]
write = ["x", "{{out}}"]
check = ["x", "{{root}}"]

[sdk]
copy = ["ex.txt"]

[[install]]
where = "any"
steps = [{{ label = "do", code = "it {{path}}" }}]
'''


def make_lang(root: Path, lang_id="demo", text=None):
    d = root / lang_id
    d.mkdir(parents=True)
    (d / "ex.txt").write_text("example")
    (d / "VERSION").write_text("v1.2.3\n")
    (d / "language.toml").write_text(text if text is not None else GOOD.format(id=lang_id), encoding="utf-8")
    return d


def test_load_and_discover(languages, tmp_path):
    make_lang(tmp_path, "zeta")
    make_lang(tmp_path, "alpha")
    (tmp_path / "_template").mkdir()
    langs = languages.discover(tmp_path)
    assert [lang.id for lang in langs] == ["alpha", "zeta"]
    lang = langs[0]
    assert lang.order == 5 and lang.section("test")["requires"] == "python" and lang.section("nope") == {}
    assert languages.read_pattern(lang.dir / "VERSION", r"^v(\S+)") == "1.2.3"
    assert languages.read_pattern(lang.dir / "missing", r"(x)") is None


def test_run_fills_placeholders(languages, tmp_path):
    lang = languages.load(make_lang(tmp_path))
    r = lang.run(lang.section("test")["command"])
    assert r.returncode == 0 and str(lang.dir) in r.stdout
    env = lang.env(out="X")
    assert env["LBD_OUT"] == "X" and env["LBD_LANG_DIR"] == str(lang.dir)


def test_missing_placeholder_value_is_an_error(languages, tmp_path):
    lang = languages.load(make_lang(tmp_path))
    with pytest.raises(languages.ManifestError, match=r"\{out\}"):
        lang.command(lang.section("crosslang")["write"])
    assert lang.command(["x", "{out}"], out="here")[1] == "here"


def test_missing_tool(languages, tmp_path, monkeypatch):
    lang = languages.load(make_lang(tmp_path))
    monkeypatch.setattr(languages.shutil, "which", lambda name: None)
    assert lang.missing_tool("test") == "python"
    assert lang.missing_tool("sdk") is None


@pytest.mark.parametrize("change, match", [
    (lambda t: t.replace('id = "demo"', 'id = "other"'), "folder name"),
    (lambda t: t.replace('name = "Lang"\n', ""), "'name' is required"),
    (lambda t: t + "\ncolour = 1\n", "unknown keys"),
    (lambda t: t.replace("order = 5", 'order = "5"'), "whole number"),
    (lambda t: t.replace('notes = ["n"]', "notes = 3"), "list of strings"),
    (lambda t: t.replace('requirements = "nothing"', "requirements = 1"), "must be text"),
    (lambda t: t.replace("[test]\nrequires", "[test]\nnope = 1\nrequires"), r"\[test\] has unknown keys"),
    (lambda t: t.replace('command = ["{python}"', 'command = [1, "{python}"'), "list of strings"),
    (lambda t: t.replace('check = ["x", "{root}"]\n', ""), "both 'write' and 'check'"),
    (lambda t: t.replace("pattern = '^v(\\\\S+)'", "pattern = '^v\\\\S+'"), "capture group"),
    (lambda t: t.replace("pattern = '^v(\\\\S+)'", "pattern = '(['"), "regular expression"),
    (lambda t: t.replace("[[version]]", "[version]"), r"\[\[version\]\] must be an array"),
    (lambda t: t.replace('where = "any"', 'where = "cloud"'), "where must be"),
    (lambda t: t.replace('steps = [{ label = "do", code = "it {path}" }]', "steps = []"), "at least one step"),
    (lambda t: t.replace('{ label = "do", code = "it {path}" }', '{ label = "do" }'), "step 1"),
    (lambda t: t.replace('example = "ex.txt"', 'example = "gone.txt"'), "not found"),
    (lambda t: t.replace("[sdk]\ncopy", "[sdk]\nfallback_copy = 3\ncopy"), r"\[sdk\].fallback_copy"),
    (lambda t: t.replace("[crosslang]", "crosslang = 1\n[x]"), "must be a table|unknown keys"),
])
def test_manifest_errors(languages, tmp_path, change, match):
    text = change(GOOD.format(id="demo"))
    d = make_lang(tmp_path, "demo", text)
    with pytest.raises(languages.ManifestError, match=match):
        languages.load(d)


def test_manifest_missing_and_invalid_toml(languages, tmp_path):
    (tmp_path / "none").mkdir()
    with pytest.raises(languages.ManifestError, match="missing"):
        languages.load(tmp_path / "none")
    d = make_lang(tmp_path, "broken", "id = [")
    with pytest.raises(languages.ManifestError, match="invalid TOML"):
        languages.load(d)


def test_real_manifests_are_valid(languages):
    ids = [lang.id for lang in languages.discover()]
    assert ids == ["python", "matlab", "julia"]


# ---- check_versions.py ---------------------------------------------------------------------------


def test_check_versions_on_the_repository(load_module, capsys):
    cv = load_module("scripts/check_versions.py")
    assert cv.main() == 0
    version = capsys.readouterr().out.strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(-dev)?", version) and cv.release_version() == version
    assert cv.spec_version() == "1.0"


def test_check_versions_reports_a_mismatch(load_module, monkeypatch, capsys):
    cv = load_module("scripts/check_versions.py")
    names = [where for where, _, _ in cv.version_locations()]
    release = dict.fromkeys(names, "1.0.0")
    release[names[0]], release[names[1]] = "1.0.1", None
    monkeypatch.setattr(cv, "collect", lambda repo=None: (release, {"x": "1.0"}))
    assert cv.main() == 1
    err = capsys.readouterr().err
    assert "1.0.1" in err and "None" in err
    with pytest.raises(cv.VersionError, match="differ"):
        cv.release_version()
    monkeypatch.setattr(cv, "collect", lambda repo=None: (dict.fromkeys(names, "1.0.0"), {"x": "9.9"}))
    assert cv.main() == 1 and "format versions differ" in capsys.readouterr().err


# ---- mkdocs_hooks.py ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hooks(load_module):
    pytest.importorskip("mkdocs")
    return load_module("scripts/mkdocs_hooks.py")


def test_style_table(hooks):
    table = hooks.style_table("FigureStyle")
    lines = table.splitlines()
    assert lines[0].startswith("| Setting | Type | Default | Allowed | Meaning |")
    assert any(line.startswith("| `width_mm` | number | `85` | > 10, ≤ 1000 |") for line in lines)
    assert "group" in table and "*FontStyle*" in table
    q = hooks.style_table("QuantityStyle")
    assert "`prefix`" in q and "text or empty" in q
    label = hooks.style_table("LabelStyle")
    assert "`auto_prefix`" in label and "`paren`, `bracket`, `slash`" in label


@pytest.mark.parametrize("name", ["Nope", "StyleError", "MM"])
def test_style_table_unknown_model(hooks, name):
    with pytest.raises(ValueError, match="not a style model"):
        hooks.style_table(name)


def test_on_page_markdown_replaces_only_outside_code(hooks):
    md = 'a\n\n{{ style_table("GridStyle") }}\n\nUse `{{ style_table("NewModel") }}` in a page.'
    out = hooks.on_page_markdown(md, page=None, config=None, files=None)
    assert "| `visible` |" in out and '`{{ style_table("NewModel") }}`' in out
    assert hooks.on_page_markdown("plain", page=None, config=None, files=None) == "plain"


def test_on_config_sets_the_version(hooks):
    config = {"site_name": "LBD", "extra": {}}
    hooks.on_config(config)
    assert re.fullmatch(r"LBD \d+\.\d+\.\d+(-dev)?", config["site_name"]) and config["extra"]["version"]


def test_release_version_mismatch_warns_and_shows_dev(hooks, monkeypatch, caplog):
    import importlib.util

    real = importlib.util.module_from_spec

    def fake_module(spec):
        mod = real(spec)
        orig_exec = spec.loader.exec_module

        def exec_module(m):
            orig_exec(m)

            def boom():
                raise m.VersionError("release versions differ")
            m.release_version = boom
        spec.loader.exec_module = exec_module
        return mod

    monkeypatch.setattr(importlib.util, "module_from_spec", fake_module)
    with caplog.at_level("WARNING"):
        assert hooks._release_version() == "dev"
    assert "differ" in caplog.text


# ---- check_doc_examples.py ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def doccheck(load_module):
    return load_module("scripts/check_doc_examples.py")


def test_extract_blocks(doccheck, tmp_path, monkeypatch):
    page = tmp_path / "p.md"
    page.write_text('''# T

```python
a = 1
```

<!-- no-check -->
```python
skipped = True
```

talk about no-check here
```python
b = 2
```

=== "Python"

    ```python
    c = 3
    ```

```julia
x = 1
```
''', encoding="utf-8")
    monkeypatch.setattr(doccheck, "doc_files", lambda: [page])
    monkeypatch.setattr(doccheck, "REPO", tmp_path)
    blocks = doccheck.extract("python")
    assert [b["code"].strip() for b in blocks] == ["a = 1", "b = 2", "c = 3"]
    assert blocks[0]["where"] == "p.md:3"
    assert [b["code"].strip() for b in doccheck.extract("julia")] == ["x = 1"]


def test_run_lang_requires_the_summary_line(doccheck, monkeypatch):
    class R:
        returncode = 0
        stdout = "ok  a\n"
        stderr = ""

    monkeypatch.setattr(doccheck.subprocess, "run", lambda *a, **k: R())
    status, out = doccheck.run_lang("python", [], verbose=False)
    assert status == "FAILED" and "summary line" in out
    R.stdout = "ok  a\n1/1 ok\n"
    assert doccheck.run_lang("python", [], verbose=False)[0] == "passed"
    R.stdout = "FAIL a x\n0/1 ok\n"
    assert doccheck.run_lang("python", [], verbose=False)[0] == "FAILED"


def test_run_lang_skips_missing_programs(doccheck, monkeypatch):
    monkeypatch.setattr(doccheck.shutil, "which", lambda name: None)
    assert doccheck.run_lang("matlab", [], verbose=False)[0] == "skipped"
    assert doccheck.run_lang("julia", [], verbose=False)[0] == "skipped"


def test_doc_examples_python_pass():
    r = subprocess.run([__import__("sys").executable, str(REPO / "scripts/check_doc_examples.py"), "--lang", "python"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr


# ---- test_all.py --------------------------------------------------------------------------------


def test_test_all_summary(load_module, monkeypatch, capsys):
    ta = load_module("scripts/test_all.py")

    class R:
        def __init__(self, code):
            self.returncode, self.stdout, self.stderr = code, "out", ""

    monkeypatch.setattr(ta, "run", lambda cmd, cwd: R(0))
    monkeypatch.setattr(ta.shutil, "which", lambda name: None)
    langs = ta.discover()
    for lang in langs:
        monkeypatch.setattr(type(lang), "run", lambda self, cmd, **kw: R(0))
    monkeypatch.setattr(type(langs[0]), "missing_tool", lambda self, section: None)
    assert ta.main(["--fast"]) == 0
    out = capsys.readouterr().out
    assert "skipped" in out and "PASSED, but" in out      # web type check skipped without npm
    monkeypatch.setattr(ta, "run", lambda cmd, cwd: R(1))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert ta.main(["--fast"]) == 1
    out = capsys.readouterr().out
    assert "SUITE(S) FAILED" in out and "::error" not in out


def test_test_all_annotates_failures_on_github(load_module, monkeypatch, capsys):
    ta = load_module("scripts/test_all.py")

    class R:
        returncode, stdout, stderr = 1, "line 1\n50% done, a: b\n", ""

    monkeypatch.setattr(ta, "run", lambda cmd, cwd: R())
    monkeypatch.setattr(ta.shutil, "which", lambda name: None)
    langs = ta.discover()
    for lang in langs:
        monkeypatch.setattr(type(lang), "run", lambda self, cmd, **kw: R())
    monkeypatch.setattr(type(langs[0]), "missing_tool", lambda self, section: None)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert ta.main(["--fast"]) == 1
    errors = [l for l in capsys.readouterr().out.splitlines() if l.startswith("::error")]
    assert errors and all("%0A" in e for e in errors)                  # one line per annotation
    assert "::error title=Viewer tests failed::line 1%0A50%25 done, a: b" in errors


# ---- crosslang runner ----------------------------------------------------------------------------


def test_run_all_unknown_language(load_module, capsys):
    ra = load_module("tests/crosslang/run_all.py")
    assert ra.main(["--only", "cobol"]) == 2
    assert "unknown language" in capsys.readouterr().err


def test_run_all_nothing_to_test(load_module, monkeypatch, capsys):
    ra = load_module("tests/crosslang/run_all.py")
    for lang in ra.discover():
        monkeypatch.setattr(type(lang), "missing_tool", lambda self, section: "tool")
    assert ra.main([]) == 1
    assert "all skipped" in capsys.readouterr().err


def test_run_all_python_only(load_module, capsys):
    ra = load_module("tests/crosslang/run_all.py")
    assert ra.main(["--only", "python"]) == 0
    assert "ALL OK (1 languages" in capsys.readouterr().out
