"""The registry of plot types (lbd.plot.kinds): how a new type joins without editing render.py."""

import numpy as np
import pytest

import lbd
import lbd.plot as lp
from lbd.plot import kinds, render
from lbd.plot import matrix


def two_axes():
    d = lbd.Dataset(title="t")
    d.add_axis("a", [0.0, 1.0, 2.0])
    d.add_axis("b", [0.0, 1.0])
    d.add_value("v", np.arange(6.0).reshape(3, 2), axes=["a", "b"])
    return d


def test_the_three_kinds_are_registered():
    assert {"curve", "heatmap", "scatter"} <= set(kinds.KINDS)
    assert render.KINDS[0] == "auto" and "heatmap" in render.KINDS
    assert kinds.KINDS["heatmap"].title == "Map"


def test_a_name_can_be_registered_once():
    with pytest.raises(ValueError, match="twice"):
        kinds.register(kinds.KINDS["curve"])


def test_a_placeholder_adds_nothing():
    assert matrix.KIND is None and "matrix" not in kinds.KINDS


def test_build_figure_goes_through_the_registry(monkeypatch):
    seen = []
    kind = kinds.Kind("test kind", "Test", lambda d, n: None, kinds.KINDS["curve"].resolve,
                      lambda d, spec, style, **kw: "the model",
                      lambda fig, ax, model, d, spec, style: seen.append(model))
    monkeypatch.setitem(kinds.KINDS, "test kind", kind)
    render.build_figure(two_axes(), {"kind": "test kind", "values": ["v"]}, lp.load_style())
    assert seen == ["the model"]


def test_a_kind_makes_its_own_axes(monkeypatch):
    made = []

    def axes(fig, model):
        made.append(model)
        return fig.add_subplot()

    kind = kinds.Kind("own axes", "Own", lambda d, n: None, kinds.KINDS["curve"].resolve,
                      lambda d, spec, style, **kw: 7, lambda fig, ax, model, d, spec, style: None, make_axes=axes)
    monkeypatch.setitem(kinds.KINDS, "own axes", kind)
    render.build_figure(two_axes(), {"kind": "own axes", "values": ["v"]}, lp.load_style())
    assert made == [7]


def test_fits_says_why_not():
    d = two_axes()
    d.add_value("line", [1.0, 2.0, 3.0], axes="a")
    assert kinds.KINDS["heatmap"].fits(d, "v") is None
    assert "2 dimensions" in kinds.KINDS["heatmap"].fits(d, "line")


def test_an_unknown_kind_is_refused_with_its_message():
    d = two_axes()
    d.plot = {"kind": "heatmap"}
    with pytest.raises(render.RenderError, match="unknown plot kind 'pie'"):
        render.resolve_spec(d, {"kind": "pie"})


def test_all_and_options_survive_a_saved_view(tmp_path):
    d = two_axes()
    d.plot = {"kind": "heatmap", "all": ["a"], "options": {"cells": "rows"}}
    d.save(tmp_path / "x.lbd")
    again = lbd.load(tmp_path / "x.lbd")
    assert again.plot["all"] == ["a"] and again.plot["options"] == {"cells": "rows"}
    out = render.resolve_spec(again, None)
    assert out["all"] == ["a"] and out["options"] == {"cells": "rows"}


def test_a_wrong_all_says_why():
    with pytest.raises(render.RenderError, match="no axis 'nope'"):
        render.resolve_spec(two_axes(), {"all": ["nope"]})
    with pytest.raises(render.RenderError, match="options must be a dict"):
        render.resolve_spec(two_axes(), {"options": "rows"})
