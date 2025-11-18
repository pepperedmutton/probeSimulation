import numpy as np

from app.iv_simulation.ion import IonModel
from app.iv_simulation.solver import compute_dynamic_iv


def test_frequency_changes_probe_response() -> None:
    # run two simulations with different RF frequencies and ensure final Vp differs
    r1 = compute_dynamic_iv(
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
        frequency_hz=1e6,
        te_amplitude_ev=0.5,
        ne_amplitude=1e14,
        vs_amplitude_v=2.0,
        total_time_s=1e-6,
        dt_s=1e-9,
        vp_initial=-10.0,
        integrator='rk4',
    )

    r2 = compute_dynamic_iv(
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
        frequency_hz=2e7,
        te_amplitude_ev=0.5,
        ne_amplitude=1e14,
        vs_amplitude_v=2.0,
        total_time_s=1e-6,
        dt_s=1e-9,
        vp_initial=-10.0,
        integrator='rk4',
    )

    vp1 = np.array(r1.vp)
    vp2 = np.array(r2.vp)
    # Expect non-negligible difference for these parameters
    assert not np.allclose(vp1[-1], vp2[-1])
