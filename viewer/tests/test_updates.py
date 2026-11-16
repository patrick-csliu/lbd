"""The check for a new version and its reminder (updates.py, plan 16.25), with fake GitHub answers."""

import json
import urllib.error
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from lbd_viewer import VERSION, cli, updates
from lbd_viewer.config import Config, ConfigError
from lbd_viewer.server import AppState, create_app
from lbd_viewer.updates import CheckError, Updates


def release(tag):
    return lambda: {"tag_name": tag, "html_url": f"https://github.com/patrick-csliu/lbd/releases/tag/{tag}"}


def offline():
    raise CheckError("no connection to GitHub (test)")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 12, 9, 0, 0)

    def __call__(self):
        return self.t

    def next_day(self):
        self.t += timedelta(days=1)


@pytest.fixture()
def clock():
    return Clock()


def updates_for(cfg, fetch, clock, automatic=True):
    return Updates(cfg, automatic=automatic, fetch=fetch, now=clock)


def started(u):
    t = u.start()
    if t:
        t.join(5)
    return t


# ---- what GitHub answers


@pytest.mark.parametrize("tag, newer", [("v99.0.0", True), (f"v{VERSION}", False), ("v0.1.0", False)])
def test_newer_same_and_older(cfg, clock, tag, newer):
    u = updates_for(cfg, release(tag), clock)
    s = u.check_now()
    assert s["latest"] == tag[1:] and s["newer"] is newer and s["checked_at"] == "2026-11-12T09:00:00"
    assert s["url"].endswith(f"/releases/tag/{tag}") and s["current"] == VERSION
    assert u.remind_due() is newer


@pytest.mark.parametrize("answer, why", [
    ({"message": "Not Found"}, "names no version"),
    ({"tag_name": "nightly"}, "names no version"),
    (["not", "a", "release"], "names no version"),
])
def test_a_bad_reply(cfg, clock, answer, why):
    u = updates_for(cfg, lambda: answer, clock)
    with pytest.raises(CheckError, match=why):
        u.check_now()
    assert cfg.settings()["updates"]["last_check"] is None          # nothing kept


def test_a_reply_without_a_page_gets_the_releases_page(cfg, clock):
    s = updates_for(cfg, lambda: {"tag_name": "v99.0.0", "html_url": "http://elsewhere.example"}, clock).check_now()
    assert s["url"] == f"{updates.RELEASES_URL}/tag/v99.0.0"


def test_ask_github_sends_only_the_program_and_its_version(monkeypatch):
    seen = {}

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b'{"tag_name": "v9.9.9"}'

    def urlopen(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), timeout=timeout, data=req.data)
        return Answer()

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert updates.ask_github.real()["tag_name"] == "v9.9.9"      # the real one (conftest: no GitHub)
    assert seen["url"] == "https://api.github.com/repos/patrick-csliu/lbd/releases/latest" and seen["timeout"] == 5
    assert seen["data"] is None
    assert {k.lower(): v for k, v in seen["headers"].items()} == {
        "user-agent": f"LBD-Viewer/{VERSION}", "accept": "application/vnd.github+json"}


@pytest.mark.parametrize("error, why", [
    (urllib.error.URLError("getaddrinfo failed"), "no connection to GitHub"),
    (urllib.error.HTTPError("u", 403, "rate limit exceeded", {}, None), "GitHub answered 403"),
    (TimeoutError("timed out"), "no answer from GitHub within 5 s"),
])
def test_ask_github_says_why_it_failed(monkeypatch, error, why):
    def urlopen(req, timeout):
        raise error

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    with pytest.raises(CheckError, match=why):
        updates.ask_github.real()


# ---- the automatic check: at a real start, once a day, quiet without internet


def test_once_a_day(cfg, clock):
    calls = []

    def fetch():
        calls.append(1)
        return release("v99.0.0")()

    assert started(updates_for(cfg, fetch, clock)) is not None and len(calls) == 1
    assert started(updates_for(cfg, fetch, clock)) is None and len(calls) == 1      # a second start today
    clock.next_day()
    assert started(updates_for(cfg, fetch, clock)) is not None and len(calls) == 2


def test_no_internet_is_quiet_and_tried_again_at_the_next_start(cfg, clock):
    u = updates_for(cfg, offline, clock)
    assert started(u) is not None and not u.checking                # no error raised
    assert cfg.settings()["updates"]["last_check"] is None
    assert started(updates_for(cfg, release("v99.0.0"), clock)) is not None
    assert cfg.settings()["updates"]["latest"] == "99.0.0"


def test_a_check_by_hand_says_why_it_failed(cfg):
    state = AppState(cfg, token="t0k")
    state.updates.fetch = offline
    c = TestClient(create_app(state), base_url="http://127.0.0.1:8000", headers={"X-LBD-Token": "t0k"})
    r = c.post("/api/updates/check")
    assert r.status_code == 502 and r.json()["detail"] == "Couldn't check for a new version: no connection to GitHub (test)."
    state.updates.fetch = release("v99.0.0")
    r = c.post("/api/updates/check")
    assert r.status_code == 200 and r.json()["newer"] and r.json()["latest"] == "99.0.0"
    assert c.get("/api/updates").json()["checked_at"]


def test_dev_and_tests_dont_check(tmp_path, monkeypatch):
    """--dev (and dev_viewer.py, which uses it) skip the check; a real start runs it once the first
    start's question was answered yes (18.8)."""
    import uvicorn

    asked = []
    monkeypatch.setattr(updates, "ask_github", lambda timeout=5: asked.append(1) or release("v99.0.0")())
    monkeypatch.setattr(cli, "lock_path", lambda: tmp_path / "server.json")
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    dev = cli.start(cli.build_parser().parse_args(["--dev"]), [], [], on_started=lambda r: None)
    dev.stop()
    assert not dev.state.updates.automatic and dev.state.updates.start() is None and asked == []
    # not answered yet at the first start (18.8): no check
    unasked = cli.start(cli.build_parser().parse_args(["--port", "8126"]), [], [], on_started=lambda r: None)
    unasked.stop()
    assert not unasked.state.updates.automatic and asked == []
    Config().set_check_updates(False)                                       # answered no: no check
    no = cli.start(cli.build_parser().parse_args(["--port", "8129"]), [], [], on_started=lambda r: None)
    no.stop()
    assert not no.state.updates.automatic and asked == []
    Config().set_check_updates(True)                                        # answered yes: a real start checks
    real = cli.start(cli.build_parser().parse_args(["--port", "8127"]), [], [], on_started=lambda r: None)
    real.stop()
    assert real.state.updates.automatic
    for _ in range(50):
        if not real.state.updates.checking:
            break
        __import__("time").sleep(0.1)
    assert asked == [1] and Config().settings()["updates"]["latest"] == "99.0.0"
    assert not AppState(Config(tmp_path / "c")).updates.automatic         # the default (tests, TestClient)
    monkeypatch.setenv("LBD_NO_UPDATE_CHECK", "1")                          # tests that start a real viewer
    off = cli.start(cli.build_parser().parse_args(["--port", "8128"]), [], [], on_started=lambda r: None)
    off.stop()
    assert not off.state.updates.automatic


# ---- the reminder


def test_the_reminder_goes_to_one_page_once(cfg, clock):
    u = updates_for(cfg, release("v99.0.0"), clock)
    started(u)
    assert u.claim_reminder() is True
    assert u.claim_reminder() is False                                   # a second page doesn't get it
    assert updates_for(cfg, release("v99.0.0"), clock).claim_reminder() is False   # nor a second start today
    clock.next_day()
    later = updates_for(cfg, release("v99.0.0"), clock)
    started(later)
    assert later.claim_reminder() is True                                 # the next day it reminds again


def test_no_reminder_while_checking_or_without_a_newer_version(cfg, clock):
    u = updates_for(cfg, release(f"v{VERSION}"), clock)
    started(u)
    assert u.claim_reminder() is False
    u.checking = True
    cfg.set_updates({"latest": "99.0.0"})
    assert u.claim_reminder() is False                                    # the page asks again shortly
    u.checking = False
    assert u.claim_reminder() is True


def test_a_viewer_left_open_overnight_doesnt_remind_again(cfg, clock):
    u = updates_for(cfg, release("v99.0.0"), clock)
    started(u)
    assert u.claim_reminder() is True
    clock.next_day()                                                      # no new start: the same Updates
    assert u.claim_reminder() is False                                    # the same run: never twice


def test_never_remind_is_for_this_version_only(cfg, clock):
    u = updates_for(cfg, release("v99.0.0"), clock)
    started(u)
    assert u.remind("never")["never_for"] == "99.0.0"
    clock.next_day()
    again = updates_for(cfg, release("v99.0.0"), clock)
    started(again)
    assert again.claim_reminder() is False and again.state()["newer"]     # Settings still shows it
    clock.next_day()
    newer = updates_for(cfg, release("v99.1.0"), clock)
    started(newer)
    assert newer.claim_reminder() is True                                 # the next new version reminds


def test_remind_later_and_install_wait_a_day(cfg, clock):
    for choice in ("later", "install"):
        u = updates_for(cfg, release("v99.0.0"), clock)
        u.check_now()
        u.remind(choice)
        assert updates_for(cfg, release("v99.0.0"), clock).remind_due() is False
        clock.next_day()
        assert updates_for(cfg, release("v99.0.0"), clock).remind_due() is True


def test_the_endpoints(cfg):
    state = AppState(cfg, token="t0k")
    state.updates.automatic = True                                        # as after a real start
    state.updates.fetch = release("v99.0.0")
    c = TestClient(create_app(state), base_url="http://127.0.0.1:8000", headers={"X-LBD-Token": "t0k"})
    s = c.get("/api/updates").json()
    assert s["latest"] is None and s["remind"] is False and s["install_command"]
    c.post("/api/updates/check").raise_for_status()
    assert c.get("/api/updates").json()["remind"] is False                # without claim: Settings → About
    assert c.get("/api/updates", params={"claim": "true"}).json()["remind"] is True
    assert c.get("/api/updates", params={"claim": "true"}).json()["remind"] is False
    assert c.post("/api/updates/remind", json={"choice": "never"}).json()["never_for"] == "99.0.0"
    r = c.post("/api/updates/remind", json={"choice": "soon"})
    assert r.status_code == 400 and "later, never, install" in r.json()["detail"]


def test_the_state_is_kept_in_the_settings(tmp_path):
    cfg = Config(tmp_path)
    cfg.set_updates({"last_check": "2026-11-12T09:00:00", "latest": "1.4.0", "url": "https://github.com/x",
                     "remind": {"never": "1.4.0"}})
    cfg.set_theme("dark")                                                 # another setting saved: kept
    data = json.loads(cfg.settings_path.read_text(encoding="utf-8"))
    assert data["updates"]["remind"] == {"never": "1.4.0"} and data["updates"]["latest"] == "1.4.0"
    data["updates"]["remind"] = {"sometime": True}
    cfg.settings_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="'remind' must be"):
        cfg.settings()
    with pytest.raises(ConfigError, match="unknown update setting"):
        Config(tmp_path / "other").set_updates({"colour": 1})
