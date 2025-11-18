import numpy as np

from app.iv_simulation.ion import IonModel
from app.iv_simulation.solver import compute_dynamic_iv


def test_dynamic_iv_with_rf_modulation() -> None:
    result = compute_dynamic_iv(
        ne_base=5e15,
        te_ev_base=3.0,
        vs_base=0.0,
        gas_type="Ar",
        mi_custom=None,
        area=1e-6,
        radius=1e-3,
        length=5e-3,
        capacitance=1e-12,
        model=IonModel.ABR,
        frequency_hz=13.56e6,  # Typical RF frequency
        te_amplitude_ev=0.5,
        ne_amplitude=1e14,
        vs_amplitude_v=2.0,
        total_time_s=1e-6,  # Short time for test
        dt_s=1e-9,
        vp_initial=-10.0,
    )
    assert len(result.time) > 0
    assert len(result.vp) == len(result.time)
    assert len(result.ie) == len(result.time)
    assert len(result.i_total) == len(result.time)
    assert result.metadata["frequency_hz"] == 13.56e6
    assert "nyquist_dt_s" in result.metadata
    # Check that Vp evolves
    assert not np.allclose(result.vp, -10.0)
