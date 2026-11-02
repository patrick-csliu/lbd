"""Explore's Save as CSV (export.py, plan 5): what a panel shows (after operations, chosen
traces, zoom), the options that can't be chosen and why, the size and warnings, several panels,
and writing in the background with progress and Cancel."""

import json

import numpy as np
import pytest

import lbd
from lbd_viewer import export, summaries
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


def test_chosen_traces_zoom_and_units_as_shown(client, sweep):
    path, d = sweep
    sid = open_view(client, path, CURVES)
    render(client, sid, {"select": {"power": [0, 2]}})
    (out,) = save(client, [sid], path.with_name("z.csv"), zoomed=True, units="shown",
                  views=[{"xlim": [4.5, 5.0], "ylim": [-100, 100]}])
    a = read(out)
    keep = (F >= 4.5e9) & (F <= 5.0e9)
    assert set(a[:, 0]) == {-30, -10} and a.shape[0] == 2 * keep.sum()
    np.testing.assert_allclose(a[: keep.sum(), 1], F[keep] / 1e9)
    text = path.with_name("z.csv").read_text(encoding="utf-8")
    assert "Frequency (GHz)" in text and "chosen traces only (2)" in text


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
    assert ask(client, [a, b])["estimate"]["files"] == 1
    (out,) = save(client, [a, b], path.with_name("p.csv"))
    assert np.genfromtxt(out, delimiter=",", names=True, encoding="utf-8").dtype.names == ("power", "f", "S21", "T")
    paths = save(client, [a, c], path.with_name("q.csv"), units="shown")
    assert len(paths) == 2 and paths[1].endswith("q – part 2.csv")


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
