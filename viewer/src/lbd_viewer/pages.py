"""Viewer pages: the browser tabs that show the viewer, and the rules for working across them.

A *page* is one browser tab with the viewer open. Several pages can be open at once (to compare
files side by side), so these rules decide who may do what (docs/viewer/folders-and-files.md,
"Several browser tabs"):

1. One owner per open file. A file is open in at most one page, so two pages never hold competing
   unsaved edits of it. `acquire` refuses a file another page owns and names that page.
2. A page is alive while it polls for commands (`poll`). It is gone after `bye`, after `stale_after`
   seconds without a poll (asleep, frozen), or after `offline_grace` seconds *offline*, unless it
   polls meanwhile. A page is offline from `register` until its first poll, and when its long-poll
   connection dropped (`connection_lost`: the tab was closed or crashed without saying goodbye).
   An offline page is not offered to the others (a page that registered but never listens, e.g.
   a tab that registered while it closed, never shows up as a target). A gone
   page's files are released and its queued commands dropped. A new page gets the lowest number
   no live page has, so closing Page 2 frees "Page 2". Numbers are only labels for people;
   everything that acts on a page uses its id.
   Commands are never lost: `poll` returns the first command the page hasn't confirmed, and the
   page confirms it with its next poll (`after`), so a command whose answer never arrived (the
   connection dropped) is sent again.
   Every live page is told the list of pages (`pages_changed`) whenever it changes: a page
   came or went, or opened, closed or took files. So its "Move to Page N" menu is always current.
3. Delivery (a double-clicked file): `offer` asks the page that already has the file open to show
   it; other files go to the most recently focused live page, which must acknowledge (`ack`)
   within `ack_timeout`. Otherwise the caller withdraws them and opens a new browser tab instead.
   Never delivered twice, never lost.
4. Moving tabs to another page is a two-step hand-off: `start_transfer` locks the files (still owned
   by the source); the target `claim`s the files with their unsaved state, then `complete`s, which
   moves ownership; only then is the source told to close its tabs. Without completion in time
   (`expire`), the transfer is cancelled and the source keeps everything. A locked file refuses
   other actions (`check_unlocked`) with a message. The target must be a live page
   (`TargetGone` otherwise), and `complete` may be repeated (its answer may have been lost).
5. File events (`broadcast`): renamed, trashed, folders or presets changed, to every live page.

Pure Python with an injectable clock and no HTTP, so every rule is tested directly
(tests/test_pages.py, tests/test_pages_random.py). server.py adapts it to HTTP; the blocking
waits (`wait_for_command`, `wait_for_ack`) use real time.
"""

from __future__ import annotations

import itertools
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


class PageError(Exception):
    """A request that breaks a rule (unknown page, file locked by a move, ...). The message says
    what happened, for the user."""


class UnknownPage(PageError):
    """The page is not registered, or is gone (closed, or no poll for too long)."""


class TargetGone(PageError):
    """Files were to be moved to a page that is closed (or whose connection dropped)."""


@dataclass
class Command:
    """A message to one page. `needs_ack` commands wait for the page to confirm (deliveries)."""

    id: int
    kind: str              # open | show | transfer | transfer_done | transfer_cancelled | event | pages_changed
    data: Dict[str, Any]
    needs_ack: bool = False


@dataclass
class Page:
    id: str
    number: int
    last_seen: float
    last_focus: float
    files: Set[str] = field(default_factory=set)
    queue: List[Command] = field(default_factory=list)   # sent, not yet confirmed by the page
    polls: int = 0                    # how many polls it made; the latest one is the open long poll
    offline_since: Optional[float] = None   # not listening: since registering (no poll yet) or since
                                            # its connection dropped; None while connected


@dataclass
class Transfer:
    id: str
    source: str            # page id
    target: Optional[str]  # page id, or None for "a new browser tab"
    paths: List[str]
    states: Dict[str, Any]
    started: float
    timeout: float
    claimed_by: Optional[str] = None


@dataclass
class Delivery:
    """Files sent to a page, waiting for it to acknowledge. `status`: pending, acked, withdrawn.

    `paths` are the names the page was sent (a sent message is never changed). `current` follows
    renames and deletions that happen before the page acknowledges: name sent -> name now, or
    None if the file was deleted. The page learns about those from the event messages that come
    after the delivery in its queue, in order."""

    command_id: int
    page: str
    paths: List[str]
    sent: float
    status: str = "pending"
    current: Dict[str, Optional[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.current = self.current or {p: p for p in self.paths}


@dataclass
class Offer:
    """The result of `Pages.offer`: what happened to each double-clicked file."""

    shown: List[str]                 # already open in a page, which was asked to show them
    delivery: Optional[Delivery]     # the other files, sent to a page (None: none sent)
    unplaced: List[str]              # files no page could take: open a new browser tab for them
    busy: List[str] = field(default_factory=list)   # being moved between pages: try again later


class Pages:
    def __init__(self, clock: Callable[[], float] = time.monotonic, stale_after: float = 40.0,
                 ack_timeout: float = 3.0, transfer_timeout: float = 5.0, new_tab_timeout: float = 15.0,
                 offline_grace: float = 3.0):
        self.clock = clock
        self.stale_after = stale_after
        self.offline_grace = offline_grace          # offline (new, or connection dropped): time to poll
        self.ack_timeout = ack_timeout
        self.transfer_timeout = transfer_timeout
        self.new_tab_timeout = new_tab_timeout      # a new browser tab must first load the viewer
        self.pages: Dict[str, Page] = {}
        self.owner_of: Dict[str, str] = {}          # file path -> page id
        self.transfers: Dict[str, Transfer] = {}
        self.locked: Dict[str, str] = {}            # file path -> transfer id
        self.deliveries: Dict[int, Delivery] = {}
        self.finished: Dict[str, Transfer] = {}     # completed transfers, kept a while: `complete` may be repeated
        self._listed: Optional[list] = None         # the page list last sent (pages_changed)
        self._command_ids = itertools.count(1)
        self._changed = threading.Condition(threading.RLock())

    # ---- pages ----------------------------------------------------------------------------------

    def register(self) -> Page:
        with self._changed:
            self.expire()                        # pages gone without a goodbye free their numbers
            now = self.clock()
            page = Page(secrets.token_urlsafe(9), self._free_number(), now, now, offline_since=now)
            self.pages[page.id] = page
            self._pages_changed()
            return page

    def _free_number(self) -> int:
        """The lowest page number (1, 2, ...) that no live page has."""
        used = {p.number for p in self.pages.values()}
        return next(n for n in itertools.count(1) if n not in used)

    def page(self, page_id: str) -> Page:
        """A live page; UnknownPage if it never existed or is gone."""
        with self._changed:
            self.expire()
            page = self.pages.get(page_id)
            if page is None:
                raise UnknownPage("this viewer page is no longer connected; reload it")
            return page

    def live_pages(self) -> List[Page]:
        """The pages files can go to, by number (not those whose connection just dropped)."""
        with self._changed:
            self.expire()
            return sorted((p for p in self.pages.values() if p.offline_since is None), key=lambda p: p.number)

    def page_list(self) -> List[Dict[str, Any]]:
        """`live_pages` as sent to the pages: [{"page": id, "number": n, "files": [...]}]."""
        with self._changed:
            self.expire()
            return self._page_list()

    def _page_list(self) -> List[Dict[str, Any]]:
        return [{"page": p.id, "number": p.number, "files": sorted(p.files)}
                for p in sorted(self.pages.values(), key=lambda p: p.number) if p.offline_since is None]

    def focus(self, page_id: str) -> None:
        with self._changed:
            page = self.page(page_id)
            page.last_focus = page.last_seen = self.clock()

    def bye(self, page_id: str) -> None:
        """The page is closing (or reloading)."""
        with self._changed:
            if page_id in self.pages:
                self._remove(self.pages[page_id])
                self._pages_changed()

    # ---- rule 1: one owner per open file ------------------------------------------------------

    def owner(self, path: str) -> Optional[Page]:
        with self._changed:
            self.expire()
            page_id = self.owner_of.get(path)
            return self.pages.get(page_id) if page_id else None

    def acquire(self, page_id: str, path: str) -> Optional[Page]:
        """`page_id` opens `path`. Returns None if that's fine (now owned by it), or the page that
        already has it open (then nothing changes: the caller offers "Show it there")."""
        with self._changed:
            page = self.page(page_id)
            other = self.owner(path)
            if other is not None and other.id != page_id:
                return other
            self.check_unlocked(path)
            page.files.add(path)
            self.owner_of[path] = page_id
            self._pages_changed()
            return None

    def release(self, page_id: str, path: str) -> None:
        """`page_id` closed `path`."""
        with self._changed:
            page = self.page(page_id)
            self.check_unlocked(path)
            page.files.discard(path)
            if self.owner_of.get(path) == page_id:
                del self.owner_of[path]
            self._pages_changed()

    def check_unlocked(self, path: str) -> None:
        """PageError while `path` is being moved between pages (rule 4)."""
        if path in self.locked:
            raise PageError(f"{path} is being moved to another page; try again in a moment")

    def attention(self) -> Optional[Page]:
        """Ask the most recently focused live page to come forward (a folder was opened). Returns
        that page, or None if no page is open."""
        with self._changed:
            page = self._last_focused()
            if page is not None:
                self._send(page, "show", {"path": None})
            return page

    def _last_focused(self) -> Optional[Page]:
        """The live page used last (files and attention go there), or None."""
        return max(self.live_pages(), key=lambda p: p.last_focus, default=None)

    def show(self, path: str) -> Optional[Page]:
        """Ask the owner of `path` to show it (switch to it, come forward). Returns that page."""
        with self._changed:
            owner = self.owner(path)
            if owner is not None:
                self._send(owner, "show", {"path": path})
            return owner

    # ---- rule 2: alive while polling ----------------------------------------------------------

    def poll(self, page_id: str, after: int = 0) -> Optional[Command]:
        """The first command the page hasn't confirmed yet, or None. Polling keeps the page alive.

        `after`: the id of the last command the page handled. That command and the ones before it
        are confirmed and dropped. A command stays queued until confirmed, so if its answer is lost
        (the connection dropped), the next poll sends it again."""
        with self._changed:
            self.start_poll(page_id, after)
            queue = self.pages[page_id].queue
            return queue[0] if queue else None

    def start_poll(self, page_id: str, after: int = 0) -> int:
        """Begin a (long) poll: confirm the commands up to `after`, and mark the page connected.
        Returns the poll's number, for `wait_for_command` and `connection_lost`."""
        with self._changed:
            page = self.page(page_id)
            page.queue = [c for c in page.queue if c.id > after]
            page.last_seen = self.clock()
            page.polls += 1
            if page.offline_since is not None:    # listening (again): offered to the others
                page.offline_since = None
                self._pages_changed()
            return page.polls

    def wait_for_command(self, page_id: str, poll: int, timeout: float) -> Optional[Command]:
        """The long poll started by `start_poll`: wait up to `timeout` real seconds for the first
        unconfirmed command. Returns None after the timeout, or at once if the connection
        dropped or a newer poll of the same page replaced this one."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                page = self.page(page_id)
                if page.polls != poll or page.offline_since is not None:
                    return None
                page.last_seen = self.clock()
                left = deadline - time.monotonic()
                if page.queue or left <= 0:
                    return page.queue[0] if page.queue else None
                self._changed.wait(min(left, 1.0))   # wake every second: expire() runs on time

    def connection_lost(self, page_id: str, poll: int) -> None:
        """The connection of the page's long poll `poll` dropped before it was answered: the tab
        was closed, reloaded or crashed (or the network failed). Unless the page polls again
        within `offline_grace`, it is gone. Nothing if a newer poll already replaced that one."""
        with self._changed:
            page = self.pages.get(page_id)
            if page is None or page.polls != poll or page.offline_since is not None:
                return
            page.offline_since = self.clock()
            self._pages_changed()                 # no longer offered to the others
            self._changed.notify_all()            # the waiting poll ends

    def expire(self) -> None:
        """Remove pages that stopped polling or lost their connection, withdraw their deliveries,
        cancel late transfers."""
        with self._changed:
            now = self.clock()
            for page in [p for p in self.pages.values() if self._gone(p, now)]:
                self._remove(page)
            for transfer in [t for t in self.transfers.values() if now - t.started > t.timeout]:
                self._cancel(transfer, "the other page didn't take the files in time")
            for transfer_id in [i for i, t in self.finished.items() if now - t.started > 60]:
                del self.finished[transfer_id]
            self._pages_changed()

    def _gone(self, page: Page, now: float) -> bool:
        if page.offline_since is not None and now - page.offline_since > self.offline_grace:
            return True
        return now - page.last_seen > self.stale_after

    # ---- rule 3: delivery ---------------------------------------------------------------------

    def offer(self, paths: List[str]) -> Offer:
        """Place double-clicked files. A file already open in a page is shown there (rule 1: no
        second copy); a file being moved is shown in the page it is moving from; the others are
        sent to the most recently focused live page, which must `ack`. With no page open they are
        `unplaced` (the caller opens a new browser tab)."""
        with self._changed:
            self.expire()
            shown, rest, busy = [], [], []
            for path in paths:
                transfer = self.transfers.get(self.locked.get(path, ""))
                if transfer is not None:                  # rule 4: never handed to a third page
                    source = self.pages.get(transfer.source)
                    if source is not None:
                        self._send(source, "show", {"path": path})
                        shown.append(path)
                    else:
                        busy.append(path)
                elif (owner := self.owner(path)) is not None:
                    self._send(owner, "show", {"path": path})
                    shown.append(path)
                else:
                    rest.append(path)
            target = self._last_focused()
            if not rest or target is None:
                return Offer(shown, None, rest, busy)
            command = self._send(target, "open", {"paths": list(rest)}, needs_ack=True)
            delivery = Delivery(command.id, target.id, list(rest), self.clock())
            self.deliveries[command.id] = delivery
            return Offer(shown, delivery, [], busy)

    def ack(self, page_id: str, command_id: int) -> Dict[str, Any]:
        """The page confirms a delivery. It owns the files it may open now ("granted"). A file
        another page opened meanwhile stays there ("elsewhere": path -> page number), and a file
        that started moving between pages meanwhile is "busy"; the page shows only the granted
        ones and says why for the others. A withdrawn delivery (too late): PageError."""
        with self._changed:
            page = self.page(page_id)
            delivery = self.deliveries.get(command_id)
            if delivery is None or delivery.page != page_id:
                raise PageError("this delivery was withdrawn (it came too late); the file was opened in a new browser tab")
            del self.deliveries[command_id]
            delivery.status = "acked"
            granted, elsewhere, busy = [], {}, []
            for sent in delivery.paths:                  # names as the page knows them
                now = delivery.current[sent]              # renamed or deleted meanwhile?
                if now is None:
                    granted.append(sent)                  # deleted: its "trashed" message follows
                    continue
                other = self.owner(now)
                if now in self.locked:
                    busy.append(sent)
                elif other is not None and other.id != page_id:
                    elsewhere[sent] = other.number
                else:
                    page.files.add(now)
                    self.owner_of[now] = page_id
                    granted.append(sent)
            self._pages_changed()
            self._changed.notify_all()
            return {"granted": granted, "elsewhere": elsewhere, "busy": busy}

    def wait_for_ack(self, delivery: Delivery, timeout: Optional[float] = None) -> bool:
        """Wait up to `timeout` real seconds (default ack_timeout) for the page to acknowledge.
        If it doesn't (or the page goes away), the delivery is withdrawn and False returned:
        the caller opens a new browser tab instead."""
        deadline = time.monotonic() + (self.ack_timeout if timeout is None else timeout)
        with self._changed:
            while delivery.status == "pending":
                left = deadline - time.monotonic()
                if left <= 0:
                    self.withdraw(delivery)
                    break
                self._changed.wait(left)
            return delivery.status == "acked"

    def withdraw(self, delivery: Delivery) -> None:
        """Take back an unacknowledged delivery, also out of the page's queue if still there."""
        with self._changed:
            if delivery.status != "pending":
                return
            delivery.status = "withdrawn"
            self.deliveries.pop(delivery.command_id, None)
            page = self.pages.get(delivery.page)
            if page is not None:
                page.queue = [c for c in page.queue if c.id != delivery.command_id]
            self._changed.notify_all()

    # ---- rule 4: moving tabs ------------------------------------------------------------------

    def start_transfer(self, source_id: str, paths: List[str], states: Dict[str, Any],
                       target_id: Optional[str]) -> Transfer:
        """Begin moving `paths` (owned by the source) to `target_id`, or to a new browser tab (None).
        The files stay with the source and are locked until the target completes."""
        with self._changed:
            source = self.page(source_id)
            if not paths:
                raise PageError("no files selected to move")
            if target_id is not None:
                target = self.pages.get(target_id)
                if target is not None and target.id == source.id:
                    raise PageError("the files are already in this page")
                if target is None or target.offline_since is not None:
                    raise TargetGone("that page was closed; the files stay here")
            for path in paths:
                if self.owner_of.get(path) != source_id:
                    raise PageError(f"{path} is not open in this page")
                self.check_unlocked(path)
            transfer = Transfer(secrets.token_urlsafe(9), source_id, target_id, list(paths),
                                dict(states), self.clock(),
                                self.transfer_timeout if target_id else self.new_tab_timeout)
            self.transfers[transfer.id] = transfer
            for path in paths:
                self.locked[path] = transfer.id
            if target_id is not None:
                self._send(self.pages[target_id], "transfer", {"id": transfer.id, "from": source.number})
            return transfer

    def claim(self, transfer_id: str, page_id: str) -> Transfer:
        """The target takes the files and their unsaved state (it shows them after `complete`)."""
        with self._changed:
            page = self.page(page_id)
            transfer = self._transfer(transfer_id)
            if transfer.target not in (None, page.id) or page.id == transfer.source:
                raise PageError("these files are being moved to another page")
            if transfer.claimed_by not in (None, page.id):
                raise PageError("another page already took these files")
            transfer.claimed_by = page.id
            return transfer

    def complete(self, transfer_id: str, page_id: str) -> List[str]:
        """The target confirms: it now owns the files; the source is told to close its tabs.
        Asking again (the first answer was lost) gives the same answer."""
        with self._changed:
            page = self.page(page_id)
            done = self.finished.get(transfer_id)
            if done is not None and done.claimed_by == page.id:
                return done.paths
            transfer = self._transfer(transfer_id)
            if transfer.claimed_by != page.id:
                raise PageError("claim the files before completing the move")
            del self.transfers[transfer.id]
            self.finished[transfer.id] = transfer
            source = self.pages.get(transfer.source)
            for path in transfer.paths:
                del self.locked[path]
                if source is not None:
                    source.files.discard(path)
                page.files.add(path)
                self.owner_of[path] = page.id
            if source is not None:
                self._send(source, "transfer_done", {"id": transfer.id, "paths": transfer.paths, "to": page.number})
            self._pages_changed()
            return transfer.paths

    def cancel_transfer(self, transfer_id: str, reason: str) -> None:
        with self._changed:
            self._cancel(self._transfer(transfer_id), reason)

    # ---- rule 5: events -----------------------------------------------------------------------

    def broadcast(self, event: str, **data: Any) -> None:
        """Tell every live page about a change: renamed(old, new), trashed(path), roots_changed,
        styles_changed. A rename also moves the file's ownership to the new name."""
        with self._changed:
            self.expire()
            if event == "renamed":
                old, new = data["old"], data["new"]
                owner = self.owner_of.pop(old, None)
                if owner is not None:
                    self.owner_of[new] = owner
                    self.pages[owner].files.discard(old)
                    self.pages[owner].files.add(new)
                self._rewrite_pending(lambda path: new if path == old else path)
            elif event == "trashed":
                owner = self.owner_of.pop(data["path"], None)
                if owner is not None:
                    self.pages[owner].files.discard(data["path"])
                self._rewrite_pending(lambda path: None if path == data["path"] else path)
            for page in self.pages.values():
                self._send(page, "event", {"event": event, **data})
            self._pages_changed()

    def _rewrite_pending(self, change: Callable[[str], Optional[str]]) -> None:
        """Deliveries not yet acknowledged follow a rename (new name) or a deletion (None), so the
        acknowledgement records the file under its current name. Sent messages stay as they are:
        the page reads the rename or deletion right after them, in order."""
        for delivery in self.deliveries.values():
            for sent, now in delivery.current.items():
                if now is not None:
                    delivery.current[sent] = change(now)

    # ---- internals ----------------------------------------------------------------------------

    def _send(self, page: Page, kind: str, data: Dict[str, Any], needs_ack: bool = False) -> Command:
        command = Command(next(self._command_ids), kind, data, needs_ack)
        page.queue.append(command)
        self._changed.notify_all()
        return command

    def _pages_changed(self) -> None:
        """If the page list changed since it was last sent, send it to every page. Each list is
        complete, so an older one still queued is replaced: the queue doesn't grow."""
        listed = self._page_list()
        if listed == self._listed:
            return
        self._listed = listed
        for page in self.pages.values():
            page.queue = [c for c in page.queue if c.kind != "pages_changed"]
            self._send(page, "pages_changed", {"pages": listed})

    def _transfer(self, transfer_id: str) -> Transfer:
        self.expire()
        transfer = self.transfers.get(transfer_id)
        if transfer is None:
            raise PageError("this move is over: it was completed or cancelled")
        return transfer

    def _cancel(self, transfer: Transfer, reason: str) -> None:
        """The files stay with the source (or, if the source is gone too, are open nowhere)."""
        self.transfers.pop(transfer.id, None)
        source_alive = transfer.source in self.pages
        for path in transfer.paths:
            self.locked.pop(path, None)
            if not source_alive and self.owner_of.get(path) == transfer.source:
                del self.owner_of[path]
        for page_id in {transfer.source, transfer.claimed_by} - {None}:
            if page_id in self.pages:
                self._send(self.pages[page_id], "transfer_cancelled",
                           {"id": transfer.id, "paths": transfer.paths, "reason": reason})

    def _remove(self, page: Page) -> None:
        del self.pages[page.id]
        for path in [p for p, owner in self.owner_of.items() if owner == page.id]:
            if path not in self.locked:        # a file being moved belongs to its transfer
                del self.owner_of[path]
        for command_id in [c for c, d in self.deliveries.items() if d.page == page.id]:
            self.deliveries.pop(command_id).status = "withdrawn"
        for transfer in [t for t in self.transfers.values() if page.id in (t.target, t.claimed_by)]:
            self._cancel(transfer, f"Page {page.number} was closed")
        self._changed.notify_all()
