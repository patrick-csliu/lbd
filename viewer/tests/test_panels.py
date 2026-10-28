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


def test_a_second_unit_gets_a_right_hand_axis(client, values_files):
    import numpy as np
    import pytest

    path = next(str(p) for p in values_files if p.name == "6 rabi.lbd")
    o = client.post("/api/explore", json={"path": path, "spec": {"values": ["I", "population"]}, "width": 500, "height": 300}).json()
    sess = client.app.state.lbd.explore.get(o["session"])
    meta = json.loads(client.post(f"/api/explore/{o['session']}/render", json={"settings": {}}).headers["X-LBD-Frame"])
    apart = sess.model.units_apart
    assert apart["right"] == [1] and sess.ax.get_ylabel() == "Digitizer I (mV)"
    assert apart["label"] == "Population" and sess.lines[1].get_linestyle() == "--"
    # the read-out gives each curve's own numbers, in its own unit
    stored = np.asarray(sess.data.values["population"].data, dtype=float)
    c = client.post(f"/api/explore/{o['session']}/cursors", json={
        "cursors": [{"x": sess.model.xs[0][5], "y": 0, "trace": 1}], "type": "vertical",
        "xlim": meta["xlim"], "ylim": meta["ylim"], "width": 500, "height": 300}).json()["cursors"][0]
    y = next(i for i in c["items"] if i["role"] == "y")
    assert y["value"] == pytest.approx(stored[5]) and y["unit"] == ""
    rows = {r["label"]: r for r in c["table"]["rows"]}
    assert rows["Digitizer I"]["unit"] == "V" and rows["Digitizer I"]["value"] == pytest.approx(sess.data.values["I"].data[5])
    # operations give one quantity: one axis; switched off, the right axis is back
    client.post(f"/api/explore/{o['session']}/render", json={"settings": {"ops": [{"op": "subtract_mean"}]}})
    assert not getattr(sess.model, "units_apart", None)
    client.post(f"/api/explore/{o['session']}/render", json={"settings": {"ops": [{"op": "subtract_mean"}], "ops_on": False}})
    assert sess.model.units_apart


def test_a_third_unit_is_refused_with_what_to_do(client, values_files):
    path = next(str(p) for p in values_files if p.name == "6 rabi.lbd")
    r = client.post("/api/explore", json={"path": path, "spec": {"values": ["I", "population", "phase"]}, "width": 500, "height": 300})
    assert r.status_code == 400 and "three units" in r.json()["detail"] and "another panel" in r.json()["detail"]
    same = client.post("/api/explore", json={"path": path, "spec": {"values": ["I", "Q"]}, "width": 500, "height": 300}).json()
    sess = client.app.state.lbd.explore.get(same["session"])
    assert not getattr(sess.model, "units_apart", None)                 # one unit (V): one axis
