"""Files with variable sweeps (axis groups, format 2.0, plan 6c) open in the viewer: values are
drawn against their point number for now, with a notice; the file page and the Library show
the group."""

import lbd
import pytest

from lbd.plot import render as rnd
from lbd.plot.style import Style
from lbd_viewer.server import file_summary


@pytest.fixture()
def files(values_files):
    return {p.name: p for p in values_files}


def test_the_summary_shows_the_group(files):
    s = file_summary(lbd.info(files["13 variable sweep.lbd"]))
    assert s["lbd_version"] == "2.0" and s["groups"] == {"scan": ["power", "freq"]}
    axes = {a["name"]: a for a in s["axes"]}
    assert axes["freq"]["group"] == "scan" and axes["freq"]["length"] == 44
    assert axes["freq"]["label"] == "Frequency (point number)"
    values = {v["name"]: v for v in s["values"]}
    assert values["S21"]["axes"] == ["freq"] and values["Q"]["axes"] == ["power"]


def test_the_library_counts_the_points(client, files):
    client.app.state.lbd.library.scan()
    rows = {r["name"]: r for r in client.get("/api/library/list").json()["rows"]}
    assert rows["13 variable sweep.lbd"]["sweep"] == "44 points (variable)"
    assert rows["14 triangle.lbd"]["sweep"] == "15 points (variable)"
    assert rows["13 variable sweep.lbd"]["points"] == 44


def test_a_value_is_drawn_against_its_point_number_with_a_notice(files):
    with pytest.warns(rnd.RenderWarning, match="drawn against the point number"):
        svg, spec = rnd.render_file(str(files["13 variable sweep.lbd"]), {"values": ["S21"], "complex": "db"},
                                    Style(), fmt="svg")
    assert spec["kind"] == "curve" and spec["x"] == "freq"
    assert b"point number" in svg


def test_explore_opens_a_file_with_groups(client, files):
    for name in ("13 variable sweep.lbd", "14 triangle.lbd", "15 adaptive map.lbd"):
        r = client.post("/api/explore", json={"path": str(files[name]), "width": 400, "height": 300, "dpr": 1})
        assert r.status_code == 200, r.text
        o = r.json()
        assert any("point number" in m for m in o.get("warnings", [])), o.get("warnings")
        client.delete(f"/api/explore/{o['session']}")


def test_a_preview_is_drawn(client, files):
    client.app.state.lbd.library.scan()
    r = client.get("/api/library/preview", params={"path": str(files["14 triangle.lbd"])}).json()
    assert r["state"] in ("ready", "queued", "drawing"), r
