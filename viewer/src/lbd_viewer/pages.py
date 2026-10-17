"""Viewer pages: the browser tabs that show the viewer, and the rules for working across them.

A *page* is one browser tab with the viewer open. Several pages can be open at once (to compare
files side by side), so these rules decide who may do what (docs/viewer/folders-and-files.md,
"Several browser tabs"):

1. One owner per open file. A file is open in at most one page, so two pages never hold competing
   unsaved edits of it. `acquire` refuses a file another page owns and names that page.
2. A page is alive while it polls for commands (`poll`). After `stale_after` seconds without a poll,
   or after `bye`, it is gone: its files are released and its queued commands dropped. Page numbers
   are never reused while the viewer runs.
3. Delivery (a double-clicked file): `offer` asks the page that already has the file open to show
   it; other files go to the most recently focused live page, which must acknowledge (`ack`)
   within `ack_timeout`. Otherwise the caller withdraws them and opens a new browser tab instead.
   Never delivered twice, never lost.
4. Moving tabs to another page is a two-step hand-off: `start_transfer` locks the files (still owned
   by the source); the target `claim`s the files with their unsaved state, then `complete`s, which
   moves ownership; only then is the source told to close its tabs. Without completion in time
   (`expire`), the transfer is cancelled and the source keeps everything. A locked file refuses
   other actions (`check_unlocked`) with a message.
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


@dataclass
class Command:
    """A message to one page. `needs_ack` commands wait for the page to confirm (deliveries)."""

    id: int
    kind: str              # open | show | transfer | transfer_done | transfer_cancelled | event
    data: Dict[str, Any]
    needs_ack: bool = False


@dataclass
class Page:
    id: str
    number: int
    last_seen: float
    last_focus: float
    files: Set[str] = field(default_factory=set)
    queue: List[Command] = field(default_factory=list)


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
                 ack_timeout: float = 3.0, transfer_timeout: float = 5.0, new_tab_timeout: float = 15.0):
        self.clock = clock
        self.stale_after = stale_after
        self.ack_timeout = ack_timeout
        self.transfer_timeout = transfer_timeout
        self.new_tab_timeout = new_tab_timeout      # a new browser tab must first load the viewer
        self.pages: Dict[str, Page] = {}
        self.owner_of: Dict[str, str] = {}          # file path -> page id
        self.transfers: Dict[str, Transfer] = {}
        self.locked: Dict[str, str] = {}            # file path -> transfer id
        self.deliveries: Dict[int, Delivery] = {}
        self._numbers = itertools.count(1)
        self._command_ids = itertools.count(1)
        self._changed = threading.Condition(threading.RLock())

    # ---- pages ----------------------------------------------------------------------------------

    def register(self) -> Page:
        with self._changed:
            now = self.clock()
            page = Page(secrets.token_urlsafe(9), next(self._numbers), now, now)
            self.pages[page.id] = page
            return page

    def page(self, page_id: str) -> Page:
        """A live page; UnknownPage if it never existed or is gone."""
        with self._changed:
            self.expire()
            page = self.pages.get(page_id)
            if page is None:
                raise UnknownPage("this viewer page is no longer connected; reload it")
            return page

    def live_pages(self) -> List[Page]:
        with self._changed:
            self.expire()
            return sorted(self.pages.values(), key=lambda p: p.number)

    def focus(self, page_id: str) -> None:
        with self._changed:
            page = self.page(page_id)
            page.last_focus = page.last_seen = self.clock()

    def bye(self, page_id: str) -> None:
        """The page is closing (or reloading)."""
        with self._changed:
            if page_id in self.pages:
                self._remove(self.pages[page_id])

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
            return None

    def release(self, page_id: str, path: str) -> None:
        """`page_id` closed `path`."""
        with self._changed:
            page = self.page(page_id)
            self.check_unlocked(path)
            page.files.discard(path)
            if self.owner_of.get(path) == page_id:
                del self.owner_of[path]

    def check_unlocked(self, path: str) -> None:
        """PageError while `path` is being moved between pages (rule 4)."""
        if path in self.locked:
            raise PageError(f"{path} is being moved to another page; try again in a moment")

    def attention(self) -> Optional[Page]:
        """Ask the most recently focused live page to come forward (a folder was opened). Returns
        that page, or None if no page is open."""
        with self._changed:
            self.expire()
            page = max(self.pages.values(), key=lambda p: p.last_focus, default=None)
            if page is not None:
                self._send(page, "show", {"path": None})
            return page

    def show(self, path: str) -> Optional[Page]:
        """Ask the owner of `path` to show it (switch to it, come forward). Returns that page."""
        with self._changed:
            owner = self.owner(path)
            if owner is not None:
                self._send(owner, "show", {"path": path})
            return owner

    # ---- rule 2: alive while polling ----------------------------------------------------------

    def poll(self, page_id: str) -> Optional[Command]:
        """The next command for the page, or None. Polling keeps the page alive."""
        with self._changed:
            page = self.page(page_id)
            page.last_seen = self.clock()
            return page.queue.pop(0) if page.queue else None

    def wait_for_command(self, page_id: str, timeout: float) -> Optional[Command]:
        """`poll`, waiting up to `timeout` real seconds for a command (the long poll)."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                command = self.poll(page_id)
                left = deadline - time.monotonic()
                if command is not None or left <= 0:
                    return command
                self._changed.wait(left)

    def expire(self) -> None:
        """Remove pages that stopped polling, withdraw their deliveries, cancel late transfers."""
        with self._changed:
            now = self.clock()
            for page in [p for p in self.pages.values() if now - p.last_seen > self.stale_after]:
                self._remove(page)
            for transfer in [t for t in self.transfers.values() if now - t.started > t.timeout]:
                self._cancel(transfer, "the other page didn't take the files in time")

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
            target = max(self.pages.values(), key=lambda p: p.last_focus, default=None)
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
                target = self.page(target_id)
                if target.id == source.id:
                    raise PageError("the files are already in this page")
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
        """The target confirms: it now owns the files; the source is told to close its tabs."""
        with self._changed:
            page = self.page(page_id)
            transfer = self._transfer(transfer_id)
            if transfer.claimed_by != page.id:
                raise PageError("claim the files before completing the move")
            del self.transfers[transfer.id]
            source = self.pages.get(transfer.source)
            for path in transfer.paths:
                del self.locked[path]
                if source is not None:
                    source.files.discard(path)
                page.files.add(path)
                self.owner_of[path] = page.id
            if source is not None:
                self._send(source, "transfer_done", {"id": transfer.id, "paths": transfer.paths, "to": page.number})
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
                self._send(self.pages[page_id], "transfer_cancelled", {"id": transfer.id, "reason": reason})

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
