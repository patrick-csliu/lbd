"""Random sequences of multi-page actions, with the rules checked after every step.

Simulated pages behave like the web UI (viewer/web/src/pages.ts): they open and close files,
receive double-clicked files, move tabs to other pages or new browser tabs, crash or go quiet,
and follow renames and deletions. Time passes in random steps. After each step the invariants
below must hold. Every run is reproducible from its seed; a failure names the seed and the
steps, so it can be replayed with `replay(seed)`.

A page can go to sleep (no polls: a laptop asleep, a frozen background tab) and wake up again.
Its connection can drop (a closed tab without goodbye, a network hiccup), and an answer to a poll
can get lost on the way. If the viewer dropped the page meanwhile, it registers anew and
re-acquires each tab; a file another page took meanwhile stays visible but locked ("now open in
Page N"), never usable twice.

Invariants (for pages that are awake; 3 once a page has read its waiting messages):
  1. No file is shown, usable, in two live pages (a tab being moved away is locked, not usable).
  2. The server's ownership is consistent: every owner is a live page (or the source of a move in
     progress), and each page's file set matches the ownership table.
  3. A live page shows usable exactly the files the server says it owns (moving tabs aside).
  4. A move never loses a file: when it ends, the file is in the target (completed) or still in
     the source (cancelled), unless that page itself is gone.
  5. Every refused action comes with a message.
  6. A page that has read its messages knows exactly which other pages are live (its "Move to"
     menu), and files never go to a page whose connection dropped.
"""

import random

import pytest

from lbd_viewer.pages import PageError, Pages

FILES = [f"f{i}.lbd" for i in range(6)]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SimPage:
    """What one browser tab shows: usable tabs, and tabs locked while being moved away."""

    def __init__(self, page):
        self.id, self.number = page.id, page.number
        self.tabs = set()            # usable
        self.moving = {}             # path -> transfer id (locked, shown with a spinner)
        self.detached = {}           # path -> number of the page that has it now (locked, see wake)
        self.alive = True            # False: asleep (laptop asleep, frozen background tab): no polls
        self.claimed = {}            # transfer id -> paths, claimed but not completed yet
        self.last = 0                # id of the last command handled (confirmed by the next poll)
        self.known = []              # page ids of the last page list (pages_changed) it read


class Sim:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.clock = Clock()
        self.pages = Pages(clock=self.clock, stale_after=40, ack_timeout=3, transfer_timeout=5, new_tab_timeout=15)
        self.sim = {}                # page id -> SimPage
        self.waiting = []            # deliveries a caller (lbd-view) waits for: (delivery, deadline)
        self.log = []

    # -- helpers

    def live(self):
        ids = {p.id for p in self.pages.live_pages()}
        return [s for s in self.sim.values() if s.id in ids]

    def new_page(self):
        """A tab that loads the viewer: it registers, then listens (only then is it offered)."""
        page = self.pages.register()
        self.pages.start_poll(page.id)
        s = SimPage(page)
        self.sim[s.id] = s
        return s

    def refused(self, error):
        assert str(error).strip(), "a refused action must say why"           # invariant 5

    # -- actions

    def act(self):
        actions = [self.open_from_panel, self.close_tab, self.double_click, self.move, self.process,
                   self.process, self.process, self.tick, self.sleep, self.wake, self.bye, self.rename,
                   self.trash, self.new_page_action, self.drop_connection]
        action = self.rng.choice(actions)
        self.log.append(action.__name__)
        action()

    def new_page_action(self):
        if len(self.live()) < 4:
            self.new_page()

    def open_from_panel(self):
        pages = [s for s in self.live() if s.alive]
        if not pages:
            return
        s, path = self.rng.choice(pages), self.rng.choice(FILES)
        if path in s.tabs or path in s.moving:
            return
        try:
            other = self.pages.acquire(s.id, path)
        except PageError as e:
            return self.refused(e)
        if other is None:
            s.tabs.add(path)

    def close_tab(self):
        pages = [s for s in self.live() if s.alive and s.tabs]
        if not pages:
            return
        s = self.rng.choice(pages)
        path = self.rng.choice(sorted(s.tabs))
        try:
            self.pages.release(s.id, path)
        except PageError as e:
            return self.refused(e)
        s.tabs.discard(path)

    def double_click(self):
        paths = self.rng.sample(FILES, self.rng.randint(1, 2))
        try:
            offer = self.pages.offer(paths)
        except PageError as e:
            return self.refused(e)
        if offer.delivery is not None:
            assert self.pages.pages[offer.delivery.page].offline_since is None, "files sent to a closed page"   # 6
            self.waiting.append((offer.delivery, self.clock.now + self.pages.ack_timeout))
        for path in offer.unplaced:
            self.fallback_tab(path)

    def fallback_tab(self, path):
        """lbd-view opens a new browser tab with ?open=<path>; the page acquires it on load."""
        s = self.new_page()
        try:
            other = self.pages.acquire(s.id, path)
        except PageError as e:                                   # being moved: the page says so
            return self.refused(e)
        if other is None:
            s.tabs.add(path)

    def move(self):
        pages = [s for s in self.live() if s.alive and s.tabs]
        if not pages:
            return
        s = self.rng.choice(pages)
        paths = self.rng.sample(sorted(s.tabs), self.rng.randint(1, len(s.tabs)))
        others = [o for o in self.live() if o.id != s.id]
        # to another page (mostly), or to a new browser tab
        target = self.rng.choice(others).id if others and self.rng.random() < 0.8 else None
        try:
            transfer = self.pages.start_transfer(s.id, paths, {p: {"x": 1} for p in paths}, target)
        except PageError as e:
            return self.refused(e)
        for path in paths:
            s.tabs.discard(path)
            s.moving[path] = transfer.id
        if target is None and self.rng.random() < 0.7:        # the new tab loads (or a popup is blocked)
            new = self.new_page()
            self.claim_and_maybe_complete(new, transfer.id)

    def claim_and_maybe_complete(self, s, transfer_id):
        try:
            transfer = self.pages.claim(transfer_id, s.id)
        except PageError as e:
            return self.refused(e)
        s.claimed[transfer_id] = list(transfer.paths)
        if self.rng.random() < 0.8:
            self.complete(s, transfer_id)

    def complete(self, s, transfer_id):
        try:
            paths = self.pages.complete(transfer_id, s.id)
        except PageError as e:
            s.claimed.pop(transfer_id, None)
            return self.refused(e)
        s.claimed.pop(transfer_id)
        s.tabs.update(paths)                                    # shown only after completing
        for path in paths:                                      # invariant 4: arrived
            assert self.pages.owner(path).id == s.id

    def process(self):
        """A live page reads its commands, in order, and reacts like the web UI (sometimes slowly)."""
        pages = [s for s in self.live() if s.alive]
        if not pages:
            return
        s = self.rng.choice(pages)
        for transfer_id in list(s.claimed):                     # finish a claimed move later
            if self.rng.random() < 0.5:
                self.complete(s, transfer_id)
        while (command := self.pages.poll(s.id, after=s.last)) is not None:
            if self.rng.random() < 0.1:
                return                                          # the answer got lost: sent again next time
            self.handle(s, command, eager=False)

    def handle(self, s, command, eager):
        """What pages.ts does with one command. `eager`: no random slowness."""
        assert command.id > s.last, "a command handled twice"
        s.last = command.id
        kind, data = command.kind, command.data
        if kind == "pages_changed":
            s.known = [p["page"] for p in data["pages"]]
        elif kind == "open":
            if not eager and self.rng.random() < 0.2:            # too slow: the caller withdraws first
                return
            try:
                result = self.pages.ack(s.id, command.id)
            except PageError as e:
                return self.refused(e)
            s.tabs.update(result["granted"])
        elif kind == "transfer":
            if eager or self.rng.random() < 0.8:
                self.claim_and_maybe_complete(s, data["id"])
        elif kind in ("transfer_done", "transfer_cancelled"):   # by transfer id: robust to renames
            s.claimed.pop(data["id"], None)
            for path, transfer_id in list(s.moving.items()):
                if transfer_id == data["id"]:
                    del s.moving[path]
                    if kind == "transfer_cancelled":
                        s.tabs.add(path)                        # invariant 4: kept by the source
        elif kind == "event" and data["event"] == "renamed":
            old, new = data["old"], data["new"]
            if old in s.tabs:
                s.tabs.discard(old)
                s.tabs.add(new)
            if old in s.moving:
                s.moving[new] = s.moving.pop(old)
        elif kind == "event" and data["event"] == "trashed":
            s.tabs.discard(data["path"])

    def drain(self, s):
        """The page reads everything waiting for it (a real page does this within milliseconds)."""
        while (command := self.pages.poll(s.id, after=s.last)) is not None:
            self.handle(s, command, eager=True)

    def tick(self):
        self.clock.now += self.rng.choice([0.5, 1, 2, 4, 6, 20, 45])
        for s in self.live():
            if s.alive and self.rng.random() < 0.9:
                self.pages.focus(s.id) if self.rng.random() < 0.3 else None
                try:
                    self.pages.page(s.id).last_seen = self.clock.now   # its long poll is open
                except PageError:
                    pass
        for delivery, deadline in list(self.waiting):           # lbd-view gives up and opens a tab
            if self.clock.now >= deadline or delivery.status != "pending":
                self.waiting.remove((delivery, deadline))
                if delivery.status == "pending":
                    self.pages.withdraw(delivery)
                if delivery.status == "withdrawn":
                    for path in delivery.current.values():      # renamed meanwhile: the new name
                        if path is not None:                     # deleted meanwhile: nothing to open
                            self.fallback_tab(path)
        self.pages.expire()

    def sleep(self):
        pages = [s for s in self.live() if s.alive]
        if pages and self.rng.random() < 0.3:
            self.rng.choice(pages).alive = False                # stops polling; expires after 40 s

    def wake(self):
        """An asleep page comes back. Still registered: it carries on (its queue waited for it).
        Dropped meanwhile: it registers anew and re-acquires its tabs, as pages.ts does."""
        asleep = [s for s in self.sim.values() if not s.alive and s.id not in {"bye"}]
        if not asleep:
            return
        s = self.rng.choice(asleep)
        s.alive = True
        if s.id in self.pages.pages:
            return self.drain(s)                                  # missed nothing: it was queued
        del self.sim[s.id]
        page = self.pages.register()
        self.pages.start_poll(page.id)
        s.id, s.number = page.id, page.number
        self.sim[s.id] = s
        s.claimed.clear()
        s.last, s.known = 0, []
        for path in sorted(s.tabs | set(s.moving)):
            s.tabs.discard(path)
            s.moving.pop(path, None)
            try:
                other = self.pages.acquire(s.id, path)
            except PageError as e:                               # it is being moved: locked here
                self.refused(e)
                s.detached[path] = 0
                continue
            if other is None:
                s.tabs.add(path)
            else:
                s.detached[path] = other.number                  # "now open in Page N", locked

    def drop_connection(self):
        """The long poll's connection drops (a tab closed without goodbye, a network hiccup). The
        page is offline until it wakes: it polls again (in time or not) or registers anew."""
        pages = [s for s in self.live() if s.alive]
        if pages:
            s = self.rng.choice(pages)
            self.pages.connection_lost(s.id, self.pages.start_poll(s.id, after=s.last))
            s.alive = False

    def bye(self):
        pages = [s for s in self.live() if s.alive]
        if pages and self.rng.random() < 0.3:
            s = self.rng.choice(pages)
            self.pages.bye(s.id)
            del self.sim[s.id]                                   # closed: never comes back

    def rename(self):
        old, new = self.rng.sample(FILES, 2)
        if self.pages.owner(new) is not None or new in self.pages.locked or old in self.pages.locked:
            return                                               # the server refuses such renames
        self.pages.broadcast("renamed", old=old, new=new)
        self.sync_events()

    def trash(self):
        path = self.rng.choice(FILES)
        if path in self.pages.locked:
            return
        self.pages.broadcast("trashed", path=path)
        self.sync_events()

    def sync_events(self):
        """After a rename or deletion, every awake page reads its messages, in order."""
        for s in self.live():
            if s.alive:
                self.drain(s)

    # -- invariants

    def check(self):
        live = {s.id: s for s in self.live()}
        server = self.pages
        # 1. a file is usable in at most one awake page (an asleep page is frozen: when it wakes,
        #    it first reads its waiting messages, or registers anew; see wake)
        seen = {}
        for s in live.values():
            if not s.alive:
                continue
            for path in s.tabs:
                assert path not in seen, f"{path} usable in Page {seen[path]} and Page {s.number}"
                seen[path] = s.number
        # 2. ownership table is consistent
        for path, owner in server.owner_of.items():
            in_move = path in server.locked and server.transfers[server.locked[path]].source == owner
            assert owner in server.pages or in_move, f"{path} owned by a gone page"
        for page in server.pages.values():
            assert page.files == {p for p, o in server.owner_of.items() if o == page.id}
        for path, transfer_id in server.locked.items():
            assert transfer_id in server.transfers and path in server.transfers[transfer_id].paths
        # 3. what a live page shows matches what it owns, once it has read its messages
        for s in live.values():
            if s.alive and not server.pages[s.id].queue:
                owned = server.pages[s.id].files
                assert s.tabs <= owned, f"Page {s.number} shows {s.tabs - owned} it doesn't own"
                assert owned <= s.tabs | set(s.moving), f"Page {s.number} owns {owned - s.tabs} it doesn't show"
        # 4. numbers are reused, but never two live pages with the same number
        numbers = [p.number for p in server.pages.values()]
        assert len(numbers) == len(set(numbers)), f"two pages share a number: {sorted(numbers)}"
        # 6. a page that has read its messages knows the live pages (its "Move to" menu)
        connected = {p.id for p in server.pages.values() if p.offline_since is None}
        for s in live.values():
            if s.alive and not server.pages[s.id].queue:
                assert set(s.known) == connected, f"Page {s.number} has an old page list"


def run(seed, steps=250):
    sim = Sim(seed)
    sim.new_page()
    for _ in range(steps):
        sim.act()
        try:
            sim.check()
        except AssertionError as e:
            raise AssertionError(f"seed {seed}, after steps {sim.log[-12:]}: {e}") from None
    return sim


@pytest.mark.parametrize("seed", range(300))
def test_random_multi_page_sequences_keep_the_rules(seed):
    run(seed)


def test_the_sequences_cover_the_interesting_cases():
    """The random runs together really exercise moves, cancels, crashes and deliveries."""
    counts = {}
    for seed in range(300):
        for name in run(seed).log:
            counts[name] = counts.get(name, 0) + 1
    for name in ("move", "double_click", "sleep", "wake", "bye", "rename", "trash", "process", "tick",
                 "drop_connection"):
        assert counts.get(name, 0) > 1000, (name, counts)
