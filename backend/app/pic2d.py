from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

ELEMENTARY_CHARGE = 1.602176634e-19
PERMITTIVITY_0 = 8.8541878128e-12
ELECTRON_MASS = 9.10938356e-31
DEFAULT_DEPTH = 1.0  # meters, quasi-2D thickness for charge density


def _maxwellian_velocity(temperature_ev: float, mass: float, size: int, rng: np.random.Generator) -> np.ndarray:
    """Sample 2D Maxwellian velocity components."""
    thermal = np.sqrt(ELEMENTARY_CHARGE * max(temperature_ev, 1e-4) / mass)
    return rng.normal(0.0, thermal, size=(size, 2))


@dataclass
class ProbeGeometry:
    """Describes the internal conductor embedded in the simulation domain."""

    shape: str
    center_x: float
    center_y: float
    radius: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None

    def contains(self, points: np.ndarray) -> np.ndarray:
        """Return boolean mask for particles located inside the probe."""
        if points.size == 0:
            return np.zeros(0, dtype=bool)

        x = points[:, 0]
        y = points[:, 1]

        if self.shape == "circle":
            if self.radius is None:
                raise ValueError("Circular probe geometry requires radius.")
            r2 = self.radius**2
            return (x - self.center_x) ** 2 + (y - self.center_y) ** 2 <= r2

        if self.shape == "rectangle":
            if self.width is None or self.height is None:
                raise ValueError("Rectangular probe geometry requires width and height.")
            half_w = self.width * 0.5
            half_h = self.height * 0.5
            return (
                (np.abs(x - self.center_x) <= half_w)
                & (np.abs(y - self.center_y) <= half_h)
            )

        raise ValueError(f"Unsupported probe geometry: {self.shape}")

    def mask(self, x_nodes: np.ndarray, y_nodes: np.ndarray) -> np.ndarray:
        """Return a (nx, ny) boolean mask of grid nodes covered by the probe."""
        xx, yy = np.meshgrid(x_nodes, y_nodes, indexing="ij")
        points = np.stack((xx, yy), axis=-1).reshape(-1, 2)
        mask_flat = self.contains(points)
        return mask_flat.reshape(xx.shape)


@dataclass
class SimulationConfig:
    """Static simulation parameters."""

    lx: float
    ly: float
    nx: int
    ny: int
    density_m3: float
    electron_temperature_ev: float
    ion_temperature_ev: float
    ion_mass: float
    particles_per_species: int
    probe: ProbeGeometry
    dt: Optional[float] = None
    boundary_potential: float = 0.0
    snapshot_interval: int = 10
    downsample: int = 2
    poisson_iterations: int = 60
    relaxation_steps: int = 0
    max_inject_per_step: int = 64
    domain_depth: float = DEFAULT_DEPTH
    rng_seed: Optional[int] = None


@dataclass
class BiasScanSettings:
    """Runtime control for the probe bias sweep."""

    bias_values: List[float]
    ramp_steps: int
    settle_steps: int
    measure_steps: int


@dataclass
class SpeciesState:
    """Stores particle data and species constants."""

    name: str
    charge: float
    mass: float
    temperature_ev: float
    macro_weight: float
    desired_particles: int
    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    velocities: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))


def build_probe_mask(
    x_nodes: np.ndarray,
    y_nodes: np.ndarray,
    geometry: ProbeGeometry,
) -> np.ndarray:
    """Convenience wrapper for geometry.mask with validation."""
    mask = geometry.mask(x_nodes, y_nodes)
    if mask.ndim != 2:
        raise ValueError("Probe mask must be 2D.")
    return mask


def apply_potential_boundary_conditions(
    phi: np.ndarray,
    boundary_value: float,
    probe_value: float,
    probe_mask: np.ndarray,
) -> None:
    """Impose Dirichlet boundaries on outer edges and probe nodes."""
    phi[0, :] = boundary_value
    phi[-1, :] = boundary_value
    phi[:, 0] = boundary_value
    phi[:, -1] = boundary_value
    phi[probe_mask] = probe_value


class ProbePICSimulation:
    """Minimal 2D electrostatic PIC solver with an internal Langmuir probe."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = np.random.default_rng(config.rng_seed)
        self.x = np.linspace(0.0, config.lx, config.nx)
        self.y = np.linspace(0.0, config.ly, config.ny)
        self.dx = self.x[1] - self.x[0]
        self.dy = self.y[1] - self.y[0]
        self.cell_area = self.dx * self.dy
        self.probe_mask = build_probe_mask(self.x, self.y, config.probe)
        self.phi = np.zeros((config.nx, config.ny))
        self.rho = np.zeros_like(self.phi)
        self.node_charge = np.zeros_like(self.phi)
        self.ex = np.zeros_like(self.phi)
        self.ey = np.zeros_like(self.phi)
        self.current_probe_voltage = config.boundary_potential
        self.currents = {"total": 0.0, "electrons": 0.0, "ions": 0.0}
        self.time = 0.0
        self.step_index = 0
        self.snapshot_interval = max(1, config.snapshot_interval)
        self.downsample = max(1, config.downsample)

        self.electrons = self._create_species(
            name="electrons",
            charge=-ELEMENTARY_CHARGE,
            mass=ELECTRON_MASS,
            temperature_ev=config.electron_temperature_ev,
        )
        self.ions = self._create_species(
            name="ions",
            charge=ELEMENTARY_CHARGE,
            mass=config.ion_mass,
            temperature_ev=config.ion_temperature_ev,
        )

        max_vel = max(
            1e3,
            np.sqrt(2 * ELEMENTARY_CHARGE * max(config.electron_temperature_ev, 1e-3) / ELECTRON_MASS),
            np.sqrt(2 * ELEMENTARY_CHARGE * max(config.ion_temperature_ev, 1e-3) / config.ion_mass),
        )
        if config.dt is None:
            self.dt = 0.2 * min(self.dx, self.dy) / max_vel
        else:
            self.dt = config.dt

        apply_potential_boundary_conditions(self.phi, config.boundary_potential, self.current_probe_voltage, self.probe_mask)

    def _create_species(self, name: str, charge: float, mass: float, temperature_ev: float) -> SpeciesState:
        desired = max(self.config.particles_per_species, 10)
        volume = self.config.lx * self.config.ly * self.config.domain_depth
        macro_weight = max(self.config.density_m3 * volume / desired, 1.0)
        positions = self._sample_positions(desired)
        velocities = _maxwellian_velocity(temperature_ev, mass, desired, self.rng)
        return SpeciesState(
            name=name,
            charge=charge,
            mass=mass,
            temperature_ev=temperature_ev,
            macro_weight=macro_weight,
            desired_particles=desired,
            positions=positions,
            velocities=velocities,
        )

    def _sample_positions(self, count: int) -> np.ndarray:
        """Uniformly sample positions excluding the probe interior."""
        samples: List[np.ndarray] = []
        attempts = 0
        max_attempts = count * 10
        while len(samples) < count and attempts < max_attempts:
            attempts += 1
            candidate = self.rng.random(2) * np.array([self.config.lx, self.config.ly])
            if not self.config.probe.contains(candidate.reshape(1, 2))[0]:
                samples.append(candidate)
        if len(samples) < count:
            # fallback: tile existing samples
            extra = count - len(samples)
            if samples:
                samples.extend(samples[:extra])
        return np.array(samples[:count])

    def reset_probe_currents(self) -> None:
        self.currents["total"] = 0.0
        self.currents["electrons"] = 0.0
        self.currents["ions"] = 0.0

    def get_probe_currents(self) -> Dict[str, float]:
        return dict(self.currents)

    def _deposit_species(self, species: SpeciesState) -> None:
        if species.positions.size == 0:
            return
        gx = np.clip(species.positions[:, 0] / self.dx, 0, self.config.nx - 2 - 1e-9)
        gy = np.clip(species.positions[:, 1] / self.dy, 0, self.config.ny - 2 - 1e-9)
        ix = gx.astype(int)
        iy = gy.astype(int)
        fx = gx - ix
        fy = gy - iy
        charge = species.charge * species.macro_weight

        w00 = (1 - fx) * (1 - fy)
        w10 = fx * (1 - fy)
        w01 = (1 - fx) * fy
        w11 = fx * fy

        np.add.at(self.node_charge, (ix, iy), charge * w00)
        np.add.at(self.node_charge, (ix + 1, iy), charge * w10)
        np.add.at(self.node_charge, (ix, iy + 1), charge * w01)
        np.add.at(self.node_charge, (ix + 1, iy + 1), charge * w11)

    def _compute_charge_density(self) -> None:
        self.node_charge.fill(0.0)
        self._deposit_species(self.ions)
        self._deposit_species(self.electrons)
        volume = self.cell_area * self.config.domain_depth
        self.rho[:, :] = self.node_charge / max(volume, 1e-12)

    def _solve_poisson(self) -> None:
        dx2 = self.dx**2
        dy2 = self.dy**2
        denom = 2 * (dx2 + dy2)
        for _ in range(self.config.poisson_iterations):
            for i in range(1, self.config.nx - 1):
                for j in range(1, self.config.ny - 1):
                    if self.probe_mask[i, j]:
                        continue
                    rhs = -self.rho[i, j] * dx2 * dy2 / PERMITTIVITY_0
                    self.phi[i, j] = (
                        (self.phi[i + 1, j] + self.phi[i - 1, j]) * dy2
                        + (self.phi[i, j + 1] + self.phi[i, j - 1]) * dx2
                        + rhs
                    ) / denom
            apply_potential_boundary_conditions(
                self.phi,
                self.config.boundary_potential,
                self.current_probe_voltage,
                self.probe_mask,
            )

    def _update_fields(self) -> None:
        self.ex = -np.gradient(self.phi, self.dx, axis=0)
        self.ey = -np.gradient(self.phi, self.dy, axis=1)

    def _interpolate_field(self, positions: np.ndarray) -> np.ndarray:
        if positions.size == 0:
            return np.zeros((0, 2))
        px = np.clip(positions[:, 0], 0.0, self.config.lx - 1e-9)
        py = np.clip(positions[:, 1], 0.0, self.config.ly - 1e-9)
        gx = np.clip(px / self.dx, 0, self.config.nx - 2 - 1e-9)
        gy = np.clip(py / self.dy, 0, self.config.ny - 2 - 1e-9)
        ix = gx.astype(int)
        iy = gy.astype(int)
        fx = gx - ix
        fy = gy - iy

        def bilinear(field: np.ndarray) -> np.ndarray:
            f00 = field[ix, iy]
            f10 = field[ix + 1, iy]
            f01 = field[ix, iy + 1]
            f11 = field[ix + 1, iy + 1]
            return (
                f00 * (1 - fx) * (1 - fy)
                + f10 * fx * (1 - fy)
                + f01 * (1 - fx) * fy
                + f11 * fx * fy
            )

        ex = bilinear(self.ex)
        ey = bilinear(self.ey)
        return np.stack((ex, ey), axis=1)

    def _handle_probe_collisions(self, species: SpeciesState) -> None:
        if species.positions.size == 0:
            return
        inside = self.config.probe.contains(species.positions)
        if not np.any(inside):
            return
        removed = np.count_nonzero(inside)
        self._record_probe_hits(species, removed)
        keep = ~inside
        species.positions = species.positions[keep]
        species.velocities = species.velocities[keep]
        self.currents["total"] = self.currents["electrons"] + self.currents["ions"]

    def _record_probe_hits(self, species: SpeciesState, count: int) -> None:
        if count <= 0:
            return
        q_per_particle = species.charge * species.macro_weight
        current = (count * q_per_particle) / max(self.dt, 1e-15)
        if species.name == "electrons":
            self.currents["electrons"] += current
        else:
            self.currents["ions"] += current
        self.currents["total"] = self.currents["electrons"] + self.currents["ions"]

    def _handle_domain_boundaries(self, species: SpeciesState) -> None:
        if species.positions.size == 0:
            return
        # Periodic wrap along x: particles re-enter opposite boundary with same velocity.
        species.positions[:, 0] = np.mod(species.positions[:, 0], self.config.lx)
        y = species.positions[:, 1]
        hits_bottom = y < 0.0
        hits_top = y > self.config.ly

        if np.any(hits_bottom):
            removed = np.count_nonzero(hits_bottom)
            self._record_probe_hits(species, removed)
            keep = ~hits_bottom
            species.positions = species.positions[keep]
            species.velocities = species.velocities[keep]
            y = species.positions[:, 1]

        if np.any(hits_top):
            keep = ~hits_top
            species.positions = species.positions[keep]
            species.velocities = species.velocities[keep]

    def _reinject_species(self, species: SpeciesState) -> None:
        deficit = species.desired_particles - species.positions.shape[0]
        if deficit <= 0:
            return
        spawn = min(deficit, max(self.config.max_inject_per_step, 1))
        positions, velocities = self._spawn_boundary_particles(species, spawn)
        if positions.size == 0:
            return
        species.positions = np.vstack((species.positions, positions))
        species.velocities = np.vstack((species.velocities, velocities))

    def _spawn_boundary_particles(self, species: SpeciesState, count: int) -> tuple[np.ndarray, np.ndarray]:
        eps = min(self.dx, self.dy) * 0.5
        x = self.rng.random(count) * self.config.lx
        y = np.full(count, self.config.ly - eps)
        positions = np.stack((x, y), axis=1)
        velocities = _maxwellian_velocity(species.temperature_ev, species.mass, count, self.rng)
        velocities[:, 1] = -np.abs(velocities[:, 1])
        return positions, velocities

    def _push_species(self, species: SpeciesState) -> None:
        if species.positions.size == 0:
            return
        field = self._interpolate_field(species.positions)
        accel = (species.charge / species.mass) * field
        species.velocities = species.velocities + accel * self.dt
        species.positions = species.positions + species.velocities * self.dt
        self._handle_probe_collisions(species)
        self._handle_domain_boundaries(species)
        self._reinject_species(species)

    def _maybe_stream(
        self,
        callback: Optional[Callable[[Dict], None]],
        *,
        bias_index: int,
        bias_value: float,
        phase: str,
    ) -> None:
        if callback is None:
            return
        if self.step_index % self.snapshot_interval != 0:
            return
        down = self.downsample
        payload = {
            "type": "snapshot",
            "step": self.step_index,
            "time": self.time,
            "bias_index": bias_index,
            "bias_value": bias_value,
            "phase": phase,
            "probe_voltage": self.current_probe_voltage,
            "currents": self.get_probe_currents(),
            "grid": {
                "x": self.x[::down].tolist(),
                "y": self.y[::down].tolist(),
            },
            "fields": {
                "phi": self.phi[::down, ::down].tolist(),
                "rho": self.rho[::down, ::down].tolist(),
                "e_magnitude": np.hypot(self.ex, self.ey)[::down, ::down].tolist(),
            },
            "particles": {
                "ions": self._sample_particles_for_viz(self.ions, 256),
                "electrons": self._sample_particles_for_viz(self.electrons, 256),
            },
        }
        callback(payload)

    def _sample_particles_for_viz(self, species: SpeciesState, limit: int) -> List[List[float]]:
        count = species.positions.shape[0]
        if count == 0:
            return []
        if count <= limit:
            return species.positions.tolist()
        idx = self.rng.choice(count, size=limit, replace=False)
        return species.positions[idx].tolist()

    def advance_step(
        self,
        *,
        bias_index: int,
        bias_value: float,
        phase: str,
        callback: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self.reset_probe_currents()
        self._compute_charge_density()
        self._solve_poisson()
        self._update_fields()
        self._push_species(self.ions)
        self._push_species(self.electrons)
        self.step_index += 1
        self.time += self.dt
        self._maybe_stream(callback, bias_index=bias_index, bias_value=bias_value, phase=phase)

    def run_bias_scan(
        self,
        scan: BiasScanSettings,
        callback: Optional[Callable[[Dict], None]] = None,
    ) -> List[Dict[str, float]]:
        results: List[Dict[str, float]] = []
        if self.config.relaxation_steps > 0:
            for _ in range(self.config.relaxation_steps):
                self.advance_step(bias_index=-1, bias_value=self.current_probe_voltage, phase="relax")
        for bias_index, bias in enumerate(scan.bias_values):
            self._ramp_to_bias(target=bias, steps=scan.ramp_steps, bias_index=bias_index, callback=callback)
            iv_point = self._measure_interval(
                steps=scan.measure_steps,
                bias=bias,
                bias_index=bias_index,
                callback=callback,
            )
            results.append(iv_point)
            if callback:
                callback(
                    {
                        "type": "iv_point",
                        "bias_index": bias_index,
                        "data": iv_point,
                    }
                )
        return results

    def _ramp_to_bias(
        self,
        *,
        target: float,
        steps: int,
        bias_index: int,
        callback: Optional[Callable[[Dict], None]],
    ) -> None:
        steps = max(steps, 1)
        delta = (target - self.current_probe_voltage) / steps
        for _ in range(steps):
            self.current_probe_voltage += delta
            self.advance_step(
                bias_index=bias_index,
                bias_value=self.current_probe_voltage,
                phase="ramp",
                callback=callback,
        )
        self.current_probe_voltage = target

    def _measure_interval(
        self,
        *,
        steps: int,
        bias: float,
        bias_index: int,
        callback: Optional[Callable[[Dict], None]],
    ) -> Dict[str, float]:
        records: List[Dict[str, float]] = []
        for _ in range(max(steps, 1)):
            self.advance_step(
                bias_index=bias_index,
                bias_value=bias,
                phase="measure",
                callback=callback,
            )
            records.append(self.get_probe_currents())
        total = np.mean([r["total"] for r in records]) if records else 0.0
        electrons = np.mean([r["electrons"] for r in records]) if records else 0.0
        ions = np.mean([r["ions"] for r in records]) if records else 0.0
        return {
            "voltage": bias,
            "current_total": total,
            "current_electrons": electrons,
            "current_ions": ions,
        }
