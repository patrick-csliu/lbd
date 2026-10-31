"""Axis groups (format 2.0): variable sweeps, the worked cases of the data API (planning:
plan 6c, "The data API"). Each case is checked as built in memory and as loaded from its file.

Case 2: group A → B, B chosen per A (A=1: B=10; A=2: B=10, 20; A=3: B=15, 25, 35); f per
(A, B) point, q per A. Case 3: the same group and a fixed axis C; h per (A, B) point × C.
Case 4: group A → B → C (B in range(A), C in range(B)); f per (A, B) point, g per (A, B, C)
point. Case 5b: a 2 × 2 matrix per (A, B) point.
"""

import h5py
import numpy as np
import pytest

import lbd

B_OF = {1: [10], 2: [10, 20], 3: [15, 25, 35]}


def group_ab(d, name="AB"):
    d.add_group(name)
    d.add_axis("A", group=name)
    d.add_axis("B", group=name)


def case2():
    d = lbd.Dataset("case 2")
    group_ab(d)
    d.add_value("f", axes=["A", "B"])
    d.add_value("q", axes=["A"])
    for a, bs in B_OF.items():
        for b in bs:
            d.write(A=a, B=b, f=100 * a + b)
        d.write(A=a, q=1.5 * a)
    return d


def case3():
    d = lbd.Dataset("case 3")
    group_ab(d)
    d.add_axis("C", [0.1, 0.2, 0.3])
    d.add_value("f", axes=["A", "B"])
    d.add_value("h", axes=["A", "B", "C"])
    for a, bs in B_OF.items():
        for b in bs:
            d.write(A=a, B=b, f=100 * a + b, h=[a, b, a + b])     # h: one number per C
    return d


def case4():
    d = lbd.Dataset("case 4")
    d.add_group("ABC")
    for a in "ABC":
        d.add_axis(a, group="ABC")
    d.add_value("f", axes=["A", "B"])
    d.add_value("g", axes=["ABC"])
    for a in [1, 2, 3]:
        for b in range(a):
            d.write(A=a, B=b, f=10 * a + b)
            c = np.arange(b)
            d.write(A=a, B=b, C=c, g=100 * a + 10 * b + c)
    return d


def case4_by_parent():
    d = lbd.Dataset("case 4")
    d.add_group("ABC")
    for a in "ABC":
        d.add_axis(a, group="ABC")
    d.add_value("f", axes=["A", "B"])
    d.add_value("g", axes=["ABC"])
    for a in [1, 2, 3]:
        i = d.write(A=a)
        for b in range(a):
            k = d.write(parent=i, B=b, f=10 * a + b)
            c = np.arange(b)
            d.write(parent=k, C=c, g=100 * a + 10 * b + c)
    return d


def case5b():
    d = lbd.Dataset("case 5b")
    group_ab(d)
    d.add_value("cov", axes=["A", "B"], shape=(2, 2), elements=[["I", "Q"], ["I", "Q"]])
    for a, bs in B_OF.items():
        d.write(A=a, B=bs, cov=np.arange(4.0 * len(bs)).reshape(len(bs), 2, 2) + a)
    return d


@pytest.fixture(params=["built", "loaded"])
def source(request, tmp_path):
    def get(make):
        d = make()
        if request.param == "built":
            return d
        return lbd.load(d.save(tmp_path / f"{make.__name__}.lbd"))
    return get


# ---- properties ------------------------------------------------------------------


def test_case2_levels_and_values(source):
    d = source(case2)
    assert list(d.groups) == ["AB"] and d.groups["AB"].order == ["A", "B"]
    assert list(d.axes["A"].data) == [1, 2, 3] and d.axes["A"].parent is None
    assert list(d.axes["B"].data) == [10, 10, 20, 15, 25, 35]
    assert list(d.axes["B"].parent) == [0, 1, 1, 2, 2, 2]
    assert d.axes["A"].group == d.axes["B"].group == "AB"
    f, q = d.values["f"], d.values["q"]
    assert f.axes == ["A", "B"] and f.dims == [("A", "B")] and f.shape == (6,) and f.point_shape == ()
    assert list(f.data) == [110, 210, 220, 315, 325, 335]
    assert q.axes == ["A"] and q.dims == [("A",)] and list(q.data) == [1.5, 3.0, 4.5]


def test_case3_a_group_and_a_fixed_axis(source):
    d = source(case3)
    h = d.values["h"]
    assert h.axes == ["A", "B", "C"] and h.dims == [("A", "B"), ("C",)] and h.shape == (6, 3)
    assert list(h.data[5]) == [3, 35, 38]
    assert d.axes["C"].group is None and d.axes["C"].parent is None


def test_case4_a_group_of_three(source):
    d = source(case4)
    assert d.groups["ABC"].order == ["A", "B", "C"]
    assert list(d.axes["B"].data) == [0, 0, 1, 0, 1, 2] and list(d.axes["B"].parent) == [0, 1, 1, 2, 2, 2]
    assert list(d.axes["C"].data) == [0, 0, 0, 1] and list(d.axes["C"].parent) == [2, 4, 5, 5]
    f, g = d.values["f"], d.values["g"]
    assert f.dims == [("A", "B")] and f.shape == (6,) and list(f.data) == [10, 20, 21, 30, 31, 32]
    assert g.axes == ["A", "B", "C"] and g.dims == [("A", "B", "C")] and list(g.data) == [210, 310, 320, 321]


def test_case5b_a_matrix_per_point_of_a_group(source):
    d = source(case5b)
    cov = d.values["cov"]
    assert cov.axes == ["A", "B"] and cov.dims == [("A", "B")]
    assert cov.point_shape == (2, 2) and cov.shape == (6, 2, 2)
    assert cov.elements == [["I", "Q"], ["I", "Q"]]
    assert np.array_equal(cov.data[4], [[7, 8], [9, 10]])      # A=3, B=25: the second of A=3's three


def test_writing_by_parent_makes_the_same_file(tmp_path):
    a = case4().save(tmp_path / "a.lbd")
    b = case4_by_parent().save(tmp_path / "b.lbd")
    with h5py.File(a, "r") as fa, h5py.File(b, "r") as fb:
        for path in ("axes/ABC/A", "axes/ABC/B", "axes/ABC/B._parent", "axes/ABC/C", "axes/ABC/C._parent",
                     "values/f", "values/g"):
            assert np.array_equal(fa[path][()], fb[path][()]), path
        assert fa["axes/ABC"].attrs["order"] == "A,B,C"
        assert fa["values/g"].attrs["axes"] == "A,B,C" and fa["values/f"].attrs["axes"] == "A,B"


def test_the_file_is_format_2_0_only_with_a_group(tmp_path):
    with h5py.File(case2().save(tmp_path / "g.lbd"), "r") as f:
        assert f.attrs["lbd_version"] == "2.0"
    d = lbd.Dataset()
    d.add_axis("x", [1, 2])
    with h5py.File(d.save(tmp_path / "x.lbd"), "r") as f:
        assert f.attrs["lbd_version"] == "1.2"


def test_points_without_inner_points_and_values_on_grown_levels():
    d = case4()
    # (A, B) = (1, 0), (2, 0), (3, 0) have no C; f has every (A, B) point
    assert len(d.axes["B"].data) == 6 and len(d.axes["C"].data) == 4
    d.write(A=4, B=0, C=7, g=1.0)                 # new A, B and C points: f gets a point not measured
    assert d.values["f"].shape == (7,) and np.isnan(d.values["f"].data[-1])


def test_the_same_coordinates_are_the_same_point():
    d = case2()
    i = d.write(A=3, B=25, f=-1.0)
    assert i == 4 and len(d.axes["B"].data) == 6 and d.values["f"].data[4] == -1
    assert list(d.write(A=3, B=[15, 99])) == [3, 6]           # found, and added


def test_integer_values_on_a_group_mark_what_was_measured():
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("n", axes=["A", "B"], dtype="int32")
    d.write(A=1, B=[1, 2], n=[5, 6])
    d.write(A=2, B=1)                               # a point, n not written there
    assert list(d.values["n"].data) == [5, 6, 0] and list(d.values["n"].measured) == [True, True, False]


# ---- reading: coords, rows, to_dense --------------------------------------------------


def test_coords(source):
    c = source(case2).values["f"].coords()
    assert list(c) == ["A", "B"]
    assert list(c["A"]) == [1, 2, 2, 3, 3, 3] and list(c["B"]) == [10, 10, 20, 15, 25, 35]
    g = source(case4).coords("g")
    assert list(g["A"]) == [2, 3, 3, 3] and list(g["B"]) == [1, 1, 2, 2] and list(g["C"]) == [0, 0, 0, 1]
    h = source(case3).values["h"].coords()
    assert len(h["A"]) == 6 and list(h["C"]) == [0.1, 0.2, 0.3]
    f = source(_fixed).values["f"].coords()
    assert list(f["A"]) == [1, 2, 3] and list(f["B"]) == [10, 20]


def test_coords_follow_the_parents():
    d = case4()
    A, B, C = d.axes["A"], d.axes["B"], d.axes["C"]
    c = d.coords("g")
    assert list(c["A"]) == list(A.data[B.parent[C.parent]]) and list(c["B"]) == list(B.data[C.parent])


def _fixed():
    d = lbd.Dataset()
    d.add_axis("A", [1, 2, 3])
    d.add_axis("B", [10, 20])
    d.add_value("f", np.arange(6.0).reshape(3, 2), axes=["A", "B"])
    return d


def test_rows_by_the_outer_axis(source):
    rows = list(source(case2).values["f"].rows(by="A"))
    assert [k for k, _ in rows] == [1, 2, 3]
    last = rows[2][1]
    assert isinstance(last, lbd.Dataset) and not last.groups
    assert list(last.axes["B"].data) == [15, 25, 35] and list(last.values["f"].data) == [315, 325, 335]
    assert list(rows[0][1].axes["B"].data) == [10]
    fixed = list(_fixed().rows("f", by="A"))
    assert [k for k, _ in fixed] == [1, 2, 3] and list(fixed[0][1].axes["B"].data) == [10, 20]


def test_rows_of_a_group_of_three(source):
    d = source(case4)
    by_b = dict(d.values["g"].rows(by="B"))
    assert list(by_b) == [(1, 0), (2, 0), (2, 1), (3, 0), (3, 1), (3, 2)]
    assert list(by_b[(3, 2)].axes["C"].data) == [0, 1] and list(by_b[(3, 2)].values["g"].data) == [320, 321]
    assert by_b[(1, 0)].values["g"].shape == (0,)                  # no C points: an empty row
    by_a = dict(d.values["g"].rows(by="A"))
    row = by_a[3]
    assert row.groups["ABC"].order == ["B", "C"] and row.values["g"].dims == [("B", "C")]
    assert list(row.axes["B"].data) == [0, 1, 2] and row.axes["B"].parent is None
    assert list(row.axes["C"].data) == [0, 0, 1] and list(row.axes["C"].parent) == [1, 2, 2]
    assert list(row.values["g"].data) == [310, 320, 321]
    points = dict(d.values["f"].rows(by="B"))
    assert points[(3, 1)].values["f"].shape == () and float(points[(3, 1)].values["f"].data) == 31


def test_rows_keep_the_other_dimensions_and_the_data_point(source):
    h_rows = dict(source(case3).values["h"].rows(by="A"))
    assert h_rows[3].values["h"].axes == ["B", "C"] and h_rows[3].values["h"].shape == (3, 3)
    cov_rows = dict(source(case5b).values["cov"].rows(by="A"))
    assert cov_rows[3].values["cov"].shape == (3, 2, 2) and cov_rows[3].values["cov"].point_shape == (2, 2)


def test_rows_are_copies():
    d = case2()
    _, row = next(d.values["f"].rows(by="A"))
    row.values["f"].data[0] = -5
    assert d.values["f"].data[0] == 110


def test_rows_of_points_written_out_of_order():
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("f", axes=["A", "B"])
    d.write(A=1, B=1, f=1.0)
    d.write(A=2, B=1, f=2.0)
    d.write(A=1, B=2, f=3.0)                        # A=1's points aren't next to each other
    rows = dict(d.values["f"].rows(by="A"))
    assert list(rows[1].axes["B"].data) == [1, 2] and list(rows[1].values["f"].data) == [1, 3]


def test_to_dense(source):
    m = source(case2).values["f"].to_dense()
    assert isinstance(m, lbd.Dataset) and not m.groups
    assert list(m.axes["A"].data) == [1, 2, 3] and list(m.axes["B"].data) == [10, 15, 20, 25, 35]
    f = m.values["f"]
    assert f.axes == ["A", "B"] and f.dims == [("A",), ("B",)] and f.shape == (3, 5) and f.measured is None
    expected = np.full((3, 5), np.nan)
    expected[0, 0], expected[1, 0], expected[1, 2] = 110, 210, 220
    expected[2, 1], expected[2, 3], expected[2, 4] = 315, 325, 335
    assert np.array_equal(f.data, expected, equal_nan=True)


def test_to_dense_of_each_case(source):
    h = source(case3).to_dense("h").values["h"]
    assert h.shape == (3, 5, 3) and list(h.data[2, 4]) == [3, 35, 38]
    d4 = source(case4)
    f, g = d4.to_dense("f"), d4.to_dense("g")
    assert f.values["f"].shape == (3, 3) and list(f.axes["B"].data) == [0, 1, 2]
    assert g.values["g"].shape == (2, 2, 2) and list(g.axes["A"].data) == [2, 3]     # g's own points
    assert list(g.axes["B"].data) == [1, 2] and list(g.axes["C"].data) == [0, 1]
    cov = source(case5b).to_dense("cov").values["cov"]
    assert cov.shape == (3, 5, 2, 2) and cov.point_shape == (2, 2)
    assert np.array_equal(cov.data[2, 3], [[7, 8], [9, 10]]) and np.all(np.isnan(cov.data[0, 1]))
    fixed = _fixed().to_dense("f").values["f"]
    assert np.array_equal(fixed.data, np.arange(6.0).reshape(3, 2))


def test_to_dense_of_integers_marks_the_gaps(tmp_path):
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("n", axes=["A", "B"], dtype="int16")
    d.write(A=1, B=[1, 2], n=[5, 6])
    d.write(A=2, B=2, n=7)
    n = d.to_dense("n").values["n"]
    assert n.data.dtype == np.int16 and n.data.tolist() == [[5, 6], [0, 7]]
    assert n.measured.tolist() == [[True, True], [False, True]]
    m = n.to_dense()                                  # a dense value: a copy
    m.save(tmp_path / "dense.lbd")                    # an ordinary 1.2 file
    with h5py.File(tmp_path / "dense.lbd", "r") as f:
        assert f.attrs["lbd_version"] == "1.2"


def test_to_dense_limit():
    d = case2()
    with pytest.raises(lbd.LBDError, match=r"15 cells .* rows\(by=...\), or give limit=None"):
        d.to_dense("f", limit=10)
    assert d.to_dense("f", limit=None).values["f"].shape == (3, 5)


def near_equal(first=0.3, second=0.1 + 0.2):
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("f", axes=["A", "B"])
    d.write(A=first, B=1, f=1.0)
    with pytest.warns(lbd.LBDWarning, match="is a new point next to"):
        d.write(A=second, B=2, f=2.0)
    return d


def test_near_equal_coordinates_are_warned_and_kept_apart():
    d = near_equal()
    assert len(d.axes["A"].data) == 2
    with pytest.warns(lbd.LBDWarning, match="differ only by rounding"):
        m = d.to_dense("f")
    assert m.values["f"].shape == (2, 2)


def test_to_dense_merges_near_equal_coordinates_when_asked():
    for d in (near_equal(), near_equal(0.1 + 0.2, 0.3)):          # the order written doesn't matter
        r = d.to_dense("f", round=9)
        assert list(r.axes["A"].data) == [0.3] and r.values["f"].data.tolist() == [[1.0, 2.0]]
        t = d.to_dense("f", rtol=1e-9)
        assert t.values["f"].shape == (1, 2) and abs(t.axes["A"].data[0] - 0.3) < 1e-15
        assert d.to_dense("f", atol=1e-12).values["f"].shape == (1, 2)


def test_merging_never_drops_a_result():
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("f", axes=["A", "B"])
    d.write(A=0.3, B=1, f=1.0)
    with pytest.warns(lbd.LBDWarning):
        d.write(A=0.1 + 0.2, B=1, f=2.0)
    with pytest.raises(lbd.LBDError, match="two points of 'f' fall into one cell"):
        d.to_dense("f", round=9)
    with pytest.raises(lbd.LBDError, match="round= or rtol= / atol=, not both"):
        d.to_dense("f", round=9, rtol=1e-9)


def test_integer_coordinates_are_never_near_equal():
    d = lbd.Dataset()
    group_ab(d)
    d.add_value("f", axes=["A", "B"])
    d.write(A=1, B=[1, 2, 3], f=[1.0, 2.0, 3.0])    # no warning (pytest turns warnings into errors)
    d.to_dense("f")


# ---- refusals, with what to do -------------------------------------------------------


def test_a_value_lies_on_an_outer_part_of_a_group():
    d = lbd.Dataset()
    d.add_group("ABC")
    for a in "ABC":
        d.add_axis(a, group="ABC")
    with pytest.raises(lbd.LBDError, match="inner axis of group 'ABC'"):
        d.add_value("x", axes=["B"])
    with pytest.raises(lbd.LBDError, match="in its order"):
        d.add_value("x", axes=["A", "C"])
    with pytest.raises(lbd.LBDError, match="appears more than once"):
        d.add_value("x", axes=["ABC", "A"])


def test_write_refusals():
    d = case2()
    with pytest.raises(lbd.LBDError, match=r"means something only under \['A'\]"):
        d.write(B=10, f=1.0)
    with pytest.raises(lbd.LBDError, match=r"give \['B'\] too"):
        d.write(A=3, f=1.0)
    with pytest.raises(lbd.LBDError, match="doesn't lie on 'B'"):
        d.write(A=3, B=15, q=1.0)
    with pytest.raises(lbd.LBDError, match="NaN or inf"):
        d.write(A=np.nan, B=1, f=1.0)
    with pytest.raises(lbd.LBDError, match="different lengths"):
        d.write(A=[1, 2], B=[1, 2, 3])
    with pytest.raises(lbd.LBDError, match="first axis of group"):
        d.write(parent=0, A=4)
    with pytest.raises(lbd.LBDError, match="is not a point of 'A'"):
        d.write(parent=7, B=1)
    with pytest.raises(lbd.LBDError, match="give the next axes of that group"):
        d.write(parent=0, f=1.0)
    with pytest.raises(lbd.LBDError, match=r"needs data of shape \(2,\)"):
        d.write(A=1, B=[1, 2], f=1.0)
    assert len(d.axes["B"].data) == 6                    # nothing was written by the refused calls


def test_group_axes_take_no_data_and_need_their_group():
    d = lbd.Dataset()
    with pytest.raises(lbd.LBDError, match="no group 'G'"):
        d.add_axis("x", group="G")
    d.add_group("G")
    with pytest.raises(lbd.LBDError, match="give no data"):
        d.add_axis("x", [1, 2], group="G")
    with pytest.raises(lbd.LBDError, match="already used by an axis, group or value"):
        d.add_axis("G", [1])
    with pytest.raises(lbd.LBDError, match="has no axes yet"):
        d.add_value("v", axes=["G"])


def test_a_value_not_in_a_dataset():
    v = lbd.Value("v", np.zeros(2), ["x"])
    with pytest.raises(lbd.LBDError, match="isn't part of a dataset"):
        v.to_dense()


# ---- files with groups: checks when reading ---------------------------------------------


def test_a_parent_outside_the_level_above_is_refused(tmp_path):
    p = case2().save(tmp_path / "g.lbd")
    with h5py.File(p, "a") as f:
        par = f["axes/AB/B._parent"]
        par[5] = 9
    with pytest.raises(lbd.LBDError, match="points outside 'A'"):
        lbd.load(p)


def test_the_same_point_twice_is_kept_with_a_warning(tmp_path):
    p = case2().save(tmp_path / "g.lbd")
    with h5py.File(p, "a") as f:
        b = f["axes/AB/B"]
        b[5] = 25                                         # (3, 35) becomes a second (3, 25)
    with pytest.warns(lbd.LBDWarning, match="the same point twice"):
        d = lbd.load(p)
    assert len(d.axes["B"].data) == 6


def test_a_group_without_its_order_is_refused(tmp_path):
    p = case2().save(tmp_path / "g.lbd")
    with h5py.File(p, "a") as f:
        del f["axes/AB"].attrs["order"]
    with pytest.raises(lbd.LBDError, match="no 'order' attribute"):
        lbd.load(p)


def test_info_reads_the_levels_without_the_data(tmp_path):
    i = lbd.info(case4().save(tmp_path / "g.lbd"))
    assert i.values["g"].data is None and i.values["g"].shape == (4,) and list(i.axes["C"].parent) == [2, 4, 5, 5]
