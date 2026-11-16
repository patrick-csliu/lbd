"""The viewer stops by itself only when no page is open (plan 16.17), also after the computer slept."""

from lbd_viewer.cli import WAKE_GRACE, IdleWatch


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def run(watch: IdleWatch, clock: Clock, seconds: float, heartbeat=None) -> bool:
    """Tick the watch for `seconds`; True as soon as it says stop. `heartbeat(now)` -> the time
    of the last heartbeat at that moment."""
    end = clock.now + seconds
    while clock.now < end:
        clock.now += IdleWatch.TICK
        if watch.should_stop(heartbeat(clock.now) if heartbeat else None, started=0.0):
            return True
    return False


def test_it_stops_after_the_idle_time_without_a_page():
    clock = Clock()
    watch = IdleWatch(90, clock)
    last = clock.now
    assert not run(watch, clock, 88, lambda now: last)
    assert run(watch, clock, 6, lambda now: last)


def test_an_open_page_keeps_it_running():
    clock = Clock()
    watch = IdleWatch(90, clock)
    assert not run(watch, clock, 3600, lambda now: now - (now % 10))   # a heartbeat every 10 s


def test_a_heartbeat_soon_after_the_computer_wakes_keeps_it_running():
    clock = Clock()
    watch = IdleWatch(90, clock)
    assert not run(watch, clock, 10, lambda now: now - (now % 10))
    slept_at = clock.now
    clock.now += 3600                                    # asleep for an hour: no tick, no heartbeat
    woke = clock.now
    assert not run(watch, clock, 9, lambda now: slept_at if now < woke + 9 else now)
    assert not run(watch, clock, 600, lambda now: now - (now % 10))


def test_without_a_page_it_stops_shortly_after_waking():
    clock = Clock()
    watch = IdleWatch(90, clock)
    last = clock.now
    clock.now += 3600
    assert not watch.should_stop(last, started=0.0)       # the first look after waking: not yet
    assert run(watch, clock, WAKE_GRACE + 2 * IdleWatch.TICK, lambda now: last)


def test_never_with_idle_zero():
    clock = Clock()
    watch = IdleWatch(0, clock)
    clock.now += 10_000
    assert not watch.should_stop(None, started=0.0)
