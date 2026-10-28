"""Several values in panels (plan 4), on the server side: what a panel must share with another to
follow its zoom (the horizontal axis as drawn; the vertical unit, or a map's vertical axis)."""

import json

import pytest


@pytest.fixture()
def frame(client, values_files):
    def render(name, spec, settings=None):
        path = next(str(p) for p in values_files if p.name == name)
        o = client.post("/api/explore", json={"path": path, "spec": spec, "width": 400, "height": 300})
        assert o.status_code == 200, o.text
        r = client.post(f"/api/explore/{o.json()['session']}/render", json={"settings": settings or {}})
        assert r.status_code == 200, r.text
        return json.loads(r.headers["X-LBD-Frame"])

    return render


def test_panels_with_the_same_axis_share_their_sync_keys(frame):
    i = frame("6 rabi.lbd", {"values": ["I"]})["sync"]
    q = frame("6 rabi.lbd", {"values": ["Q"]})["sync"]
    pop = frame("6 rabi.lbd", {"values": ["population"]})["sync"]
    assert i["x"] == q["x"] == pop["x"] == "Drive amplitude (mV)"
    assert (i["y"], q["y"], pop["y"]) == ("mV", "µV", "")              # y: the unit, prefix included


def test_another_x_axis_or_a_changed_x_has_another_key(frame):
    s21 = frame("8 mixed axes.lbd", {"values": ["S21"], "kind": "heatmap"})["sync"]
    ref = frame("8 mixed axes.lbd", {"values": ["S21_ref"]})["sync"]
    f0 = frame("8 mixed axes.lbd", {"values": ["f0"]})["sync"]
    assert s21["x"] == ref["x"] == "Frequency (GHz)" and f0["x"] == "Power (dBm)"
    assert s21["y"] == "Power (dBm)"                                    # a map: its vertical axis
    eq = frame("8 mixed axes.lbd", {"values": ["S21_ref"]}, {"equations": {"x": "x * 1e-9"}})["sync"]
    fft = frame("8 mixed axes.lbd", {"values": ["S21_ref"]}, {"ops": [{"op": "fft"}]})["sync"]
    assert eq["x"] == "x * 1e-9" and fft["x"] not in (ref["x"], "")
