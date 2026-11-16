"""The mock files for several values (mock_values.py) have the structure their tests rely on."""

import numpy as np
import pytest

import lbd
import mock_values


@pytest.mark.parametrize("small", [True, False])
def test_the_mock_files(tmp_path, small):
    paths = {p.name: p for p in mock_values.write_all(tmp_path, small=small)}
    assert list(paths) == mock_values.NAMES

    rabi = lbd.load(paths["6 rabi.lbd"])
    assert sorted(rabi.values) == ["I", "Q", "phase", "population"]   # listed alphabetically (spec §1)
    assert {rabi.values[n].unit for n in rabi.values} == {"V", "", "rad"}

    spec = lbd.load(paths["7 spectroscopy 3d.lbd"])
    assert spec.values["amplitude"].axes == ["qubit_power", "flux", "frequency"]

    mixed = lbd.load(paths["8 mixed axes.lbd"])
    assert [mixed.values[n].axes for n in ("S21", "S21_ref", "f0", "Q_i", "temperature")] == \
        [["power", "frequency"], ["frequency"], ["power"], ["power"], []]

    assert len(lbd.load(paths["9 many values.lbd"]).values) == 8
    assert list(lbd.load(paths["10 one value.lbd"]).values) == ["S21"]

    iq = lbd.load(paths["11 single shot iq.lbd"])
    assert np.iscomplexobj(iq.values["IQ"].data) and iq.values["IQ"].axes == ["readout_power", "state", "shot"]
    fid = np.asarray(iq.values["fidelity"].data)
    assert np.all((fid > 0.5) & (fid <= 1)) and fid[-1] >= fid[0]     # better at higher power


def test_the_files_for_the_plot_types(tmp_path):
    paths = {p.name: p for p in mock_values.write_all(tmp_path, small=True)}
    d = lbd.load(paths["16 density matrix.lbd"])
    assert d.values["rho"].shape == (3, 4, 4) and d.axes["row"].elements == ["00", "01", "10", "11"]
    assert np.iscomplexobj(d.values["rho"].data)
    d = lbd.load(paths["17 assignment matrix.lbd"])
    assert np.allclose(d.values["probability"].data.sum(axis=1), 1)
    d = lbd.load(paths["18 bars.lbd"])
    assert d.values["fidelity"].shape == () and d.axes["state"].elements[0] == "ground"
    d = lbd.load(paths["19 curved grid.lbd"])
    assert np.all(np.bincount(np.asarray(d.axes["x"].parent)) == 5)


@pytest.mark.parametrize("small", [True, False])
def test_the_uneven_grids(tmp_path, small):
    paths = {p.name: p for p in mock_values.write_all(tmp_path, small=small)}
    d = lbd.load(paths["20 uneven map.lbd"])
    for axis in ("x", "y"):                                             # steps that grow on both axes
        assert np.all(np.diff(np.diff(d.axes[axis].data)) > 0)
    v = d.values["value"].data
    assert v[2, 3] == 3 + 10 * 2 and d.plot["kind"] == "heatmap"     # a cell's value says where it is
    d = lbd.load(paths["21 log axis map.lbd"])
    assert np.allclose(np.diff(np.log10(d.axes["f"].data)), np.diff(np.log10(d.axes["f"].data))[0])
    assert d.plot["x_scale"] == "log"
    x = lbd.load(paths["22 uneven curve.lbd"]).axes["x"].data
    steps = np.diff(x)
    assert np.all(steps > 0) and steps.max() > 10 * steps.min()        # dense near the peak, sparse away


def test_the_old_record_is_todays_single_view():
    rec = mock_values.old_record()
    assert "version" not in rec and rec["spec"]["values"] == ["S21"]
