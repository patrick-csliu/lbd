"""Equations in the Explore view (equations.py): only formulas are accepted (never code), each
problem says what is wrong at its field, results are worked out by hand, and the legend says what
each name means."""

import json

import numpy as np
import pytest

import lbd
from lbd_viewer import equations as eq


@pytest.mark.parametrize("text", ["__import__('os')", "x.real", "[y for y in x]", "lambda: 1", "y if x else 1",
                                  "x < 2", "'text'", "open('f')", "y; x", "x[0]", "y(2)", "True"])
def test_only_formulas_are_accepted(text):
    with pytest.raises(eq.EquationError):
        eq.evaluate(text, {"x": np.ones((1, 3)), "y": np.ones((1, 3))}, (1, 3))


def test_messages_say_what_is_wrong():
    names = {"x": np.arange(3.0)[None, :], "y": np.ones((1, 3)), "S21": np.ones((1, 3)) * (1 + 1j)}
    cases = {"y - * 2": "at character", "pwr * 2": "'pwr' isn't a value or axis of this plot; there are: x, y, S21",
             "sinus(y)": "'sinus' isn't one of the functions", "S21": "the result is complex: take abs()",
             "sqrt": "is a function: write sqrt(…)", "arctan2(y)": "was given 1 value(s)",
             "`S21 (ref)`": "'S21 (ref)' isn't a value or axis", "`x": "closing backtick"}
    for text, match in cases.items():
        with pytest.raises(eq.EquationError, match=match.replace("(", r"\(").replace(")", r"\)").replace("*", r"\*")):
            eq.evaluate(text, names, (1, 3))


def test_results_by_hand():
    x = np.array([[1.0, 2, 3]])
    names = {"x": x, "y": np.array([[2.0, 4, 6]]), "power": np.array([[-10.0], [-20.0]])[:1], "pi": None}
    names.pop("pi")
    assert eq.evaluate("y - 0.5 * power", names, (1, 3)).tolist() == [[7, 9, 11]]
    assert eq.evaluate("y - mean(y)", names, (1, 3)).tolist() == [[-2, 0, 2]]
    assert eq.evaluate("x * 1e-9", names, (1, 3)) == pytest.approx(np.array([[1e-9, 2e-9, 3e-9]]))
    assert eq.evaluate("abs(`S21 (ref)`) * 2", {**names, "S21 (ref)": np.array([[3j, 4, -5]])}, (1, 3)).tolist() == [[6, 8, 10]]
    assert eq.evaluate("2 ** 3 + sin(pi / 2) − 1", names, (1, 3)).tolist() == [[8, 8, 8]]    # a − typed as minus


def test_empty_points_are_gaps_and_a_map_keeps_sorted_axes(client, data_dir):
    d = lbd.Dataset(title="eq")
    d.add_axis("k", np.array([1.0, 2.0]), unit="dBm", label="Power")
    d.add_axis("f", np.array([1.0, 2.0, 3.0]), unit="Hz", label="Frequency")
    d.add_value("v", np.array([[1.0, -4, 9], [4, 16, -1]]), axes=["k", "f"], unit="V")
    d.add_value("ref", np.array([[1.0, 1, 1], [2, 2, 2]]), axes=["k", "f"], unit="V")
    d.save(data_dir / "eq.lbd")

    def render(spec, eqs):
        o = client.post("/api/explore", json={"path": str(data_dir / "eq.lbd"), "spec": spec, "width": 300, "height": 200}).json()
        r = client.post(f"/api/explore/{o['session']}/render", json={"settings": {"equations": eqs}})
        assert r.status_code == 200, r.text
        return client.app.state.lbd.explore.get(o["session"]), json.loads(r.headers["X-LBD-Frame"])["ops"]

    sess, info = render({"kind": "curve", "values": ["v"], "x": "f", "series": "k"}, {"y": "sqrt(y) / ref"})
    assert info["equations"]["y"]["note"].startswith("2 points have no value")
    assert sess.model.lines[0][0][:1] == pytest.approx([1]) and np.isnan(sess.model.lines[0][0][1])
    assert sess.ax.get_ylabel() == "sqrt(y) / ref"                          # no unit: the equation
    legend = {n["name"]: n["means"] for n in info["names"]}
    assert legend["x"] == "Frequency, in Hz" and legend["y"] == "v, in V" and legend["ref"] == "ref, in V, as stored"
    assert legend["k"] == "Power, in dBm, an axis: one per trace"

    sess, info = render({"kind": "curve", "values": ["v"], "x": "f", "series": "k"}, {"x": "x * k", "y": "y + k"})
    assert len(sess.x_groups) == 2 and sess.model.lines[1][0][0] == pytest.approx(6)   # each trace its own x
    sess, info = render({"kind": "heatmap", "values": ["v"], "x": "f", "y": "k"}, {"x": "x ** 2", "y": "-y", "z": "z * 0"})
    assert sess.model.x == pytest.approx([1, 4, 9]) and sess.model.y == pytest.approx([-1, -2]) and info["equations"]["z"] == {}
    legend = {n["name"]: n["means"] for n in info["names"]}
    assert legend["k"].endswith("an axis: one per row") and legend["f"].endswith("an axis")   # the map's y and x
    sess, info = render({"kind": "heatmap", "values": ["v"], "x": "f", "y": "k"}, {"z": "z * k + f"})
    assert sess.model.z[1] / sess.model.zf == pytest.approx([4 * 2 + 1, 16 * 2 + 2, -1 * 2 + 3])   # k per row, f per column
    sess, info = render({"kind": "heatmap", "values": ["v"], "x": "f", "y": "k"}, {"x": "sin(x * 3)"})
    assert "must stay one sorted row" in info["equations"]["x"]["error"]
    sess, info = render({"kind": "curve", "values": ["v"], "x": "f", "series": "k"}, {"y": "pwr"})
    assert "isn't a value or axis" in info["equations"]["y"]["error"] and sess.model is sess.base_model
