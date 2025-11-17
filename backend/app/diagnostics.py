from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class DiagnosticsConfig:
    """Configuration for offline diagnostics and snapshot capture."""

    snapshot_steps: List[int] = field(default_factory=list)
    snapshot_interval: Optional[int] = None
    snapshot_directory: Optional[str] = None
    summary_path: Optional[str] = None
    downsample: int = 1
    save_fields: bool = True
    save_charge: bool = True
    save_e_field: bool = True
    save_particles: bool = False
    particle_sample_limit: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class DiagnosticsWriter:
    """Writes snapshots/summary data for offline inspection."""

    def __init__(self, config: DiagnosticsConfig) -> None:
        self.config = config
        self._snapshot_dir: Optional[Path] = None
        if config.snapshot_directory:
            self._snapshot_dir = Path(config.snapshot_directory).expanduser().resolve()
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._step_set = {int(step) for step in config.snapshot_steps}
        self._interval = (
            int(config.snapshot_interval) if config.snapshot_interval else None
        )
        self._downsample = max(1, int(config.downsample or 1))
        self._snapshot_log: List[Dict[str, Any]] = []
        self._step_log: List[Dict[str, Any]] = []

    def _should_capture(self, step: int) -> bool:
        if step in self._step_set:
            return True
        if self._interval and step % self._interval == 0:
            return True
        return False

    def maybe_capture(
        self,
        *,
        sim: "ProbePICSimulation",
        step: int,
        bias_index: int,
        bias_value: float,
        phase: str,
    ) -> None:
        if not self._should_capture(step):
            return
        snapshot: Dict[str, Any] = {
            "step": step,
            "time": sim.time,
            "bias_index": bias_index,
            "bias_value": bias_value,
            "phase": phase,
            "probe_currents": sim.get_probe_currents(),
            "electron_count": int(sim.electrons.positions.shape[0]),
            "ion_count": int(sim.ions.positions.shape[0]),
        }
        if self.config.save_fields:
            phi_window = sim.get_windowed_field(sim.phi)
            snapshot["phi"] = self._downsample_array(phi_window)
            x_coords, y_coords = sim.get_windowed_coords()
            snapshot["grid_x"] = x_coords[:: self._downsample].copy()
            snapshot["grid_y"] = y_coords[:: self._downsample].copy()
        if self.config.save_charge:
            snapshot["rho"] = self._downsample_array(sim.get_windowed_field(sim.rho))
        if self.config.save_e_field:
            snapshot["ex"] = self._downsample_array(sim.get_windowed_field(sim.ex))
            snapshot["ey"] = self._downsample_array(sim.get_windowed_field(sim.ey))
        if self.config.save_particles and self.config.particle_sample_limit > 0:
            snapshot["sampled_electrons"] = self._sample_positions(
                sim.electrons.positions
            )
            snapshot["sampled_ions"] = self._sample_positions(sim.ions.positions)
        if self._snapshot_dir:
            file_path = self._snapshot_dir / f"snapshot_{step:07d}.npz"
            np.savez_compressed(file_path, **snapshot)
            self._snapshot_log.append({"step": step, "path": str(file_path)})
        else:
            self._snapshot_log.append({"step": step})
        self._step_log.append(
            {
                "step": step,
                "time": sim.time,
                "bias_value": bias_value,
                "currents": snapshot["probe_currents"],
            }
        )

    def finalize(self, final_payload: Dict[str, Any]) -> None:
        if not self.config.summary_path:
            return
        summary_path = Path(self.config.summary_path).expanduser().resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        lines: List[str] = []
        lines.append("Langmuir Probe PIC Run Summary")
        lines.append("=" * 40)
        if self.config.metadata:
            lines.append("Input Metadata:")
            for key, value in self.config.metadata.items():
                lines.append(f"  - {key}: {value}")
            lines.append("")
        lines.append(f"Snapshots saved: {len(self._snapshot_log)}")
        for item in self._snapshot_log:
            if "path" in item:
                lines.append(f"  * step {item['step']}: {item['path']}")
            else:
                lines.append(f"  * step {item['step']}")
        lines.append("")
        lines.append("Final Diagnostics JSON:")
        lines.append(json.dumps(final_payload, indent=2))
        lines.append("")
        lines.append("Probe Current Samples:")
        for entry in self._step_log[-10:]:
            currents = entry["currents"]
            lines.append(
                f"  step={entry['step']} time={entry['time']:.3e}s "
                f"I_total={currents['total']:.4e} A"
            )
        summary_path.write_text("\n".join(lines), encoding="utf-8")

    def _downsample_array(self, array: np.ndarray) -> np.ndarray:
        return array[:: self._downsample, :: self._downsample].copy()

    def _sample_positions(self, positions: np.ndarray) -> np.ndarray:
        limit = min(self.config.particle_sample_limit, positions.shape[0])
        if limit <= 0:
            return np.empty((0, 2))
        if positions.shape[0] <= limit:
            return positions.copy()
        indices = np.random.choice(positions.shape[0], limit, replace=False)
        return positions[indices].copy()
