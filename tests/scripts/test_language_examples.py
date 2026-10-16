"""Each language's example file (shown on the viewer's Language modules page) must run as is."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _run(cmd, cwd, extra_env=None):
    env = dict(os.environ, MPLBACKEND="Agg", **(extra_env or {}))
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=600)


def test_python_example(tmp_path):
    shutil.copy(REPO / "languages/python/example.py", tmp_path)
    r = _run([sys.executable, "-W", "error::UserWarning", "example.py"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert {"example.lbd", "example_heatmap.pdf", "example_trace.pdf"} <= {p.name for p in tmp_path.iterdir()}


@pytest.mark.skipif(shutil.which("julia") is None, reason="julia not on PATH")
def test_julia_example(tmp_path):
    shutil.copy(REPO / "languages/julia/example.jl", tmp_path)
    r = _run(["julia", f"--project={REPO / 'languages/julia'}", "--startup-file=no", "example.jl"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "example.lbd").exists()


@pytest.mark.skipif(shutil.which("matlab") is None, reason="matlab not on PATH")
def test_matlab_example(tmp_path):
    shutil.copy(REPO / "languages/matlab/example.m", tmp_path)
    lang = str(REPO / "languages/matlab").replace("'", "''")
    r = _run(["matlab", "-batch", f"addpath('{lang}'); example"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "example.lbd").exists()
