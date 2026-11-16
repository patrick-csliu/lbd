"""Labels in the data file (plan 17, spec §1.9): star, project, users, tags, comment, and when
they were set; on a Dataset, on the Writer, and on existing files with lbd.set_labels."""

import json
import time

import h5py
import numpy as np
import pytest

import lbd
from lbd import LBDError, LBDWarning


def small(groups=False):
    d = lbd.Dataset("labels")
    if groups:
        d.add_group("AB")
        d.add_axis("A", group="AB")
        d.add_axis("B", group="AB")
        d.add_value("f", axes=["A", "B"])
        d.write(A=1.0, B=2.0, f=3.0)
    else:
        d.add_axis("x", np.arange(3.0))
        d.add_value("y", np.arange(3.0), axes=["x"])
    return d


def test_labels_are_written_and_read_back(tmp_path):
    d = small()
    assert not d.labels and d.labels.written is None
    d.labels.star = True
    d.labels.project = " Chip 3 / Cooldown 7 "
    d.labels.users.add("Ana")
    d.add_tags("calibration", "b")
    d.labels.comment = "first try"
    p = d.save(tmp_path / "a.lbd")
    e = lbd.load(p)
    assert e.lbd_version == "1.3"
    assert e.labels == {"star": True, "project": "Chip 3/Cooldown 7", "users": ["Ana"],
                        "tags": ["b", "calibration"], "comment": "first try"}
    assert e.labels.written == d.labels.written
    with h5py.File(p) as f:
        g = f["labels"]
        assert g.attrs["star"] == 1 and json.loads(g.attrs["tags"]) == ["b", "calibration"]
        assert g.attrs["written"].endswith("Z")


def test_the_version_is_the_lowest_that_holds_the_content(tmp_path):
    assert lbd.load(small().save(tmp_path / "a.lbd")).lbd_version == "1.2"
    assert lbd.load(small(groups=True).save(tmp_path / "b.lbd")).lbd_version == "2.0"
    d = small(groups=True)
    d.labels = {"tags": ["x"]}
    assert lbd.load(d.save(tmp_path / "c.lbd")).lbd_version == "2.1"


def test_each_label_is_checked_at_once():
    d = small()
    with pytest.raises(TypeError, match="True or False"):
        d.labels.star = "yes"
    with pytest.raises(TypeError, match="list of labels"):
        d.labels.tags = "calibration"
    with pytest.raises(LBDError, match="empty part"):
        d.add_tags("a//b")
    with pytest.raises(TypeError, match="must be text"):
        d.labels.users.add(3)
    with pytest.raises(TypeError, match="comment must be text"):
        d.labels.comment = None
    with pytest.raises(LBDError, match="unknown key"):
        d.labels = {"stars": True}
    with pytest.raises(TypeError, match="must be a dict"):
        d.labels = ["x"]
    assert not d.labels                            # nothing half-set


def test_labels_are_kept_by_load_and_save_and_by_a_copy(tmp_path):
    d = small()
    d.labels = {"tags": ["kept"], "star": True}
    p = d.save(tmp_path / "a.lbd")
    e = lbd.load(p)
    e.title = "again"
    e.save(p)
    assert lbd.labels(p).tags == ["kept"]
    first_id = e.id
    q = e.save(tmp_path / "copy.lbd")             # another file: a new id, the same labels
    c = lbd.load(q)
    assert c.parent_id == first_id and c.labels == e.labels and c.labels.written == d.labels.written
    with lbd.open(p, mode="r+") as o:             # saved in place
        o.labels.users.add("Ana")
        o.save()
    assert lbd.labels(p).users == ["Ana"] and lbd.info(p).lbd_version == "1.3"


def test_labels_removed_on_purpose_are_written_empty(tmp_path):
    d = small()
    d.labels = None                               # removed now: the time counts (newer than an old copy)
    p = d.save(tmp_path / "a.lbd")
    got = lbd.labels(p)
    assert got is not None and not got and got.written is not None


def test_set_labels_adds_or_replaces_and_raises_the_version(tmp_path):
    p = small().save(tmp_path / "a.lbd")
    assert lbd.labels(p) is None
    data = lbd.load(p).values["y"].data.copy()
    got = lbd.set_labels(p, tags=["a"], users=["Ana"], star=True)
    assert got.tags == ["a"] and lbd.info(p).lbd_version == "1.3"
    first = got.written
    time.sleep(0.01)
    lbd.set_labels(p, tags=["b"])                 # added
    assert lbd.labels(p).tags == ["a", "b"] and lbd.labels(p).written > first
    lbd.set_labels(p, tags=["c"], replace=True)   # replaced
    assert lbd.labels(p).tags == ["c"] and lbd.labels(p).users == ["Ana"]
    lbd.set_labels(p, project="P", comment="note")
    lbd.set_labels(p, project=None)
    got = lbd.remove_labels(p, tags=["c", "not there"], users=["Ana"])
    assert got == {"star": True, "project": None, "users": [], "tags": [], "comment": "note"}
    np.testing.assert_array_equal(lbd.load(p).values["y"].data, data)   # the data untouched

    g = small(groups=True).save(tmp_path / "g.lbd")
    lbd.set_labels(g, star=True)
    assert lbd.info(g).lbd_version == "2.1"


def test_set_labels_refuses_with_a_reason(tmp_path):
    p = small().save(tmp_path / "a.lbd")
    with pytest.raises(TypeError, match="at least one"):
        lbd.set_labels(p)
    with pytest.raises(LBDError, match="empty part"):
        lbd.set_labels(p, tags=["/"])
    assert lbd.labels(p) is None                  # checked before the file was opened
    with pytest.raises(LBDError, match="still being written"):
        lbd.set_labels(tmp_path / "b.lbd.writing", star=True)
    with pytest.raises(FileNotFoundError):
        lbd.set_labels(tmp_path / "missing.lbd", star=True)


def test_a_bad_label_in_a_file_is_left_out_with_a_warning(tmp_path):
    p = small().save(tmp_path / "a.lbd")
    lbd.set_labels(p, tags=["a"], star=True, comment="kept")
    with h5py.File(p, "r+") as f:
        f["labels"].attrs["tags"] = "not json"
        f["labels"].attrs["star"] = 7
    with pytest.warns(LBDWarning) as rec:
        got = lbd.labels(p)
    assert len(rec) == 2 and "'tags'" in str(rec[0].message) + str(rec[1].message)
    assert got.comment == "kept" and not got.star and not got.tags


def test_writer_labels_before_and_after_the_start(tmp_path):
    with lbd.Writer(tmp_path / "w.lbd", title="w") as w:
        w.add_axis("x", np.arange(3.0))
        w.add_value("y", axes=["x"])
        w.labels.star = True
        set_at = w.labels.written
        w.start()
        with h5py.File(w.writing_path, "r", locking=False, swmr=True, libver="latest") as f:
            assert f["labels"].attrs["star"] == 1     # in the file from the start
        for i in range(3):
            w.write(x=i, y=float(i))
        time.sleep(0.02)
        w.add_tags("while measuring")
        tag_at = w.labels.written
    got = lbd.load(w.path)
    assert got.lbd_version == "1.3" and got.labels.star and got.labels.tags == ["while measuring"]
    assert set_at < tag_at == got.labels.written  # the time they were set, not the finish
