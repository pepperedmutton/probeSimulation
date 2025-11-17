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

export interface SheathResult {
  electron_debye_length_m: number;
  sheath_thickness_m: number;
  ion_sound_speed_m_s: number;
  floating_potential_v: number;
  plasma_potential_v: number;
  electron_plasma_frequency_hz: number;
  ion_plasma_frequency_hz: number;
  quasi_neutrality_ratio: number;
  neutral_gas_pressure_pa: number;
  neutral_density_cm3: number;
  ionization_fraction: number;
  ion_species: IonSpecies;
  derived_density_cm3: number;
  effective_ion_density_cm3: number;
  effective_electron_density_cm3: number;
  ion_saturation_current_a: number;
  probe_temperature_k: number;
  message: string;
}

export interface IVPoint {
  voltage: number;
  current: number;
}

export interface IVCurveRequest {
  plasma_params: PlasmaInput;
  min_voltage: number;
  max_voltage: number;
  steps: number;
}

export interface IVCurveResult {
  sheath_params: SheathResult;
  iv_curve: IVPoint[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function solveSheath(payload: PlasmaInput): Promise<SheathResult> {
  const response = await fetch(`${API_BASE}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "求解鞘层失败");
  }

  return response.json();
}

export async function calculateIVCurve(request: IVCurveRequest): Promise<IVCurveResult> {
  const response = await fetch(`${API_BASE}/iv-curve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "计算 I-V 曲线失败");
  }

  return response.json();
}
