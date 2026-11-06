"""points_of and iter_points: a value as a list of points, some axes whole, some fixed."""

import numpy as np

import lbd
from lbd.plot.points import iter_points, points_of
from lbd.plot import render


def cube():
    d = lbd.Dataset()
    d.add_axis("a", [10.0, 20.0])
    d.add_axis("b", [1.0, 2.0, 3.0])
    d.add_axis("c", [0.1, 0.2, 0.3, 0.4])
    d.add_value("v", np.arange(24.0).reshape(2, 3, 4), axes=["a", "b", "c"])
    return d


def test_a_slider_axis_is_fixed():
    p = points_of(cube(), {"index": {"a": 1}}, "v")
    assert p.data.size == 12 and p.data[0] == 12.0
    assert set(p.coords) == {"b", "c"} and set(p.stored["a"]) == {1}


def test_all_keeps_every_point():
    p = points_of(cube(), {"index": {"a": 1}, "all": ["a"]}, "v")
    assert p.data.size == 24 and p.coords["a"][-1] == 20.0


def test_stored_indices_point_back():
    d = cube()
    p = points_of(d, {"index": {"b": 2}}, "v")
    back = d.values["v"].data[p.stored["a"], p.stored["b"], p.stored["c"]]
    assert np.array_equal(back, p.data)


def test_a_group_gives_real_coordinates():
    d = lbd.Dataset()
    d.add_group("scan")
    d.add_axis("p", group="scan")
    d.add_axis("f", group="scan")
    d.add_value("v", axes=["p", "f"])
    for p, fs in ((1.0, (10.0, 11.0)), (2.0, (20.0, 21.0, 22.0))):
        for f in fs:
            d.write(p=p, f=f, v=p + f)
    points = points_of(d, {}, "v")
    assert list(points.coords["f"]) == [10.0, 11.0, 20.0, 21.0, 22.0]
    assert list(points.coords["p"]) == [1.0, 1.0, 2.0, 2.0, 2.0]
    assert list(points.data) == [11.0, 12.0, 22.0, 23.0, 24.0]


def test_complex_is_kept():
    d = lbd.Dataset()
    d.add_axis("a", [0.0, 1.0])
    d.add_value("z", np.array([1 + 2j, 3 + 4j]), axes="a")
    assert points_of(d, {}, "z").data[1] == 3 + 4j


def test_a_data_point_axis_can_be_all():
    d = lbd.Dataset()
    d.add_axis("amp", [0.0, 1.0])
    d.add_value("bloch", np.arange(6.0).reshape(2, 3), axes="amp", shape=(3,))
    f = render.flat(d)
    point = f.values["bloch"].axes[-1]
    p = points_of(d, {"index": {"amp": 1}, "all": [point]}, "bloch")
    assert list(p.data) == [3.0, 4.0, 5.0] and point in p.coords


def test_iter_points_gives_the_same_numbers_in_blocks():
    d = cube()
    blocks = list(iter_points(d, {"index": {"a": 1}}, "v", block=5))
    assert len(blocks) > 1 and all(step is None for step, _ in blocks)
    assert np.array_equal(np.concatenate([n for _, n in blocks]), points_of(d, {"index": {"a": 1}}, "v").data)


def test_iter_points_by_colour():
    d = cube()
    blocks = list(iter_points(d, {"color": "a", "index": {"b": 0}}, "v"))
    assert [s for s, _ in blocks] == [0, 1]
    assert list(blocks[1][1]) == [12.0, 13.0, 14.0, 15.0]
