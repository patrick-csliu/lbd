"""Moving tabs between pages in unusual ways: pages closed at the wrong moment, without saying
goodbye, numbers reused while a menu is open, answers lost on the way, and a random "chaos" run.

Each test acts like a user in real browser tabs (see test_pages_e2e.py). The viewer runs with
short timeouts (conftest.py): a page whose connection dropped is gone after 2 s.
"""

import random
import re
import time
from pathlib import Path

import httpx
import pytest
from pageui import deliver, menu, open_file, plot_type, row, tab, tab_names, toast, use
from playwright.sync_api import Page, expect

LOCKED = re.compile(r"\blocked\b")


def number(page: Page) -> int:
    return int(re.search(r"Page (\d+)$", page.title()).group(1))


def open_menu(page: Page, name: str):
    """Right-click a tab: its menu."""
    tab(page, name).click(button="right")
    expect(page.locator(".context-menu")).to_be_visible()


def move_entry(page: Page, n: int):
    return menu(page, re.compile(rf"^Move (\d+ tabs )?to Page {n}\b"))


def close_without_goodbye(page: Page):
    """The tab disappears without saying goodbye (crashed, or the browser didn't send it)."""
    page.route("**/bye", lambda route: route.abort())
    page.close()


def server_pages(viewer) -> dict:
    """Page number -> its files' names, as the viewer sees them."""
    r = httpx.get(f"http://127.0.0.1:{viewer.port}/api/pages", headers={"X-LBD-Token": viewer.state.token})
    return {p["number"]: sorted(Path(f).name for f in p["files"]) for p in r.json()["pages"]}


# ---- the two cases from the user ---------------------------------------------------------------


def test_a_page_closed_without_goodbye_leaves_the_other_pages_menus(viewer, new_page):
    one, two, three = new_page(), new_page(), new_page()
    open_file(two, "a.lbd")
    open_file(three, "b.lbd")
    open_menu(two, "a.lbd")                            # open while Page 1 is still there
    expect(move_entry(two, 1)).to_be_enabled()

    close_without_goodbye(one)
    closed = menu(two, "Page 1 was closed")
    expect(closed).to_be_visible()                     # the open menu updates itself
    expect(closed).to_be_disabled()
    expect(move_entry(two, 3)).to_be_enabled()

    open_menu(three, "b.lbd")                          # a menu opened now doesn't list Page 1
    expect(move_entry(three, 2)).to_be_visible()
    expect(three.locator(".context-menu")).not_to_contain_text("Page 1")
    assert set(server_pages(viewer)) == {2, 3}


def test_a_menu_open_while_its_target_closes_cant_move_there(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    two_id = next(p["page"] for p in httpx.get(f"http://127.0.0.1:{viewer.port}/api/pages",
                                                  headers={"X-LBD-Token": viewer.state.token}).json()["pages"]
                  if p["number"] == 2)
    open_menu(one, "a.lbd")
    expect(move_entry(one, 2)).to_be_enabled()

    two.close(run_before_unload=True)
    expect(menu(one, "Page 2 was closed")).to_be_disabled()
    expect(tab(one, "a.lbd")).not_to_have_class(LOCKED)
    expect(plot_type(one)).to_have_value("scatter")

    # A click that slipped through anyway (it raced the update) is refused with a clear message.
    r = httpx.post(f"http://127.0.0.1:{viewer.port}/api/transfers", headers={"X-LBD-Token": viewer.state.token},
                   json={"page": _page_id(viewer, 1), "paths": [viewer.path("a.lbd")], "to": two_id})
    assert r.status_code == 409 and "that page was closed" in r.json()["detail"]
    assert server_pages(viewer) == {1: ["a.lbd"]}


def _page_id(viewer, n: int) -> str:
    pages = httpx.get(f"http://127.0.0.1:{viewer.port}/api/pages", headers={"X-LBD-Token": viewer.state.token}).json()
    return next(p["page"] for p in pages["pages"] if p["number"] == n)


# ---- unusual sequences ---------------------------------------------------------------------------


def test_a_reused_number_in_an_open_menu_goes_to_the_new_page(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    open_menu(one, "a.lbd")
    two.close(run_before_unload=True)
    again = new_page()                                  # takes the free number: Page 2
    assert number(again) == 2
    expect(menu(one, "Page 2 was closed")).to_be_disabled()
    move_entry(one, 2).click()                          # the entry of the new Page 2
    expect(tab(again, "a.lbd")).to_be_visible()
    expect(one.locator(".tab")).to_have_count(0)


def test_closing_a_new_browser_tab_at_once_cancels_the_move_at_once(viewer, new_page, context):
    one = new_page()
    open_file(one, "a.lbd")
    context.route("**/api/transfers/*/claim", lambda route: None)   # the new tab never gets that far
    open_menu(one, "a.lbd")
    with context.expect_page() as popup:
        menu(one, "Move to a new browser tab").click()
    started = time.monotonic()
    popup.value.close()
    expect(toast(one, "the new browser tab was closed")).to_be_visible()
    assert time.monotonic() - started < viewer.state.pages.new_tab_timeout    # not its timeout
    expect(tab(one, "a.lbd")).not_to_have_class(LOCKED)


def test_ping_pong_keeps_the_unsaved_settings(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    plot_type(one).select_option("scatter")
    for source, target in [(one, two), (two, one), (one, two)]:
        use(source)
        open_menu(source, "a.lbd")
        move_entry(source, number(target)).click()
        expect(tab(target, "a.lbd")).to_be_visible()
        expect(source.locator(".tab")).to_have_count(0)
        expect(plot_type(target)).to_have_value("scatter")
    assert server_pages(viewer) == {1: [], 2: ["a.lbd"]}


def test_two_pages_move_files_to_each_other_at_the_same_time(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    open_file(two, "b.lbd")
    open_menu(one, "a.lbd")
    open_menu(two, "b.lbd")
    move_entry(one, 2).click()
    move_entry(two, 1).click()
    expect(tab(one, "b.lbd")).to_be_visible()
    expect(tab(two, "a.lbd")).to_be_visible()
    assert tab_names(one) == ["b.lbd"] and tab_names(two) == ["a.lbd"]
    assert server_pages(viewer) == {1: ["b.lbd"], 2: ["a.lbd"]}


def test_the_target_reloads_during_the_move(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    two.route("**/api/transfers/*/claim", lambda route: None)        # Page 2 is slow to take it...
    open_menu(one, "a.lbd")
    move_entry(one, 2).click()
    expect(tab(one, "a.lbd")).to_have_class(LOCKED)
    two.reload()                                                     # ...and reloads meanwhile
    expect(toast(one, "The move was cancelled")).to_be_visible()
    expect(tab(one, "a.lbd")).not_to_have_class(LOCKED)
    assert server_pages(viewer)[1] == ["a.lbd"]


def test_the_source_reloads_right_after_starting_the_move(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    open_menu(one, "a.lbd")
    move_entry(one, 2).click()
    one.reload()                                                     # the move goes on without it
    expect(tab(two, "a.lbd")).to_be_visible()
    expect(one).to_have_title(re.compile(r"Page \d+$"))
    expect(one.locator(".tab")).to_have_count(0)
    assert server_pages(viewer)[2] == ["a.lbd"]


def test_a_lost_answer_is_sent_again_so_a_file_is_never_in_two_pages(viewer, context):
    lost = []

    def lose_the_first_transfer_done(route):
        response = route.fetch(timeout=60_000)        # the viewer answers the long poll...
        if not lost and "transfer_done" in response.text():
            lost.append(True)
            route.abort()                             # ...but the answer never reaches the page
        else:
            route.fulfill(response=response)

    one = context.new_page()
    one.route(re.compile(r"/api/pages/[^/]+/next"), lose_the_first_transfer_done)
    one.goto(viewer.url)
    expect(one).to_have_title(re.compile(r"Page 1$"))
    two = context.new_page()
    two.goto(viewer.url)
    expect(two).to_have_title(re.compile(r"Page 2$"))

    open_file(one, "a.lbd")
    open_menu(one, "a.lbd")
    move_entry(one, 2).click()
    expect(tab(two, "a.lbd")).to_be_visible()
    expect(one.locator(".tab")).to_have_count(0)      # the "moved" message came again
    expect(toast(one, "Moved 1 file")).to_be_visible()
    assert lost == [True]
    one.unroute_all(behavior="ignoreErrors")       # the open long poll is still routed


def test_move_every_tab_out_then_close_the_empty_page(viewer, new_page):
    one, two = new_page(), new_page()
    open_file(one, "a.lbd")
    open_file(one, "b.lbd")
    tab(one, "a.lbd").locator(".tab-label").click(modifiers=["Control"])
    open_menu(one, "a.lbd")
    move_entry(one, 2).click()
    expect(two.locator(".tab")).to_have_count(2)
    expect(one.locator(".tab")).to_have_count(0)
    one.close(run_before_unload=True)
    for name in ("a.lbd", "b.lbd"):
        expect(tab(two, name)).not_to_have_class(LOCKED)
    assert server_pages(viewer) == {2: ["a.lbd", "b.lbd"]}


# ---- chaos: random actions, the rules checked after each one ----------------------------------

FILES = ["a.lbd", "b.lbd", "c.lbd"]


class Chaos:
    """Random user actions on up to 4 pages. After each one, once things have settled, the pages
    must agree with each other and with the viewer (see `check`)."""

    def __init__(self, seed, viewer, context, new_page):
        self.rng = random.Random(seed)
        self.viewer, self.context, self.new_page = viewer, context, new_page
        self.pages = [new_page(), new_page(), new_page()]
        self.log = []

    def step(self):
        actions = [self.open, self.open, self.close_tab, self.move, self.move, self.move,
                   self.move_to_new_tab, self.close_page, self.reload, self.deliver, self.add_page]
        action = self.rng.choice(actions)
        self.log.append(action.__name__)
        action()

    def pick(self, with_tabs=False):
        pages = [p for p in self.pages if not with_tabs or tab_names(p)]
        return self.rng.choice(pages) if pages else None

    def open(self):
        page, name = self.pick(), self.rng.choice(FILES)
        if page is None:
            return
        row(page, name).dblclick()
        dialog = page.get_by_role("dialog")
        try:
            dialog.wait_for(timeout=500)              # "Already open in Page N"
            self.log.append(f"  {name} is open elsewhere")
            dialog.get_by_role("button", name="Cancel").click()
        except Exception:
            pass

    def close_tab(self):
        page = self.pick(with_tabs=True)
        if page is not None:
            open_menu(page, self.rng.choice(tab_names(page)))
            menu(page, re.compile(r"^Close$")).click()

    def move(self):
        page = self.pick(with_tabs=True)
        if page is None:
            return
        open_menu(page, self.rng.choice(tab_names(page)))
        entries = page.locator(".context-menu").get_by_role("menuitem", name=re.compile(r"^Move to Page"))
        enabled = [e for e in entries.all() if e.is_enabled()]
        if enabled:
            choice = self.rng.choice(enabled)
            self.log.append(f"  {choice.inner_text()}")
            choice.click()
        else:
            page.keyboard.press("Escape")

    def move_to_new_tab(self):
        page = self.pick(with_tabs=True)
        if page is None or len(self.pages) >= 4:
            return
        open_menu(page, self.rng.choice(tab_names(page)))
        with self.context.expect_page() as popup:
            menu(page, "Move to a new browser tab").click()
        self.pages.append(popup.value)

    def close_page(self):
        if len(self.pages) <= 1:
            return
        page = self.rng.choice(self.pages)
        self.pages.remove(page)
        if self.rng.random() < 0.5:
            self.log.append("  without goodbye")
            close_without_goodbye(page)
        else:
            page.close(run_before_unload=True)

    def reload(self):
        page = self.pick()
        if page is not None:
            page.reload()

    def deliver(self):
        use(self.pick())
        deliver(self.viewer, self.rng.choice(FILES))

    def add_page(self):
        if len(self.pages) < 4:
            self.pages.append(self.new_page())

    # -- the rules

    def check(self):
        """What every page shows agrees with the viewer: each file in at most one page, each
        page's tabs exactly the files the viewer says it has, nothing left locked, and every
        page's Move menu lists exactly the other open pages."""
        shown = {}
        for page in self.pages:
            expect(page).to_have_title(re.compile(r"Page \d+$"))
            for name in tab_names(page):
                assert name not in shown, f"{name} is in Page {shown[name]} and Page {number(page)}"
                shown[name] = number(page)
            assert page.locator(".tab.locked").count() == 0, f"Page {number(page)} has a locked tab"
        viewer = server_pages(self.viewer)
        assert set(viewer) == {number(p) for p in self.pages}, f"pages: viewer {sorted(viewer)}"
        for page in self.pages:
            assert sorted(tab_names(page)) == viewer[number(page)], f"Page {number(page)}: {tab_names(page)} vs {viewer[number(page)]}"
        for page in self.pages:
            if not tab_names(page):
                continue
            open_menu(page, tab_names(page)[0])
            listed = {int(m) for m in re.findall(r"Move to Page (\d+)", page.locator(".context-menu").inner_text())}
            page.keyboard.press("Escape")
            assert listed == {number(p) for p in self.pages} - {number(page)}, f"Page {number(page)}'s menu lists {sorted(listed)}"

    def settle(self):
        """Wait until the rules hold (moves and closes take a moment), at most a few seconds."""
        deadline = time.monotonic() + 8
        while True:
            try:
                return self.check()
            except AssertionError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.3)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_chaos(seed, viewer, context, new_page):
    chaos = Chaos(seed, viewer, context, new_page)
    for _ in range(20):
        chaos.step()
        try:
            chaos.settle()
        except AssertionError as e:
            raise AssertionError(f"seed {seed}, after {chaos.log[-8:]}: {e}") from None
