"""Stopping the viewer (plan 16.2, 16.16): preview workers end when the viewer is gone, and
Ctrl+C stops the viewer within a second or two, with one line and no error text."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import psutil
import pytest

from lbd_viewer.pages import Pages
from lbd_viewer.previews import _worker_init

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "data"


def wait_for(cond, timeout: float, step: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def a_finished_process() -> int:
    """The number of a process that has ended: a viewer that is gone."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def worker_pid(parent_pid: int):
    pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"),
                               initializer=_worker_init, initargs=(parent_pid, False))
    return pool, pool.submit(os.getpid).result(timeout=60)


def test_a_preview_worker_stops_when_the_viewer_is_gone():
    pool, pid = worker_pid(a_finished_process())
    try:
        assert wait_for(lambda: not psutil.pid_exists(pid), timeout=10), "the worker is still running"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def test_a_preview_worker_stays_while_the_viewer_runs():
    pool, pid = worker_pid(os.getpid())
    try:
        time.sleep(5)                                  # more than two checks
        assert psutil.pid_exists(pid)
        assert pool.submit(os.getpid).result(timeout=10) == pid
    finally:
        pool.shutdown(wait=True)


def test_closing_pages_ends_every_waiting_poll():
    pages = Pages()
    page = pages.register()
    first = pages.poll(page.id)                         # its first command (the list of pages), confirmed below
    poll = pages.start_poll(page.id, after=first.id)
    answered = []
    t = threading.Thread(target=lambda: answered.append(pages.wait_for_command(page.id, poll, 25)))
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    pages.close()
    t.join(timeout=5)
    assert answered == [None] and time.monotonic() - started < 1
    # A poll that starts after the close doesn't wait either.
    poll = pages.start_poll(page.id)
    started = time.monotonic()
    assert pages.wait_for_command(page.id, poll, 25) is None and time.monotonic() - started < 1


def _api(port: int, token: str, method: str, path: str, body=None, timeout: float = 30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-LBD-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def test_ctrl_c_stops_the_viewer_quickly_and_quietly(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(EXAMPLES / "temperature_map.lbd", data / "map.lbd")
    env = {**os.environ, "LBD_CONFIG_DIR": str(tmp_path / "config"), "LBD_RUNTIME_DIR": str(tmp_path / "run"),
           "PYTHONUNBUFFERED": "1"}
    windows = sys.platform == "win32"
    viewer = subprocess.Popen(
        [sys.executable, "-m", "lbd_viewer", "--new", "--no-browser", "--idle-exit", "0", str(data)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        # Ctrl+Break reaches only this new group on Windows (not the test itself)
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0)
    output: list = []
    reader = threading.Thread(target=lambda: output.extend(viewer.stdout), daemon=True)
    reader.start()
    try:
        assert wait_for(lambda: any("token=" in line for line in output), timeout=60), "".join(output)
        url = next(line for line in output if "token=" in line)
        port, token = int(re.search(r":(\d+)/", url)[1]), re.search(r"token=([\w-]+)", url)[1]

        # An open page, waiting for commands (its long poll), and a preview worker drawing.
        page = json.loads(_api(port, token, "POST", "/api/pages"))["page"]
        threading.Thread(target=lambda: _api(port, token, "GET", f"/api/pages/{page}/next?wait=25"),
                         daemon=True).start()
        _api(port, token, "POST", "/api/library/preview/want", {"paths": [str(data / "map.lbd")], "now": True})
        server = psutil.Process(viewer.pid)
        assert wait_for(lambda: server.children(recursive=True), timeout=60), "no preview worker started"
        children = server.children(recursive=True)
        time.sleep(0.5)

        started = time.monotonic()
        viewer.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
        viewer.wait(timeout=30)
        took = time.monotonic() - started
        reader.join(timeout=5)
        text = "".join(output)
        assert took < 3, f"stopping took {took:.1f} s:\n{text}"
        assert "Traceback" not in text, text
        assert text.strip().splitlines()[-1] == "LBD viewer stopped", text
        assert viewer.returncode == 0, text
        assert wait_for(lambda: not any(c.is_running() for c in children), timeout=5), "a worker is left"
    finally:
        if viewer.poll() is None:
            viewer.kill()
