from dataclasses import dataclass
from math import sqrt
from typing import List

import numpy as np

ELEMENTARY_CHARGE = 1.602176634e-19
PERMITTIVITY_0 = 8.8541878128e-12
ELECTRON_MASS = 9.10938356e-31
AMU = 1.6605390666e-27
KB = 1.380649e-23


ION_MASS_LOOKUP = {
    "Ar": 39.948 * AMU,
    "Xe": 131.293 * AMU,
}


@dataclass
class PICConfig:
    macroparticles_per_species: int = 400
    steps: int = 200
    output_frames: int = 20


def _maxwellian_velocity(temperature_ev: float, mass: float, size: int) -> np.ndarray:
    thermal = sqrt(2 * ELEMENTARY_CHARGE * max(temperature_ev, 1e-3) / mass)
    return np.random.normal(0.0, thermal / np.sqrt(2), size=size)


def _dst(vector: np.ndarray) -> np.ndarray:
    """DST-I implemented via FFT (SciPy-free)."""
    n = vector.size
    extended = np.zeros(2 * (n + 1))
    extended[1 : n + 1] = vector
    extended[n + 2 :] = -vector[::-1]
    fft_vals = np.fft.fft(extended)
    return -fft_vals.imag[1 : n + 1]


def _solve_poisson_dirichlet(charge_density: np.ndarray, spacing: float, phi_bottom: float, phi_top: float) -> np.ndarray:
    """Solve 1D Poisson equation using a spectral (DST) approach with Dirichlet BC."""
    ny = charge_density.size
    if ny < 3:
        return np.linspace(phi_bottom, phi_top, ny)

    interior = charge_density[1:-1]
    rhs = -interior * spacing**2 / PERMITTIVITY_0
    rhs_hat = _dst(rhs)
    n = rhs.size
    k = np.arange(1, n + 1)
    eigenvalues = 2 * (1 - np.cos(k * np.pi / (n + 1)))
    eigenvalues[eigenvalues == 0] = 1e-12
    phi_hat = rhs_hat / eigenvalues
    phi_interior = (2.0 / (n + 1)) * _dst(phi_hat)

    phi = np.zeros(ny)
    phi[0] = phi_bottom
    phi[-1] = phi_top
    # add linear profile to satisfy boundaries
    linear = np.linspace(phi_bottom, phi_top, ny)
    phi[1:-1] = phi_interior + linear[1:-1]
    return phi


def _deposit_charges(y_positions: np.ndarray, charge_weight: float, accumulation: np.ndarray, spacing: float):
    """Cloud-In-Cell deposition onto 1D nodes (accumulates charge in Coulombs)."""
    ny = accumulation.size
    idx = np.clip((y_positions / spacing).astype(int), 0, ny - 2)
    frac = (y_positions - idx * spacing) / spacing
    np.add.at(accumulation, idx, charge_weight * (1 - frac))
    np.add.at(accumulation, idx + 1, charge_weight * frac)


def _initialize_particles(num: int, domain_height: float, temperature_ev: float, mass: float, drift: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.random.uniform(0.0, domain_height, size=num)
    vy = _maxwellian_velocity(temperature_ev, mass, num) + drift
    x = np.random.uniform(0.0, 1.0, size=num)
    return x, y, vy


def run_pic_slice_simulation(
    domain_width_m: float,
    conductor_thickness_m: float,
    sheath_thickness_m: float,
    presheath_thickness_m: float,
    bulk_thickness_m: float,
    ion_density_m3: float,
    electron_density_m3: float,
    ion_temperature_ev: float,
    electron_temperature_ev: float,
    plasma_potential_v: float,
    probe_bias_v: float,
    neutral_pressure_pa: float,
    ion_species: str,
    config: PICConfig,
) -> dict:
    domain_height = conductor_thickness_m + sheath_thickness_m + presheath_thickness_m + bulk_thickness_m
    debye_length = domain_height / 10.0
    spacing = debye_length / 10.0
    ny = max(int(domain_height / spacing) + 1, 64)
    y_grid = np.linspace(0.0, domain_height, ny)
    spacing = y_grid[1] - y_grid[0]

    ion_mass = ION_MASS_LOOKUP.get(ion_species, ION_MASS_LOOKUP["Ar"])
    n_particles = config.macroparticles_per_species
    cross_section = domain_width_m * 1e-3  # assume 1 mm depth for quasi-2D slice
    volume = cross_section * domain_height

    ion_weight = max(ion_density_m3 * volume / n_particles, 1.0)
    electron_weight = max(electron_density_m3 * volume / n_particles, 1.0)

    ion_x, ion_y, ion_vy = _initialize_particles(n_particles, domain_height, ion_temperature_ev, ion_mass, drift=-50.0)
    ele_x, ele_y, ele_vy = _initialize_particles(n_particles, domain_height, electron_temperature_ev, ELECTRON_MASS, drift=-500.0)

    vth_e = sqrt(2 * ELEMENTARY_CHARGE * max(electron_temperature_ev, 0.1) / ELECTRON_MASS)
    vth_i = sqrt(2 * ELEMENTARY_CHARGE * max(ion_temperature_ev, 0.01) / ion_mass)
    dt = 0.1 * spacing / max(vth_e, vth_i, 1e3)

    trajectories_ions: List[dict] = []
    trajectories_electrons: List[dict] = []
    frame_stride = max(config.steps // max(config.output_frames, 1), 1)

    for step in range(config.steps):
        node_charge = np.zeros(ny)
        _deposit_charges(ion_y, ELEMENTARY_CHARGE * ion_weight, node_charge, spacing)
        _deposit_charges(ele_y, -ELEMENTARY_CHARGE * electron_weight, node_charge, spacing)
        charge_density = node_charge / (cross_section * spacing)

        phi = _solve_poisson_dirichlet(charge_density, spacing, probe_bias_v, plasma_potential_v)
        electric_field = -np.gradient(phi, y_grid)

        ion_field = np.interp(ion_y, y_grid, electric_field)
        ele_field = np.interp(ele_y, y_grid, electric_field)

        ion_vy += (ELEMENTARY_CHARGE * ion_field / ion_mass) * dt
        ele_vy += (-ELEMENTARY_CHARGE * ele_field / ELECTRON_MASS) * dt

        ion_y += ion_vy * dt
        ele_y += ele_vy * dt

        # boundary: bottom probe absorbs & reinjects from top (bulk)
        for positions, velocities, mass, temp_ev, drift in (
            (ion_y, ion_vy, ion_mass, ion_temperature_ev, -50.0),
            (ele_y, ele_vy, ELECTRON_MASS, electron_temperature_ev, -500.0),
        ):
            mask_bottom = positions < 0
            mask_top = positions > domain_height
            reset_mask = mask_bottom | mask_top
            if np.any(reset_mask):
                positions[reset_mask] = domain_height * np.random.rand(reset_mask.sum())
                velocities[reset_mask] = _maxwellian_velocity(temp_ev, mass, reset_mask.sum()) + drift

        if step % frame_stride == 0:
            trajectories_ions.append({"x": ion_x.tolist(), "y": ion_y.tolist()})
            trajectories_electrons.append({"x": ele_x.tolist(), "y": ele_y.tolist()})

    node_charge = np.zeros(ny)
    _deposit_charges(ion_y, ELEMENTARY_CHARGE * ion_weight, node_charge, spacing)
    _deposit_charges(ele_y, -ELEMENTARY_CHARGE * electron_weight, node_charge, spacing)
    charge_density = node_charge / (cross_section * spacing)
    phi = _solve_poisson_dirichlet(charge_density, spacing, probe_bias_v, plasma_potential_v)
    electric_field = -np.gradient(phi, y_grid)

    stats = {
        "ion_temperature_ev": ion_temperature_ev,
        "electron_temperature_ev": electron_temperature_ev,
        "neutral_pressure_pa": neutral_pressure_pa,
        "ion_density_m3": ion_density_m3,
        "electron_density_m3": electron_density_m3,
        "macroparticle_weight_ion": ion_weight,
        "macroparticle_weight_electron": electron_weight,
        "time_step_s": dt,
    }

    return {
        "grid_y": y_grid.tolist(),
        "potential_profile": phi.tolist(),
        "electric_field_profile": electric_field.tolist(),
        "charge_density_profile": charge_density.tolist(),
        "ion_trajectories": trajectories_ions,
        "electron_trajectories": trajectories_electrons,
        "statistics": stats,
        "domain_width_m": domain_width_m,
        "domain_height_m": domain_height,
    }
