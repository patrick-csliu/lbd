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
