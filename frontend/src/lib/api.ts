export type IonSpecies = "Ar" | "Xe";

export interface PlasmaInput {
  neutral_gas_pressure_pa: number;
  ionization_fraction: number;
  ion_species: IonSpecies;
  ion_density_cm3?: number | null;
  ion_energy_ev: number;
  electron_density_cm3?: number | null;
  electron_energy_ev: number;
  plasma_potential_v: number;
}

export interface PICSimulationPayload {
  patch_width_mm: number;
  conductor_thickness_mm: number;
  sheath_thickness_mm: number;
  presheath_thickness_mm: number;
  bulk_thickness_mm: number;
  ion_density_cm3: number;
  electron_density_cm3: number;
  ion_temperature_ev: number;
  electron_temperature_ev: number;
  plasma_potential_v: number;
  probe_bias_v: number;
  neutral_pressure_pa: number;
  ion_species: IonSpecies;
}

export interface PICSimulationResult {
  grid_y: number[];
  potential_profile: number[];
  electric_field_profile: number[];
  charge_density_profile: number[];
  ion_trajectories: { x: number[]; y: number[] }[];
  electron_trajectories: { x: number[]; y: number[] }[];
  statistics: Record<string, number>;
  domain_width_m: number;
  domain_height_m: number;
}

export interface ProbeGeometryPayload {
  shape: "circle" | "rectangle";
  center_x: number;
  center_y: number;
  radius?: number | null;
  width?: number | null;
  height?: number | null;
}

export interface PICDomainConfig {
  lx: number;
  ly: number;
  nx: number;
  ny: number;
  dt?: number | null;
  particles_per_species: number;
  snapshot_interval: number;
  downsample: number;
  poisson_iterations: number;
  relaxation_steps: number;
  max_inject_per_step: number;
  domain_depth: number;
  rng_seed?: number | null;
}

export interface PICPlasmaConfig {
  density_m3?: number | null;
  density_cm3?: number | null;
  electron_temperature_ev: number;
  ion_temperature_ev: number;
  ion_species: IonSpecies;
  ion_mass_override?: number | null;
  boundary_potential_v: number;
}

export interface PICBiasScanConfig {
  bias_values?: number[] | null;
  min_voltage?: number | null;
  max_voltage?: number | null;
  voltage_step?: number | null;
  ramp_steps: number;
  settle_steps: number;
  measure_steps: number;
}

export interface PICJobRequest {
  plasma: PICPlasmaConfig;
  domain: PICDomainConfig;
  probe: ProbeGeometryPayload;
  bias_scan: PICBiasScanConfig;
}

export interface SimulationJobResponse {
  job_id: string;
  status: string;
}

export interface SimulationStatusResponse {
  job_id: string;
  status: string;
  error?: string | null;
  completed_bias_points: number;
  total_bias_points: number;
  iv_points: number;
}

export interface PICIvPoint {
  voltage: number;
  current_total: number;
  current_electrons: number;
  current_ions: number;
}

export interface PICIvResponse {
  job_id: string;
  iv_data: PICIvPoint[];
}

export type PicSnapshotMessage = {
  type: "snapshot";
  step: number;
  time: number;
  bias_index: number;
  bias_value: number;
  phase: string;
  probe_voltage: number;
  currents: {
    total: number;
    electrons: number;
    ions: number;
  };
  grid: {
    x: number[];
    y: number[];
  };
  fields: {
    phi: number[][];
    rho: number[][];
    e_magnitude: number[][];
  };
  particles: {
    ions: number[][];
    electrons: number[][];
  };
};

export type PicStatusMessage = {
  type: "status";
  job_id: string;
  status: string;
  completed_bias_points: number;
  total_bias_points: number;
  error?: string | null;
};

export type PicIvPointMessage = {
  type: "iv_point";
  bias_index: number;
  data: PICIvPoint;
};

export type PicErrorMessage = {
  type: "error";
  message: string;
};

export type PicStreamMessage =
  | PicSnapshotMessage
  | PicStatusMessage
  | PicIvPointMessage
  | PicErrorMessage;

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function runPicSlice(payload: PICSimulationPayload): Promise<PICSimulationResult> {
  const response = await fetch(`${API_BASE}/pic-slice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "PIC 仿真失败");
  }

  return response.json();
}

export async function createPicJob(payload: PICJobRequest): Promise<SimulationJobResponse> {
  const response = await fetch(`${API_BASE}/pic/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "启动 PIC 仿真失败");
  }
  return response.json();
}

export async function fetchPicJob(jobId: string): Promise<SimulationStatusResponse> {
  const response = await fetch(`${API_BASE}/pic/jobs/${jobId}`);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "获取 PIC 仿真状态失败");
  }
  return response.json();
}

export async function fetchPicIvData(jobId: string): Promise<PICIvResponse> {
  const response = await fetch(`${API_BASE}/pic/jobs/${jobId}/iv`);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "获取 PIC I-V 数据失败");
  }
  return response.json();
}
