# Langmuir I–V Simulation Module

This document summarizes the physics approximations and JSON interface for the Langmuir I–V simulator.

## Implemented models

- **Electron branch:** Maxwell–Boltzmann distribution with a soft saturation cap once the probe exceeds the plasma potential.
- **Ion branch:** selectable via the `model` parameter
  - `OML`: orbital-motion-limited current for tenuous plasmas.
  - `ABR`: Allen–Boyd–Reynolds approximation (cold, radial ions) implemented as an OML curve with a geometry factor that follows ξ\_p.
  - `BRL`: Bernstein–Rabinowitz–Laframboise variant with a higher geometry factor to mimic sheath-limited collection.
  - `ChildLangmuir`: phenomenological Child–Langmuir scaling that enforces an `I^(4/3) ∝ (V_f - V)` trend in dense RF plasmas.

Each solver call also reports the Bohm ion saturation current (`metadata.bohm_isat`) for reference.

## RF Modulation Support

The dynamic solver supports time-domain simulations with RF modulation of plasma parameters:

- Electron density \( n_e(t) = n_{e0} + A_{ne} \sin(2\pi f t) \)
- Electron temperature \( T_e(t) = T_{e0} + A_{Te} \sin(2\pi f t) \)
- Space potential \( V_s(t) = V_{s0} + A_{Vs} \sin(2\pi f t) \)

Time step is automatically checked against the Nyquist criterion: \( \Delta t < \frac{1}{2f} \).

## Assumptions and limitations

- Electrons are Maxwellian, ions are cold at the sheath edge.
- Magnetic fields, collisions, and RF modulation of the sheath are not yet modeled explicitly.
- ABR/BRL branches currently rely on smooth geometry scalings; swap in full Poisson solutions or interpolation tables for higher accuracy.
- The Child–Langmuir branch is a placeholder to recover the experimentally observed `I^(4/3)` trend; it does not solve the full diode equation.

## REST API

The module now exposes only the time-domain dynamic endpoint. Static sweeps were removed in favor of physics-forward dynamic simulations.

`POST /api/iv/dynamic`

```json
{
  "plasma": {
    "ne": 5e15,
    "te_eV": 3.0,
    "vs": 0.0,
    "gas_type": "Ar"
  },
  "probe": {
    "area": 1e-6,
    "radius": 1e-3,
    "length": 5e-3,
    "capacitance": 1e-12
  },
  "rf": {
    "frequency_hz": 13560000.0,
    "te_amplitude_ev": 0.5,
    "ne_amplitude": 1e14,
    "vs_amplitude_v": 2.0
  },
  "time_range": {
    "total_time_s": 1e-6,
    "dt_s": 1e-9
  },
  "vp_initial": -10.0,
  "model": "ABR"
}
```

Response: see `POST /api/iv/dynamic` section below.

## REST API

`POST /api/iv/dynamic`

```json
{
  "plasma": {
    "ne": 5e15,
    "te_eV": 3.0,
    "vs": 0.0,
    "gas_type": "Ar"
  },
  "probe": {
    "area": 1e-6,
    "radius": 1e-3,
    "length": 5e-3,
    "capacitance": 1e-12
  },
  "rf": {
    "frequency_hz": 13560000.0,
    "te_amplitude_ev": 0.5,
    "ne_amplitude": 1e14,
    "vs_amplitude_v": 2.0
  },
  "time_range": {
    "total_time_s": 1e-6,
    "dt_s": 1e-9
  },
  "vp_initial": -10.0,
  "model": "ABR"
}
```

Response:

```json
{
  "time": [...],
  "vp": [...],
  "ne": [...],
  "te_eV": [...],
  "vs": [...],
  "ie": [...],
  "ii": [...],
  "i_total": [...],
  "metadata": {
    "model": "ABR",
    "frequency_hz": 13560000.0,
    "nyquist_dt_s": 3.69e-09,
    "actual_dt_s": 1e-09,
    "capacitance_f": 1e-12
  }
}
```

The frontend converts these arrays into time-domain plots for probe potential and current evolution.
