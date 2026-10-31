"""Writing while measuring (plan 6b): lbd.Writer, writing_status, recover, and reading files
being written. Other programs are real processes here: HDF5 shares one handle per file within a
process, so only another process shows what a viewer or a second script sees."""

import subprocess
import sys
import textwrap
import time

import h5py
import numpy as np
import pytest

import lbd
from lbd import LBDError, LBDWarning
from lbd import writer as writer_module

ON_WINDOWS = sys.platform == "win32"


def run_python(code: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(code), *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for(condition, seconds=20.0):
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        time.sleep(0.05)


def load_writing(path):
    with pytest.warns(LBDWarning, match="still being written"):
        return lbd.load(path)


# A measurement in another process: `rows` traces of S21[power, freq], a growing log, an integer
# value; prints "started" after the first write, then measures slowly. `crash` ends the process
# without closing the Writer (as a crash or a killed script does).
MEASURE = """
    import sys, time, os
    import numpy as np, lbd
    path, rows, crash = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "crash"
    w = lbd.Writer(path, title="live", flush_every=0.05)
    w.add_axis("power", np.arange(rows, dtype=float))
    w.add_axis("freq", np.linspace(0, 1, 7))
    w.add_value("S21", axes=["power", "freq"], dtype="complex128")
    w.add_value("n", axes="power", dtype="int64")
    w.add_axis("time", grows=True)
    w.add_value("T", axes="time")
    for i in range(rows):
        w.write(power=i, S21=np.full(7, i + 1j * i), n=i)
        w.write(time=float(i), T=10.0 * i)
        if i == 0:
            w.flush()
            print("started", flush=True)
        time.sleep(0.03)
    w.flush()
    if crash:
        print("crashing", flush=True)
        os._exit(3)
    w.close()
    print("finished", flush=True)
"""


def check_rows(d, n):
    """The first n rows hold what MEASURE wrote. Later rows may be measured too (a reader reads
    the datasets one after the other, while the writer goes on), but only as a run from the
    start: every row is either right or not measured, never something else."""
    s21, t = d.values["S21"].data, d.values["T"].data
    measured = [not np.all(np.isnan(row)) for row in s21]
    assert all(measured[:n])
    assert measured == sorted(measured, reverse=True)
    for i in np.flatnonzero(measured):
        assert np.all(s21[i] == i + 1j * i)
    assert np.array_equal(t, 10.0 * np.arange(len(t)))
    assert np.array_equal(d.axes["time"].data, np.arange(len(t)))


# ---- in this process -------------------------------------------------------


def test_a_measurement_written_live_becomes_an_lbd_file(tmp_path):
    path = tmp_path / "sweep.lbd"
    with lbd.Writer(path, title="Resonator", description="first") as w:
        w.add_axis("power", np.linspace(-60, 0, 3), unit="dBm")
        w.add_axis("freq", np.linspace(6e9, 7e9, 4), unit="Hz")
        w.add_axis("state", elements=["ground", "excited"])
        w.add_value("S21", axes=["power", "freq"], dtype="complex128")
        w.add_value("counts", axes=["state", "power"], dtype="int32")
        w.add_value("f0", 6.5e9, unit="Hz")                     # given whole
        w.meta["sample"] = "R7"
        for i in range(3):
            w.write(power=i, S21=np.arange(4) + 1j * i)
            for s in ("ground", "excited"):
                w.write(state=s, power=i, counts=10 * i)
        assert w.writing_path.exists() and not path.exists()
        w.description = "changed while measuring"
        w.meta["T_mK"] = 12
    assert path.exists() and not w.writing_path.exists()
    d = lbd.load(path)
    assert d.title == "Resonator" and d.description == "changed while measuring"
    assert d.meta == {"sample": "R7", "T_mK": 12}
    assert np.array_equal(d.values["S21"].data[2], np.arange(4) + 2j)
    assert d.values["counts"].measured is None                 # everything measured: no mask
    assert d.values["f0"].data == 6.5e9
    assert d.id == w.id and d.writer.startswith("python lbd")
    with h5py.File(path, "r") as f:
        assert "measured" not in f


def test_a_growing_axis_and_values_stopped_early(tmp_path):
    path = tmp_path / "log.lbd"
    w = lbd.Writer(path)
    w.add_axis("time", unit="s", grows=True)
    w.add_axis("ch", [1, 2])
    w.add_value("V", axes=["time", "ch"])
    w.add_value("ok", axes="time", dtype="bool")
    w.add_value("plan", axes="ch", dtype="uint8")
    for t in range(5):
        w.write(time=t * 0.5, V=[t, -t], ok=t % 2 == 0)
    w.write(time=[2.5, 3.0], V=[[5, -5], [6, -6]])               # two rows; ok not given
    w.write(ch=0, plan=7)
    assert w.close(stopped=True) == path                         # no warning: stopped on purpose
    d = lbd.load(path)
    assert np.allclose(d.axes["time"].data, np.arange(7) * 0.5)
    assert np.array_equal(d.values["V"].data[:, 1], -np.arange(7))
    assert list(d.values["ok"].measured) == [True] * 5 + [False] * 2
    assert list(d.values["ok"].data[:5]) == [True, False, True, False, True]
    assert list(d.values["plan"].measured) == [True, False]


def test_values_not_measured_everywhere_are_reported_at_the_finish(tmp_path):
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1, 2, 3])
    w.add_value("n", axes="x", dtype="int16")
    w.write(x=0, n=1)
    with pytest.warns(LBDWarning, match="n not measured everywhere"):
        w.close()


def test_reading_in_the_writing_process_sees_everything_written(tmp_path):
    w = lbd.Writer(tmp_path / "a.lbd", flush_every=60)            # nothing flushed by the thread
    w.add_axis("time", grows=True)
    w.add_value("T", axes="time")
    w.write(time=[0, 1, 2], T=[5, 6, 7])
    d = load_writing(w.writing_path)
    assert list(d.values["T"].data) == [5, 6, 7]
    assert lbd.writing_status(w.writing_path) == "measuring"
    w.close()


def test_a_planned_size_takes_no_memory_or_disk(tmp_path):
    w = lbd.Writer(tmp_path / "big.lbd")
    w.add_axis("a", np.arange(20_000))
    w.add_axis("b", np.arange(20_000))
    w.add_value("S", axes=["a", "b"], dtype="float64")         # 3.2 GB if it were stored
    w.write(a=5, b=7, S=1.0)
    path = w.close()
    assert path.stat().st_size < 5_000_000
    assert lbd.load(path, values=[]).values["S"].shape == (20_000, 20_000)
    with h5py.File(path, "r") as f:
        assert f["values/S"][5, 7] == 1.0 and np.isnan(f["values/S"][5, 8])


# ---- refusals and errors ------------------------------------------------------


def test_refusals(tmp_path):
    with pytest.raises(LBDError, match="ending in .lbd"):
        lbd.Writer(tmp_path / "a.h5")
    (tmp_path / "taken.lbd").write_bytes(b"")
    with pytest.raises(FileExistsError, match="never replaces"):
        lbd.Writer(tmp_path / "taken.lbd")
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1, 2])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    with pytest.raises(FileExistsError):
        lbd.Writer(tmp_path / "a.lbd")                         # a second writer
    with pytest.raises(LBDError, match="before the first write"):
        w.add_axis("z", [1])
    with pytest.raises(LBDError, match="still being written"):
        lbd.recover(w.writing_path)
    with pytest.raises(LBDError, match="only by lbd.Writer"):
        lbd.Dataset().save(w.writing_path)
    w.close()
    with pytest.raises(LBDError, match="closed"):
        w.write(x=1, y=2.0)
    with pytest.raises(FileNotFoundError):
        lbd.writing_status(w.writing_path)
    with pytest.raises(LBDError, match="not a file being written"):
        lbd.writing_status(tmp_path / "a.h5")


def test_an_error_in_the_block_leaves_a_stopped_file(tmp_path):
    path = tmp_path / "a.lbd"
    with pytest.warns(LBDWarning, match="stopped with RuntimeError"):
        with pytest.raises(RuntimeError, match="instrument"):
            with lbd.Writer(path, flush_every=60) as w:
                w.add_axis("x", np.arange(4))
                w.add_value("y", axes="x")
                w.write(x=0, y=1.0)
                w.write(x=1, y=2.0)                            # not flushed yet: written on the way out
                raise RuntimeError("instrument did not answer")
    assert not path.exists()
    assert lbd.writing_status(w.writing_path) == "stopped"
    assert list(load_writing(w.writing_path).values["y"].data[:2]) == [1.0, 2.0]
    assert lbd.recover(w.writing_path) == path
    assert not w.writing_path.exists()
    d = lbd.load(path)
    assert d.id == w.id and list(d.values["y"].data[:2]) == [1.0, 2.0] and np.isnan(d.values["y"].data[2])


def test_bad_metadata_is_refused_before_the_finish(tmp_path):
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1, 2])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    w.meta["oops"] = None
    with pytest.raises(LBDError, match="None"):
        w.close()
    assert lbd.writing_status(w.writing_path) == "measuring"    # still writing, nothing lost
    w.write(x=1, y=2.0)
    del w.meta["oops"]
    assert list(lbd.load(w.close()).values["y"].data) == [1.0, 2.0]


def test_a_failed_write_to_the_file_is_raised_at_the_next_call(tmp_path, monkeypatch):
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1, 2])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    w.flush()

    def disk_full(items):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(w, "_apply", disk_full)
    w.write(x=1, y=2.0)
    with pytest.raises(LBDError, match="No space left.*What was written before is in"):
        w.flush()
    with pytest.raises(LBDError, match="No space left"):
        w.close()
    assert lbd.writing_status(w.writing_path) == "stopped"
    assert load_writing(w.writing_path).values["y"].data[0] == 1.0


def test_a_file_made_meanwhile_is_not_replaced(tmp_path):
    path = tmp_path / "a.lbd"
    w = lbd.Writer(path)
    w.add_axis("x", [1])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    path.write_bytes(b"someone else's")
    with pytest.warns(LBDWarning, match=r"saved as a \(2\)\.lbd"):
        out = w.close()
    assert out == tmp_path / "a (2).lbd" and w.path == out
    assert path.read_bytes() == b"someone else's"


# ---- other processes ----------------------------------------------------------


def test_another_process_reads_live_and_ordinary_opens_are_refused(tmp_path):
    path = tmp_path / "live.lbd"
    writing = tmp_path / "live.lbd.writing"
    rows = 60
    w = run_python(MEASURE, path, rows, "finish")
    assert w.stdout.readline().strip() == "started", w.stderr.read()
    assert lbd.writing_status(writing) == "measuring"
    ordinary = run_python("""
        import sys, h5py
        try:
            h5py.File(sys.argv[1], "r").close()
            print("opened")
        except OSError as e:
            print("refused")
    """, writing)
    assert ordinary.communicate(timeout=60)[0].strip() == "refused"
    seen = []
    while w.poll() is None and writing.exists():
        try:
            d = load_writing(writing)
        except (FileNotFoundError, OSError):
            if not writing.exists():                            # renamed meanwhile: finished
                break
            raise
        n = len(d.axes["time"])
        check_rows(d, n)
        seen.append(n)
        time.sleep(0.1)
    out, err = w.communicate(timeout=60)
    assert "finished" in out, err
    assert len(seen) >= 2 and seen == sorted(seen) and seen[-1] > seen[0]
    d = lbd.load(path)
    check_rows(d, rows)
    assert d.values["n"].measured is None


def test_a_killed_writer_leaves_a_file_that_recovers(tmp_path):
    path = tmp_path / "crash.lbd"
    writing = tmp_path / "crash.lbd.writing"
    w = run_python(MEASURE, path, 12, "crash")
    out, err = w.communicate(timeout=60)
    assert w.returncode == 3 and "crashing" in out, err
    assert lbd.writing_status(writing) == "stopped"
    check_rows(load_writing(writing), 12)
    assert lbd.recover(writing) == path
    assert not writing.exists()
    d = lbd.load(path)
    check_rows(d, 12)
    assert d.title == "live" and d.id is not None


@pytest.mark.skipif(not ON_WINDOWS, reason="only Windows refuses to rename a file another program has open")
def test_a_program_holding_the_file_at_the_finish(tmp_path, monkeypatch):
    hold = """
        import sys, time
        f = open(sys.argv[1], "rb")
        print("holding", flush=True)
        time.sleep(float(sys.argv[2]))
    """
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    holder = run_python(hold, w.writing_path, 1.0)
    assert holder.stdout.readline().strip() == "holding"
    assert w.close() == tmp_path / "a.lbd"                      # waits until it lets go
    holder.communicate()

    monkeypatch.setattr(writer_module, "FINISH_WAIT", 0.5)
    w = lbd.Writer(tmp_path / "b.lbd")
    w.add_axis("x", [1])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    holder = run_python(hold, w.writing_path, 30)
    try:
        assert holder.stdout.readline().strip() == "holding"
        with pytest.raises(PermissionError, match=r"(?i)python.*kept b\.lbd\.writing open.*lbd\.recover"):
            w.close()
    finally:
        holder.kill()
        holder.communicate()
    assert lbd.writing_status(tmp_path / "b.lbd.writing") == "stopped"
    assert lbd.load(lbd.recover(tmp_path / "b.lbd.writing")).values["y"].data[0] == 1.0


def test_a_status_checker_in_another_process(tmp_path):
    w = lbd.Writer(tmp_path / "a.lbd")
    w.add_axis("x", [1])
    w.add_value("y", axes="x")
    w.write(x=0, y=1.0)
    status = run_python("import sys, lbd; print(lbd.writing_status(sys.argv[1]))", w.writing_path)
    assert status.communicate(timeout=60)[0].strip() == "measuring"
    w.close()


# ---- axis groups (format 2.0) ------------------------------------------------


# A variable sweep in another process (case 4 of the data API, growing): for each A, B in
# range(A), C in range(B); f per (A, B) point, g per (A, B, C) point, written with parent=.
MEASURE_GROUP = """
    import sys, time, os
    import numpy as np, lbd
    path, rows, crash = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "crash"
    w = lbd.Writer(path, title="variable", flush_every=0.05)
    w.add_group("ABC")
    for a in "ABC":
        w.add_axis(a, group="ABC")
    w.add_value("f", axes=["A", "B"])
    w.add_value("g", axes=["ABC"])
    for a in range(1, rows + 1):
        i = w.write(A=a)
        for b in range(a):
            k = w.write(parent=i, B=b, f=10 * a + b)
            c = np.arange(b)
            w.write(parent=k, C=c, g=100 * a + 10 * b + c)
        if a == 1:
            w.flush()
            print("started", flush=True)
        time.sleep(0.03)
    w.flush()
    if crash:
        print("crashing", flush=True)
        os._exit(3)
    w.close()
    print("finished", flush=True)
"""


def check_group(d):
    """What a reader sees of MEASURE_GROUP: consistent levels (load checks the parents), and
    every value either right for its point's coordinates or not measured yet."""
    c = d.coords("f")
    f = d.values["f"].data
    ok = np.isnan(f) | (f == 10 * c["A"] + c["B"])
    assert ok.all(), (f, c)
    c = d.coords("g")
    g = d.values["g"].data
    assert (np.isnan(g) | (g == 100 * c["A"] + 10 * c["B"] + c["C"])).all()
    return len(d.axes["B"].data)


def test_a_group_written_live_makes_the_same_file_as_in_memory(tmp_path):
    with lbd.Writer(tmp_path / "live.lbd") as w:
        w.add_group("ABC")
        for a in "ABC":
            w.add_axis(a, group="ABC")
        w.add_value("f", axes=["A", "B"])
        w.add_value("g", axes=["ABC"])
        w.add_value("n", axes=["A"], dtype="int16")
        for a in [1, 2, 3]:
            assert w.write(A=a, n=a) == a - 1
            for b in range(a):
                w.write(A=a, B=b, f=10 * a + b)
                c = np.arange(b)
                w.write(A=a, B=b, C=c, g=100 * a + 10 * b + c)
    d = lbd.load(tmp_path / "live.lbd")
    assert d.lbd_version == "2.0" and d.groups["ABC"].order == ["A", "B", "C"]
    assert list(d.axes["B"].data) == [0, 0, 1, 0, 1, 2] and list(d.axes["C"].parent) == [2, 4, 5, 5]
    assert list(d.values["f"].data) == [10, 20, 21, 30, 31, 32] and list(d.values["g"].data) == [210, 310, 320, 321]
    assert list(d.values["n"].data) == [1, 2, 3] and d.values["n"].measured is None


def test_a_group_value_on_a_fixed_axis_too_grows_along_the_group(tmp_path):
    with lbd.Writer(tmp_path / "h.lbd") as w:
        w.add_group("AB")
        w.add_axis("A", group="AB")
        w.add_axis("B", group="AB")
        w.add_axis("C", [0.1, 0.2, 0.3])
        w.add_value("h", axes=["C", "A", "B"])            # the group's dimension isn't the first
        w.add_value("cov", axes=["A", "B"], shape=(2, 2))
        w.write(A=1, B=[10, 20], h=[[1, 2], [3, 4], [5, 6]], cov=np.ones((2, 2, 2)))
        w.write(A=2, B=10, C=1, h=7)
    d = lbd.load(tmp_path / "h.lbd")
    h = d.values["h"]
    assert h.dims == [("C",), ("A", "B")] and h.shape == (3, 3)
    assert h.data[1].tolist() == [3, 4, 7] and np.isnan(h.data[0, 2])
    assert d.values["cov"].shape == (3, 2, 2) and np.all(np.isnan(d.values["cov"].data[2]))


def test_another_process_reads_a_group_live(tmp_path):
    path = tmp_path / "var.lbd"
    writing = tmp_path / "var.lbd.writing"
    w = run_python(MEASURE_GROUP, path, 25, "finish")
    assert w.stdout.readline().strip() == "started", w.stderr.read()
    seen = []
    while w.poll() is None and writing.exists():
        try:
            d = load_writing(writing)
        except (FileNotFoundError, OSError):
            if not writing.exists():
                break
            raise
        seen.append(check_group(d))
        time.sleep(0.05)
    out, err = w.communicate(timeout=60)
    assert "finished" in out, err
    assert len(seen) >= 2 and seen == sorted(seen)
    d = lbd.load(path)
    assert check_group(d) == 25 * 26 // 2 and not np.isnan(d.values["f"].data).any()


def test_a_stopped_group_file_recovers(tmp_path):
    path = tmp_path / "var.lbd"
    writing = tmp_path / "var.lbd.writing"
    w = run_python(MEASURE_GROUP, path, 6, "crash")
    out, err = w.communicate(timeout=60)
    assert w.returncode == 3 and "crashing" in out, err
    assert check_group(load_writing(writing)) == 21
    assert lbd.recover(writing) == path
    d = lbd.load(path)
    assert check_group(d) == 21 and d.lbd_version == "2.0" and d.title == "variable"
