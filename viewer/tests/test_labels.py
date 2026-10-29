"""The labels sidecar (labels.py): edits recorded item by item, merged without losing anything,
never overwriting a change made meanwhile, conflict copies from sync tools merged and recycled,
a newer or damaged sidecar handled with a note."""

import json
import multiprocessing as mp
import os
import threading
from pathlib import Path

import pytest

from lbd_viewer import labels


def entry(doc, name="a.lbd"):
    return next(e for e in doc["files"] if e["name"] == name)


def add(folder, name="a.lbd", ident=None, **changes):
    def change(doc):
        e = labels.find(doc, ident, name)
        if e is None:
            e = labels.new_entry(ident, name, "2026-10-29T10:00:00+08:00")
            doc["files"].append(e)
        labels.apply(e, changes)
    return labels.update(folder, change)


def test_labels_are_written_read_and_removed(tmp_path):
    add(tmp_path, star=True, project="Qubit A / Device 3", add_tags=["flux/bias", "resonator"],
        add_users=["Lab A/Qubit team/Patrick"], comment="punch-out")
    e = entry(labels.read(tmp_path))
    assert e["star"] and e["project"] == "Qubit A/Device 3" and e["tags"] == ["flux/bias", "resonator"]
    assert e["changed"]["tags"]["resonator"][2] is True and e["changed"]["star"][1] == labels.computer()
    add(tmp_path, star=False, project=None, remove_tags=["flux/bias", "resonator"], remove_users=["Lab A/Qubit team/Patrick"],
        comment="")
    assert not (tmp_path / labels.SIDECAR).exists()                  # no labels left: no file
    with pytest.raises(labels.LabelsError, match="empty part"):
        add(tmp_path, add_tags=["a//b"])


def test_a_merge_keeps_both_computers_changes_and_removals():
    a = labels.new_entry("x", "a.lbd", None)
    b = labels.new_entry("x", "a.lbd", None)
    labels.apply(a, {"add_tags": ["t1", "t2"]}, "2026-01-01T00:00:00.000Z", "PC1")
    b = json.loads(json.dumps(a))                                     # both start the same
    labels.apply(a, {"remove_tags": ["t1"], "comment": "from PC1"}, "2026-01-02T00:00:00.000Z", "PC1")
    labels.apply(b, {"add_tags": ["t3"], "comment": "from PC2"}, "2026-01-03T00:00:00.000Z", "PC2")
    m = labels.merge(a, b)
    assert m["tags"] == ["t2", "t3"]                                  # t1 removed stays removed; t3 added kept
    assert m["comment"] == "from PC2"                                 # the newer comment
    assert {"field": "comment", "value": "from PC1", "changed": ["2026-01-02T00:00:00.000Z", "PC1"]} in m["history"]
    assert labels.merge(b, a)["tags"] == m["tags"]                    # the same either way


def test_a_tie_keeps_one_value_with_a_note_and_the_other_in_history():
    a, b = labels.new_entry("x", "a.lbd", None), labels.new_entry("x", "a.lbd", None)
    labels.apply(a, {"project": "P1"}, "2026-01-01T00:00:00.000Z", "PC1")
    labels.apply(b, {"project": "P2"}, "2026-01-01T00:00:00.000Z", "PC2")
    notes = []
    m = labels.merge(a, b, notes)
    assert m["project"] == "P1" and any(h["value"] == "P2" for h in m["history"]) and "same moment" in notes[0]


def test_a_change_made_meanwhile_is_merged_not_overwritten(tmp_path):
    add(tmp_path, add_tags=["base"])
    def slow_change(doc):
        # another computer's change arrives through sync while this one works
        other = labels.read(tmp_path)
        labels.apply(entry(other), {"add_tags": ["synced in"]})
        (tmp_path / labels.SIDECAR).write_text(json.dumps(other), encoding="utf-8")
        labels.apply(entry(doc), {"add_tags": ["mine"]})
    labels.update(tmp_path, slow_change)
    assert entry(labels.read(tmp_path))["tags"] == ["base", "mine", "synced in"]


def test_writers_at_the_same_time_lose_nothing(tmp_path):
    def worker(k):
        add(tmp_path, add_tags=[f"t{k}"])
    threads = [threading.Thread(target=worker, args=(k,)) for k in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert entry(labels.read(tmp_path))["tags"] == sorted((f"t{k}" for k in range(12)), key=str.lower)


def _tag_in_process(args):
    folder, k = args
    add(Path(folder), add_tags=[f"p{k}"])


def test_two_programs_at_the_same_time_lose_nothing(tmp_path):
    with mp.get_context("spawn").Pool(4) as pool:
        pool.map(_tag_in_process, [(str(tmp_path), k) for k in range(8)])
    assert set(entry(labels.read(tmp_path))["tags"]) == {f"p{k}" for k in range(8)}
    assert not (tmp_path / labels.LOCK).exists()


def test_sync_conflict_copies_are_merged_then_recycled(tmp_path):
    add(tmp_path, add_tags=["here"])
    other = labels.read(tmp_path)
    labels.apply(entry(other), {"add_tags": ["there"], "star": True}, "2099-01-01T00:00:00.000Z", "PC2")
    copy = tmp_path / ".lbd-library_PC2_Oct-29-140513-2026_Conflict.json"
    copy.write_text(json.dumps(other), encoding="utf-8")
    recycled = []
    notes = labels.update(tmp_path, lambda doc: None, trash=lambda p: (recycled.append(p.name), p.unlink()))
    e = entry(labels.read(tmp_path))
    assert e["tags"] == ["here", "there"] and e["star"]
    assert recycled == [copy.name] and any("merged" in n for n in notes)


def test_a_newer_sidecar_is_read_only_and_a_damaged_one_set_aside(tmp_path):
    (tmp_path / labels.SIDECAR).write_text(json.dumps({"format": "lbd-library", "version": 99, "files": []}))
    notes = []
    assert labels.read(tmp_path, notes)["read_only"] and "newer LBD" in notes[0]
    with pytest.raises(labels.LabelsError, match="newer LBD"):
        add(tmp_path, star=True)
    (tmp_path / labels.SIDECAR).write_text("{ not json")
    notes = add(tmp_path, star=True)
    assert entry(labels.read(tmp_path))["star"] and any("couldn't be read" in n for n in notes)
    assert list(tmp_path.glob(".lbd-library.broken-*.json"))


def test_a_lock_left_behind_is_taken_over(tmp_path):
    lock = tmp_path / labels.LOCK
    lock.write_text("crashed")
    old = os.path.getmtime(lock) - 60
    os.utime(lock, (old, old))
    add(tmp_path, star=True)
    assert entry(labels.read(tmp_path))["star"]
