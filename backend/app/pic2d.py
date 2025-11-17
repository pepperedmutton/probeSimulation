from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .diagnostics import DiagnosticsConfig, DiagnosticsWriter

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
    planar_effective_area_m2: Optional[float] = None
    rng_seed: Optional[int] = None
    diagnostics: Optional[DiagnosticsConfig] = None
    charge_smoothing_steps: int = 0
    charge_relaxation: float = 1.0
    planar_symmetry: bool = False
    window_x_fraction: Tuple[float, float] = (0.0, 1.0)
    window_y_fraction: Tuple[float, float] = (0.0, 1.0)


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
        self.prev_rho = np.zeros_like(self.phi)
        self._planar_phi: Optional[np.ndarray] = None
        self.effective_domain_depth = config.domain_depth
        if config.planar_symmetry and config.planar_effective_area_m2:
            area = max(config.planar_effective_area_m2, 1e-18)
            self.effective_domain_depth = area / max(config.lx, 1e-12)
        self.current_probe_voltage = config.boundary_potential
        self.currents = {"total": 0.0, "electrons": 0.0, "ions": 0.0}
        self.time = 0.0
        self.step_index = 0
        self.snapshot_interval = max(1, config.snapshot_interval)
        self.downsample = max(1, config.downsample)
        self.diagnostics_writer: Optional[DiagnosticsWriter] = None
        if config.diagnostics:
            metadata = dict(config.diagnostics.metadata)
            metadata.setdefault(
                "grid",
                {
                    "nx": config.nx,
                    "ny": config.ny,
                    "lx": config.lx,
                    "ly": config.ly,
                },
            )
            metadata.setdefault(
                "plasma",
                {
                    "density_m3": config.density_m3,
                    "electron_temperature_ev": config.electron_temperature_ev,
                    "ion_temperature_ev": config.ion_temperature_ev,
                },
            )
            config.diagnostics.metadata = metadata
            self.diagnostics_writer = DiagnosticsWriter(config.diagnostics)
        self._init_display_window()

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
        volume = self.config.lx * self.config.ly * self.effective_domain_depth
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
        volume = self.cell_area * self.effective_domain_depth
        self.rho[:, :] = self.node_charge / max(volume, 1e-12)
        mean_charge = np.mean(self.rho)
        if not np.isclose(mean_charge, 0.0):
            self.rho -= mean_charge
        for _ in range(max(0, self.config.charge_smoothing_steps)):
            self.rho = self._smooth_charge(self.rho)
        alpha = float(np.clip(self.config.charge_relaxation, 0.0, 1.0))
        if alpha < 1.0:
            self.rho = alpha * self.rho + (1.0 - alpha) * self.prev_rho
        self.prev_rho = self.rho.copy()
        if self.config.planar_symmetry:
            self._enforce_planar_profile(self.rho)

    def _solve_poisson(self) -> None:
        if self.config.planar_symmetry:
            self._solve_planar_poisson()
            return
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
        if self.config.planar_symmetry:
            self.ex.fill(0.0)
            self._enforce_planar_profile(self.ey)

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

    def _smooth_charge(self, rho: np.ndarray) -> np.ndarray:
        kernel = (
            0.25 * rho
            + 0.125 * (np.roll(rho, 1, axis=0) + np.roll(rho, -1, axis=0))
            + 0.125 * (np.roll(rho, 1, axis=1) + np.roll(rho, -1, axis=1))
        )
        kernel[0, :] = rho[0, :]
        kernel[-1, :] = rho[-1, :]
        kernel[:, 0] = rho[:, 0]
        kernel[:, -1] = rho[:, -1]
        return kernel

    def _enforce_planar_profile(self, array: np.ndarray) -> None:
        profile = np.mean(array, axis=0, keepdims=True)
        array[:, :] = profile

    def _compute_window_slice(self, length: float, coords: np.ndarray, fraction: Tuple[float, float]) -> slice:
        f0 = max(0.0, min(1.0, float(fraction[0])))
        f1 = max(f0 + 1e-6, min(1.0, float(fraction[1])))
        x_min = length * f0
        x_max = length * f1
        start = int(np.searchsorted(coords, x_min, side="left"))
        stop = int(np.searchsorted(coords, x_max, side="right"))
        n = coords.size
        start = max(0, min(n - 2, start))
        stop = max(start + 2, min(n, stop))
        return slice(start, stop)

    def _init_display_window(self) -> None:
        self.window_slice_x = self._compute_window_slice(
            self.config.lx, self.x, self.config.window_x_fraction
        )
        self.window_slice_y = self._compute_window_slice(
            self.config.ly, self.y, self.config.window_y_fraction
        )
        self.window_x_coords = self.x[self.window_slice_x]
        self.window_y_coords = self.y[self.window_slice_y]
        self.window_bounds_x = (
            float(self.window_x_coords[0]),
            float(self.window_x_coords[-1]),
        )
        self.window_bounds_y = (
            float(self.window_y_coords[0]),
            float(self.window_y_coords[-1]),
        )

    def get_windowed_field(self, array: np.ndarray) -> np.ndarray:
        return array[self.window_slice_x, self.window_slice_y]

    def get_windowed_coords(self) -> tuple[np.ndarray, np.ndarray]:
        return self.window_x_coords, self.window_y_coords

    def _solve_planar_poisson(self) -> None:
        ny = self.config.ny
        dy2 = self.dy**2
        rho_avg = np.mean(self.rho, axis=0)
        probe_rows = np.any(self.probe_mask, axis=0)
        dirichlet = np.zeros(ny, dtype=bool)
        dirichlet_values = np.full(ny, self.config.boundary_potential)
        dirichlet[0] = True
        dirichlet_values[0] = self.current_probe_voltage
        dirichlet[-1] = True
        dirichlet_values[-1] = self.config.boundary_potential
        probe_indices = np.where(probe_rows)[0]
        if probe_indices.size:
            max_probe = probe_indices.max()
            dirichlet[: max_probe + 1] = True
            dirichlet_values[: max_probe + 1] = self.current_probe_voltage
        free_indices = [j for j in range(ny) if not dirichlet[j]]
        phi_y = dirichlet_values.copy()
        if free_indices:
            n_free = len(free_indices)
            A = np.zeros((n_free, n_free))
            b = np.zeros(n_free)
            index_map = {value: idx for idx, value in enumerate(free_indices)}
            for idx, j in enumerate(free_indices):
                A[idx, idx] = -2.0 / dy2
                rhs = -rho_avg[j] / PERMITTIVITY_0
                if j - 1 >= 0:
                    if dirichlet[j - 1]:
                        rhs -= dirichlet_values[j - 1] / dy2
                    else:
                        A[idx, index_map[j - 1]] = 1.0 / dy2
                if j + 1 < ny:
                    if dirichlet[j + 1]:
                        rhs -= dirichlet_values[j + 1] / dy2
                    else:
                        A[idx, index_map[j + 1]] = 1.0 / dy2
                b[idx] = rhs
            solution = np.linalg.solve(A, b)
            for idx, j in enumerate(free_indices):
                phi_y[j] = solution[idx]
        self._planar_phi = phi_y
        self.phi[:, :] = phi_y[np.newaxis, :]
        if np.any(self.probe_mask):
            self.phi[self.probe_mask] = self.current_probe_voltage

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
        species.positions[:, 0] = np.mod(species.positions[:, 0], self.config.lx)
        y = species.positions[:, 1]
        hits_bottom = y < 0.0

        if np.any(hits_bottom):
            removed = np.count_nonzero(hits_bottom)
            if self.config.planar_symmetry:
                self._record_probe_hits(species, removed)
            keep = ~hits_bottom
            species.positions = species.positions[keep]
            species.velocities = species.velocities[keep]
        if species.positions.size == 0:
            return
        y = species.positions[:, 1]
        hits_top = y > self.config.ly
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
        positions = self._sample_positions(count)
        velocities = _maxwellian_velocity(species.temperature_ev, species.mass, count, self.rng)
        if species.charge > 0:
            drift = -np.sqrt(
                max(species.temperature_ev, 1e-4) * ELEMENTARY_CHARGE / max(species.mass, 1e-30)
            )
            velocities[:, 1] = -np.abs(velocities[:, 1]) + drift
        else:
            signs = self.rng.choice([-1.0, 1.0], size=count)
            velocities[:, 1] = signs * np.abs(velocities[:, 1])
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
        window_phi = self.get_windowed_field(self.phi)
        window_rho = self.get_windowed_field(self.rho)
        e_mag = np.hypot(self.ex, self.ey)
        window_e_mag = self.get_windowed_field(e_mag)
        x_coords, y_coords = self.get_windowed_coords()
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
                "x": x_coords[::down].tolist(),
                "y": y_coords[::down].tolist(),
            },
            "fields": {
                "phi": window_phi[::down, ::down].tolist(),
                "rho": window_rho[::down, ::down].tolist(),
                "e_magnitude": window_e_mag[::down, ::down].tolist(),
            },
            "particles": {
                "ions": self._sample_particles_for_viz(self.ions, 256),
                "electrons": self._sample_particles_for_viz(self.electrons, 256),
            },
        }
        callback(payload)

    def _maybe_record_snapshot(
        self,
        *,
        bias_index: int,
        bias_value: float,
        phase: str,
    ) -> None:
        if not self.diagnostics_writer:
            return
        self.diagnostics_writer.maybe_capture(
            sim=self,
            step=self.step_index,
            bias_index=bias_index,
            bias_value=bias_value,
            phase=phase,
        )

    def _sample_particles_for_viz(self, species: SpeciesState, limit: int) -> List[List[float]]:
        positions = species.positions
        if positions.size == 0:
            return []
        if (
            self.window_slice_x.start > 0
            or self.window_slice_x.stop < self.config.nx
            or self.window_slice_y.start > 0
            or self.window_slice_y.stop < self.config.ny
        ):
            x_min, x_max = self.window_bounds_x
            y_min, y_max = self.window_bounds_y
            mask = (
                (positions[:, 0] >= x_min)
                & (positions[:, 0] <= x_max)
                & (positions[:, 1] >= y_min)
                & (positions[:, 1] <= y_max)
            )
            positions = positions[mask]
        count = positions.shape[0]
        if count == 0:
            return []
        if count <= limit:
            return positions.tolist()
        idx = self.rng.choice(count, size=limit, replace=False)
        return positions[idx].tolist()

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
        self._maybe_record_snapshot(bias_index=bias_index, bias_value=bias_value, phase=phase)

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
        if self.diagnostics_writer:
            self.diagnostics_writer.finalize(
                {
                    "iv_curve": results,
                    "completed_steps": self.step_index,
                    "simulation_time_s": self.time,
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
