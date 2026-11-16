"""Editing a finished data file (plan 16.19, built in plan 17): in place or copy and swap, as
Settings says, for ids, Save view and labels; and label writes that don't count as a change."""

import os
import shutil
from collections import namedtuple
from pathlib import Path

import h5py
import numpy as np
import pytest

import lbd
from lbd.io import _apply_labels
from lbd_viewer import files, previews, versions
from lbd_viewer.files import DataEditError, edit_data_file
from lbd_viewer.server import file_version


def a_file(folder: Path, name="a.lbd") -> Path:
    d = lbd.Dataset("edits")
    d.add_axis("x", np.arange(1000.0))
    d.add_value("y", np.arange(1000.0), axes="x")
    return d.save(folder / name)


def set_attr(key, value):
    def change(f):
        f.attrs[key] = value
    return change


@pytest.mark.parametrize("method", files.EDIT_METHODS)
def test_both_ways_change_the_file_and_nothing_else(tmp_path, method):
    p = a_file(tmp_path)
    seen = []
    edit_data_file(p, set_attr("title", "edited"), method, progress=seen.append)
    d = lbd.load(p)
    assert d.title == "edited"
    np.testing.assert_array_equal(d["y"].data, np.arange(1000.0))
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.lbd"]          # no copy left behind
    assert (seen and seen[-1] == 1.0) if method == "copy_and_swap" else not seen


@pytest.mark.parametrize("method", files.EDIT_METHODS)
def test_a_failed_change_leaves_the_file_as_it_was_with_copy_and_swap(tmp_path, method):
    p = a_file(tmp_path)
    before = p.read_bytes()

    def broken(f):
        f.attrs["title"] = "half"
        raise RuntimeError("the change failed")
    with pytest.raises(RuntimeError):
        edit_data_file(p, broken, method)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.lbd"]
    if method == "copy_and_swap":
        assert p.read_bytes() == before                                     # the original never touched


def test_refusals_say_why(tmp_path, monkeypatch):
    p = a_file(tmp_path)
    with pytest.raises(DataEditError, match="changed since it was shown"):
        edit_data_file(p, set_attr("title", "x"), expect="0-0")
    with pytest.raises(DataEditError, match="being written"):
        edit_data_file(tmp_path / "b.lbd.writing", set_attr("title", "x"))
    with pytest.raises(DataEditError, match="unknown way"):
        edit_data_file(p, set_attr("title", "x"), "sideways")
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: Usage(10**9, 10**9, 1000))
    with pytest.raises(DataEditError, match="needs room for a copy") as e:
        edit_data_file(p, set_attr("title", "x"), "copy_and_swap")
    assert "in place" in str(e.value)
    assert lbd.info(p).title == "edits"
    edit_data_file(p, set_attr("title", "x"), "in_place")                # in place needs no room


def test_the_setting_is_used_by_save_view(client, data_dir, monkeypatch):
    used = []
    real = files.edit_data_file
    monkeypatch.setattr(files, "edit_data_file", lambda *a, **k: used.append(a[2]) or real(*a, **k))
    p = str(data_dir / "curve.lbd")
    client.put("/api/file/plot", json={"path": p, "style_name": "thesis"}).raise_for_status()
    client.put("/api/settings", json={"library": {"data_file_edits": "copy_and_swap"}}).raise_for_status()
    r = client.put("/api/file/plot", json={"path": p, "spec": {"kind": "curve"}})
    r.raise_for_status()
    assert used == ["in_place", "copy_and_swap"]
    assert lbd.info(p).style_name == "thesis" and lbd.info(p).plot == {"kind": "curve"}
    r = client.put("/api/settings", json={"library": {"data_file_edits": "sideways"}})
    assert r.status_code == 400 and "data_file_edits" in r.json()["detail"]


def test_a_label_write_by_lbd_is_not_a_change_of_the_file(client, data_dir):
    p = data_dir / "curve.lbd"
    shown = client.get("/api/file", params={"path": str(p)}).json()["version"]
    before = versions.raw(os.stat(p))
    edit_data_file(p, lambda f: _apply_labels(f, lbd.Labels(star=True), p))
    after = versions.raw(os.stat(p))
    assert before != after
    versions.label_written(p, before, after)
    assert file_version(p) == shown == previews.file_version(str(p))
    r = client.put("/api/file/plot", json={"path": str(p), "spec": {"kind": "curve"}, "if_version": shown})
    assert r.status_code == 200                                              # not "changed since you opened it"
    assert file_version(p) != shown                                          # a real change counts again
    with h5py.File(p, "r") as f:
        assert f["labels"].attrs["star"] == 1
