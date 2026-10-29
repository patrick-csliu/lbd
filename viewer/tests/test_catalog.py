"""LBD's database (catalog.py): remembered Explore views, kept on this computer, never in the file."""

import lbd
import numpy as np

from lbd_viewer.catalog import Catalog, fitting, misfit, structure, upgrade


def test_a_view_is_remembered_and_forgotten(tmp_path):
    c = Catalog(tmp_path)
    assert c.view("a.lbd") is None
    c.remember("a.lbd", {"axes": {"t": 5}, "values": {}}, {"spec": {"kind": "curve"}, "zoom": [1, 2]})
    c.remember("a.lbd", {"axes": {"t": 5}, "values": {}}, {"spec": {"kind": "heatmap"}})   # the last save wins
    assert Catalog(tmp_path).view("a.lbd")["state"] == {"spec": {"kind": "heatmap"}}         # kept on disk
    c.forget("a.lbd")
    assert c.view("a.lbd") is None


def test_only_the_newest_views_are_kept(tmp_path):
    c = Catalog(tmp_path, keep=3)
    for i in range(5):
        c.remember(f"{i}.lbd", {}, {"n": i})
    assert [c.view(f"{i}.lbd") is not None for i in range(5)] == [False, False, True, True, True]


def test_a_renamed_file_keeps_its_view(tmp_path):
    c = Catalog(tmp_path)
    c.remember("old.lbd", {}, {"n": 1})
    c.renamed("old.lbd", "new.lbd")
    assert c.view("old.lbd") is None and c.view("new.lbd")["state"] == {"n": 1}


def test_a_schema_1_database_is_upgraded_keeping_its_views(tmp_path):
    import sqlite3

    db = sqlite3.connect(tmp_path / "catalog.sqlite")
    db.execute("CREATE TABLE explore_views (path TEXT PRIMARY KEY, structure TEXT NOT NULL, "
               "state TEXT NOT NULL, updated REAL NOT NULL)")
    db.execute("INSERT INTO explore_views VALUES ('a.lbd', '{}', '{\"n\": 1}', 1.0)")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    c = Catalog(tmp_path)
    assert c.view("a.lbd")["state"] == {"n": 1} and c.problem is None
    assert c.chosen_preview(["path:a.lbd"]) is None


def test_a_chosen_preview_is_kept_by_key_and_follows_renames(tmp_path):
    c = Catalog(tmp_path)
    c.choose_preview("path:old.lbd", "old.lbd", b"picture", "v1")
    c.choose_preview("id:abc", "x.lbd", b"shared", "v2")
    c.renamed("old.lbd", "new.lbd")
    row = Catalog(tmp_path).chosen_preview(["path:new.lbd"])                  # kept on disk
    assert row["picture"] == b"picture" and row["path"] == "new.lbd" and row["version"] == "v1"
    assert c.chosen_preview(["id:none", "id:abc"])["picture"] == b"shared"     # the first key that has one
    assert c.forget_preview(["id:abc", "path:new.lbd"]) == 2
    assert c.chosen_preview(["id:abc", "path:new.lbd"]) is None


def test_a_broken_database_is_put_aside_and_said_so(tmp_path):
    (tmp_path / "catalog.sqlite").write_bytes(b"this is not a database" * 100)
    c = Catalog(tmp_path)
    assert c.view("a.lbd") is None                                  # works, with a new database
    assert "couldn't be read" in c.problem and "catalog.broken-" in c.problem
    assert list(tmp_path.glob("catalog.broken-*.sqlite"))


def test_a_view_that_no_longer_fits_says_why(tmp_path):
    d = lbd.Dataset()
    d.add_axis("f", np.arange(4.0))
    d.add_axis("p", np.arange(3.0))
    d.add_value("S21", np.zeros((3, 4)), axes=["p", "f"])
    old = structure(d)
    state = {"spec": {"values": ["S21"], "x": "f", "series": "p"}}
    assert misfit(old, old, state) is None
    longer = lbd.Dataset()
    longer.add_axis("f", np.arange(4.0))
    longer.add_axis("p", np.arange(30.0))                          # data added: still fits
    longer.add_value("S21", np.zeros((30, 4)), axes=["p", "f"])
    assert misfit(old, structure(longer), state) is None
    renamed = lbd.Dataset()
    renamed.add_axis("freq", np.arange(4.0))
    renamed.add_axis("p", np.arange(3.0))
    renamed.add_value("S21", np.zeros((3, 4)), axes=["p", "freq"])
    assert "now has the axes" in misfit(old, structure(renamed), state)


def test_the_viewer_remembers_explore_views_by_file(client, data_dir):
    path = str((data_dir / "curve.lbd").resolve())
    assert client.get("/api/explore/remembered", params={"path": path}).json() == {"state": None, "note": None}
    state = {"spec": {"values": ["a"], "x": "t"}, "view": {"xlim": [0, 1e-7]}, "settings": {"cmap": "magma"}}
    client.put("/api/explore/remembered", json={"path": path, "state": state}).raise_for_status()
    assert client.get("/api/explore/remembered", params={"path": path}).json()["state"] == upgrade(state)
    # the file is rewritten without 'a': the remembered view no longer fits
    d = lbd.load(path)
    d2 = lbd.Dataset(title="curve")
    d2.add_axis("t", d.axes["t"].data, unit="s")
    d2.add_value("b", d.values["b"].data, axes="t")
    d2.save(path)
    r = client.get("/api/explore/remembered", params={"path": path}).json()
    assert r["state"] is None and "the value 'a' is gone" in r["note"]
    client.delete("/api/explore/remembered", params={"path": path}).raise_for_status()
    assert client.get("/api/explore/remembered", params={"path": path}).json()["note"] is None


def test_a_view_remembered_before_panels_becomes_one_panel(client, values_files):
    """Records written before plan 4 hold one plot; they open as one panel, nothing lost."""
    import mock_values

    old = mock_values.old_record()
    new = upgrade(old)
    assert new["version"] == 2 and new["panels"] == [old] and new["active"] == 0
    assert new["layout"] == "side" and new["sync"] == {"x": True, "y": False, "sliders": True}
    assert upgrade(new) == new                                          # the newest shape stays as it is
    path = str(next(p for p in values_files if p.name == "10 one value.lbd").resolve())
    client.put("/api/explore/remembered", json={"path": path, "state": old}).raise_for_status()
    r = client.get("/api/explore/remembered", params={"path": path}).json()
    assert r == {"state": new, "note": None}


def test_panels_that_no_longer_fit_are_left_out_and_named(tmp_path):
    d = lbd.Dataset()
    d.add_axis("t", np.arange(4.0))
    d.add_value("I", np.zeros(4), axes="t")
    d.add_value("Q", np.zeros(4), axes="t")
    before = structure(d)
    panel = lambda v: {"spec": {"values": [v], "x": "t"}}             # noqa: E731
    state = {"version": 2, "panels": [panel("I"), panel("Q")], "active": 1}
    after = lbd.Dataset()
    after.add_axis("t", np.arange(4.0))
    after.add_value("Q", np.zeros(4), axes="t")
    kept, note = fitting(before, structure(after), state)
    assert kept["panels"] == [panel("Q")] and kept["active"] == 0
    assert note == "panel 1: the value 'I' is gone"
    gone = lbd.Dataset()
    gone.add_axis("t", np.arange(4.0))
    gone.add_value("P", np.zeros(4), axes="t")
    kept, note = fitting(before, structure(gone), state)
    assert kept is None and "panel 1: the value 'I' is gone; panel 2: the value 'Q' is gone" == note
