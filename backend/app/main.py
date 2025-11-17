import asyncio
import logging
from enum import Enum
from math import exp, log, pi, sqrt
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .pic import PICConfig, run_pic_slice_simulation
from .pic2d import BiasScanSettings, ProbeGeometry, SimulationConfig
from .sim_manager import simulation_manager
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ELEMENTARY_CHARGE = 1.602176634e-19  # 库仑
PERMITTIVITY_0 = 8.8541878128e-12  # 法拉/米
ELECTRON_MASS = 9.10938356e-31  # 千克
AMU = 1.6605390666e-27  # 千克
BOLTZMANN = 1.380649e-23  # 焦/开
CM3_TO_M3 = 1e6
MIN_DENSITY_CM3 = 1e4
GAS_TEMPERATURE_K = 300.0
PROBE_DIAMETER_M = 1e-3
PROBE_LENGTH_M = 5e-3
PROBE_SURFACE_AREA = pi * PROBE_DIAMETER_M * PROBE_LENGTH_M
PROBE_COOLING_COEFF = 0.04  # 简化对流系数 (W/K)
AMBIENT_TEMP_K = 300.0


class IonSpecies(str, Enum):
    AR = "Ar"
    XE = "Xe"


ION_MASS_MAP = {
    IonSpecies.AR: 39.948 * AMU,
    IonSpecies.XE: 131.293 * AMU,
}


class PlasmaInput(BaseModel):
    """均匀等离子体参数，定义探针周围的无碰撞鞘层。零维模型，假设薄鞘层理论成立。"""

    neutral_gas_pressure_pa: float = Field(..., gt=0, description="背景中性气体压强 (Pa)")
    ionization_fraction: float = Field(0.1, ge=0, le=1, description="电离率 0-1")
    ion_species: IonSpecies = Field(IonSpecies.AR, description="离子种类")
    ion_density_cm3: Optional[float] = Field(None, gt=0, description="可选的离子密度 (cm^-3)")
    ion_energy_ev: float = Field(..., gt=0, description="离子温度 (eV)，当前假设 Ti << Te")
    electron_density_cm3: Optional[float] = Field(None, gt=0, description="可选的电子密度 (cm^-3)")
    electron_energy_ev: float = Field(..., gt=0, description="电子温度 (eV)")
    plasma_potential_v: float = Field(..., description="等离子体空间电势 (V)")


class SheathResult(BaseModel):
    electron_debye_length_m: float
    sheath_thickness_m: float
    ion_sound_speed_m_s: float
    floating_potential_v: float
    plasma_potential_v: float
    electron_plasma_frequency_hz: float
    ion_plasma_frequency_hz: float
    quasi_neutrality_ratio: float
    neutral_gas_pressure_pa: float
    neutral_density_cm3: float
    ionization_fraction: float
    ion_species: IonSpecies
    derived_density_cm3: float
    effective_ion_density_cm3: float
    effective_electron_density_cm3: float
    ion_saturation_current_a: float
    probe_temperature_k: float
    message: str


class IVPoint(BaseModel):
    voltage: float
    current: float


class IVCurveRequest(BaseModel):
    plasma_params: PlasmaInput
    min_voltage: float = Field(-30.0, description="最小扫描电压 (V)")
    max_voltage: float = Field(30.0, description="最大扫描电压 (V)")
    steps: int = Field(60, ge=10, le=500, description="扫描点数")


class IVCurveResult(BaseModel):
    sheath_params: SheathResult
    iv_curve: list[IVPoint]


class PICSimulationRequest(BaseModel):
    patch_width_mm: float = Field(1.0, description="探针截面宽度 (mm)")
    conductor_thickness_mm: float = Field(0.1, description="导体厚度 (mm)")
    sheath_thickness_mm: float = Field(0.05, description="鞘层厚度 (mm)")
    presheath_thickness_mm: float = Field(0.2, description="预鞘层厚度 (mm)")
    bulk_thickness_mm: float = Field(1.0, description="bulk plasma 厚度 (mm)")
    ion_density_cm3: float
    electron_density_cm3: float
    ion_temperature_ev: float
    electron_temperature_ev: float
    plasma_potential_v: float
    probe_bias_v: float
    neutral_pressure_pa: float
    ion_species: IonSpecies


class PICSimulationResult(BaseModel):
    grid_y: list[float]
    potential_profile: list[float]
    electric_field_profile: list[float]
    charge_density_profile: list[float]
    ion_trajectories: list[dict]
    electron_trajectories: list[dict]
    statistics: dict
    domain_width_m: float
    domain_height_m: float


class ProbeGeometryPayload(BaseModel):
    shape: Literal["circle", "rectangle"] = "circle"
    center_x: float = Field(..., description="Probe center x coordinate (m)")
    center_y: float = Field(..., description="Probe center y coordinate (m)")
    radius: Optional[float] = Field(None, gt=0, description="Radius for circular probe (m)")
    width: Optional[float] = Field(None, gt=0, description="Width for rectangular probe (m)")
    height: Optional[float] = Field(None, gt=0, description="Height for rectangular probe (m)")


class PICDomainConfig(BaseModel):
    lx: float = Field(..., gt=0, description="Domain width in meters")
    ly: float = Field(..., gt=0, description="Domain height in meters")
    nx: int = Field(64, ge=16, description="Grid nodes along x")
    ny: int = Field(64, ge=16, description="Grid nodes along y")
    dt: Optional[float] = Field(None, gt=0, description="Explicit time step (s)")
    particles_per_species: int = Field(2000, ge=100, description="Macroparticles per species")
    snapshot_interval: int = Field(10, ge=1, description="Steps between streamed snapshots")
    downsample: int = Field(2, ge=1, description="Downsample factor for streamed grids")
    poisson_iterations: int = Field(60, ge=10, description="Gauss-Seidel iterations per step")
    relaxation_steps: int = Field(0, ge=0, description="Initial steps at V_probe=0")
    max_inject_per_step: int = Field(128, ge=1, description="Max macroparticles injected per step")
    domain_depth: float = Field(1.0, gt=0, description="Effective depth for quasi-2D (m)")
    rng_seed: Optional[int] = Field(None, description="Optional random seed for reproducibility")


class PICPlasmaConfig(BaseModel):
    density_m3: Optional[float] = Field(None, gt=0, description="Background density (m^-3)")
    density_cm3: Optional[float] = Field(None, gt=0, description="Background density (cm^-3)")
    electron_temperature_ev: float = Field(..., gt=0, description="Electron temperature (eV)")
    ion_temperature_ev: float = Field(..., gt=0, description="Ion temperature (eV)")
    ion_species: IonSpecies = IonSpecies.AR
    ion_mass_override: Optional[float] = Field(
        None, gt=0, description="Optional ion mass override (kg)"
    )
    boundary_potential_v: float = Field(0.0, description="Outer boundary potential (V)")


class PICBiasScanRequest(BaseModel):
    bias_values: Optional[List[float]] = Field(
        None, description="Explicit bias list (V) applied sequentially"
    )
    min_voltage: Optional[float] = Field(
        None, description="Bias sweep minimum (if bias_values not provided)"
    )
    max_voltage: Optional[float] = Field(None, description="Bias sweep maximum")
    voltage_step: Optional[float] = Field(None, description="Bias sweep step")
    ramp_steps: int = Field(200, ge=1, description="Steps used to ramp toward target bias")
    settle_steps: int = Field(400, ge=0, description="Steps discarded for settling")
    measure_steps: int = Field(400, ge=1, description="Measurement steps per bias")


class PICJobRequest(BaseModel):
    plasma: PICPlasmaConfig
    domain: PICDomainConfig
    probe: ProbeGeometryPayload
    bias_scan: PICBiasScanRequest


class SimulationJobResponse(BaseModel):
    job_id: str
    status: str


class SimulationStatusResponse(BaseModel):
    job_id: str
    status: str
    error: Optional[str]
    completed_bias_points: int
    total_bias_points: int
    iv_points: int


class IVDataPoint(BaseModel):
    voltage: float
    current_total: float
    current_electrons: float
    current_ions: float


class IVDataResponse(BaseModel):
    job_id: str
    iv_data: List[IVDataPoint]


app = FastAPI(
    title="Plasma Sheath Simulation Service",
    description="在均匀等离子体中估算平板朗缪尔探针的无碰撞鞘层参数。",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cm3_to_m3(value_cm3: float) -> float:
    return value_cm3 * CM3_TO_M3


def _neutral_density_cm3_from_pressure(pressure_pa: float) -> float:
    density_m3 = pressure_pa / (BOLTZMANN * GAS_TEMPERATURE_K)
    return density_m3 / CM3_TO_M3


def _bohm_velocity(electron_energy_ev: float, ion_mass: float) -> float:
    """玻姆速度：假设 Ti << Te 且为单电荷离子，v_B = sqrt(kTe/mi)。"""
    te_joule = max(electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE
    return sqrt(te_joule / ion_mass)


def _floating_potential(plasma_potential_v: float, electron_energy_ev: float, ion_mass: float) -> float:
    """浮动电位：Vf = Vp - (kTe/e) * 0.5 * ln(mi/2πme)。Te 以 eV 输入。"""
    mass_ratio = ion_mass / ELECTRON_MASS
    te_volts = max(electron_energy_ev, 1e-3)  # eV -> (kTe/e) in volts
    correction = 0.5 * te_volts * log(mass_ratio / (2 * pi))
    return plasma_potential_v - correction


def _debye_length(electron_density_m3: float, electron_energy_ev: float) -> float:
    te_joule = max(electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE
    return sqrt(PERMITTIVITY_0 * te_joule / (electron_density_m3 * ELEMENTARY_CHARGE**2))


def _ion_saturation_current(
    ion_density_m3: float, electron_energy_ev: float, ion_energy_ev: float, ion_mass: float
) -> float:
    """离子饱和电流（单电荷，平板探针）。

    I_isat ≈ 0.61 e n_i A sqrt(k(Te + Ti)/m_i)
    """
    te_joule = max(electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE
    ti_joule = max(ion_energy_ev, 1e-6) * ELEMENTARY_CHARGE
    effective_energy = te_joule + ti_joule
    return 0.61 * ELEMENTARY_CHARGE * ion_density_m3 * PROBE_SURFACE_AREA * sqrt(effective_energy / ion_mass)


def _probe_temperature(current_a: float, bias_voltage: float) -> float:
    deposited_power = abs(current_a * bias_voltage)
    return AMBIENT_TEMP_K + deposited_power / PROBE_COOLING_COEFF


def _resolve_densities(payload: PlasmaInput, derived_density_cm3: float) -> tuple[float, float]:
    manual_ion = payload.ion_density_cm3
    manual_e = payload.electron_density_cm3

    if manual_ion is not None and manual_e is not None:
        raise HTTPException(status_code=400, detail="已设置电子密度时不可再设置离子密度（准中性假设）。")

    if manual_ion is not None:
        density = max(manual_ion, MIN_DENSITY_CM3)
        return density, density

    if manual_e is not None:
        density = max(manual_e, MIN_DENSITY_CM3)
        return density, density

    density = max(derived_density_cm3, MIN_DENSITY_CM3)
    return density, density


def _ensure_probe_geometry(payload: ProbeGeometryPayload) -> ProbeGeometry:
    if payload.shape == "circle" and payload.radius is None:
        raise HTTPException(status_code=400, detail="圆形探针需要设置 radius。")
    if payload.shape == "rectangle" and (payload.width is None or payload.height is None):
        raise HTTPException(status_code=400, detail="矩形探针需要设置 width 和 height。")
    return ProbeGeometry(
        shape=payload.shape,
        center_x=payload.center_x,
        center_y=payload.center_y,
        radius=payload.radius,
        width=payload.width,
        height=payload.height,
    )


def _resolve_density_m3(plasma: PICPlasmaConfig) -> float:
    if plasma.density_m3 is not None:
        return plasma.density_m3
    if plasma.density_cm3 is not None:
        return plasma.density_cm3 * CM3_TO_M3
    raise HTTPException(status_code=400, detail="需要 density_m3 或 density_cm3。")


def _resolve_ion_mass(plasma: PICPlasmaConfig) -> float:
    if plasma.ion_mass_override is not None:
        return plasma.ion_mass_override
    return ION_MASS_MAP[plasma.ion_species]


def _build_bias_values(payload: PICBiasScanRequest) -> List[float]:
    if payload.bias_values:
        if not payload.bias_values:
            raise HTTPException(status_code=400, detail="bias_values 不能为空。")
        return [float(value) for value in payload.bias_values]

    if payload.min_voltage is None or payload.max_voltage is None or payload.voltage_step is None:
        raise HTTPException(status_code=400, detail="需要 bias_values 或 min/max/step 参数。")

    step = payload.voltage_step
    if abs(step) < 1e-12:
        raise HTTPException(status_code=400, detail="voltage_step 不能为 0。")

    start = payload.min_voltage
    stop = payload.max_voltage
    direction = 1 if stop >= start else -1
    step = abs(step) * direction

    values: List[float] = []
    current = start
    limit = 2000
    while (direction > 0 and current <= stop + 1e-9) or (direction < 0 and current >= stop - 1e-9):
        values.append(round(current, 9))
        current += step
        if len(values) > limit:
            raise HTTPException(status_code=400, detail="扫描点数过多 (>2000)。")
    return values


def _build_simulation_config(request: PICJobRequest) -> SimulationConfig:
    geometry = _ensure_probe_geometry(request.probe)
    density = _resolve_density_m3(request.plasma)
    ion_mass = _resolve_ion_mass(request.plasma)
    domain = request.domain
    plasma = request.plasma
    return SimulationConfig(
        lx=domain.lx,
        ly=domain.ly,
        nx=domain.nx,
        ny=domain.ny,
        density_m3=density,
        electron_temperature_ev=plasma.electron_temperature_ev,
        ion_temperature_ev=plasma.ion_temperature_ev,
        ion_mass=ion_mass,
        particles_per_species=domain.particles_per_species,
        probe=geometry,
        dt=domain.dt,
        boundary_potential=plasma.boundary_potential_v,
        snapshot_interval=domain.snapshot_interval,
        downsample=domain.downsample,
        poisson_iterations=domain.poisson_iterations,
        relaxation_steps=domain.relaxation_steps,
        max_inject_per_step=domain.max_inject_per_step,
        domain_depth=domain.domain_depth,
        rng_seed=domain.rng_seed,
    )


def _build_bias_scan(request: PICBiasScanRequest) -> BiasScanSettings:
    bias_values = _build_bias_values(request)
    return BiasScanSettings(
        bias_values=bias_values,
        ramp_steps=request.ramp_steps,
        settle_steps=request.settle_steps,
        measure_steps=request.measure_steps,
    )


def run_sheath_model(payload: PlasmaInput) -> SheathResult:
    logger.info("=" * 80)
    logger.info("开始鞘层模型计算")
    logger.info(f"输入参数: 压强={payload.neutral_gas_pressure_pa} Pa, 电离率={payload.ionization_fraction}")
    logger.info(f"           离子种类={payload.ion_species}, Te={payload.electron_energy_ev} eV")
    logger.info(f"           等离子体电势={payload.plasma_potential_v} V")
    
    neutral_pressure_pa = max(payload.neutral_gas_pressure_pa, 1e-3)
    neutral_density_cm3 = max(_neutral_density_cm3_from_pressure(neutral_pressure_pa), MIN_DENSITY_CM3)
    logger.info(f"中性密度: {neutral_density_cm3:.2e} cm^-3")
    
    ionization_fraction = max(0.0, min(payload.ionization_fraction, 1.0))
    derived_density_cm3 = max(neutral_density_cm3 * max(ionization_fraction, 1e-4), MIN_DENSITY_CM3)
    logger.info(f"推导等离子体密度: {derived_density_cm3:.2e} cm^-3")

    ion_density_cm3, electron_density_cm3 = _resolve_densities(payload, derived_density_cm3)
    logger.info(f"有效密度: n_i={ion_density_cm3:.2e}, n_e={electron_density_cm3:.2e} cm^-3")

    ion_density_m3 = _cm3_to_m3(ion_density_cm3)
    electron_density_m3 = _cm3_to_m3(electron_density_cm3)

    lambda_debye = _debye_length(electron_density_m3, payload.electron_energy_ev)
    logger.info(f"德拜长度: {lambda_debye:.6e} m")
    
    ion_mass = ION_MASS_MAP[payload.ion_species]
    bohm_velocity = _bohm_velocity(payload.electron_energy_ev, ion_mass)
    logger.info(f"玻姆速度: {bohm_velocity:.2f} m/s")

    electron_plasma_frequency = sqrt(
        electron_density_m3 * ELEMENTARY_CHARGE**2 / (PERMITTIVITY_0 * ELECTRON_MASS)
    )
    ion_plasma_frequency = sqrt(ion_density_m3 * ELEMENTARY_CHARGE**2 / (PERMITTIVITY_0 * ion_mass))

    # 浮动电位：考虑质量比的精确公式
    floating_potential = _floating_potential(payload.plasma_potential_v, payload.electron_energy_ev, ion_mass)
    logger.info(f"浮动电位: {floating_potential:.3f} V (Vp={payload.plasma_potential_v} V)")
    
    potential_drop = max(abs(payload.plasma_potential_v - floating_potential), 1e-3)
    logger.info(f"电势降: {potential_drop:.3f} V")
    
    # 鞘层厚度：基于Child-Langmuir定律的近似 s ≈ λD * sqrt(2eΔV/kTe)
    # 这里 ΔV 是从等离子体电势到浮动电位的电势降
    normalized_potential = potential_drop / max(payload.electron_energy_ev, 1e-3)
    sheath_thickness = sqrt((2 * PERMITTIVITY_0 * potential_drop) / (ELEMENTARY_CHARGE * ion_density_m3))
    logger.info(f"鞘层厚度: {sheath_thickness:.6e} m")

    quasi_neutrality_ratio = ion_density_m3 / electron_density_m3 if electron_density_m3 else float("inf")

    ion_current = _ion_saturation_current(ion_density_m3, payload.electron_energy_ev, payload.ion_energy_ev, ion_mass)
    logger.info(f"离子饱和电流: {ion_current:.6e} A ({ion_current*1e3:.3f} mA)")
    logger.info(f"  (考虑 Ti={payload.ion_energy_ev} eV 的影响)")
    
    bias_voltage = payload.plasma_potential_v - floating_potential
    probe_temperature = _probe_temperature(ion_current, bias_voltage)
    logger.info(f"探针温度: {probe_temperature:.2f} K")
    
    # 检查NaN
    result_dict = {
        "electron_debye_length_m": lambda_debye,
        "sheath_thickness_m": sheath_thickness,
        "ion_sound_speed_m_s": bohm_velocity,
        "floating_potential_v": floating_potential,
        "electron_plasma_frequency_hz": electron_plasma_frequency,
        "ion_plasma_frequency_hz": ion_plasma_frequency,
        "quasi_neutrality_ratio": quasi_neutrality_ratio,
        "ion_saturation_current_a": ion_current,
        "probe_temperature_k": probe_temperature,
    }
    
    for key, value in result_dict.items():
        if value != value:  # NaN检测
            logger.error(f"⚠️ 发现NaN: {key} = {value}")
        elif abs(value) == float('inf'):
            logger.error(f"⚠️ 发现无穷: {key} = {value}")
    
    logger.info("计算完成")
    logger.info("=" * 80)

    return SheathResult(
        electron_debye_length_m=round(lambda_debye, 6),
        sheath_thickness_m=round(sheath_thickness, 5),
        ion_sound_speed_m_s=round(bohm_velocity, 2),
        floating_potential_v=round(floating_potential, 3),
        plasma_potential_v=payload.plasma_potential_v,
        electron_plasma_frequency_hz=round(electron_plasma_frequency, 1),
        ion_plasma_frequency_hz=round(ion_plasma_frequency, 1),
        quasi_neutrality_ratio=round(quasi_neutrality_ratio, 3),
        neutral_gas_pressure_pa=neutral_pressure_pa,
        neutral_density_cm3=round(neutral_density_cm3, 2),
        ionization_fraction=ionization_fraction,
        ion_species=payload.ion_species,
        derived_density_cm3=derived_density_cm3,
        effective_ion_density_cm3=ion_density_cm3,
        effective_electron_density_cm3=electron_density_cm3,
        ion_saturation_current_a=round(ion_current, 6),
        probe_temperature_k=round(probe_temperature, 2),
        message="零维无碰撞鞘层模型：假设准中性、薄鞘层理论成立、冷离子近似 (Ti << Te)。",
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/simulate", response_model=SheathResult)
def simulate(payload: PlasmaInput):
    """使用输入的等离子体常数求解无碰撞鞘层。"""
    try:
        logger.info(f"收到请求: {payload.model_dump()}")
        result = run_sheath_model(payload)
        logger.info("请求处理成功")
        return result
    except Exception as e:
        logger.error(f"❌ 计算错误: {type(e).__name__}: {str(e)}")
        logger.exception("详细错误信息:")
        raise HTTPException(status_code=500, detail=f"计算错误: {str(e)}")


@app.post("/iv-curve", response_model=IVCurveResult)
def calculate_iv_curve(request: IVCurveRequest):
    """计算朗缪尔探针的 I-V 特性曲线。
    
    基于完整的鞘层物理模型，包括：
    - 离子玻姆流（考虑离子温度）
    - 麦克斯韦-玻尔兹曼电子分布
    - 电子饱和效应
    """
    try:
        logger.info(f"收到 I-V 曲线请求: {request.min_voltage} ~ {request.max_voltage} V, {request.steps} 点")
        
        # 1. 先计算基础鞘层参数
        sheath_result = run_sheath_model(request.plasma_params)
        
        # 2. 提取计算所需参数
        payload = request.plasma_params
        ion_mass = ION_MASS_MAP[payload.ion_species]
        electron_density_m3 = _cm3_to_m3(sheath_result.effective_electron_density_cm3)
        
        te_joule = max(payload.electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE
        ti_joule = max(payload.ion_energy_ev, 1e-6) * ELEMENTARY_CHARGE
        
        # 3. 计算基础物理量
        # 电子热速度
        electron_thermal_velocity = sqrt((8 * te_joule) / (pi * ELECTRON_MASS))
        # 电子随机热流通量
        electron_thermal_flux = 0.25 * electron_density_m3 * electron_thermal_velocity
        # 离子饱和电流（考虑离子温度）
        ion_saturation = sheath_result.ion_saturation_current_a
        
        logger.info(f"电子热速度: {electron_thermal_velocity:.2e} m/s")
        logger.info(f"电子热流通量: {electron_thermal_flux:.2e} m^-2 s^-1")
        logger.info(f"离子饱和电流: {ion_saturation:.2e} A")
        
        # 4. 生成 I-V 曲线
        iv_points = []
        for i in range(request.steps):
            ratio = i / (request.steps - 1) if request.steps > 1 else 0
            voltage = request.min_voltage + (request.max_voltage - request.min_voltage) * ratio
            
            # 探针相对于等离子体电势的电位
            probe_potential = voltage - payload.plasma_potential_v
            normalized_potential = probe_potential / max(payload.electron_energy_ev, 1e-3)
            
            # 离子电流：始终为玻姆流（负值，流入探针）
            ion_current = -ion_saturation
            
            # 电子电流
            if normalized_potential < 0:
                # 排斥区：exp(eΔV/kTe)
                electron_current = ELEMENTARY_CHARGE * PROBE_SURFACE_AREA * electron_thermal_flux * \
                                 exp(normalized_potential)
            else:
                # 吸引区：饱和到随机热流
                electron_current = ELEMENTARY_CHARGE * PROBE_SURFACE_AREA * electron_thermal_flux
            
            total_current = ion_current + electron_current
            iv_points.append(IVPoint(voltage=voltage, current=total_current))
        
        logger.info(f"生成 {len(iv_points)} 个 I-V 数据点")
        logger.info("I-V 曲线计算完成")
        
        return IVCurveResult(
            sheath_params=sheath_result,
            iv_curve=iv_points
        )
        
    except Exception as e:
        logger.error(f"❌ I-V 曲线计算错误: {type(e).__name__}: {str(e)}")
        logger.exception("详细错误信息:")
        raise HTTPException(status_code=500, detail=f"I-V 曲线计算错误: {str(e)}")


@app.post("/pic-slice", response_model=PICSimulationResult)
def run_pic_slice(payload: PICSimulationRequest):
    """运行二维无碰撞 PIC 片段仿真。"""
    try:
        ion_density_m3 = max(payload.ion_density_cm3, MIN_DENSITY_CM3) * CM3_TO_M3
        electron_density_m3 = max(payload.electron_density_cm3, MIN_DENSITY_CM3) * CM3_TO_M3
        result = run_pic_slice_simulation(
            patch_width_m=payload.patch_width_mm * 1e-3,
            conductor_thickness_m=payload.conductor_thickness_mm * 1e-3,
            sheath_thickness_m=payload.sheath_thickness_mm * 1e-3,
            presheath_thickness_m=payload.presheath_thickness_mm * 1e-3,
            bulk_thickness_m=payload.bulk_thickness_mm * 1e-3,
            ion_density_m3=ion_density_m3,
            electron_density_m3=electron_density_m3,
            ion_temperature_ev=payload.ion_temperature_ev,
            electron_temperature_ev=payload.electron_temperature_ev,
            plasma_potential_v=payload.plasma_potential_v,
            probe_bias_v=payload.probe_bias_v,
            neutral_pressure_pa=payload.neutral_pressure_pa,
            ion_species=payload.ion_species.value,
            config=PICConfig(),
        )
        return result
    except Exception as exc:
        logger.exception("PIC 仿真错误")
        raise HTTPException(status_code=500, detail=f"PIC 仿真错误: {exc}")


@app.post("/pic/jobs", response_model=SimulationJobResponse)
async def create_pic_job(payload: PICJobRequest):
    """启动完整 2D PIC 仿真并返回 job_id。"""
    config = _build_simulation_config(payload)
    bias_scan = _build_bias_scan(payload.bias_scan)
    job = simulation_manager.create_job(config, bias_scan)
    loop = asyncio.get_running_loop()
    job.start(loop)
    return SimulationJobResponse(job_id=job.job_id, status=job.status)


@app.get("/pic/jobs", response_model=list[SimulationStatusResponse])
def list_pic_jobs():
    jobs = simulation_manager.list_jobs()
    return [
        SimulationStatusResponse(
            job_id=item["job_id"],
            status=item["status"],
            error=item["error"],
            completed_bias_points=item["completed_bias_points"],
            total_bias_points=item["total_bias_points"],
            iv_points=item["iv_points"],
        )
        for item in jobs
    ]


@app.get("/pic/jobs/{job_id}", response_model=SimulationStatusResponse)
def get_pic_job(job_id: str):
    job = simulation_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到 PIC 仿真任务。")
    return SimulationStatusResponse(
        job_id=job.job_id,
        status=job.status,
        error=job.error,
        completed_bias_points=job.completed_bias_points,
        total_bias_points=job.total_bias_points,
        iv_points=len(job.iv_data),
    )


@app.get("/pic/jobs/{job_id}/iv", response_model=IVDataResponse)
def get_pic_iv_data(job_id: str):
    job = simulation_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到 PIC 仿真任务。")
    return IVDataResponse(
        job_id=job.job_id,
        iv_data=[
            IVDataPoint(**point)
            for point in job.iv_data
        ],
    )


@app.websocket("/ws/pic/{job_id}")
async def stream_pic_updates(websocket: WebSocket, job_id: str):
    await websocket.accept()
    job = simulation_manager.get_job(job_id)
    if not job:
        await websocket.send_json({"type": "error", "message": "未找到仿真任务。"})
        await websocket.close(code=4404)
        return
    queue = await job.subscribe()
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.info("WebSocket 断开：%s", job_id)
    finally:
        job.unsubscribe(queue)
