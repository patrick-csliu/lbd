"""What the Values & axes table gets for a variable sweep (plan 16, 16.42 and 16.40): the real
axes of each value, its shape in steps, and per axis of the sweep its range over the file, its
points per step and the axis it depends on."""

import lbd
import mock_values
import pytest
from lbd_viewer.server import file_summary


@pytest.fixture(scope="module")
def full_size(tmp_path_factory):
    folder = tmp_path_factory.mktemp("variable")
    for name in ("13 variable sweep.lbd", "14 triangle.lbd"):
        mock_values.MAKERS[name](False).save(folder / name)
    return folder


def rows(summary):
    return ({v["name"]: v.get("variable") for v in summary["values"]},
            {a["name"]: a.get("variable") for a in summary["axes"]})


def test_a_triangle_sweep(full_size):
    values, axes = rows(file_summary(lbd.info(full_size / "14 triangle.lbd")))
    assert values["S"] == {"axes": ["A", "B"], "shape": "40 steps × 1–40 (820 points)"}
    assert axes["A"] == {"label": "A", "total": 40, "min": 1.0, "max": 40.0}           # the outer axis: no note
    assert axes["B"]["per_step"] == [1, 40] and axes["B"]["total"] == 820 and axes["B"]["depends_on"] == "A"


def test_a_power_sweep_with_frequencies_chosen_per_power(full_size):
    values, axes = rows(file_summary(lbd.info(full_size / "13 variable sweep.lbd")))
    assert values["S21"] == {"axes": ["power", "freq"], "shape": "21 steps × 40–46 (894 points)"}
    assert values["Q"] == {"axes": ["power"], "shape": "21"}
    assert axes["freq"]["per_step"] == [40, 46] and axes["freq"]["depends_on"] == "Power"
    assert axes["freq"]["min"] == pytest.approx(6.995e9)                                # over the file, not point numbers


def test_files_without_a_variable_sweep_get_nothing_new(values_files, data_dir):
    values, axes = rows(file_summary(lbd.info(data_dir / "6 rabi.lbd")))
    assert not any(values.values()) and not any(axes.values())
