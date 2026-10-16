"""Shared fixtures of the viewer tests: a data folder, an isolated config, an API client."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

import lbd
from lbd_viewer.config import Config
from lbd_viewer.server import AppState, create_app


@pytest.fixture()
def data_dir(tmp_path):
    root = tmp_path / "data"
    (root / "sub" / "deeper").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "@eaDir").mkdir()

    d = lbd.Dataset(title="curve")
    t = np.linspace(0, 1e-6, 50)
    d.add_axis("t", t, unit="s", label="Time")
    d.add_value("a", np.sin(1e7 * t), axes="t", unit="V")
    d.add_value("b", np.cos(1e7 * t), axes="t", unit="V")
    d.save(root / "curve.lbd")

    f = np.linspace(6.99e9, 7.01e9, 30)
    p = np.arange(-60, 1, 10.0)
    z = 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 1e6) * np.ones((len(p), 1))
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", p, unit="dBm", label="Power")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", z, axes=["power", "freq"])
    d.plot = {"kind": "heatmap", "complex": "db"}
    d.save(root / "sub" / "sweep.lbd")

    d = lbd.Dataset(title="cube")
    d.add_axis("a", [1.0, 2.0])
    d.add_axis("b", [1.0, 2.0, 3.0])
    d.add_axis("c", [1.0, 2.0, 3.0, 4.0])
    d.add_value("T", np.arange(24.0).reshape(2, 3, 4), axes=["a", "b", "c"], unit="K")
    d.add_value("q", 3.5)
    d.save(root / "sub" / "deeper" / "cube.lbd")
    (root / "sub" / "notes.txt").write_text("not data")
    return root


@pytest.fixture()
def cfg(tmp_path):
    return Config(tmp_path / "config")


@pytest.fixture()
def client(cfg, data_dir):
    state = AppState(cfg, token="t0k")
    c = TestClient(create_app(state), base_url="http://127.0.0.1:8000")
    c.headers["X-LBD-Token"] = "t0k"
    c.post("/api/roots", json={"path": str(data_dir)}).raise_for_status()
    return c
