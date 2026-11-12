"""How the Library notices new files (library_watch.py, plan 16, 16.20): the system's
notifications, a slow full check as the safety net, timed checks for network drives and for
folders whose notifications fail, and checking only some folders (`scan(folders=...)`)."""

import shutil
import time

import pytest

import lbd
from lbd_viewer import library_watch
from lbd_viewer.library import LibraryIndex


def _small_file(path, title):
    d = lbd.Dataset(title=title, created="2026-10-29T10:00:00+08:00")
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [3.0, 4.0], axes="x")
    d.save(path)


def _wait_for(condition, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@pytest.fixture()
def folder(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    _small_file(root / "first.lbd", "First")
    return root


@pytest.fixture()
def running(tmp_path, folder):
    """An index of `folder`, kept up to date in the background; stopped after the test."""
    made = []

    def start(prepare=lambda ix: None):
        ix = LibraryIndex(tmp_path / "db", lambda: [str(folder)], lambda: True)
        prepare(ix)
        made.append(ix)
        ix.start()
        assert _wait_for(lambda: ix.status["scans"] >= 1, 10), "the first full check didn't finish"
        return ix

    yield start
    for ix in made:
        ix.close()


def _listed(ix, title):
    return ix.list(q=title)["total"] == 1


def test_a_new_file_appears_by_notification_within_3_s(running, folder, monkeypatch):
    monkeypatch.setattr(library_watch, "FULL_EVERY", 3600.0)      # no full check meanwhile
    ix = running()
    assert ix.status["watching"] == [{"path": str(folder.resolve()), "how": "notifications", "every": None, "reason": ""}]
    t0 = time.monotonic()
    _small_file(folder / "sub" / "new.lbd", "Noticed")
    assert _wait_for(lambda: _listed(ix, "Noticed"), 3), "the new file wasn't noticed within 3 s"
    print(f"\nnoticed after {time.monotonic() - t0:.2f} s")
    scans = ix.status["scans"]
    shutil.rmtree(folder / "sub")                                    # a folder removed: its files go
    assert _wait_for(lambda: not _listed(ix, "Noticed"), 3)
    assert ix.status["scans"] > scans and _listed(ix, "First")


def test_a_failing_observer_falls_back_to_timed_checks(running, folder, monkeypatch):
    monkeypatch.setattr(library_watch, "FULL_EVERY", 3600.0)
    monkeypatch.setattr(library_watch, "FALLBACK_EVERY", 0.5)

    def broken():
        raise OSError("no notifications on this drive")

    ix = running(lambda ix: setattr(ix.watcher, "make_observer", broken))
    [watch] = ix.status["watching"]
    assert watch["how"] == "timed" and watch["every"] == 0.5
    assert "notifications couldn't start: no notifications on this drive" in watch["reason"]
    _small_file(folder / "timed.lbd", "Timed")
    assert _wait_for(lambda: _listed(ix, "Timed"), 3)


def test_an_observer_that_stops_falls_back_to_timed_checks(running, folder, monkeypatch):
    monkeypatch.setattr(library_watch, "FULL_EVERY", 3600.0)
    monkeypatch.setattr(library_watch, "FALLBACK_EVERY", 0.5)
    monkeypatch.setattr(library_watch, "LOOK_EVERY", 0.2)
    ix = running()
    [watch] = ix.watcher._watches.values()
    watch.observer.stop()                                            # as when the system ends it
    watch.observer.join(timeout=5)
    _small_file(folder / "later.lbd", "Later")
    assert _wait_for(lambda: _listed(ix, "Later"), 3)
    assert ix.status["watching"][0]["how"] == "timed" and ix.status["watching"][0]["reason"] == "notifications stopped"


def test_the_full_check_finds_a_file_whose_notice_was_lost(running, folder, monkeypatch):
    monkeypatch.setattr(library_watch, "FULL_EVERY", 2.0)
    lost = []

    def drop(path):
        lost.append(path)
        return False

    ix = running(lambda ix: setattr(ix.watcher, "accept", drop))
    _small_file(folder / "lost.lbd", "Lost notice")
    assert _wait_for(lambda: _listed(ix, "Lost notice"), 5), "the full check didn't find it"
    assert lost, "the notice wasn't suppressed: the test proves nothing"


def test_a_network_drive_gets_timed_checks_only(running, folder, monkeypatch):
    monkeypatch.setattr(library_watch, "on_network_drive", lambda path: True)

    def no_observer():
        raise AssertionError("a network drive gets no observer")

    ix = running(lambda ix: setattr(ix.watcher, "make_observer", no_observer))
    [watch] = ix.status["watching"]
    assert watch["how"] == "timed" and watch["every"] == library_watch.NETWORK_EVERY == 60.0
    assert "network drive" in watch["reason"]


def test_this_computer_s_folders_are_not_network_drives(tmp_path):
    assert library_watch.on_network_drive(str(tmp_path)) is False


def test_a_scan_of_some_folders_looks_only_at_them(tmp_path, folder):
    other = folder / "other"
    other.mkdir()
    ix = LibraryIndex(tmp_path / "db", lambda: [str(folder)], lambda: True)
    ix.scan()
    _small_file(folder / "sub" / "a.lbd", "In sub")
    _small_file(other / "b.lbd", "In other")
    found = ix.scan(folders={str(folder.resolve() / "sub"): False})
    assert found.new == [str(folder.resolve() / "sub" / "a.lbd")] and found.gone == []
    assert _listed(ix, "In sub") and not _listed(ix, "In other")
    # a folder alone: not what is in its subfolders, nor files elsewhere gone
    assert not ix.scan(folders={str(folder.resolve()): False}).new
    assert ix.scan(folders={str(folder.resolve()): True}).new == [str(other.resolve() / "b.lbd")]
    shutil.rmtree(other)                                             # removed: its files are gone
    gone = ix.scan(folders={str(other.resolve()): True})
    assert gone.gone == [str(other.resolve() / "b.lbd")] and gone.errors == []
    assert _listed(ix, "In sub") and _listed(ix, "First")
