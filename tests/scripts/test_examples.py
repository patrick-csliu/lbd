"""The documentation examples (examples/python): each runs cleanly, and the docs pages match them."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import make_gallery  # noqa: E402

pytest.importorskip("matplotlib")


@pytest.mark.parametrize("name", make_gallery.ORDER)
def test_example_runs_cleanly(name, tmp_path):
    """Runs like a user would (in an empty folder), with every LBD warning as an error."""
    script = make_gallery.EXAMPLES / f"{name}.py"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "LBD_CONFIG_DIR": str(tmp_path / "config"),
           "MPLBACKEND": "Agg"}
    r = subprocess.run([sys.executable, "-c", make_gallery.RUNNER, str(script)], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / f"{name}.png").is_file(), f"{name}.py must save {name}.png"


def test_docs_pages_match_the_examples():
    assert make_gallery.check(make_gallery.examples()) == [], \
        "the Examples pages are out of date: run `uv run python scripts/make_gallery.py`"


def test_every_example_has_a_complete_docstring():
    for e in make_gallery.examples():
        assert e.title and e.text and e.figure and e.code and e.tasks and e.uses and e.explanation.is_file()
        assert e.code_lines[0] > 1                       # the shown code starts after the docstring
