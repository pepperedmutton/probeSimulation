import numpy as np
from app.iv_simulation.ion import IonModel
from app.iv_simulation.solver import compute_dynamic_iv


def run_sim(frequency_hz, integrator='rk4', dt_override=None, capacitance=1e-12):
    dt = dt_override if dt_override is not None else min(1e-9, 1.0/(20.0*frequency_hz))
    return compute_dynamic_iv(
        ne_base=5e15,
        te_ev_base=3.0,
        vs_base=0.0,
        gas_type="Ar",
        mi_custom=None,
        area=1e-6,
        radius=1e-3,
        length=5e-3,
        capacitance=capacitance,
        model=IonModel.ABR,
        frequency_hz=frequency_hz,
        te_amplitude_ev=0.5,
        ne_amplitude=1e14,
        vs_amplitude_v=2.0,
        total_time_s=1e-6,
        dt_s=dt,
        vp_initial=-10.0,
        integrator=integrator,
    )


if __name__ == '__main__':
    f1 = 1e6
    f2 = 2e7
    print(f"Running simulations f1={f1}, f2={f2}")

    r1 = run_sim(f1)
    r2 = run_sim(f2)

    print('len time:', len(r1.time), len(r2.time))
    print('metadata f1,f2:', r1.metadata.get('frequency_hz'), r2.metadata.get('frequency_hz'))

    vp1 = np.array(r1.vp)
    vp2 = np.array(r2.vp)
    it1 = np.array(r1.i_total)
    it2 = np.array(r2.i_total)

    print('final Vp f1:', vp1[-1])
    print('final Vp f2:', vp2[-1])
    print('Vp diff norm:', np.linalg.norm(vp1 - vp2))
    print('i_total diff norm:', np.linalg.norm(it1 - it2))

    # also try with much smaller capacitance to see sensitivity
    r1_smallC = run_sim(f1, capacitance=1e-15)
    r2_smallC = run_sim(f2, capacitance=1e-15)
    print('\nWith smaller capacitance (1e-15 F):')
    print('final Vp f1:', r1_smallC.vp[-1])
    print('final Vp f2:', r2_smallC.vp[-1])
    print('Vp diff norm:', np.linalg.norm(np.array(r1_smallC.vp) - np.array(r2_smallC.vp)))

    print('\nDone')
