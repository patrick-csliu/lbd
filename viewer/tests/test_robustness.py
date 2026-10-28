"""Every operation × scale × kind of data, through the viewer: always a proper answer (a picture,
or a message saying what to change), never a crash; and whatever the scales hide, or a result with
nothing to show, is said on screen (`hidden`, `empty`), never silently left out.

Small arrays, so the whole matrix runs in seconds. New operations and equations join the lists."""

import itertools
import json

import numpy as np
import pytest

# numpy's warnings (log of 0, 0/0, …) are errors here: each is a case the viewer must handle itself
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")
from fastapi.testclient import TestClient

import lbd
from lbd_viewer.server import AppState, create_app

REAL_OPS = [[], [{"op": "subtract_mean"}], [{"op": "subtract_mean", "along": "traces"}], [{"op": "normalize"}],
            [{"op": "derivative"}], [{"op": "derivative", "along": "traces"}], [{"op": "smooth", "n": 3}],
            [{"op": "smooth", "n": 500}], [{"op": "smooth", "method": "gaussian", "sigma": 1.5}],
            [{"op": "smooth", "method": "median", "n": 5, "along": "traces"}], [{"op": "subtract_first"}], [{"op": "subtract_previous"}],
            [{"op": "average"}], [{"op": "std"}], [{"op": "fft"}], [{"op": "histogram", "bins": 7}],
            [{"op": "histogram", "along": "traces"}], [{"op": "average"}, {"op": "subtract_previous"}]]
COMPLEX_OPS = [[{"op": "delay", "tau": 1e-9}], [{"op": "rotation", "phi": 30}], [{"op": "auto_rotate"}],
               [{"op": "iq_histogram", "bins": 10}], [{"op": "delay", "tau": 1e-9}, {"op": "derivative"}],
               [{"op": "iq_histogram", "bins": 10}, {"op": "smooth"}]]
SCALES = [{}, {"yscale": "log"}, {"xscale": "log", "yscale": "log"}]     # log x alone: covered by both
EQUATIONS = [{"y": "1/y"}, {"y": "log(y)"}, {"y": "sqrt(y) - mean(y)"}, {"x": "x * 2", "y": "y * 0"},
             {"x": "-x"}, {"y": "y +"}, {"z": "z / max(z)", "x": "x ** 2"}]


@pytest.fixture()
def matrix_file(data_dir):
    """Values on (k: 4 traces) × (f: 30 points): with a missing trace, a zero, negatives; complex;
    constant; and a second real value usable as x."""
    f = np.linspace(-1e9, 2e9, 30)                   # crosses 0: a log x axis hides part
    v = np.sin(np.add.outer(np.arange(4.0), np.linspace(0, 6, 30)))
    v[2] = np.nan
    v[3, 5] = 0
    d = lbd.Dataset(title="matrix")
    d.add_axis("k", np.arange(4.0))
    d.add_axis("f", f, unit="Hz")
    d.add_value("v", v, axes=["k", "f"], unit="V")
    d.add_value("c", (v + 2) * np.exp(1j * np.linspace(0, 3, 30)), axes=["k", "f"], unit="V")
    d.add_value("const", np.ones((4, 30)), axes=["k", "f"])
    d.add_value("w", np.cumsum(np.ones((4, 30)), axis=1), axes=["k", "f"])
    path = data_dir / "matrix.lbd"
    d.save(path)
    return path


CASES = [("curve", "v", {"x": "f", "series": "k"}), ("heatmap", "v", {"x": "f", "y": "k"}),
         ("curve", "c", {"x": "f", "series": "k", "complex": "db"}), ("heatmap", "c", {"x": "f", "y": "k", "complex": "abs"}),
         ("curve", "const", {"x": "f", "series": "k"}), ("curve", "v", {"x": "w", "series": "k"}),
         ("curve", "v", {"x": "f", "series": "k", "index": {"k": 1}})]


def check_shown(sess, meta, settings):
    """Whatever the scales hide is in `hidden`, and nothing-to-show is `empty`."""
    hidden = " ".join(meta["hidden"])
    m = sess.model
    with np.errstate(invalid="ignore"):
        if sess.kind == "curve":
            shown = [k for k, v in enumerate(sess.visible) if v]
            ys = [np.asarray(m.lines[k][0], dtype=float) for k in shown]
            xs = [np.asarray(m.xs[k], dtype=float) for k in shown]
            finite = any(np.isfinite(x).any() and np.isfinite(y).any() for x, y in zip(xs, ys))
            low_y = any(((y <= 0) & np.isfinite(y) & np.isfinite(x)).any() for x, y in zip(xs, ys))
            low_x = any(((x <= 0) & np.isfinite(y) & np.isfinite(x)).any() for x, y in zip(xs, ys))
        else:
            finite = np.isfinite(m.z).any()
            low_x, low_y = (np.asarray(m.x) <= 0).any(), (np.asarray(m.y) <= 0).any()
    if not finite:
        assert meta["empty"], "nothing to show, and nothing said"
        return
    for key, low, which in (("xscale", low_x, "horizontal"), ("yscale", low_y, "vertical")):
        if settings.get(key) == "log" and low:
            assert f"log {which} axis" in hidden or f"{which} axis has no value above 0" in hidden, (key, hidden)


def test_every_operation_on_every_kind_of_data_answers_properly(cfg, data_dir, matrix_file):
    client = TestClient(create_app(AppState(cfg, token="t")), base_url="http://127.0.0.1:8000")
    client.headers["X-LBD-Token"] = "t"
    client.post("/api/roots", json={"path": str(data_dir)}).raise_for_status()
    checked = 0
    for kind, value, axes in CASES:
        o = client.post("/api/explore", json={"path": str(matrix_file), "spec": {"kind": kind, "values": [value], **axes},
                                              "width": 300, "height": 200}).json()
        sess = client.app.state.lbd.explore.get(o["session"])
        ops_lists = REAL_OPS + (COMPLEX_OPS if value == "c" else [])
        scales = SCALES + ([{"cscale": "log"}] if kind == "heatmap" else [])
        combos = [{**scale, "ops": ops} for ops, scale in itertools.product(ops_lists, scales)]
        combos += [{**scale, "equations": e, "ops": ops} for e in EQUATIONS for scale in SCALES[:2]
                   for ops in ([], [{"op": "smooth", "n": 3}])]
        for settings in combos:
            where = (kind, value, axes, settings)
            try:
                r = client.post(f"/api/explore/{o['session']}/render", json={"settings": settings})
            except Exception as e:                    # a crash (or a warning made an error): name the case
                raise AssertionError(f"{where}: {type(e).__name__}: {e}") from e
            assert r.status_code in (200, 400), (where, r.status_code, r.text[:300])
            if r.status_code == 400:
                assert r.json()["detail"], where
                continue
            meta = json.loads(r.headers["X-LBD-Frame"])
            check_shown(sess, meta, settings)
            (x0, x1), (y0, y1) = meta["xlim"], meta["ylim"]
            for kind_c in ("vertical" if checked % 2 else "cross",):   # the types in turn
                c = client.post(f"/api/explore/{o['session']}/cursors",
                                json={"cursors": [{"x": (x0 + x1) / 2, "y": (y0 + y1) / 2}], "type": kind_c,
                                      "xlim": [x0, x1], "ylim": [y0, y1], "width": 300, "height": 200})
                assert c.status_code in (200, 400), (where, kind_c, c.text[:300])
            f = client.post(f"/api/explore/{o['session']}/find", json={"what": "peak", "xlim": [x0, x1], "ylim": [y0, y1]})
            assert f.status_code in (200, 400), (where, f.text[:300])
            checked += 1
    assert checked > 250


def test_a_normalized_constant_says_why_nothing_is_shown(client, matrix_file):
    o = client.post("/api/explore", json={"path": str(matrix_file), "spec": {"kind": "curve", "values": ["const"],
                                          "x": "f", "series": "k"}, "width": 300, "height": 200}).json()
    r = client.post(f"/api/explore/{o['session']}/render", json={"settings": {"ops": [{"op": "normalize"}]}})
    meta = json.loads(r.headers["X-LBD-Frame"])
    assert "Nothing to show" in meta["empty"] and "Normalize" in meta["empty"]


def test_a_log_axis_says_what_it_hides_or_stays_linear(client, matrix_file):
    o = client.post("/api/explore", json={"path": str(matrix_file), "spec": {"kind": "curve", "values": ["v"],
                                          "x": "f", "series": "k"}, "width": 300, "height": 200}).json()
    meta = json.loads(client.post(f"/api/explore/{o['session']}/render",
                                  json={"settings": {"yscale": "log"}}).headers["X-LBD-Frame"])
    assert meta["yscale"] == "log" and any("≤ 0 aren't shown on the log vertical axis" in h for h in meta["hidden"])
    meta = json.loads(client.post(f"/api/explore/{o['session']}/render",
                                  json={"settings": {"yscale": "log", "ops": [{"op": "subtract_mean"},
                                                                              {"op": "histogram", "bins": 3}]}}
                                  ).headers["X-LBD-Frame"])
    assert meta["yscale"] == "log"                    # counts are above 0
    o2 = client.post("/api/explore", json={"path": str(matrix_file), "spec": {"kind": "curve", "values": ["const"],
                                           "x": "f", "series": "k"}, "width": 300, "height": 200}).json()
    meta = json.loads(client.post(f"/api/explore/{o2['session']}/render",
                                  json={"settings": {"yscale": "log", "ops": [{"op": "subtract_mean"}]}}).headers["X-LBD-Frame"])
    assert meta["yscale"] == "linear" and any("stays linear" in h for h in meta["hidden"])


def test_an_unexpected_error_says_it_is_a_bug_and_where_the_details_are(cfg, data_dir, matrix_file, monkeypatch):
    from lbd_viewer import explore

    client = TestClient(create_app(AppState(cfg, token="t")), base_url="http://127.0.0.1:8000",
                        raise_server_exceptions=False)
    client.headers["X-LBD-Token"] = "t"
    client.post("/api/roots", json={"path": str(data_dir)}).raise_for_status()
    o = client.post("/api/explore", json={"path": str(matrix_file), "spec": {"kind": "curve", "values": ["v"],
                                          "x": "f", "series": "k"}, "width": 300, "height": 200}).json()

    def broken(*a, **k):
        raise ZeroDivisionError("a test")

    monkeypatch.setattr(explore.ExploreSession, "render", broken)
    r = client.post(f"/api/explore/{o['session']}/render", json={})
    detail = r.json()["detail"]
    assert r.status_code == 500 and "while drawing the plot: ZeroDivisionError: a test" in detail and "This is a bug" in detail
    log = detail.split("the details are in ")[1].rstrip(".")
    assert "ZeroDivisionError: a test" in open(log, encoding="utf-8").read()
