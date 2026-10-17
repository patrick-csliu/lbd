"""The HTTP endpoints of the page rules (server.py <-> pages.py): statuses, messages, events."""

import threading

import pytest
from fastapi.testclient import TestClient

from lbd_viewer.pages import Pages
from lbd_viewer.server import AppState, create_app


@pytest.fixture
def api(cfg, data_dir):
    """A client whose viewer uses short page timeouts, so waiting tests stay fast."""
    state = AppState(cfg, token="t0k", pages=Pages(ack_timeout=0.5, transfer_timeout=0.5, new_tab_timeout=0.5))
    c = TestClient(create_app(state), base_url="http://127.0.0.1:8000")
    c.headers["X-LBD-Token"] = "t0k"
    c.post("/api/roots", json={"path": str(data_dir)}).raise_for_status()
    c.state = state
    return c


def new_page(api):
    r = api.post("/api/pages").json()
    return r["page"], r["number"]


def next_command(api, page, wait=0):
    return api.get(f"/api/pages/{page}/next", params={"wait": wait}).json()


def drain(api, page):
    out = []
    while (command := next_command(api, page)):
        out.append(command)
    return out


def test_pages_register_and_unknown_pages_are_404(api):
    page, number = new_page(api)
    assert number == 1 and new_page(api)[1] == 2
    assert api.post(f"/api/pages/{page}/focus").json() == {"ok": True}
    assert next_command(api, page) == {}
    r = api.get("/api/pages/nope/next", params={"wait": 0})
    assert r.status_code == 404 and "reload" in r.json()["detail"]
    assert api.post("/api/pages/nope/focus").status_code == 404


def test_list_pages_with_their_files(api, data_dir):
    one, _ = new_page(api)
    two, _ = new_page(api)
    path = str(data_dir / "curve.lbd")
    api.post(f"/api/pages/{two}/acquire", json={"path": path}).raise_for_status()
    assert api.get("/api/pages").json() == {"pages": [
        {"page": one, "number": 1, "files": []},
        {"page": two, "number": 2, "files": [path]},
    ]}


def test_acquire_is_refused_for_a_file_open_in_another_page(api, data_dir):
    one, _ = new_page(api)
    two, _ = new_page(api)
    path = str(data_dir / "curve.lbd")
    assert api.post(f"/api/pages/{one}/acquire", json={"path": path}).json() == {"path": path}
    assert api.post(f"/api/pages/{two}/acquire", json={"path": path}).json() == {"path": path, "owner": 1}
    assert api.post("/api/pages/show", json={"path": path}).json() == {"page": 1}
    assert next_command(api, one)["kind"] == "show"
    assert api.post(f"/api/pages/{one}/release", json={"path": path}).json() == {"ok": True}
    assert api.post("/api/pages/show", json={"path": path}).status_code == 404
    assert api.post(f"/api/pages/{one}/acquire", json={"path": "C:/Windows/win.ini"}).status_code == 403


def test_deliver_to_the_open_page(api, data_dir):
    page, _ = new_page(api)
    path = str(data_dir / "curve.lbd")

    def take():        # the page's long poll gets the file and acknowledges it
        command = next_command(api, page, wait=5)
        assert command["kind"] == "open" and command["data"] == {"paths": [path]}
        assert api.post(f"/api/pages/{page}/ack/{command['id']}").json()["granted"] == [path]

    t = threading.Thread(target=take)
    t.start()
    r = api.post("/api/deliver", json={"files": [path]}).json()
    t.join()
    assert r == {"delivered": True, "shown": [], "busy": [], "unplaced": []}
    assert api.post(f"/api/pages/{new_page(api)[0]}/acquire", json={"path": path}).json()["owner"] == 1


def test_deliver_without_an_answer_falls_back_to_a_browser_tab(api, data_dir):
    page, _ = new_page(api)
    path = str(data_dir / "curve.lbd")
    r = api.post("/api/deliver", json={"files": [path]}).json()        # nobody acknowledges
    assert r == {"delivered": False, "shown": [], "busy": [], "unplaced": [path]}
    assert next_command(api, page) == {}                                # withdrawn: never arrives late


def test_deliver_with_no_page_open(api, data_dir):
    path = str(data_dir / "curve.lbd")
    assert api.post("/api/deliver", json={"files": [path]}).json()["unplaced"] == [path]
    assert api.post("/api/deliver", json={"files": [str(data_dir / "gone.lbd")]}).status_code == 404


def test_deliver_a_folder_brings_a_page_forward(api, tmp_path):
    folder = tmp_path / "more"
    folder.mkdir()
    assert api.post("/api/deliver", json={"dirs": [str(folder)]}).json()["delivered"] is False   # no page
    page, _ = new_page(api)
    drain(api, page)
    assert api.post("/api/deliver", json={"dirs": [str(folder)]}).json()["delivered"] is True
    kinds = [(c["kind"], c["data"]) for c in drain(api, page)]
    assert ("event", {"event": "roots_changed"}) in kinds and ("show", {"path": None}) in kinds


def test_move_tabs_between_pages(api, data_dir):
    one, _ = new_page(api)
    two, _ = new_page(api)
    path = str(data_dir / "curve.lbd")
    api.post(f"/api/pages/{one}/acquire", json={"path": path}).raise_for_status()
    t = api.post("/api/transfers", json={"page": one, "paths": [path], "states": {path: {"kind": "curve"}}, "to": two}).json()
    command = next_command(api, two)
    assert command["kind"] == "transfer" and command["data"] == {"id": t["id"], "from": 1}
    claimed = api.post(f"/api/transfers/{t['id']}/claim", json={"page": two}).json()
    assert claimed == {"paths": [path], "states": {path: {"kind": "curve"}}, "from": 1}
    assert api.post(f"/api/transfers/{t['id']}/complete", json={"page": two}).json() == {"paths": [path]}
    done = next_command(api, one)
    assert done["kind"] == "transfer_done" and done["data"]["paths"] == [path] and done["data"]["to"] == 2


def test_a_file_being_moved_cannot_be_saved_renamed_or_trashed(api, data_dir):
    one, _ = new_page(api)
    path = str(data_dir / "curve.lbd")
    api.post(f"/api/pages/{one}/acquire", json={"path": path}).raise_for_status()
    api.post("/api/transfers", json={"page": one, "paths": [path], "to": None}).raise_for_status()
    for r in (api.put("/api/file/plot", json={"path": path, "spec": {"kind": "curve"}}),
              api.post("/api/file/rename", json={"path": path, "name": "x.lbd"}),
              api.post("/api/file/trash", json={"path": path})):
        assert r.status_code == 409 and "being moved" in r.json()["detail"]


@pytest.mark.parametrize("body, status, message", [
    ({"paths": []}, 409, "no files selected"),
    ({"paths": ["{data}/curve.lbd"]}, 409, "not open in this page"),
    ({"paths": ["{data}/curve.lbd"], "to": "nope"}, 404, "reload"),
])
def test_transfer_errors(api, data_dir, body, status, message):
    one, _ = new_page(api)
    body = {**body, "page": one, "paths": [p.format(data=data_dir) for p in body["paths"]]}
    r = api.post("/api/transfers", json=body)
    assert r.status_code == status and message in r.json()["detail"]
    assert api.post("/api/transfers/nope/claim", json={"page": one}).status_code == 409


def test_events_reach_every_page(api, data_dir):
    one, _ = new_page(api)
    two, _ = new_page(api)
    api.post("/api/file/rename", json={"path": str(data_dir / "curve.lbd"), "name": "c2.lbd"}).raise_for_status()
    api.put("/api/styles/mine", json={"preset": {}}).raise_for_status()
    for page in (one, two):
        events = [c["data"] for c in drain(api, page) if c["kind"] == "event"]
        assert events[0] == {"event": "renamed", "old": str(data_dir / "curve.lbd"), "new": str(data_dir / "c2.lbd")}
        assert {"event": "styles_changed"} in events


def test_save_refuses_a_file_changed_since_it_was_opened(api, data_dir):
    path = str(data_dir / "curve.lbd")
    version = api.get("/api/file", params={"path": path}).json()["version"]
    ok = api.put("/api/file/plot", json={"path": path, "spec": {"kind": "curve"}, "if_version": version})
    assert ok.status_code == 200
    stale = api.put("/api/file/plot", json={"path": path, "spec": {"kind": "curve"}, "if_version": version})
    assert stale.status_code == 409 and "changed since you opened it" in stale.json()["detail"]
    forced = api.put("/api/file/plot", json={"path": path, "spec": {"kind": "curve"}})     # "Overwrite"
    assert forced.status_code == 200


def test_open_files_in_setting(api):
    assert api.get("/api/state").json()["open_files_in"] == "viewer"
    assert api.put("/api/settings", json={"open_files_in": "browser-tab"}).json()["open_files_in"] == "browser-tab"
    r = api.put("/api/settings", json={"open_files_in": "popup"})
    assert r.status_code == 400 and "viewer, browser-tab" in r.json()["detail"]
    assert api.put("/api/settings", json={}).status_code == 400
