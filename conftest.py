"""Shared pytest setup for every Python test suite of the repository.

- No test touches the real LBD settings: LBD_CONFIG_DIR points to a fresh temporary folder.
- matplotlib draws off-screen and every figure is closed after each test.
- `load_module` imports a script (scripts/, packaging/, examples/) by path, for testing it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolated_lbd_config(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("LBD_CONFIG_DIR", str(tmp_path_factory.mktemp("lbd-config")))
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


def pytest_configure(config):
    import matplotlib

    matplotlib.use("Agg")
