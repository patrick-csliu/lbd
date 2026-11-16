"""Labels in the Library (library_labels.py, plan 8b): set on many files, shared by identical
copies, kept apart for copies in conflict, followed when files are renamed or moved outside LBD,
listed as missing otherwise; filters, search and the actions that change identities."""

import json
import os
import shutil
from pathlib import Path

import h5py
import pytest

import lbd
from lbd_viewer import labels, library_labels as ll
from lbd_viewer.library import LibraryIndex


def make(folder: Path, name: str, title: str = "t", created: str = "2026-10-29T10:00:00+08:00", ident: bool = True):
    folder.mkdir(parents=True, exist_ok=True)
    d = lbd.Dataset(title=title, created=created)
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [1.0, 2.0], axes="x")
    d.save(folder / name)
    if not ident:                                                    # as an older file
        with h5py.File(folder / name, "a") as f:
            del f.attrs["id"]
    return folder / name


@pytest.fixture()
def lib(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    make(a, "one.lbd", "One")
    make(a, "two.lbd", "Two", "2026-10-28T10:00:00+08:00")
    make(b, "three.lbd", "Three", "2026-10-27T10:00:00+08:00")
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a), str(b)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    ix.scan()
    return ix, a, b


def row(ix, name):
    return next(r for r in ix.list(limit=1000)["rows"] if r["name"] == name)


def test_labels_set_on_several_files_are_listed_filtered_and_searched(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd"), str(b / "three.lbd")],
                  {"star": True, "project": "Qubit A/Device 3", "add_tags": ["flux/bias"], "add_users": ["Lab/Patrick"],
                   "comment": "good one"})
    one = row(ix, "one.lbd")
    assert one["star"] and one["project"] == "Qubit A/Device 3" and one["tags"] == ["flux/bias"] and one["comment"] == "good one"
    assert ix.list(project="Qubit A")["total"] == 2                  # a parent includes its children
    assert ix.list(tags=["flux"])["total"] == 2 and ix.list(tags=["flu"])["total"] == 0
    assert ix.list(users=["Lab/Patrick", "nobody"])["total"] == 2     # OR within a box
    assert ix.list(starred=True, project="Qubit A/Device 3", tags=["flux/bias"])["total"] == 2   # AND across
    assert ix.list(q="good one")["total"] == 2                        # labels are searched
    f = ix.facets()
    assert f["starred"] == 2 and f["projects"][0]["label"] == "Qubit A" and f["projects"][0]["children"][0]["count"] == 2
    assert json.loads((a / labels.SIDECAR).read_text())["files"][0]["id"] == lbd.info(a / "one.lbd").id


def test_identical_copies_share_labels_and_conflicts_dont(lib, tmp_path):
    ix, a, b = lib
    shutil.copy2(a / "one.lbd", b / "one.lbd")                       # a backup in the other folder
    ix.scan()
    ll.set_labels(ix, [str(a / "one.lbd")], {"add_tags": ["shared"]})
    rows = [r for r in ix.list(limit=1000)["rows"] if r["name"] == "one.lbd"]
    assert [r["tags"] for r in rows] == [["shared"], ["shared"]]
    assert (b / labels.SIDECAR).exists()                              # written next to the copy too
    r = lbd.load(b / "one.lbd")
    r.description = "edited after copying"
    r.save(b / "one.lbd")                                             # now they differ: a conflict
    ix.scan()
    ll.set_labels(ix, [str(b / "one.lbd")], {"add_tags": ["only here"]})
    tags = {r["path"]: r["tags"] for r in ix.list(limit=1000)["rows"] if r["name"] == "one.lbd"}
    assert tags[str((a / "one.lbd").resolve())] == ["shared"]          # not synced while in conflict
    assert sorted(tags[str((b / "one.lbd").resolve())]) == ["only here", "shared"]


def test_resolving_a_conflict(lib):
    ix, a, b = lib
    shutil.copy2(a / "one.lbd", b / "one.lbd")
    r = lbd.load(b / "one.lbd")
    r.description = "changed"
    r.save(b / "one.lbd")
    ix.scan()
    assert row(ix, "one.lbd")["conflict"]
    ll.same_measurement(ix, str(b / "one.lbd"))                       # "they are the same measurement"
    assert not any(r["conflict"] for r in ix.list(limit=1000)["rows"])
    r.description = "changed again"
    r.save(b / "one.lbd")                                             # a new change: asked again
    ix.scan()
    assert any(r["conflict"] for r in ix.list(limit=1000)["rows"])
    old = lbd.info(b / "one.lbd").id
    ll.new_measurement(ix, str(b / "one.lbd"))                        # "make this a new measurement"
    info = lbd.info(b / "one.lbd")
    assert info.id != old and info.parent_id == old and lbd.info(a / "one.lbd").id == old
    assert not any(r["conflict"] for r in ix.list(limit=1000)["rows"])


def test_new_measurement_refuses_a_file_changed_meanwhile(lib):
    ix, a, b = lib
    d = lbd.load(a / "one.lbd")
    d.description = "changed after the list was read"
    d.save(a / "one.lbd")
    with pytest.raises(labels.LabelsError, match="changed since it was shown"):
        ll.new_measurement(ix, str(a / "one.lbd"))


def test_duplicate_as_new_measurement(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd")], {"star": True})
    before = (a / "one.lbd").read_bytes()
    path, _ = ll.duplicate(ix, str(a / "one.lbd"))
    assert Path(path).name == "one (copy).lbd" and (a / "one.lbd").read_bytes() == before   # original untouched
    copy = lbd.info(path)
    assert copy.parent_id == lbd.info(a / "one.lbd").id and copy.id != copy.parent_id
    assert row(ix, "one (copy).lbd")["star"]
    path2, _ = ll.duplicate(ix, str(a / "one.lbd"))
    assert Path(path2).name == "one (copy 2).lbd"                     # never replaces a file


def test_labels_follow_files_renamed_or_moved_outside_lbd(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd")], {"add_tags": ["moved with it"]})
    os.replace(a / "one.lbd", b / "renamed.lbd")                     # Explorer: rename and move
    ix.scan()
    assert row(ix, "renamed.lbd")["tags"] == ["moved with it"]
    assert json.loads((b / labels.SIDECAR).read_text())["files"][0]["name"] == "renamed.lbd"
    assert not (a / labels.SIDECAR).exists() or not json.loads((a / labels.SIDECAR).read_text())["files"]


def test_files_without_id_are_followed_then_listed_as_missing(tmp_path):
    a = tmp_path / "A"
    make(a, "old.lbd", "Old", ident=False)
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    ix.scan()
    ll.set_labels(ix, [str(a / "old.lbd")], {"add_tags": ["no id"]})
    os.replace(a / "old.lbd", a / "older.lbd")                       # same drive: the file system's id
    ix.scan()
    assert row(ix, "older.lbd")["tags"] == ["no id"]
    (a / "older.lbd").unlink()
    ix.scan()
    assert len(ix.missing) == 1 and ix.missing[0]["tags"] == ["no id"] and ix.facets()["missing"] == 1
    make(a, "found.lbd", "Elsewhere", "2020-01-01T00:00:00+00:00", ident=False)
    ix.scan()
    ll.resolve_missing(ix, ix.missing[0], str(a / "found.lbd"))      # pointed to a file
    assert row(ix, "found.lbd")["tags"] == ["no id"] and ix.missing == []


def test_a_file_that_lost_its_id_keeps_its_labels(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd")], {"add_tags": ["kept"]})
    with h5py.File(a / "one.lbd", "a") as f:                         # saved again by an older program
        del f.attrs["id"]
    ix.scan()
    assert row(ix, "one.lbd")["tags"] == ["kept"] and ix.missing == []


def test_give_ids_and_renames_and_trash_in_lbd(tmp_path):
    a = tmp_path / "A"
    make(a, "old.lbd", ident=False)
    ix = LibraryIndex(tmp_path / "db", lambda: [str(a)], lambda: True)
    ix.trash = lambda p: Path(p).unlink()
    ix.scan()
    ll.set_labels(ix, [str(a / "old.lbd")], {"star": True})
    ll.give_ids(ix, [str(a / "old.lbd")])
    ident = lbd.info(a / "old.lbd").id
    assert ident and json.loads((a / labels.SIDECAR).read_text())["files"][0]["id"] == ident
    os.replace(a / "old.lbd", a / "new.lbd")
    ll.renamed(ix, str(a / "old.lbd"), str(a / "new.lbd"))
    ix.scan()
    assert row(ix, "new.lbd")["star"]
    ll.trashed(ix, str(a / "new.lbd"), ident)
    assert not (a / labels.SIDECAR).exists()


def test_the_labels_api(client, data_dir, library_files):
    lib = client.app.state.lbd.library
    lib.trash = lambda p: Path(p).unlink()
    lib.scan()
    rows = client.get("/api/library/list", params={"q": "resonator", "limit": 3}).json()["rows"]
    paths = [r["path"] for r in rows]
    r = client.post("/api/library/labels", json={"paths": paths, "star": True, "add_tags": ["api/test"],
                                                 "project": "Qubit A", "add_users": ["Lab/Patrick"]})
    assert r.status_code == 200, r.text
    got = client.get("/api/library/list", params=[("tags", "api"), ("starred", "true"), ("limit", 10)]).json()
    assert got["total"] == 3 and all(x["star"] and x["tags"] == ["api/test"] for x in got["rows"])
    f = client.get("/api/library/facets").json()
    assert f["starred"] == 3 and f["tags"][0]["label"] == "api" and f["projects"][0]["count"] == 3
    assert client.post("/api/library/labels", json={"paths": [paths[0]], "project": ""}).status_code == 200
    assert client.get("/api/library/list", params={"project": "Qubit A"}).json()["total"] == 2   # "" removed it
    assert client.post("/api/library/labels", json={"paths": [paths[0]], "add_tags": ["a//b"]}).status_code == 409
    dup = client.post("/api/library/duplicate", json={"path": paths[1]}).json()
    assert dup["path"].endswith("(copy).lbd") and lbd.info(dup["path"]).parent_id == lbd.info(paths[1]).id
    assert client.get("/api/library/same", params={"path": paths[1]}).json()["others"] == []
    assert client.post("/api/library/resolve", json={"path": paths[1], "action": "nonsense"}).status_code == 400
    assert client.get("/api/library/missing").json() == {"missing": []}
    assert client.get("/api/state").json()["login"]


def tree_labels(nodes):
    out = []
    for n in nodes:
        out.append((n["label"], n["count"]))
        out += tree_labels(n["children"])
    return out


def test_a_label_kept_without_a_file_is_listed_with_none_and_survives_writes(lib):
    ix, a, b = lib
    ll.create_label(ix, "project", "Qubit C/Device 1", str(b))
    assert ("Qubit C/Device 1", 0) in tree_labels(ix.facets()["projects"])
    doc = json.loads((b / labels.SIDECAR).read_text())
    assert doc["labels"]["project"]["Qubit C/Device 1"][2] is True and doc["files"] == []   # kept with no file
    # another edit in that folder keeps it; so does a merge with a sync tool's copy
    ll.set_labels(ix, [str(b / "three.lbd")], {"add_tags": ["x"]})
    assert "Qubit C/Device 1" in labels.kept(labels.read(b))["project"]
    other = {"format": labels.FORMAT, "version": 1, "files": [], "future_key": {"kept": True},
             "labels": {"tags": {"later": [labels.now(), "LAPTOP", True]}}}
    merged = labels.merge_docs(labels.read(b), other)
    assert labels.kept(merged)["tags"] == ["later"] and "Qubit C/Device 1" in labels.kept(merged)["project"]
    assert merged["future_key"] == {"kept": True}                     # a newer writer's key isn't dropped
    with pytest.raises(labels.LabelsError):
        ll.create_label(ix, "colour", "red", str(b))


def test_a_label_is_renamed_moved_and_removed_on_every_file_with_its_children(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd"), str(b / "three.lbd")], {"add_tags": ["flux", "flux/bias"]})
    ll.set_labels(ix, [str(a / "two.lbd")], {"project": "Qubit A/Device 3"})
    ll.create_label(ix, "tags", "flux/new", str(a))
    # the dry run counts the files, and changes nothing
    assert ll.rename_label(ix, "tags", "flux", "flux bias", dry=True)["files"] == 2
    assert row(ix, "one.lbd")["tags"] == ["flux", "flux/bias"]
    r = ll.rename_label(ix, "tags", "flux", "flux bias")
    assert r["files"] == 2
    assert row(ix, "one.lbd")["tags"] == ["flux bias", "flux bias/bias"] and row(ix, "three.lbd")["tags"] == ["flux bias", "flux bias/bias"]
    assert ("flux bias/new", 0) in tree_labels(ix.facets()["tags"])   # a kept label follows too
    # move a project into another group
    ll.rename_label(ix, "project", "Qubit A/Device 3", "Qubit B/Device 3")
    assert row(ix, "two.lbd")["project"] == "Qubit B/Device 3"
    with pytest.raises(labels.LabelsError):                            # not inside itself
        ll.rename_label(ix, "project", "Qubit B", "Qubit B/Device 3/Qubit B")
    # remove a tag and the ones under it from every file
    assert ll.remove_label(ix, "tags", "flux bias", dry=True)["files"] == 2
    ll.remove_label(ix, "tags", "flux bias")
    assert row(ix, "one.lbd")["tags"] == [] and row(ix, "three.lbd")["tags"] == []
    assert not any(label.startswith("flux") for label, _ in tree_labels(ix.facets()["tags"]))


def test_what_removing_a_folder_changes(lib):
    ix, a, b = lib
    ll.set_labels(ix, [str(a / "one.lbd")], {"add_tags": ["only in A", "shared"]})
    ll.set_labels(ix, [str(b / "three.lbd")], {"add_tags": ["shared"], "project": "B project"})
    s = ix.folder_summary(str(a))
    assert s["files"] == 2 and s["labelled"] == 1
    assert s["labels_only_here"] == {"project": [], "users": [], "tags": ["only in A"]}
    assert ix.folder_summary(str(b))["labels_only_here"]["project"] == ["B project"]


def test_the_folder_summary_api(client, data_dir, library_files):
    lib = client.app.state.lbd.library
    lib.scan()
    s = client.get("/api/roots/summary", params={"path": str(data_dir)}).json()
    assert s["files"] == lib.facets()["total"] and s["labelled"] == 0 and s["pages"] == 0 and s["inside"] == []
    assert client.get("/api/roots/summary", params={"path": str(data_dir / "nowhere")}).status_code == 404
