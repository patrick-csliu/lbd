"""The rules for several viewer pages (lbd_viewer/pages.py), one by one, with a fake clock."""

import pytest

from lbd_viewer.pages import PageError, Pages, TargetGone, UnknownPage


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def pages(clock):
    return Pages(clock=clock, stale_after=40, ack_timeout=3, transfer_timeout=5, new_tab_timeout=15)


def listening(pages):
    """A browser tab with the viewer: it registers, then listens for commands (its long poll).
    Only then is it offered to the other pages."""
    page = pages.register()
    pages.start_poll(page.id)
    return page


def drain(pages, page, lists=False):
    """All queued commands of a page, as (kind, data), each confirmed by the next poll as the web
    page does. The page lists (pages_changed) are left out unless `lists`."""
    out, last = [], 0
    while (command := pages.poll(page.id, after=last)) is not None:
        last = command.id
        if lists or command.kind != "pages_changed":
            out.append((command.kind, command.data))
    return out


def queued(pages, page, kind):
    """The first queued command of this kind (e.g. a delivery to acknowledge)."""
    return next(c for c in pages.pages[page.id].queue if c.kind == kind)


# ---- pages -------------------------------------------------------------------------------------


def test_pages_are_numbered_and_a_closed_page_frees_its_number(pages):
    one, two, three = listening(pages), listening(pages), listening(pages)
    assert (one.number, two.number, three.number) == (1, 2, 3)
    pages.bye(one.id)
    pages.bye(two.id)
    assert listening(pages).number == 1          # the lowest free number
    assert listening(pages).number == 2
    assert listening(pages).number == 4         # 1, 2 and 3 are taken


def test_a_page_gone_without_goodbye_frees_its_number_only_when_it_expires(pages, clock):
    one, two = listening(pages), listening(pages)
    clock.now = 30
    pages.poll(two.id)                           # two keeps polling, one doesn't
    assert listening(pages).number == 3          # one may only be asleep: its number is kept
    clock.now = 41
    assert listening(pages).number == 1          # one is gone now


def test_a_page_that_stops_polling_is_gone_and_releases_its_files(pages, clock):
    one, two = listening(pages), listening(pages)
    assert pages.acquire(one.id, "a.lbd") is None
    clock.now = 30
    pages.poll(two.id)                           # two keeps polling, one doesn't
    clock.now = 41
    assert [p.number for p in pages.live_pages()] == [2]
    assert pages.owner("a.lbd") is None
    with pytest.raises(UnknownPage, match="reload"):
        pages.poll(one.id)


def test_a_page_whose_connection_dropped_is_gone_unless_it_polls_again_soon(pages, clock):
    one, two, three = listening(pages), listening(pages), listening(pages)
    pages.acquire(one.id, "a.lbd")
    pages.connection_lost(one.id, pages.start_poll(one.id))     # tab closed without a goodbye
    assert [p.number for p in pages.live_pages()] == [2, 3]     # not offered any more, at once
    clock.now = 2
    pages.connection_lost(two.id, pages.start_poll(two.id))     # a network hiccup...
    clock.now = 3.5
    pages.start_poll(two.id)                                  # ...and two polls again in time
    clock.now = 4
    pages.expire()
    assert sorted(p.number for p in pages.live_pages()) == [2, 3]
    assert one.id not in pages.pages and pages.owner("a.lbd") is None   # one is gone, its file free
    assert listening(pages).number == 1


def test_a_page_that_registers_but_never_listens_is_never_offered_and_soon_gone(pages, clock):
    """A closing tab can still register (the answer to its last poll arrives as it closes). It
    never listens, so it must not show up as a target, and it is gone after the grace time."""
    one = listening(pages)
    pages.acquire(one.id, "a.lbd")
    ghost = pages.register()
    assert [p.id for p in pages.live_pages()] == [one.id]       # not listed...
    with pytest.raises(TargetGone):                              # ...not a target...
        pages.start_transfer(one.id, ["a.lbd"], {}, ghost.id)
    clock.now = 1
    pages.focus(ghost.id)
    assert pages.offer(["b.lbd"]).delivery.page == one.id         # ...gets no files
    clock.now = 4
    pages.poll(one.id)
    assert ghost.id not in pages.pages                           # gone after offline_grace


def test_a_new_page_is_listed_once_it_listens(pages):
    one = listening(pages)
    two = pages.register()
    assert [p.number for p in pages.live_pages()] == [1]
    pages.start_poll(two.id)
    assert [p.number for p in pages.live_pages()] == [1, 2]
    assert [[p["number"] for p in d["pages"]] for k, d in drain(pages, one, lists=True) if k == "pages_changed"] == [[1, 2]]


def test_a_dropped_connection_of_an_older_poll_doesnt_count(pages):
    one = listening(pages)
    old = pages.start_poll(one.id)
    pages.start_poll(one.id)                     # the page polls again (the old answer was lost)
    pages.connection_lost(one.id, old)           # the old connection is noticed late
    assert [p.id for p in pages.live_pages()] == [one.id]


def test_a_page_whose_connection_dropped_gets_no_files(pages, clock):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "a.lbd")
    clock.now = 1
    pages.focus(two.id)                          # two was used last...
    pages.connection_lost(two.id, pages.start_poll(two.id))   # ...but its tab was just closed
    offer = pages.offer(["b.lbd"])
    assert offer.delivery.page == one.id
    with pytest.raises(TargetGone, match="that page was closed"):
        pages.start_transfer(one.id, ["a.lbd"], {}, two.id)
    assert pages.attention().id == one.id


def test_a_command_is_sent_again_until_the_page_confirms_it(pages):
    one = listening(pages)
    drain(pages, one)
    pages.broadcast("styles_changed")
    first = pages.poll(one.id)                   # the answer is lost on the way...
    again = pages.poll(one.id)                   # ...so the page asks again, confirming nothing new
    assert first.id == again.id and first.data == {"event": "styles_changed"}
    assert pages.poll(one.id, after=again.id) is None       # confirmed: the next poll has nothing


def test_every_page_is_told_the_page_list_when_it_changes(pages):
    one = listening(pages)

    def lists():
        return [[(p["number"], p["files"]) for p in d["pages"]] for k, d in drain(pages, one, lists=True) if k == "pages_changed"]

    assert lists() == [[(1, [])]]
    two = listening(pages)
    pages.acquire(two.id, "a.lbd")
    assert lists() == [[(1, []), (2, ["a.lbd"])]]          # one list, the latest: older ones replaced
    pages.acquire(two.id, "a.lbd")                          # nothing changed: nothing sent
    assert lists() == []
    transfer = pages.start_transfer(two.id, ["a.lbd"], {}, one.id)
    pages.claim(transfer.id, one.id)
    pages.complete(transfer.id, one.id)
    assert lists() == [[(1, ["a.lbd"]), (2, [])]]
    pages.release(one.id, "a.lbd")
    assert lists() == [[(1, []), (2, [])]]
    pages.connection_lost(two.id, pages.start_poll(two.id))
    assert lists() == [[(1, [])]]                           # left out at once
    pages.start_poll(two.id)
    assert lists() == [[(1, []), (2, [])]]                  # back in time
    pages.bye(two.id)
    assert lists() == [[(1, [])]]


# ---- rule 1: one owner per open file ----------------------------------------------------------


def test_a_file_is_open_in_one_page_only(pages):
    one, two = listening(pages), listening(pages)
    assert pages.acquire(one.id, "a.lbd") is None
    assert pages.acquire(one.id, "a.lbd") is None          # again in the same page: fine
    assert pages.acquire(two.id, "a.lbd").number == 1      # refused: open in Page 1
    assert pages.owner("a.lbd").id == one.id
    pages.release(one.id, "a.lbd")
    assert pages.acquire(two.id, "a.lbd") is None


def test_show_asks_the_owner(pages):
    one = listening(pages)
    pages.acquire(one.id, "a.lbd")
    assert pages.show("a.lbd").id == one.id
    assert drain(pages, one) == [("show", {"path": "a.lbd"})]
    assert pages.show("b.lbd") is None


# ---- rule 3: delivery -------------------------------------------------------------------------


def test_delivery_goes_to_the_most_recently_focused_page(pages, clock):
    one, two = listening(pages), listening(pages)
    clock.now = 1
    pages.focus(one.id)
    offer = pages.offer(["a.lbd"])
    assert offer.delivery.page == one.id and offer.shown == [] and offer.unplaced == []
    (kind, data), = drain(pages, one)
    assert kind == "open" and data == {"paths": ["a.lbd"]}
    assert drain(pages, two) == []


def test_delivery_acknowledged_makes_the_page_the_owner(pages):
    one = listening(pages)
    offer = pages.offer(["a.lbd", "b.lbd"])
    command = queued(pages, one, "open")
    assert pages.ack(one.id, command.id) == {"granted": ["a.lbd", "b.lbd"], "elsewhere": {}, "busy": []}
    assert offer.delivery.status == "acked"
    assert pages.owner("b.lbd").id == one.id


def test_an_already_open_file_is_shown_where_it_is(pages, clock):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "a.lbd")
    clock.now = 1
    pages.focus(two.id)                           # two is more recent, but one has the file
    offer = pages.offer(["a.lbd", "b.lbd"])
    assert offer.shown == ["a.lbd"] and offer.delivery.paths == ["b.lbd"] and offer.delivery.page == two.id
    assert drain(pages, one) == [("show", {"path": "a.lbd"})]


def test_no_page_open_means_a_new_browser_tab(pages):
    offer = pages.offer(["a.lbd"])
    assert offer.delivery is None and offer.unplaced == ["a.lbd"]


def test_an_unacknowledged_delivery_is_withdrawn_and_never_arrives_late(pages):
    one = listening(pages)
    offer = pages.offer(["a.lbd"])
    assert pages.wait_for_ack(offer.delivery, timeout=0.01) is False
    assert offer.delivery.status == "withdrawn"
    assert drain(pages, one) == []                # out of the queue: never opened twice
    with pytest.raises(PageError, match="withdrawn"):
        pages.ack(one.id, offer.delivery.command_id)


def test_a_delivery_to_a_page_that_goes_away_is_withdrawn(pages, clock):
    one = listening(pages)
    offer = pages.offer(["a.lbd"])
    clock.now = 41                                # the page stopped polling
    pages.expire()
    assert offer.delivery.status == "withdrawn"
    assert pages.wait_for_ack(offer.delivery, timeout=0.01) is False


def test_a_file_opened_elsewhere_meanwhile_stays_there(pages):
    one, two = listening(pages), listening(pages)
    pages.focus(one.id)
    offer = pages.offer(["a.lbd"])
    pages.acquire(two.id, "a.lbd")                # two opened it from its folder panel first
    result = pages.ack(one.id, queued(pages, one, "open").id)
    assert result == {"granted": [], "elsewhere": {"a.lbd": 2}, "busy": []}
    assert pages.owner("a.lbd").id == two.id


# ---- rule 4: moving tabs ----------------------------------------------------------------------


def test_moving_tabs_to_another_page(pages):
    one, two = listening(pages), listening(pages)
    for f in ("1.lbd", "2.lbd", "3.lbd"):
        pages.acquire(one.id, f)
    transfer = pages.start_transfer(one.id, ["1.lbd", "2.lbd"], {"1.lbd": {"kind": "heatmap"}}, two.id)
    assert pages.owner("1.lbd").id == one.id      # still the source's until completed
    (kind, data), = drain(pages, two)
    assert kind == "transfer" and data["from"] == 1
    claimed = pages.claim(data["id"], two.id)
    assert claimed.states == {"1.lbd": {"kind": "heatmap"}}   # unsaved changes travel along
    assert pages.complete(transfer.id, two.id) == ["1.lbd", "2.lbd"]
    assert pages.owner("1.lbd").id == two.id and pages.owner("3.lbd").id == one.id
    assert drain(pages, one) == [("transfer_done", {"id": transfer.id, "paths": ["1.lbd", "2.lbd"], "to": 2})]


def test_moving_to_a_new_browser_tab(pages):
    one = listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {}, None)
    new = listening(pages)                         # the new tab loads with ?claim=<id>
    pages.claim(transfer.id, new.id)
    pages.complete(transfer.id, new.id)
    assert pages.owner("1.lbd").id == new.id


def test_completing_again_gives_the_same_answer(pages):
    one, two, three = listening(pages), listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    pages.claim(transfer.id, two.id)
    assert pages.complete(transfer.id, two.id) == ["1.lbd"]
    assert pages.complete(transfer.id, two.id) == ["1.lbd"]    # the first answer was lost: ask again
    with pytest.raises(PageError, match="over"):
        pages.complete(transfer.id, three.id)                  # but only the page that took them
    done = [k for k, _ in drain(pages, one) if k == "transfer_done"]
    assert done == ["transfer_done"]                           # the source is told once


def test_files_being_moved_are_locked(pages):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    with pytest.raises(PageError, match="being moved"):
        pages.release(one.id, "1.lbd")
    with pytest.raises(PageError, match="being moved"):
        pages.start_transfer(one.id, ["1.lbd"], {}, None)
    with pytest.raises(PageError, match="being moved"):
        pages.check_unlocked("1.lbd")              # e.g. "Save this view" during a move


def test_a_move_not_completed_in_time_is_cancelled_and_the_source_keeps_its_tabs(pages, clock):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    clock.now = 6
    pages.focus(one.id)                           # alive, without reading their messages
    pages.focus(two.id)
    pages.expire()
    assert pages.owner("1.lbd").id == one.id
    pages.check_unlocked("1.lbd")                  # unlocked again
    assert ("transfer_cancelled", {"id": transfer.id, "paths": ["1.lbd"], "reason": "the other page didn't take the files in time"}) in drain(pages, one)
    with pytest.raises(PageError, match="over"):
        pages.claim(transfer.id, two.id)


def test_a_late_completion_after_cancel_is_refused(pages, clock):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    pages.claim(transfer.id, two.id)
    clock.now = 6
    pages.focus(one.id)                           # alive, without reading their messages
    pages.focus(two.id)
    with pytest.raises(PageError, match="over"):   # the target must not show the files
        pages.complete(transfer.id, two.id)
    assert pages.owner("1.lbd").id == one.id
    assert any(kind == "transfer_cancelled" for kind, _ in drain(pages, two))


def test_the_target_closing_cancels_the_move(pages):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    pages.bye(two.id)
    assert pages.owner("1.lbd").id == one.id
    assert [k for k, d in drain(pages, one) if k == "transfer_cancelled" and "Page 2 was closed" in d["reason"]]


def test_the_source_closing_does_not_stop_the_move(pages):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {"1.lbd": {"x": 1}}, two.id)
    pages.bye(one.id)                              # the unsaved state is already with the transfer
    pages.claim(transfer.id, two.id)
    pages.complete(transfer.id, two.id)
    assert pages.owner("1.lbd").id == two.id


def test_a_cancelled_move_from_a_closed_page_leaves_the_file_open_nowhere(pages, clock):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    pages.bye(one.id)
    clock.now = 6
    pages.poll(two.id)
    pages.expire()
    assert pages.owner("1.lbd") is None and pages.owner_of == {}


@pytest.mark.parametrize("case, message", [
    ("nothing", "no files selected"),
    ("not-owned", "not open in this page"),
    ("same-page", "already in this page"),
])
def test_moves_that_make_no_sense_are_refused(pages, case, message):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.acquire(two.id, "2.lbd")
    args = {"nothing": ([], two.id), "not-owned": (["2.lbd"], two.id), "same-page": (["1.lbd"], one.id)}[case]
    with pytest.raises(PageError, match=message):
        pages.start_transfer(one.id, args[0], {}, args[1])


def test_only_the_target_may_claim(pages):
    one, two, three = listening(pages), listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    transfer = pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    with pytest.raises(PageError, match="another page"):
        pages.claim(transfer.id, three.id)
    with pytest.raises(PageError, match="claim"):
        pages.complete(transfer.id, two.id)        # complete before claim


def test_a_double_clicked_file_being_moved_is_shown_in_its_source(pages):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    drain(pages, two)
    offer = pages.offer(["1.lbd"])
    assert offer.shown == ["1.lbd"] and offer.delivery is None


# ---- rule 5: events ---------------------------------------------------------------------------


def test_events_reach_every_page_and_renames_move_ownership(pages):
    one, two = listening(pages), listening(pages)
    pages.acquire(one.id, "old.lbd")
    pages.broadcast("renamed", old="old.lbd", new="new.lbd")
    assert pages.owner("new.lbd").id == one.id and pages.owner("old.lbd") is None
    pages.broadcast("trashed", path="new.lbd")
    assert pages.owner("new.lbd") is None
    pages.broadcast("roots_changed")
    for page in (one, two):
        events = [d["event"] for k, d in drain(pages, page) if k == "event"]
        assert events == ["renamed", "trashed", "roots_changed"]


def test_the_long_poll_returns_a_command_at_once(pages):
    import threading

    one = listening(pages)
    drain(pages, one)
    threading.Timer(0.05, lambda: pages.broadcast("styles_changed")).start()
    command = pages.wait_for_command(one.id, pages.start_poll(one.id), timeout=5)
    assert command.kind == "event" and command.data == {"event": "styles_changed"}
    poll = pages.start_poll(one.id, after=command.id)
    assert pages.wait_for_command(one.id, poll, timeout=0.01) is None   # nothing: returns after its timeout


def test_waiting_for_an_ack_ends_when_the_page_acknowledges(pages):
    import threading

    one = listening(pages)
    offer = pages.offer(["a.lbd"])
    threading.Timer(0.05, lambda: pages.ack(one.id, queued(pages, one, "open").id)).start()
    assert pages.wait_for_ack(offer.delivery, timeout=5) is True


# ---- cases found by the randomized test (test_pages_random.py) --------------------------------


def test_a_file_renamed_before_the_page_acknowledges_is_owned_under_its_new_name(pages):
    one = listening(pages)
    offer = pages.offer(["old.lbd"])
    pages.broadcast("renamed", old="old.lbd", new="new.lbd")
    queue = [(c.kind, c.data) for c in pages.pages[one.id].queue if c.kind != "pages_changed"]
    assert queue[0] == ("open", {"paths": ["old.lbd"]})      # sent messages never change...
    assert queue[1][1]["event"] == "renamed"                  # ...the rename follows, in order
    result = pages.ack(one.id, offer.delivery.command_id)
    assert result["granted"] == ["old.lbd"]                    # the page opens the name it was sent
    assert pages.owner("new.lbd").id == one.id and pages.owner("old.lbd") is None


def test_a_file_deleted_before_the_page_acknowledges_is_owned_by_nobody(pages):
    one = listening(pages)
    offer = pages.offer(["a.lbd"])
    pages.broadcast("trashed", path="a.lbd")
    assert pages.ack(one.id, offer.delivery.command_id)["granted"] == ["a.lbd"]   # then "trashed" closes it
    assert pages.owner("a.lbd") is None


def test_a_file_moving_from_a_closed_page_is_never_handed_to_a_third_page(pages):
    one, two, three = listening(pages), listening(pages), listening(pages)
    pages.acquire(one.id, "1.lbd")
    pages.start_transfer(one.id, ["1.lbd"], {}, two.id)
    pages.bye(one.id)                                          # the move goes on without its source
    offer = pages.offer(["1.lbd"])
    assert offer.busy == ["1.lbd"] and offer.delivery is None and offer.unplaced == []
    with pytest.raises(PageError, match="being moved"):
        pages.acquire(three.id, "1.lbd")


def test_a_file_that_started_moving_before_the_ack_is_busy(pages, clock):
    one, two = listening(pages), listening(pages)
    clock.now = 1
    pages.focus(two.id)
    offer = pages.offer(["1.lbd"])                             # to Page 2...
    pages.acquire(one.id, "1.lbd")                             # ...but Page 1 opened it meanwhile
    pages.start_transfer(one.id, ["1.lbd"], {}, None)          # and started moving it
    assert pages.ack(two.id, offer.delivery.command_id) == {"granted": [], "elsewhere": {}, "busy": ["1.lbd"]}
