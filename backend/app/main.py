from enum import Enum
from math import exp, log, pi, sqrt
from typing import Optional
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
