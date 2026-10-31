"""Files being written (plan 6b): name.lbd.writing in folders and the Library, their status,
Recover, no previews, and the actions LBD refuses for them."""

import numpy as np
import pytest

import lbd


def measuring(folder, name="live.lbd"):
    """A measurement still being written (its Writer open in this process)."""
    w = lbd.Writer(folder / name, title="live")
    w.add_axis("power", [1.0, 2.0, 3.0])
    w.add_axis("time", grows=True)
    w.add_value("S21", axes="power", dtype="complex128")
    w.add_value("T", axes="time")
    w.write(power=0, S21=1 + 1j)
    w.write(time=[0.0, 1.0], T=[5.0, 6.0])
    w.flush()
    return w


def stopped(folder, name="stopped.lbd"):
    """A measurement that stopped before finishing (an error in its block)."""
    with pytest.warns(lbd.LBDWarning, match="stopped with RuntimeError"):
        with pytest.raises(RuntimeError):
            with lbd.Writer(folder / name, title="stopped") as w:
                w.add_axis("x", np.arange(4.0))
                w.add_value("y", axes="x")
                w.write(x=0, y=1.0)
                raise RuntimeError("instrument did not answer")
    return folder / (name + ".writing")


@pytest.fixture()
def writing(data_dir):
    w = measuring(data_dir)
    s = stopped(data_dir)
    yield w, s
    if w._state == "writing":
        w.close()


def library_rows(client):
    client.app.state.lbd.library.scan()
    return {r["name"]: r for r in client.get("/api/library/list").json()["rows"]}


def test_listed_with_their_status(client, data_dir, writing):
    w, s = writing
    files = {f["name"]: f["type"] for f in client.get("/api/list", params={"path": str(data_dir)}).json()["files"]}
    assert files["live.lbd.writing"] == "lbd" and files["stopped.lbd.writing"] == "lbd"
    rows = library_rows(client)
    assert rows["live.lbd.writing"]["writing"] == "measuring"
    assert rows["stopped.lbd.writing"]["writing"] == "stopped"
    assert rows["curve.lbd"]["writing"] is None
    assert rows["live.lbd.writing"]["title"] == "live" and not rows["live.lbd.writing"]["error"]
    info = client.get("/api/library/file", params={"path": str(s)}).json()
    assert info["writing"] == "stopped" and info["title"] == "stopped"


def test_opened_with_a_notice(client, writing):
    w, _ = writing
    r = client.get("/api/file", params={"path": str(w.writing_path)}).json()
    assert r["writing"] == "measuring"
    assert any("still being written" in m for m in r["warnings"])
    assert [a["length"] for a in r["axes"] if a["name"] == "time"] == [2]


def test_no_preview_while_written(client, writing):
    w, _ = writing
    r = client.get("/api/library/preview", params={"path": str(w.writing_path)}).json()
    assert r["state"] == "writing" and "being written" in r["reason"]


@pytest.mark.parametrize("call", [
    lambda c, p: c.put("/api/file/plot", json={"path": p, "spec": {"kind": "curve"}}),
    lambda c, p: c.post("/api/file/rename", json={"path": p, "name": "other.lbd"}),
    lambda c, p: c.post("/api/file/trash", json={"path": p}),
    lambda c, p: c.post("/api/library/duplicate", json={"path": p}),
    lambda c, p: c.post("/api/library/give-ids", json={"paths": [p]}),
])
def test_actions_refused(client, writing, call):
    for p in (str(writing[0].writing_path), str(writing[1])):
        r = call(client, p)
        assert r.status_code == 409, r.text
        assert "being written by a measurement" in r.json()["detail"]
    assert writing[1].exists()


def test_recover(client, data_dir, writing):
    w, s = writing
    r = client.post("/api/file/recover", json={"path": str(w.writing_path)})
    assert r.status_code == 409 and "still being written" in r.json()["detail"]
    r = client.post("/api/file/recover", json={"path": str(s)})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == str(data_dir / "stopped.lbd")
    assert not s.exists()
    d = lbd.load(data_dir / "stopped.lbd")
    assert d.values["y"].data[0] == 1.0 and np.isnan(d.values["y"].data[1])
    rows = library_rows(client)
    assert "stopped.lbd" in rows and "stopped.lbd.writing" not in rows
    assert client.post("/api/file/recover", json={"path": str(data_dir / "curve.lbd")}).status_code == 400


def test_a_finished_measurement_becomes_a_normal_file(client, data_dir, writing):
    w, _ = writing
    w.write(power=1, S21=2 + 2j)
    w.close(stopped=True)
    rows = library_rows(client)
    assert "live.lbd" in rows and "live.lbd.writing" not in rows
    assert rows["live.lbd"]["writing"] is None


def test_explored_while_written(client, writing):
    w, s = writing
    for p in (w.writing_path, s):
        r = client.post("/api/explore", json={"path": str(p), "width": 400, "height": 300, "dpr": 1})
        assert r.status_code == 200, r.text
        o = r.json()
        assert any("still being written" in m for m in o.get("warnings", [])), o.get("warnings")
        client.delete(f"/api/explore/{o['session']}")
