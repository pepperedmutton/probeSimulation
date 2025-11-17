from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .diagnostics import DiagnosticsConfig
from .main import (
    BOLTZMANN,
    ELEMENTARY_CHARGE,
    ELECTRON_MASS,
    PERMITTIVITY_0,
    IonSpecies,
    ION_MASS_MAP,
)
from .pic2d import BiasScanSettings, ProbeGeometry, ProbePICSimulation, SimulationConfig


def load_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data


def compute_plasma_params(plasma_cfg: Dict[str, Any]) -> Dict[str, Any]:
    pressure = float(plasma_cfg.get("neutral_pressure_pa", 0.0))
    gas_temp = float(plasma_cfg.get("gas_temperature_k", 300.0))
    ionization_fraction = float(plasma_cfg.get("ionization_fraction", 0.0))
    electron_temperature = float(plasma_cfg["electron_temperature_ev"])
    ion_temperature = float(plasma_cfg["ion_temperature_ev"])
    species = IonSpecies(plasma_cfg.get("gas", "Xe"))
    neutral_density_m3 = pressure / (BOLTZMANN * gas_temp) if pressure > 0 else 0.0
    if "plasma_density_m3" in plasma_cfg:
        plasma_density_m3 = float(plasma_cfg["plasma_density_m3"])
    elif "plasma_density_cm3" in plasma_cfg:
        plasma_density_m3 = float(plasma_cfg["plasma_density_cm3"]) * CM3_TO_M3
    else:
        plasma_density_m3 = neutral_density_m3 * ionization_fraction
    debye_length = math.sqrt(
        (PERMITTIVITY_0 * electron_temperature * ELEMENTARY_CHARGE)
        / (plasma_density_m3 * ELEMENTARY_CHARGE**2)
    )
    electron_plasma_frequency = math.sqrt(
        plasma_density_m3 * ELEMENTARY_CHARGE**2 / (PERMITTIVITY_0 * ELECTRON_MASS)
    )
    ion_mass = ION_MASS_MAP[species]
    metadata = {
        "gas": species.value,
        "pressure_Pa": pressure,
        "gas_temperature_K": gas_temp,
        "ionization_fraction": ionization_fraction,
        "neutral_density_m3": neutral_density_m3,
        "plasma_density_m3": plasma_density_m3,
        "electron_temperature_eV": electron_temperature,
        "ion_temperature_eV": ion_temperature,
        "debye_length_m": debye_length,
        "electron_plasma_frequency_Hz": electron_plasma_frequency,
    }
    derived = {
        "density_m3": plasma_density_m3,
        "electron_temperature_ev": electron_temperature,
        "ion_temperature_ev": ion_temperature,
        "ion_mass": ion_mass,
        "species": species,
        "metadata": metadata,
        "plasma_potential_v": float(plasma_cfg["plasma_potential_v"]),
    }
    return derived


def build_probe_geometry(cfg: Dict[str, Any]) -> ProbeGeometry:
    shape = cfg.get("shape", "circle")
    if shape == "circle":
        return ProbeGeometry(
            shape="circle",
            center_x=float(cfg["center_x_m"]),
            center_y=float(cfg["center_y_m"]),
            radius=float(cfg["radius_m"]),
        )
    if shape == "rectangle":
        return ProbeGeometry(
            shape="rectangle",
            center_x=float(cfg["center_x_m"]),
            center_y=float(cfg["center_y_m"]),
            width=float(cfg["width_m"]),
            height=float(cfg["height_m"]),
        )
    raise ValueError(f"Unsupported probe shape {shape}")


def build_bias_scan(cfg: Dict[str, Any]) -> BiasScanSettings:
    values: Optional[List[float]] = cfg.get("bias_values")
    if not values:
        vmin = cfg["min_voltage"]
        vmax = cfg["max_voltage"]
        step = cfg["voltage_step"]
        values = []
        value = vmin
        if step == 0:
            raise ValueError("voltage_step cannot be zero")
        direction = 1 if vmax >= vmin else -1
        while (direction > 0 and value <= vmax + 1e-9) or (
            direction < 0 and value >= vmax - 1e-9
        ):
            values.append(round(value, 6))
            value += step * direction
            if len(values) > 3000:
                raise ValueError("bias_values too long")
    return BiasScanSettings(
        bias_values=values,
        ramp_steps=int(cfg.get("ramp_steps", 200)),
        settle_steps=int(cfg.get("settle_steps", 0)),
        measure_steps=int(cfg.get("measure_steps", 200)),
    )


def build_diagnostics(cfg: Dict[str, Any], metadata: Dict[str, Any]) -> DiagnosticsConfig:
    snapshot_dir = cfg.get("snapshot_dir")
    summary_path = cfg.get("summary_path")
    steps = cfg.get("snapshot_steps", [])
    interval = cfg.get("snapshot_interval")
    downsample = cfg.get("downsample", 1)
    save_particles = bool(cfg.get("save_particles", False))
    particle_limit = int(cfg.get("particle_sample_limit", 0))
    metadata_copy = dict(metadata)
    metadata_copy.update(cfg.get("metadata_overrides", {}))
    return DiagnosticsConfig(
        snapshot_steps=[int(step) for step in steps],
        snapshot_interval=int(interval) if interval else None,
        snapshot_directory=snapshot_dir,
        summary_path=summary_path,
        downsample=int(downsample),
        save_particles=save_particles,
        particle_sample_limit=particle_limit,
        metadata=metadata_copy,
    )


def build_simulation_config(data: Dict[str, Any]) -> tuple[SimulationConfig, BiasScanSettings]:
    plasma = compute_plasma_params(data["plasma"])
    domain_cfg = data["domain"]
    probe_cfg = data["probe"]
    diag_cfg = data.get("diagnostics")
    diagnostics = (
        build_diagnostics(diag_cfg, plasma["metadata"]) if diag_cfg else None
    )

    def _parse_window(key: str) -> Tuple[float, float]:
        values = domain_cfg.get(key, [0.0, 1.0])
        if isinstance(values, (list, tuple)) and len(values) == 2:
            return float(values[0]), float(values[1])
        raise ValueError(f"{key} must be a list of two numbers between 0 and 1")

    window_x_fraction = _parse_window("window_fraction_x")
    window_y_fraction = _parse_window("window_fraction_y")
    sim_config = SimulationConfig(
        lx=float(domain_cfg["lx_m"]),
        ly=float(domain_cfg["ly_m"]),
        nx=int(domain_cfg["nx"]),
        ny=int(domain_cfg["ny"]),
        density_m3=plasma["density_m3"],
        electron_temperature_ev=plasma["electron_temperature_ev"],
        ion_temperature_ev=plasma["ion_temperature_ev"],
        ion_mass=plasma["ion_mass"],
        particles_per_species=int(domain_cfg.get("particles_per_species", 2000)),
        probe=build_probe_geometry(probe_cfg),
        dt=domain_cfg.get("dt"),
        boundary_potential=plasma["plasma_potential_v"],
        snapshot_interval=int(domain_cfg.get("snapshot_interval", 10)),
        downsample=int(domain_cfg.get("downsample", 2)),
        poisson_iterations=int(domain_cfg.get("poisson_iterations", 60)),
        relaxation_steps=int(domain_cfg.get("relaxation_steps", 0)),
        max_inject_per_step=int(domain_cfg.get("max_inject_per_step", 128)),
        domain_depth=float(domain_cfg.get("domain_depth", 1.0)),
        rng_seed=domain_cfg.get("rng_seed"),
        diagnostics=diagnostics,
        charge_smoothing_steps=int(domain_cfg.get("charge_smoothing_steps", 0)),
        charge_relaxation=float(domain_cfg.get("charge_relaxation", 1.0)),
        planar_symmetry=bool(domain_cfg.get("planar_symmetry", False)),
        planar_effective_area_m2=domain_cfg.get("planar_effective_area_m2"),
        window_x_fraction=window_x_fraction,
        window_y_fraction=window_y_fraction,
    )
    bias_scan = build_bias_scan(data["bias_scan"])
    return sim_config, bias_scan


def run_from_config(path: Path) -> None:
    data = load_config(path)
    sim_config, bias = build_simulation_config(data)
    print(
        f"Running PIC simulation with grid {sim_config.nx}x{sim_config.ny}, "
        f"density={sim_config.density_m3:.3e} m^-3"
    )
    simulation = ProbePICSimulation(sim_config)
    results = simulation.run_bias_scan(bias)
    for idx, point in enumerate(results):
        print(
            f"Bias #{idx}: V={point['voltage']:.2f} V, "
            f"I_total={point['current_total']:.4e} A "
            f"(electrons={point['current_electrons']:.4e} A, ions={point['current_ions']:.4e} A)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Langmuir probe PIC solver from a YAML config file."
    )
    parser.add_argument("config", type=Path, help="Path to YAML/JSON config file")
    args = parser.parse_args()
    run_from_config(args.config)


if __name__ == "__main__":
    main()
