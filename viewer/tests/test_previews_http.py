"""The Library's previews over HTTP (plan 8c): automatic and chosen pictures, settings."""

import json
import shutil
import time

import numpy as np
import pytest

import lbd


def write(path, n=50, title="t"):
    x = np.linspace(0, 1, n)
    d = lbd.Dataset(title=title)
    d.add_axis("x", x)
    d.add_value("y", np.sin(5 * x), axes=["x"])
    d.add_value("z", np.cos(5 * x), axes=["x"])
    d.save(path)
    return path


def preview(client, path, timeout=30.0):
    """The answer once it isn't "drawing": (picture bytes or None, header or JSON)."""
    end = time.monotonic() + timeout
    while True:
        r = client.get("/api/library/preview", params={"path": str(path)})
        r.raise_for_status()
        if r.headers["content-type"] == "image/webp":
            return r.content, json.loads(r.headers["X-LBD-Preview"])
        body = r.json()
        if body["state"] != "drawing" or time.monotonic() > end:
            return None, body
        time.sleep(0.05)


def indexed(client):
    """Wait until the Library has scanned (so it knows the files' ids)."""
    first = client.get("/api/library/status").json()["scans"]
    end = time.monotonic() + 30
    while client.get("/api/library/status").json()["scans"] <= first + 1 and time.monotonic() < end:
        time.sleep(0.05)


ONE_PANEL = {"panels": [{"spec": {"values": ["z"]}, "settings": {}, "view": None}], "grid": [1, 1]}


def test_an_automatic_preview_is_drawn_and_described(client, data_dir):
    path = write(data_dir / "a.lbd")
    picture, about = preview(client, path)
    assert picture[:4] == b"RIFF" and about["source"] == "automatic"
    status = client.get("/api/library/status").json()["previews"]
    assert status["mode"] == "all" and {"drawn", "total", "drawing"} <= set(status)


def test_a_file_that_cant_be_drawn_says_why(client, data_dir):
    d = lbd.Dataset(title="numbers")
    d.add_value("f0", 7.0)
    d.save(data_dir / "numbers.lbd")
    picture, body = preview(client, data_dir / "numbers.lbd")
    assert picture is None and body["state"] == "error" and "single numbers" in body["reason"]


def test_with_previews_off_show_preview_draws_one(client, data_dir):
    client.put("/api/settings", json={"library": {"previews": "off"}}).raise_for_status()
    path = write(data_dir / "a.lbd")
    assert preview(client, path) == (None, {"state": "off", "reason": None})
    client.post("/api/library/preview/want", json={"paths": [str(path)], "now": True}).raise_for_status()
    picture, _ = preview(client, path)
    assert picture


def test_every_file_is_refused_while_headers_arent_read(client):
    client.put("/api/settings", json={"library": {"read_headers": False}}).raise_for_status()
    r = client.put("/api/settings", json={"library": {"previews": "all"}})
    assert r.status_code == 400 and "Read each data file's details" in r.json()["detail"]
    assert client.get("/api/library/status").json()["previews"]["mode"] == "nearby"


def test_a_chosen_preview_is_kept_and_reset(client, data_dir):
    path = write(data_dir / "a.lbd")
    automatic, _ = preview(client, path)
    r = client.post("/api/library/preview/choose", json={"path": str(path), **ONE_PANEL})
    r.raise_for_status()
    chosen, about = preview(client, path)
    assert chosen != automatic and about["source"] == "chosen" and about["changed_since"] is False
    # emptying the cache keeps it; a file change keeps it, with a note
    client.post("/api/library/preview/clear").raise_for_status()
    time.sleep(0.02)
    write(path, n=80)
    again, about = preview(client, path)
    assert again == chosen and about["changed_since"] is True
    # reset: the automatic one again (of the file as it is now)
    assert client.delete("/api/library/preview/choose", params={"path": str(path)}).json() == {"forgotten": 1}
    _, about = preview(client, path)
    assert about["source"] == "automatic"


def test_a_chosen_preview_follows_a_rename_and_goes_with_the_file(client, data_dir):
    path = write(data_dir / "a.lbd")
    client.post("/api/library/preview/choose", json={"path": str(path), **ONE_PANEL}).raise_for_status()
    new = client.post("/api/file/rename", json={"path": str(path), "name": "b.lbd"}).json()["path"]
    assert preview(client, new)[1]["source"] == "chosen"
    client.post("/api/file/trash", json={"path": new}).raise_for_status()
    write(data_dir / "b.lbd")                             # a new file with that name: its own preview
    assert preview(client, data_dir / "b.lbd")[1]["source"] == "automatic"


def test_identical_copies_share_a_chosen_preview_but_copies_that_differ_dont(client, data_dir):
    a = write(data_dir / "a.lbd")
    (data_dir / "sub" / "copy.lbd").write_bytes(a.read_bytes())
    shutil.copystat(a, data_dir / "sub" / "copy.lbd")
    indexed(client)
    client.post("/api/library/preview/choose", json={"path": str(a), **ONE_PANEL}).raise_for_status()
    assert preview(client, data_dir / "sub" / "copy.lbd")[1]["source"] == "chosen"
    # the copy changed: copies that differ, each keeps its own
    d = lbd.load(data_dir / "sub" / "copy.lbd")
    d.description = "changed later"
    d.save(data_dir / "sub" / "copy.lbd")
    indexed(client)
    assert preview(client, data_dir / "sub" / "copy.lbd")[1]["source"] == "automatic"
    assert preview(client, a)[1]["source"] == "chosen"


def test_choose_checks_its_panels(client, data_dir):
    path = write(data_dir / "a.lbd")
    r = client.post("/api/library/preview/choose", json={"path": str(path), "panels": [], "grid": [1, 1]})
    assert r.status_code == 400
    r = client.post("/api/library/preview/choose",
                    json={"path": str(path), "panels": [{"spec": {"values": ["nope"]}}], "grid": [1, 1]})
    assert r.status_code == 422 and "nope" in r.json()["detail"]


def test_the_cache_size_is_told_and_emptied(client, data_dir):
    path = write(data_dir / "a.lbd")
    preview(client, path)
    size = client.get("/api/library/preview/cache").json()
    assert size["count"] == 1 and size["bytes"] > 1000
    assert client.post("/api/library/preview/clear").json()["freed"] == size["bytes"]
    assert client.get("/api/library/preview/cache").json() == {"count": 0, "bytes": 0}
