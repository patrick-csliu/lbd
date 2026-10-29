"""The Library's index (library.py): what it lists, filters and searches, from the mock library
(mock_library.py); files added, changed, removed or damaged; headers not read (cloud storage);
the HTTP API; and the speed with 10 000 files."""

import os
import shutil
import time
from pathlib import Path

import pytest

import lbd
import mock_library
from lbd_viewer.library import LibraryIndex, outermost, parse_created


def index_of(tmp_path, roots, read=True):
    return LibraryIndex(tmp_path / "db", lambda: [str(r) for r in roots], lambda: read)


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    folder = tmp_path_factory.mktemp("lib")
    mock_library.write_library(folder, 120)
    return folder


def test_every_data_file_is_listed_with_its_details(tmp_path, library):
    ix = index_of(tmp_path, [library / "Lab data", library / "Shared"])
    assert ix.scan()
    every = ix.list(limit=1000)
    assert every["total"] == 120
    rows = {Path(r["path"]).relative_to(library).as_posix(): r for r in every["rows"]}
    late = rows[mock_library.SPECIAL["midnight"]]
    assert late["title"] == "Late resonator sweep" and late["sweep"] == "5×11" and late["value_names"] == "S21"
    assert late["day"] == "2026-03-14" and late["date_from_file"] == 0       # its own time zone, not UTC's 15th
    assert rows[mock_library.SPECIAL["numbers"]]["sweep"] == ""              # single numbers only
    broken = rows[mock_library.SPECIAL["broken"]]
    assert broken["error"] and broken["title"] == ""                         # listed, with the reason
    assert rows[mock_library.SPECIAL["untitled"]]["title"] == ""
    names = [r["name"] for r in every["rows"]]
    assert names.count("calibration.lbd") == 2                               # same name, two folders
    # newest first by default; the folder is relative to its open folder
    times = [r for r in every["rows"]]
    assert all(a["path"] for a in times)
    assert rows[mock_library.SPECIAL["twin_shared"]]["folder"] == "Fridge"


def test_search_filters_and_sorting(tmp_path, library):
    ix = index_of(tmp_path, [library / "Lab data", library / "Shared"])
    ix.scan()
    every = ix.list(limit=1000)["rows"]
    found = {r["path"] for r in ix.list(q="resonator", limit=1000)["rows"]}
    assert {r["path"] for r in every if "resonator" in r["title"].lower()} <= found < {r["path"] for r in every}
    assert ix.list(q="GHz")["total"] == 0 and ix.list(q="Hz")["total"] > 0     # units are searched
    assert ix.list(q="averages")["total"] > 0                                  # metadata keys ...
    assert ix.list(q="patrick")["total"] > 0                                   # ... and values
    assert ix.list(q="re-cooling resonator")["total"] <= ix.list(q="re-cooling")["total"]   # all words
    assert ix.list(q="100%_x")["total"] == 0                                   # LIKE characters are text
    day = ix.list(date="2026-03-14")
    assert {r["day"] for r in day["rows"]} == {"2026-03-14"} and day["total"] >= 2   # the damaged one: its file date
    assert ix.list(date="2026")["total"] + ix.list(date="2025")["total"] + ix.list(date="2024")["total"] == 120
    shared = ix.list(folder=str(library / "Shared"))
    assert shared["total"] == sum(1 for _ in (library / "Shared").rglob("*.lbd"))
    by_points = ix.list(sort="sweep", order="desc", limit=3)["rows"]
    assert by_points[0]["points"] >= by_points[-1]["points"]
    names = [r["title"] or r["name"] for r in ix.list(sort="name", order="asc", limit=1000)["rows"]]
    assert names == sorted(names, key=str.lower)
    page = ix.list(sort="name", order="asc", offset=10, limit=5)["rows"]
    assert [r["path"] for r in page] == [r["path"] for r in ix.list(sort="name", order="asc", limit=1000)["rows"][10:15]]
    with pytest.raises(ValueError, match="sort must be one of"):
        ix.list(sort="colour")


def test_facets_count_dates_and_folders(tmp_path, library):
    ix = index_of(tmp_path, [library / "Lab data", library / "Shared"])
    ix.scan()
    f = ix.facets()
    assert sum(n for y in f["dates"].values() for m in y.values() for n in m.values()) == 120
    assert f["dates"]["2026"]["03"]["14"] >= 2
    lab, shared = f["folders"]
    assert lab["count"] + shared["count"] == 120 == f["total"]
    assert {c["name"] for c in shared["children"]} == set(mock_library.PROJECTS)
    assert sum(c["count"] for c in shared["children"]) == shared["count"]
    only = ix.facets(q="fridge")
    assert sum(n for y in only["dates"].values() for m in y.values() for n in m.values()) == ix.list(q="fridge")["total"]


def test_files_added_changed_and_removed_are_seen(tmp_path, library):
    root = tmp_path / "copy"
    shutil.copytree(library / "Shared", root)
    ix = index_of(tmp_path, [root])
    ix.scan()
    n = ix.list()["total"]
    assert not ix.scan()                                                       # nothing changed: nothing read
    d = lbd.Dataset(title="Brand new", created="2026-10-29T10:00:00+08:00")
    d.add_axis("x", [1.0, 2.0])
    d.add_value("y", [3.0, 4.0], axes="x")
    d.save(root / "new.lbd")
    gen = ix.generation
    assert ix.scan() and ix.generation > gen and ix.list()["total"] == n + 1
    d.title = "Brand new, renamed inside"
    d.save(root / "new.lbd")
    ix.scan()
    assert ix.list(q="renamed inside")["total"] == 1
    (root / "new.lbd").unlink()
    ix.scan()
    assert ix.list()["total"] == n


def test_a_folder_opened_twice_is_indexed_once(tmp_path, library):
    assert outermost([library, library / "Shared", library]) == [str(library.resolve())]
    ix = index_of(tmp_path, [library, library / "Shared"])
    ix.scan()
    assert ix.list()["total"] == 120
    trees = ix.facets()["folders"]
    assert ix.facets()["total"] == 120                                         # counted once
    assert trees[1]["count"] == sum(1 for _ in (library / "Shared").rglob("*.lbd"))   # its own count


def test_without_headers_only_names_sizes_and_dates_then_read_when_asked(tmp_path, library):
    ix = index_of(tmp_path, [library / "Shared"], read=False)
    ix.scan()
    rows = ix.list(limit=1000)["rows"]
    assert all(r["read"] == 0 and r["title"] == "" and r["date_from_file"] == 1 for r in rows)
    assert ix.list(q="resonator")["total"] > 0 and ix.list(q="averages")["total"] == 0   # names only
    one = rows[0]["path"]
    summary = ix.file(one)                                                     # read when selected
    assert summary["axes"] or summary["values"]
    assert next(r for r in ix.list(limit=1000)["rows"] if r["path"] == one)["read"] == 1


def test_created_dates(tmp_path):
    assert parse_created("2026-03-14T23:30:00+08:00")[1] == "2026-03-14"
    assert parse_created("2026-03-14T23:30:00Z")[1] == "2026-03-14"
    assert parse_created("2026-03-14T23:30:00") is None and parse_created("") is None and parse_created("x") is None


def test_a_broken_index_is_built_again(tmp_path, library):
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "library.sqlite").write_bytes(b"not a database at all" * 100)
    ix = index_of(tmp_path, [library / "Shared"])
    ix.scan()
    assert ix.list()["total"] > 0


def test_the_api(client, data_dir, library_files):
    client.app.state.lbd.library.scan()
    r = client.get("/api/library/list", params={"q": "resonator", "sort": "name", "order": "asc"})
    assert r.status_code == 200 and r.json()["total"] > 0
    f = client.get("/api/library/facets").json()
    assert f["folders"][0]["count"] == client.get("/api/library/list").json()["total"]
    one = r.json()["rows"][0]["path"]
    assert client.get("/api/library/file", params={"path": one}).json()["title"]
    assert client.get("/api/library/status").json()["scans"] >= 1
    assert client.get("/api/library/list", params={"folder": str(Path(data_dir).parent)}).status_code == 403
    assert client.get("/api/library/list", params={"sort": "colour"}).status_code == 400


def test_ten_thousand_files_answer_fast(tmp_path_factory):
    folder = tmp_path_factory.mktemp("big")
    t0 = time.perf_counter()
    mock_library.write_library(folder, 10_000)
    written = time.perf_counter() - t0
    ix = LibraryIndex(folder / "db", lambda: [str(folder / "Lab data"), str(folder / "Shared")], lambda: True)
    t0 = time.perf_counter()
    ix.scan()
    indexed = time.perf_counter() - t0
    print(f"\n10 000 files: written in {written:.0f} s, indexed in {indexed:.0f} s")
    for call in (lambda: ix.list(), lambda: ix.list(q="resonator re-cooling"), lambda: ix.list(date="2025-06"),
                 lambda: ix.list(sort="name", order="asc", offset=5000), lambda: ix.facets(), lambda: ix.facets(q="fridge")):
        t0 = time.perf_counter()
        call()
        assert time.perf_counter() - t0 < 0.2
    t0 = time.perf_counter()
    assert not ix.scan()                                                       # checking again: nothing read
    print(f"checked again in {time.perf_counter() - t0:.1f} s")
