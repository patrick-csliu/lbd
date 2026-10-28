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


def test_the_old_record_is_todays_single_view():
    rec = mock_values.old_record()
    assert "version" not in rec and rec["spec"]["values"] == ["S21"]
