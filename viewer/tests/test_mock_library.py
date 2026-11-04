"""The mock library (mock_library.py) has the files and special cases the Library's tests rely on."""

from datetime import datetime

import pytest

import lbd
import mock_library


def test_the_mock_library(tmp_path):
    written = mock_library.write_library(tmp_path, 60)
    assert sum(len(v) for v in written.values()) == 60
    assert sorted(p.relative_to(tmp_path).as_posix() for v in written.values() for p in v) == \
        sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.lbd"))
    late = lbd.info(tmp_path / mock_library.SPECIAL["midnight"])
    assert late.created == "2026-03-14T23:30:00+08:00"
    assert lbd.info(tmp_path / mock_library.SPECIAL["untitled"]).title == ""
    assert all(len(v.shape) == 0 for v in lbd.info(tmp_path / mock_library.SPECIAL["numbers"]).values.values())
    with pytest.raises(OSError):
        lbd.info(tmp_path / mock_library.SPECIAL["broken"])
    # dated folders hold files created on that day, in the file's own time zone
    for p in written["Lab data"][:20]:
        created = datetime.fromisoformat(lbd.info(p).created)
        assert p.parent.relative_to(tmp_path / "Lab data").as_posix() == created.strftime("%Y/%m/%d")


def test_the_mock_library_with_labels(tmp_path):
    from lbd_viewer import labels

    mock_library.write_library(tmp_path, 60)
    special = mock_library.add_labels(tmp_path)
    sidecars = list(tmp_path.rglob(labels.SIDECAR))
    assert sidecars and any(e["tags"] for s in sidecars for e in labels.read(s.parent)["files"])
    ids = [lbd.info(p).id for p in tmp_path.rglob("*.lbd") if "broken" not in p.name]
    assert ids.count(lbd.info(special["copy"]).id) == 2                 # the copy and its original
    assert ids.count(lbd.info(special["conflict"]).id) == 2              # changed after copying
    assert not special["missing"].exists() and lbd.info(special["no_id"]).id is None
    assert list(tmp_path.rglob(".lbd-library_LAPTOP_*_Conflict.json"))


def test_many_labels_make_long_lists():
    import mock_library

    v = mock_library.many_labels()
    assert len(v["users"]) == 300 and len(v["tags"]) >= 800 and len(v["project"]) > 50
    assert any(t.count("/") == 3 for t in v["tags"])                              # nested 4 deep
    assert any(len(t) > 80 for t in v["tags"]) and any(len(p) > 80 for p in v["project"])
    assert v == mock_library.many_labels()                                         # the same every time
