"""Shared pytest setup for every Python test suite of the repository.

- No test touches the real LBD settings or "running viewer" record: LBD_CONFIG_DIR and
  LBD_RUNTIME_DIR point to fresh temporary folders.
- matplotlib draws off-screen and every figure is closed after each test.
- `load_module` imports a script (scripts/, packaging/, examples/) by path, for testing it.
- `example_files` is a folder with the example files, made once per session.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolated_lbd_config(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path_factory.mktemp("lbd-config")))
    monkeypatch.setenv("LBD_RUNTIME_DIR", str(tmp_path_factory.mktemp("lbd-runtime")))
    yield
    if "matplotlib.pyplot" in sys.modules:
        sys.modules["matplotlib.pyplot"].close("all")


def _load(rel: str):
    """Import a script by path under its own name (scripts import their siblings by name)."""
    path = REPO / rel
    for folder in (REPO / "scripts", REPO / "packaging", path.parent):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    name = path.stem
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # dataclasses and sibling imports need it registered
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def load_module():
    """load_module("scripts/languages.py") -> the module, imported once under its own name."""
    return _load


@pytest.fixture(scope="session")
def example_files(tmp_path_factory):
    """The example files (examples/make_examples.py: rabi.lbd, temperature_map.lbd, …), written once
    per test session into a temporary folder: they aren't kept in the repository. Read them, or
    copy them before changing one."""
    return _load("examples/make_examples.py").ensure_examples(tmp_path_factory.mktemp("lbd-examples") / "examples")


def pytest_configure(config):
    import matplotlib

    matplotlib.use("Agg")
