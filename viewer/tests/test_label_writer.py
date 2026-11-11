"""Labels written into the data files (plan 17, label_writer.py): about 2 s after the last edit,
only by the computer that made it, never into a file being written; files that can't be written
now are tried again; labels a script wrote into a file win when they are newer."""

import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

import lbd
from lbd_viewer import labels, library_labels as ll
from lbd_viewer.label_writer import RETRY_AFTER, WRITE_AFTER, LabelWriter
from lbd_viewer.library import LibraryIndex


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def wait(self, seconds):
        self.t += seconds


def make(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    d = lbd.Dataset(title=name)
    d.add_axis("x", np.arange(100.0))
    d.add_value("y", np.arange(100.0), axes="x")
    return d.save(folder / name)


@pytest.fixture()
def setup(tmp_path):
    a = tmp_path / "A"
    one, two = make(a, "one.lbd"), make(a, "two.lbd")
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    ix.scan()
    clock = Clock()
    writer = LabelWriter(ix, lambda: ix.edit_method(), clock=clock)
    ix.after_apply.append(writer.check)
    return ix, writer, clock, str(one.resolve()), str(two.resolve())


def entry_time(ix, path):
    folder = Path(path).parent
    e = labels.find(labels.read(folder, []), lbd.info(path).id, Path(path).name)
    return labels.last_change(e)[0]


def row(ix, path):
    return next(r for r in ix.list(limit=1000)["rows"] if r["path"] == path)


def test_edits_are_written_once_about_two_seconds_after_the_last(setup):
    ix, w, clock, one, _ = setup
    ll.set_labels(ix, [one], {"star": True})
    clock.wait(1.0)
    ll.set_labels(ix, [one], {"add_tags": ["calibration"]})
    clock.wait(WRITE_AFTER - 0.5)
    assert w.run_due() == 0 and lbd.labels(one) is None    # the second edit made it wait again
    assert w.pending(one)
    clock.wait(1.0)
    assert w.run_due() == 1
    got = lbd.labels(one)
    assert got.star and got.tags == ["calibration"]
    assert got.written == entry_time(ix, one)               # the time of the edit, not of the write
    assert lbd.info(one).lbd_version == "1.3"
    ix.scan()
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 0                                 # up to date: nothing written again


def test_only_the_computer_that_made_the_edit_writes(setup):
    ix, w, clock, one, _ = setup
    w.host = lambda: "ANOTHER-PC"
    ll.set_labels(ix, [one], {"star": True})
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 0 and lbd.labels(one) is None


def test_labels_set_before_plan_17_are_written_in_once(tmp_path):
    a = tmp_path / "A"
    one = str(make(a, "one.lbd").resolve())
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    ix.scan()
    ll.set_labels(ix, [one], {"add_tags": ["old"]})          # no writer yet: only in the label file
    clock = Clock()
    w = LabelWriter(ix, lambda: "in_place", clock=clock)
    ix.after_apply.append(w.check)
    ix.scan()
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 1 and lbd.labels(one).tags == ["old"]


def test_a_file_that_cant_be_written_now_is_tried_again(setup):
    ix, w, clock, one, _ = setup
    ll.set_labels(ix, [one], {"star": True})
    clock.wait(WRITE_AFTER + 1)
    with h5py.File(one, "r"):                                # open elsewhere (HDF5 refuses a second opening)
        assert w.run_due() == 0
    assert one in w.problems and lbd.labels(one) is None
    w.check()                                                # (its thread checks every few seconds)
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 0                                  # not before RETRY_AFTER
    clock.wait(RETRY_AFTER)
    w.check()
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 1 and lbd.labels(one).star and one not in w.problems


def test_everything_waiting_is_written_when_the_viewer_closes(setup):
    ix, w, clock, one, two = setup
    ll.set_labels(ix, [one, two], {"comment": "before closing"})
    w.close()
    assert lbd.labels(one).comment == lbd.labels(two).comment == "before closing"


def test_copy_and_swap_writes_the_same(setup):
    ix, w, clock, one, _ = setup
    ix.edit_method = lambda: "copy_and_swap"
    ll.set_labels(ix, [one], {"add_users": ["Ana"]})
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 1 and lbd.labels(one).users == ["Ana"]


def test_a_scripts_newer_labels_win_and_a_newer_removal_wins_over_the_file(setup):
    ix, w, clock, one, two = setup
    lbd.set_labels(one, tags=["from a script"], star=True)    # no viewer involved
    ix.scan()
    r = row(ix, one)
    assert r["star"] and r["tags"] == ["from a script"]
    assert "from a script" in labels.find(labels.read(Path(one).parent, []), lbd.info(one).id, "one.lbd")["tags"]
    assert w.run_due(everything=True) == 0                     # the file already has them

    w.host = lambda: "ANOTHER-PC"                               # the file keeps its star: not written here
    ll.set_labels(ix, [one], {"star": False})                   # newer than the file's labels
    ix.scan()
    assert not row(ix, one)["star"] and lbd.labels(one).star


def test_a_file_with_labels_and_no_entry_is_listed_with_them(setup):
    ix, w, clock, _, two = setup
    lbd.set_labels(two, project="P", users=["Bo"])
    ix.scan()
    r = row(ix, two)
    assert r["project"] == "P" and r["users"] == ["Bo"]


def test_a_label_write_doesnt_make_copies_differ(setup, tmp_path):
    ix, w, clock, one, _ = setup
    shutil.copy(one, Path(one).parent / "one copy.lbd")
    ix.scan()
    assert row(ix, one)["copies"] == 1
    ll.set_labels(ix, [one], {"star": True})
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 2                                   # the copy shares the labels: both written
    ix.scan()
    r = row(ix, one)
    assert r["copies"] == 1 and not r["conflict"]
    lbd.set_labels(Path(one).parent / "one copy.lbd", comment="only this one")   # labels differ, data doesn't
    ix.scan()
    assert not row(ix, one)["conflict"]


def test_a_file_being_written_gets_its_labels_when_finished(tmp_path):
    a = tmp_path / "A"
    a.mkdir()
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    clock = Clock()
    w = LabelWriter(ix, lambda: "in_place", clock=clock)
    ix.after_apply.append(w.check)
    wr = lbd.Writer(a / "live.lbd")
    wr.add_axis("x", np.arange(3.0))
    wr.add_value("y", axes=["x"])
    wr.labels.tags = ["from the script"]
    wr.write(x=0, y=1.0)
    ix.scan()
    writing = str(wr.writing_path.resolve())
    ll.set_labels(ix, [writing], {"star": True})              # an edit while it is measuring
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 0                                    # never into a file being written
    wr.write(x=1, y=2.0)
    wr.write(x=2, y=3.0)
    done = str(wr.close().resolve())
    ix.scan()
    clock.wait(WRITE_AFTER + 1)
    assert w.run_due() == 1
    got = lbd.labels(done)
    assert got.star                                            # the Library's edit is newer than the script's
