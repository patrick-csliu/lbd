"""Explore's Save as CSV (export.py, plan 5): what a panel shows (after operations, chosen
traces, zoom), the options that can't be chosen and why, the size and warnings, several panels,
and writing in the background with progress and Cancel."""

import json

import numpy as np
import pytest

import lbd
from lbd_viewer import export, server, summaries
from test_large_view import MAP, big, little_room  # noqa: F401  (fixture)


F = np.linspace(4e9, 6e9, 201)
P = np.array([-30.0, -20.0, -10.0])


@pytest.fixture()
def sweep(data_dir):
    d = lbd.Dataset(title="sweep")
    d.add_axis("power", P, unit="dBm", label="Power")
    d.add_axis("f", F, unit="Hz", label="Frequency")
    rng = np.random.default_rng(3)
    d.add_value("S21", rng.normal(size=(3, 201)) + 1j * rng.normal(size=(3, 201)), axes=["power", "f"])
    d.add_value("T", 10 * np.arange(3.0)[:, None] + 2e-9 * (F[None, :] - 4e9), axes=["power", "f"], unit="K")
    path = data_dir / "sweep.lbd"
    d.save(path)
    return path, d


def open_view(client, path, spec):
    r = client.post("/api/explore", json={"path": str(path), "spec": spec, "width": 640, "height": 420, "dpr": 1})
    r.raise_for_status()
    return r.json()["session"]


def render(client, sid, settings):
    r = client.post(f"/api/explore/{sid}/render", json={"settings": settings})
    assert r.status_code == 200, r.text
    return json.loads(r.headers["X-LBD-Frame"])


def ask(client, sids, **kw):
    r = client.post("/api/explore/export-csv", json={"sessions": sids, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def save(client, sids, path, **kw):
    out = ask(client, sids, path=str(path), **kw)
    info = client.app.state.lbd.exports.wait(out["job"])
    assert info["state"] == "done", info
    return out["paths"]


def read(path):
    return np.loadtxt(path, delimiter=",", ndmin=2, encoding="utf-8")


CURVES = {"kind": "curve", "values": ["S21"], "x": "f", "series": "power", "complex": "db"}


def test_curves_as_shown(client, sweep, tmp_path):
    path, d = sweep
    sid = open_view(client, path, CURVES)
    plan = ask(client, [sid])
    assert plan["path"].endswith("sweep_S21_db.csv") and plan["error"] is None
    assert plan["estimate"]["rows"] == 3 * 201 and plan["estimate"]["warnings"] == []
    assert plan["options"] == {"stored": None, "both": None, "zoomed": None}
    (out,) = save(client, [sid], path.with_name("a.csv"))
    a = read(out)
    np.testing.assert_array_equal(a[:, 2], 20 * np.log10(np.abs(d.values["S21"].data)).ravel())
    assert 0.8 < plan["estimate"]["bytes"] / path.with_name("a.csv").stat().st_size < 1.2


def test_chosen_traces_and_zoom_in_stored_units(client, sweep):
    path, d = sweep
    sid = open_view(client, path, CURVES)
    render(client, sid, {"select": {"power": [0, 2]}})
    (out,) = save(client, [sid], path.with_name("z.csv"), zoomed=True,
                  views=[{"xlim": [4.5, 5.0], "ylim": [-100, 100]}])                  # the view: GHz, as drawn
    a = read(out)
    keep = (F >= 4.5e9) & (F <= 5.0e9)
    assert set(a[:, 0]) == {-30, -10} and a.shape[0] == 2 * keep.sum()
    np.testing.assert_array_equal(a[: keep.sum(), 1], F[keep])                       # the file: Hz
    text = path.with_name("z.csv").read_text(encoding="utf-8")
    assert "Frequency (Hz)" in text and "chosen traces only (2)" in text


def test_after_operations(client, sweep):
    path, d = sweep
    sid = open_view(client, path, {"kind": "curve", "values": ["T"], "x": "f", "series": "power"})
    render(client, sid, {"ops": [{"op": "subtract_mean"}]})
    plan = ask(client, [sid], numbers="both")
    assert plan["options"]["stored"] is None
    (out,) = save(client, [sid], path.with_name("o.csv"), numbers="both")
    g = np.genfromtxt(out, delimiter=",", names=True, encoding="utf-8")
    assert g.dtype.names == ("power", "f", "T", "T_stored")
    t = d.values["T"].data
    np.testing.assert_allclose(g["T"], (t - t.mean(axis=1, keepdims=True)).ravel(), atol=1e-12)
    np.testing.assert_array_equal(g["T_stored"], t.ravel())
    assert "after: subtract mean" in path.with_name("o.csv").read_text(encoding="utf-8")
    render(client, sid, {"ops": [{"op": "fft"}]})
    plan = ask(client, [sid])
    assert "aren't the stored ones" in plan["options"]["stored"]
    r = client.post("/api/explore/export-csv", json={"sessions": [sid], "numbers": "stored"})
    assert r.status_code == 400 and "aren't the stored ones" in r.json()["detail"]


def test_a_map_as_a_matrix_and_its_warnings(client, sweep, monkeypatch):
    path, d = sweep
    sid = open_view(client, path, {"kind": "heatmap", "values": ["T"], "x": "f", "y": "power"})
    (out,) = save(client, [sid], path.with_name("m.csv"), layout="matrix")
    a = read(out)
    np.testing.assert_array_equal(a[0, 1:], F)
    np.testing.assert_array_equal(a[1:, 1:], d.values["T"].data)
    monkeypatch.setattr(export, "WARN_BYTES", 1000)
    monkeypatch.setattr(export, "EXCEL_COLUMNS", 100)
    plan = ask(client, [sid], layout="matrix")["estimate"]
    assert plan["big"] and any("Excel opens only the first 100 columns" in w for w in plan["warnings"])
    assert not any("columns" in w for w in ask(client, [sid], layout="matrix", rows_are="x")["estimate"]["warnings"])
    curves = open_view(client, path, {"kind": "curve", "values": ["T", "S21"], "x": "f", "complex": "db"})
    assert "two axes" in ask(client, [curves], layout="matrix")["error"]


def test_panels_sharing_axes_go_into_one_file(client, sweep):
    path, d = sweep
    a = open_view(client, path, CURVES)
    b = open_view(client, path, {**CURVES, "values": ["T"], "complex": None})
    c = open_view(client, path, {"kind": "curve", "values": ["T"], "x": "power", "series": "f"})   # other axes
    plan = ask(client, [a, b])
    assert plan["estimate"]["files"] == 1 and plan["left_out"] == [] and plan["columns"] == ["power", "f", "S21", "T"]
    (out,) = save(client, [a, b], path.with_name("p.csv"))
    assert np.genfromtxt(out, delimiter=",", names=True, encoding="utf-8").dtype.names == ("power", "f", "S21", "T")
    assert ask(client, [a, c], names=["Panel 1", "Panel 3"])["left_out"] == ["Panel 3"]   # a save writes one file
    assert len(save(client, [a, c], path.with_name("q.csv"))) == 1
    assert not list(path.parent.glob("q*part*"))


def test_an_existing_file_is_never_replaced(client, sweep):
    path, _ = sweep
    sid = open_view(client, path, CURVES)
    path.with_name("x.csv").write_text("mine")
    r = client.post("/api/explore/export-csv", json={"sessions": [sid], "path": str(path.with_name("x.csv"))})
    assert r.status_code == 400 and "exists already" in r.json()["detail"]
    r = client.post("/api/explore/export-csv", json={"sessions": [sid], "path": str(path.with_name("x.txt"))})
    assert r.status_code == 400 and ".csv" in r.json()["detail"]
    assert path.with_name("x.csv").read_text() == "mine"


def test_a_map_bigger_than_memory_is_saved_part_by_part(client, big, monkeypatch):  # noqa: F811
    path, z = big
    little_room(monkeypatch)
    sid = open_view(client, path, MAP)
    assert client.app.state.lbd.explore.get(sid).summarised
    (out,) = save(client, [sid], path.with_name("big.csv"), layout="matrix")
    a = read(out)
    np.testing.assert_allclose(a[1:, 1:], z)
    assert "part by part" in path.with_name("big.csv").read_text(encoding="utf-8")[:2000]


def test_writing_can_be_cancelled(client, sweep, monkeypatch):
    path, _ = sweep
    sid = open_view(client, path, CURVES)
    monkeypatch.setattr("lbd.plot.tables.BLOCK_NUMBERS", 4)       # many small steps
    real = summaries.Job.step

    def slow(self, fraction):
        import time

        time.sleep(0.01)
        real(self, fraction)

    monkeypatch.setattr(summaries.Job, "step", slow)
    job = ask(client, [sid], path=str(path.with_name("c.csv")))["job"]
    jobs = client.get("/api/exports").json()["jobs"]
    assert [j["state"] for j in jobs if j["id"] == job] == ["writing"]
    assert client.post("/api/exports/cancel", json={"job": job}).json() == {"ok": True}
    assert client.app.state.lbd.exports.wait(job)["state"] == "cancelled"
    assert not path.with_name("c.csv").exists() and not path.with_name("c.csv.part").exists()



def test_the_csv_names_the_files_id(client, sweep, big, monkeypatch):
    """Plan 12: the comments give the measurement's id, also for a map read part by part."""
    little_room(monkeypatch)
    for path, spec, name in ((sweep[0], CURVES, "a.csv"), (big[0], MAP, "b.csv")):
        sid = open_view(client, path, spec)
        (out,) = save(client, [sid], path.with_name(name))
        assert f"# id: {lbd.info(path).id}" in open(out, encoding="utf-8").read()


def pick(client, path, name, fmt="csv"):
    return client.post("/api/pick-save", json={"path": str(path), "name": name, "fmt": fmt, "title": "Save"})


def test_the_save_dialog_chooses_where(client, sweep, tmp_path, monkeypatch):
    """Plan 12: a path chosen in the system's dialog may be written, wherever it is, and it may
    replace a file (the dialog asked); the file stays whole until the new one is complete."""
    path, _ = sweep
    sid = open_view(client, path, CURVES)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "mine.csv"
    outside = client.post("/api/explore/export-csv", json={"sessions": [sid], "path": str(target)})
    assert outside.status_code == 403                                  # not chosen: refused
    monkeypatch.setattr(server, "native_save_dialog", lambda folder, name, fmt, title, fallback: str(target))
    assert pick(client, path, "x.csv").json() == {"path": str(target)}
    save(client, [sid], target)
    assert target.read_text(encoding="utf-8").startswith("# power")
    target.write_text("old")
    save(client, [sid], target)                                        # replaced, as agreed in the dialog
    assert target.read_text(encoding="utf-8").startswith("# power")
    assert sorted(p.name for p in elsewhere.iterdir()) == ["mine.csv"]  # no part left behind


def test_the_save_dialog_cancelled_or_missing_or_wrong(client, sweep, monkeypatch):
    path, _ = sweep
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: None)
    assert pick(client, path, "x.csv").json() == {"path": None}
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(path.with_name("x.txt")))
    assert "must end in .csv" in pick(client, path, "x.csv").json()["detail"]
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(path))
    r = pick(client, path, "x.lbd", "lbd")
    assert r.status_code == 400 and "isn't replaced" in r.json()["detail"]
    assert pick(client, path, "x.txt", "txt").status_code == 400


def test_a_picture_goes_where_the_dialog_chose(client, sweep, tmp_path, monkeypatch):
    path, _ = sweep
    target = tmp_path / "plot.png"
    r = client.post("/api/save-picture", params={"path": str(target)}, content=b"png bytes")
    assert r.status_code == 403 and not target.exists()                # only a path chosen in the dialog
    monkeypatch.setattr(server, "native_save_dialog", lambda *a: str(target))
    pick(client, path, "plot.png", "png").raise_for_status()
    client.post("/api/save-picture", params={"path": str(target)}, content=b"png bytes").raise_for_status()
    assert target.read_bytes() == b"png bytes"


MAP_T = {"kind": "heatmap", "values": ["T"], "x": "f", "y": "power"}


def cut(which="row", power=1, f=0):
    return {"which": which, "index": {"power": power, "f": f}}


def test_a_cut_as_csv(client, sweep):
    """Plan 12: a row of a map, the file's numbers along its axis, saying where it lies."""
    path, d = sweep
    sid = open_view(client, path, MAP_T)
    plan = ask(client, [sid], cuts=[cut()])
    assert plan["path"].endswith(".csv") and "Power" in plan["path"] and plan["columns"] == ["f", "T"]
    (out,) = save(client, [sid], path.with_name("row.csv"), cuts=[cut()])
    a = read(out)
    np.testing.assert_array_equal(a[:, 0], F)
    np.testing.assert_array_equal(a[:, 1], d.values["T"].data[1])
    text = open(out, encoding="utf-8").read()
    assert "cut: row at Power = -20" in text and f"# id: {lbd.info(path).id}" in text


def test_a_cut_of_a_complex_value_as_stored(client, sweep):
    path, d = sweep
    sid = open_view(client, path, {"kind": "heatmap", "values": ["S21"], "x": "f", "y": "power", "complex": "db"})
    (out,) = save(client, [sid], path.with_name("c.csv"), cuts=[cut(power=2)], numbers="stored")
    a = read(out)
    np.testing.assert_array_equal(a[:, 1] + 1j * a[:, 2], d.values["S21"].data[2])


def test_panels_with_the_same_cut_go_into_one_file(client, sweep):
    """All panels: those with a cut along the same axis at the same place; the others are named."""
    path, d = sweep
    a = open_view(client, path, MAP_T)
    b = open_view(client, path, {"kind": "heatmap", "values": ["S21"], "x": "f", "y": "power", "complex": "abs"})
    c = open_view(client, path, MAP_T)
    plan = ask(client, [a, b, c], cuts=[cut(power=1), cut(power=1), cut(power=2)], names=["Panel 1", "Panel 2", "Panel 3"])
    assert plan["columns"] == ["f", "T", "S21"] and plan["left_out"] == ["Panel 3"]
    (out,) = save(client, [a, b], path.with_name("two.csv"), cuts=[cut(), cut()])
    np.testing.assert_array_equal(read(out)[:, 2], np.abs(d.values["S21"].data[1]))


def test_with_operations_a_cut_holds_the_stored_numbers(client, sweep):
    path, d = sweep
    sid = open_view(client, path, MAP_T)
    render(client, sid, {"ops": [{"op": "subtract_mean", "along": "x"}]})
    r = client.post("/api/explore/export-csv", json={"sessions": [sid], "cuts": [cut()]})
    assert r.status_code == 400 and "choose stored" in r.text
    plan = ask(client, [sid], cuts=[cut()], numbers="stored")
    assert plan["options"]["shown"] and plan["options"]["stored"] is None


@pytest.fixture()
def mixed(data_dir):
    """Values on different axes: u(A), v(A, B), t(C); and a number."""
    d = lbd.Dataset(title="Mixed")
    d.add_axis("A", [1.0, 2.0, 3.0], unit="V")
    d.add_axis("B", [10.0, 20.0])
    d.add_axis("C", np.arange(4.0))
    d.add_value("u", [0.1, 0.2, 0.3], axes="A")
    d.add_value("v", np.arange(6.0).reshape(3, 2) * (1 + 1j), axes=["A", "B"])
    d.add_value("t", np.arange(4.0) ** 2, axes="C")
    d.add_value("fidelity", 0.93)
    path = data_dir / "mixed.lbd"
    d.save(path)
    return path


def ask_file(client, datafile, **kw):
    r = client.post("/api/file-csv", json={"file": str(datafile), **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_whole_file_group_by_group(client, mixed):
    """Plan 12: the file's groups, one chosen; a CSV holds that group, as stored."""
    plan = ask_file(client, mixed)
    assert sorted(g["label"] for g in plan["groups"]) == ["t (C)", "u (A)", "v (A, B)"]
    plan = ask_file(client, mixed, group="v")
    assert plan["group"] == "v" and plan["columns"] == ["A", "B", "v_re", "v_im"]
    assert plan["path"].endswith("mixed - v.csv") and plan["estimate"]["rows"] == 6
    out = ask_file(client, mixed, group="v", path=plan["path"])
    info = client.app.state.lbd.exports.wait(out["job"])
    assert info["state"] == "done", info
    a = read(plan["path"])
    np.testing.assert_array_equal(a[:, 2], np.arange(6.0))
    text = open(plan["path"], encoding="utf-8").read()
    assert "fidelity = 0.93" in text and f"# id: {lbd.info(mixed).id}" in text


def test_the_whole_file_as_a_matrix_says_when_it_cant(client, mixed):
    plan = ask_file(client, mixed, group="v", layout="matrix")
    assert plan["estimate"] is None and "one number per cell" in plan["error"]


def test_a_file_of_single_numbers_has_no_table(client, data_dir):
    d = lbd.Dataset()
    d.add_value("x", 1.0)
    d.save(data_dir / "one.lbd")
    r = client.post("/api/file-csv", json={"file": str(data_dir / "one.lbd")})
    assert r.status_code == 400 and "only single numbers" in r.text


def test_every_mock_file_converts(client, values_files):
    """Every group of every kind of file: variable sweeps, data points with a shape, complex …"""
    for path in values_files:
        for g in ask_file(client, path)["groups"]:
            plan = ask_file(client, path, group=g["key"])
            assert plan["error"] is None, (path.name, g)
            out = ask_file(client, path, group=g["key"], path=plan["path"])
            assert client.app.state.lbd.exports.wait(out["job"])["state"] == "done", (path.name, g)
            lines = [x for x in open(plan["path"], encoding="utf-8") if not x.startswith("#")]
            assert lines and len(lines) <= g["rows"], (path.name, g)
