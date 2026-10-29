"""The Library's previews (plan 8c): the cache of automatic pictures and what gets drawn when."""

import os
import shutil
import time
from concurrent.futures.process import BrokenProcessPool

import numpy as np
import pytest

import lbd
from lbd_viewer import previews
from lbd_viewer.config import ConfigError, previews_mode
from lbd_viewer.previews import PreviewCache, Previewer, file_version


def write(path, n=50, title="t"):
    x = np.linspace(0, 1, n)
    d = lbd.Dataset(title=title)
    d.add_axis("x", x)
    d.add_value("y", np.sin(5 * x), axes=["x"])
    d.save(path)
    return str(path)


def wait_for(check, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


class World:
    """A Previewer over a folder, with the Library's answers made by hand."""

    def __init__(self, tmp_path, cfg, mode="all", processes=False):
        self.folder = tmp_path / "files"
        self.folder.mkdir()
        self.mode, self.generation, self.chosen = mode, 0, set()
        self.files = {}
        self.p = Previewer(PreviewCache(tmp_path / "cache"), lambda: dict(self.files), lambda: self.generation,
                           lambda: self.mode, lambda: cfg.resolve().model_dump(), chosen=lambda p: p in self.chosen,
                           processes=processes)

    def add(self, name, **kw):
        path = write(self.folder / name, **kw)
        self.files[path] = file_version(path)
        self.generation += 1
        return path

    def drawn(self, path):
        row = self.p.cache.get(path)
        return row is not None and row["version"] == file_version(path)


@pytest.fixture()
def world(tmp_path, cfg):
    w = World(tmp_path, cfg)
    yield w
    w.p.close()


def test_every_file_is_drawn_in_the_background(world):
    paths = [world.add(f"{i}.lbd") for i in range(3)]
    world.p.start()
    assert wait_for(lambda: all(world.drawn(p) for p in paths))
    assert wait_for(lambda: world.p.status["drawn"] == 3 and world.p.status["total"] == 3)


def test_a_current_picture_is_given_at_once_and_a_changed_file_drawn_again(world):
    path = world.add("a.lbd")
    world.p.start()
    assert wait_for(lambda: world.drawn(path))
    first = world.p.answer(path)
    assert first["picture"] and first["error"] is None
    time.sleep(0.02)
    write(path, n=80)                                   # more data
    world.files[path] = file_version(path)
    assert world.p.answer(path) == {"state": "drawing"}
    assert wait_for(lambda: world.drawn(path))
    assert world.p.answer(path)["picture"] != first["picture"]


def test_a_style_change_keeps_the_pictures(world, cfg):
    path = world.add("a.lbd")
    world.p.start()
    assert wait_for(lambda: world.drawn(path))
    before = world.p.answer(path)["picture"]
    world.p.style = lambda: pytest.fail("a style change must not redraw a current picture")
    world.generation += 1                                # the index changed (and so might the style)
    time.sleep(1.5)
    assert world.p.answer(path)["picture"] == before


def test_nearby_draws_only_what_is_asked(world):
    world.mode = "nearby"
    a, b = world.add("a.lbd"), world.add("b.lbd")
    world.p.start()
    time.sleep(1.5)
    assert not world.drawn(a) and not world.drawn(b)
    world.p.want([b], now=False)
    assert wait_for(lambda: world.drawn(b))
    assert world.p.answer(a) == {"state": "drawing"}       # selected: drawn now
    assert wait_for(lambda: world.drawn(a))


def test_off_draws_nothing_until_show_preview(world):
    world.mode = "off"
    a = world.add("a.lbd")
    world.p.start()
    world.p.want([a], now=False)                           # rows near the selection: not when off
    time.sleep(1.5)
    assert world.p.answer(a) == {"state": "off"}
    world.p.want([a], now=True)                            # Show preview
    assert wait_for(lambda: world.drawn(a))
    assert world.p.answer(a)["picture"]                    # drawn ones are still shown


def test_files_with_a_chosen_picture_are_not_drawn_automatically(world):
    a, b = world.add("a.lbd"), world.add("b.lbd")
    world.chosen.add(a)
    world.p.start()
    assert wait_for(lambda: world.drawn(b))
    time.sleep(0.5)
    assert not world.drawn(a)


def test_pictures_of_files_that_are_gone_are_dropped(world):
    a, b = world.add("a.lbd"), world.add("b.lbd")
    world.p.start()
    assert wait_for(lambda: world.drawn(a) and world.drawn(b))
    del world.files[a]
    world.generation += 1
    assert wait_for(lambda: world.p.cache.get(a) is None)
    assert world.p.cache.get(b) is not None


def test_a_file_that_cant_be_drawn_says_why_and_isnt_tried_again(world):
    bad = world.folder / "bad.lbd"
    bad.write_bytes(b"not an hdf5 file")
    world.files[str(bad)] = file_version(str(bad))
    world.generation += 1
    world.p.start()
    assert wait_for(lambda: world.p.cache.get(str(bad)) is not None)
    answer = world.p.answer(str(bad))
    assert answer["picture"] is None and answer["error"]


def test_a_file_that_keeps_changing_is_redrawn_in_the_background_at_most_every_30_s(world):
    world.mode = "nearby"
    path = world.add("a.lbd")
    world.p.start()
    world.p.want([path], now=False)
    assert wait_for(lambda: world.drawn(path))
    write(path, n=60)
    world.p.want([path], now=False)                      # a row near the selection: held back
    with world.p._cond:
        _, not_before = world.p._queue[path]
    assert not_before - time.monotonic() > previews.REDRAW_EVERY - 2
    world.p.want([path], now=True)                       # selected: drawn at once
    assert wait_for(lambda: world.drawn(path))


def test_emptying_the_cache_draws_them_again(world):
    a = world.add("a.lbd")
    world.p.start()
    assert wait_for(lambda: world.drawn(a))
    assert world.p.cache.size()[0] == 1 and world.p.clear() > 0
    assert world.p.cache.size() == (0, 0)
    assert wait_for(lambda: world.drawn(a))


def test_renamed_files_keep_their_picture(world):
    a = world.add("a.lbd")
    world.p.start()
    assert wait_for(lambda: world.drawn(a))
    new = str(world.folder / "renamed.lbd")
    os.replace(a, new)
    world.p.renamed(a, new)
    assert world.p.answer(new)["picture"]


def test_a_worker_that_stops_is_replaced_and_the_reason_kept(world):
    class Broken:
        def submit(self, *a, **kw):
            raise BrokenProcessPool("the process ended")

        def shutdown(self, **kw):
            pass

    a = world.add("a.lbd")
    world.mode = "off"
    world.p._pools["now"] = Broken()                     # the next one is a working one again
    world.p.start()
    world.p.want([a], now=True)
    assert wait_for(lambda: world.drawn(a))


def test_drawing_in_worker_processes(tmp_path, cfg):
    w = World(tmp_path, cfg, processes=True)
    try:
        a = w.add("a.lbd")
        w.p.start()
        assert wait_for(lambda: w.drawn(a), timeout=120)
        assert w.p.answer(a)["picture"][:4] == b"RIFF"    # WebP
    finally:
        w.p.close()


def test_every_file_needs_reading_headers(cfg):
    cfg.set_library({"read_headers": False})
    with pytest.raises(ConfigError, match="Read each data file's details"):
        cfg.set_library({"previews": "all"})
    assert previews_mode(cfg.settings()["library"]) == "nearby"   # the default "all", while headers are off
    cfg.set_library({"previews": "off"})
    assert previews_mode(cfg.settings()["library"]) == "off"
    cfg.set_library({"read_headers": True, "previews": "all"})
    assert previews_mode(cfg.settings()["library"]) == "all"
    with pytest.raises(ConfigError):
        cfg.set_library({"previews": "sometimes"})
