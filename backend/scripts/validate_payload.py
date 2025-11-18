import json
from app.iv_simulation.schemas import IVDynamicRequest

payload = {
  "plasma": {"ne": 5000000000000000, "te_eV": 3, "vs": 15, "gas_type": "Ar", "mi_custom": None},
  "probe": {"area": 1e-6, "radius": 0.001, "length": 0.005, "capacitance": 1e-12},
  "rf": {"frequency_hz": 13560000, "te_amplitude_ev": 0.5, "ne_amplitude": 100000000000000, "vs_amplitude_v": 2},
  "time_range": {"total_time_s": 1e-6, "dt_s": 1e-9},
  "vp_initial": -10,
  "model": "ABR",
  "integrator": "rk4",
}

try:
    req = IVDynamicRequest(**payload)
    print('Pydantic validation OK')
    print('time_range:', req.time_range)
    print('vp_fixed:', req.vp_fixed)
except Exception as e:
    print('Validation error:')
    print(e)
