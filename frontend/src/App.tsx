import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import type {
  IonSpecies,
  PlasmaInput,
  PICIvPoint,
  PicSnapshotMessage,
  PicStreamMessage,
} from "./lib/api";
import { API_BASE, createPicJob, fetchPicIvData } from "./lib/api";
import "./App.css";

const CM3_TO_M3 = 1e6;
const BOLTZMANN = 1.380649e-23;
const GAS_TEMPERATURE_K = 300;
const EPSILON_0 = 8.8541878128e-12;
const ELEMENTARY_CHARGE = 1.602176634e-19;
const ELECTRON_MASS = 9.10938356e-31;
const AMU = 1.6605390666e-27;
const ION_MASS_MAP: Record<IonSpecies, number> = {
  Ar: 39.948 * AMU,
  Xe: 131.293 * AMU,
};

const DEFAULT_FORM: PlasmaInput = {
  neutral_gas_pressure_pa: 0.01,  // 降低到0.01 Pa，更接近低压等离子体实验条件
  ionization_fraction: 0.01,      // 降低到1%，更真实的低压放电
  ion_species: "Ar",
  ion_density_cm3: null,
  ion_energy_ev: 0.5,             // 降低离子温度
  electron_density_cm3: null,
  electron_energy_ev: 3,
  plasma_potential_v: 15,
};

type DensityMode = "derived" | "electron" | "ion";

type ScanSettings = {
  minVoltage: number;
  maxVoltage: number;
  steps: number;
  duration_ms: number;
};

function App() {
  const [formValues, setFormValues] = useState<PlasmaInput>(DEFAULT_FORM);
  const [densityMode, setDensityMode] = useState<DensityMode>("derived");
  const [picJobId, setPicJobId] = useState<string | null>(null);
  const [picJobStatus, setPicJobStatus] = useState<string>("idle");
  const [picSnapshot, setPicSnapshot] = useState<PicSnapshotMessage | null>(null);
  const [picIvData, setPicIvData] = useState<PICIvPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picLoading, setPicLoading] = useState(false);
  const [picError, setPicError] = useState<string | null>(null);
  const [picProgress, setPicProgress] = useState({ completed: 0, total: 0 });
  const [picStreamConnected, setPicStreamConnected] = useState(false);
  const websocketRef = useRef<WebSocket | null>(null);
  const [scanSettings, setScanSettings] = useState<ScanSettings>({
    minVoltage: -30,
    maxVoltage: 30,
    steps: 60,
    duration_ms: 200,
  });

  const neutralDensityCm3 = useMemo(() => {
    const density = formValues.neutral_gas_pressure_pa / (BOLTZMANN * GAS_TEMPERATURE_K) / CM3_TO_M3;
    return Math.max(density, 1e4);
  }, [formValues.neutral_gas_pressure_pa]);

  const derivedDensity = useMemo(
    () => neutralDensityCm3 * Math.max(formValues.ionization_fraction, 1e-4),
    [neutralDensityCm3, formValues.ionization_fraction],
  );

  const activeDensityCm3 = useMemo(() => {
    if (densityMode === "electron") {
      return Math.max(formValues.electron_density_cm3 ?? derivedDensity, 1e4);
    }
    if (densityMode === "ion") {
      return Math.max(formValues.ion_density_cm3 ?? derivedDensity, 1e4);
    }
    return derivedDensity;
  }, [densityMode, formValues.electron_density_cm3, formValues.ion_density_cm3, derivedDensity]);

  const debyeLength = useMemo(() => {
    const electronDensityM3 = activeDensityCm3 * CM3_TO_M3;
    const teJoule = Math.max(formValues.electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE;
    const denominator = Math.max(electronDensityM3 * ELEMENTARY_CHARGE ** 2, 1e-20);
    return Math.sqrt((EPSILON_0 * teJoule) / denominator);
  }, [activeDensityCm3, formValues.electron_energy_ev]);

  const ionMass = ION_MASS_MAP[formValues.ion_species];
  const activeDensityM3 = activeDensityCm3 * CM3_TO_M3;

  const electronPlasmaFrequency = useMemo(() => {
    return Math.sqrt(
      Math.max(activeDensityM3, 1e6) * ELEMENTARY_CHARGE ** 2 / (EPSILON_0 * ELECTRON_MASS),
    );
  }, [activeDensityM3]);

  const ionPlasmaFrequency = useMemo(() => {
    return Math.sqrt(
      Math.max(activeDensityM3, 1e6) * ELEMENTARY_CHARGE ** 2 / (EPSILON_0 * ionMass),
    );
  }, [activeDensityM3, ionMass]);

  const bohmVelocity = useMemo(() => {
    const teJoule = Math.max(formValues.electron_energy_ev, 1e-3) * ELEMENTARY_CHARGE;
    return Math.sqrt(teJoule / ionMass);
  }, [formValues.electron_energy_ev, ionMass]);

  const domainWidthMeters = Math.max(debyeLength * 20, 1e-4);
  const domainHeightMeters = Math.max(debyeLength * 10, 1e-4);

  const picFieldStats = useMemo(() => {
    if (!picSnapshot) return null;
    const maxValue = (grid: number[][]) => {
      let maximum = -Infinity;
      for (const row of grid) {
        for (const value of row) {
          if (value > maximum) {
            maximum = value;
          }
        }
      }
      return maximum === -Infinity ? 0 : maximum;
    };
    const minValue = (grid: number[][]) => {
      let minimum = Infinity;
      for (const row of grid) {
        for (const value of row) {
          if (value < minimum) {
            minimum = value;
          }
        }
      }
      return minimum === Infinity ? 0 : minimum;
    };
    return {
      ePeak: maxValue(picSnapshot.fields.e_magnitude),
      phiMin: minValue(picSnapshot.fields.phi),
      phiMax: maxValue(picSnapshot.fields.phi),
      rhoMin: minValue(picSnapshot.fields.rho),
      rhoMax: maxValue(picSnapshot.fields.rho),
    };
  }, [picSnapshot]);

  useEffect(() => {
    return () => {
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!picJobId) {
      return;
    }
    const normalizedBase = API_BASE.replace(/\/$/, "");
    const protocol = normalizedBase.startsWith("https") ? "wss" : "ws";
    const host = normalizedBase.replace(/^https?:\/\//, "");
    const wsUrl = `${protocol}://${host}/ws/pic/${picJobId}`;

    const ws = new WebSocket(wsUrl);
    websocketRef.current = ws;
    setPicStreamConnected(false);

    ws.onopen = () => {
      setPicStreamConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const payload: PicStreamMessage = JSON.parse(event.data);
        if (payload.type === "snapshot") {
          setPicSnapshot(payload);
        } else if (payload.type === "status") {
          setPicJobStatus(payload.status);
          setPicProgress({
            completed: payload.completed_bias_points ?? 0,
            total: payload.total_bias_points ?? 0,
          });
          if (payload.error) {
            setPicError(payload.error);
          }
        } else if (payload.type === "iv_point") {
          setPicIvData((prev) => {
            const map = new Map(prev.map((point) => [point.voltage, point]));
            map.set(payload.data.voltage, payload.data);
            return Array.from(map.values()).sort((a, b) => a.voltage - b.voltage);
          });
        } else if (payload.type === "error") {
          setPicError(payload.message);
          setPicJobStatus("failed");
        }
      } catch (err) {
        console.error("无法解析 PIC 流消息", err);
      }
    };

    ws.onerror = () => {
      setPicStreamConnected(false);
      setPicError("PIC 数据流连接出现问题");
    };

    ws.onclose = () => {
      setPicStreamConnected(false);
      if (websocketRef.current === ws) {
        websocketRef.current = null;
      }
    };

    return () => {
      ws.close();
    };
  }, [picJobId]);

  useEffect(() => {
    if (!picJobId || picJobStatus !== "completed") {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const response = await fetchPicIvData(picJobId);
        if (!cancelled) {
          setPicIvData(response.iv_data);
        }
      } catch (err) {
        if (!cancelled) {
          setPicError(err instanceof Error ? err.message : "获取 PIC I-V 数据失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [picJobId, picJobStatus]);

  useEffect(() => {
    if (picJobStatus === "pending" || picJobStatus === "running") {
      setPicLoading(true);
    } else if (picJobStatus === "completed" || picJobStatus === "failed") {
      setPicLoading(false);
    }
  }, [picJobStatus]);

  const handleNumberChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target;
    if (value === "" || value === "-" || value === "." || value === "-.") {
      return;
    }
    const parsed = Number(value);
    if (Number.isNaN(parsed)) {
      return;
    }
    setFormValues((prev) => ({
      ...prev,
      [name]: parsed,
    }));
  };

  const handleSpeciesChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const { value } = event.target;
    setFormValues((prev) => ({
      ...prev,
      ion_species: value as IonSpecies,
    }));
  };

  const handleDensityModeChange = (event: ChangeEvent<HTMLInputElement>) => {
    setDensityMode(event.target.value as DensityMode);
  };

  const handleScanChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target;
    if (value === "" || value === "-" || value === "." || value === "-.") {
      return;
    }
    const parsed = Number(value);
    if (Number.isNaN(parsed)) {
      return;
    }
    setScanSettings((prev) => ({
      ...prev,
      [name]: parsed,
    }));
  };

  const handleReset = () => {
    setFormValues(DEFAULT_FORM);
    setDensityMode("derived");
  };

  const handleRunPic = async () => {
    setError(null);
    setPicError(null);
    setLoading(true);

    const start = scanSettings.minVoltage;
    const end = scanSettings.maxVoltage;
    const rawSteps = Math.max(scanSettings.steps, 1);
    const biases: number[] = [];
    const span = end - start;
    if (rawSteps === 1 || Math.abs(span) < 1e-6) {
      biases.push(Number(start.toFixed(2)));
    } else {
      const direction = span >= 0 ? 1 : -1;
      const absoluteStep = Math.abs(span) / (rawSteps - 1);
      for (let i = 0; i < rawSteps; i += 1) {
        const value = start + direction * absoluteStep * i;
        biases.push(Number(value.toFixed(2)));
      }
    }
    if (!biases.length) {
      setPicError("无法生成有效的偏压序列。");
      setLoading(false);
      return;
    }

    const safeDebye = Math.max(debyeLength, 1e-5);
    const cellsPerDebye = 6;
    const estimateNx = Math.max(48, Math.round((domainWidthMeters / safeDebye) * cellsPerDebye));
    const estimateNy = Math.max(48, Math.round((domainHeightMeters / safeDebye) * cellsPerDebye));
    const nx = Math.min(200, estimateNx);
    const ny = Math.min(200, estimateNy);
    const particlesPerSpecies = Math.min(8000, Math.max(2000, Math.round((nx * ny) / 2)));

    const probeRadius = Math.max(Math.min(domainWidthMeters, domainHeightMeters) * 0.06, 5e-5);
    const probeGeometry = {
      shape: "circle" as const,
      center_x: domainWidthMeters / 2,
      center_y: Math.min(domainHeightMeters * 0.25, probeRadius * 2.5),
      radius: probeRadius,
    };

    const durationScale = Math.max(scanSettings.duration_ms, 80);
    const rampSteps = Math.max(60, Math.round(durationScale * 0.25));
    const measureSteps = Math.max(200, Math.round(durationScale));

    const densityCm3 = activeDensityCm3;
    const payloadDensity = Math.max(densityCm3, 1e4);

    const payload = {
      plasma: {
        density_cm3: payloadDensity,
        electron_temperature_ev: formValues.electron_energy_ev,
        ion_temperature_ev: formValues.ion_energy_ev,
        ion_species: formValues.ion_species,
        boundary_potential_v: formValues.plasma_potential_v,
      },
      domain: {
        lx: domainWidthMeters,
        ly: domainHeightMeters,
        nx,
        ny,
        dt: null,
        particles_per_species: Math.round(particlesPerSpecies),
        snapshot_interval: 10,
        downsample: 2,
        poisson_iterations: 80,
        relaxation_steps: 50,
        max_inject_per_step: 128,
        domain_depth: Math.max(domainWidthMeters * 0.2, 1e-3),
        rng_seed: undefined,
      },
      probe: probeGeometry,
      bias_scan: {
        bias_values: biases,
        ramp_steps: rampSteps,
        settle_steps: 0,
        measure_steps: measureSteps,
      },
    };

    setPicError(null);
    setPicSnapshot(null);
    setPicIvData([]);
    setPicProgress({ completed: 0, total: biases.length });
    setPicJobStatus("pending");
    setPicStreamConnected(false);
    if (websocketRef.current) {
      websocketRef.current.close();
      websocketRef.current = null;
    }
    setPicJobId(null);

    try {
      const response = await createPicJob(payload);
      setPicJobId(response.job_id);
      setPicJobStatus(response.status ?? "pending");
    } catch (err) {
      setPicError(err instanceof Error ? err.message : "PIC 仿真启动失败");
      setPicJobStatus("failed");
      setPicLoading(false);
      setLoading(false);
      return;
    }

    setLoading(false);
  };

  return (
    <div className="app-shell">
      <header>
        <h1>等离子体鞘层场景（零维仿真）</h1>
        <p>假设在无限均匀等离子体中，探针形成无碰撞鞘层。零维模型计算特征尺度，假设薄鞘层理论成立。</p>
      </header>

      <main>
        <section className="panel">
          <div className="panel-heading">
            <h2>背景气体</h2>
            <p className="panel-subtitle">
              设置 bulk plasma 的中性气体密度与电离率，鞘层区域以无碰撞近似求解。
            </p>
          </div>
          <div className="probe-form">
            <div className="field-grid">
              <label>
                中性气体压强 (Pa)
                <input
                  type="number"
                  step="any"
                  name="neutral_gas_pressure_pa"
                  value={formValues.neutral_gas_pressure_pa}
                  onChange={handleNumberChange}
                  min={1e-3}
                />
              </label>
              <label>
                电离率
                <input
                  type="number"
                  step="any"
                  name="ionization_fraction"
                  value={formValues.ionization_fraction}
                  onChange={handleNumberChange}
                  min={0}
                  max={1}
                />
              </label>
              <label>
                离子种类
                <select name="ion_species" value={formValues.ion_species} onChange={handleSpeciesChange}>
                  <option value="Ar">Ar (氩)</option>
                  <option value="Xe">Xe (氙)</option>
                </select>
              </label>
            </div>

            <div className="density-toggle">
              <label>
                <input
                  type="radio"
                  value="derived"
                  checked={densityMode === "derived"}
                  onChange={handleDensityModeChange}
                />
                使用背景密度 × 电离率推导离子/电子密度
              </label>
              <label>
                <input
                  type="radio"
                  value="electron"
                  checked={densityMode === "electron"}
                  onChange={handleDensityModeChange}
                />
                手动设置电子密度（等于离子密度）
              </label>
              <label>
                <input
                  type="radio"
                  value="ion"
                  checked={densityMode === "ion"}
                  onChange={handleDensityModeChange}
                />
                手动设置离子密度（等于电子密度）
              </label>
              <p>
                中性密度 ≈ {neutralDensityCm3.toExponential(2)} cm⁻³，推导离子密度 ≈{" "}
                {derivedDensity.toExponential(2)} cm⁻³
              </p>
            </div>

            {densityMode === "electron" && (
              <div className="field-grid">
                <label>
                  电子密度 (cm⁻³)
                  <input
                  type="number"
                  step="any"
                  name="electron_density_cm3"
                  value={formValues.electron_density_cm3 ?? derivedDensity}
                  onChange={handleNumberChange}
                  min={1e6}
                />
                </label>
              </div>
            )}

            {densityMode === "ion" && (
              <div className="field-grid">
                <label>
                  离子密度 (cm⁻³)
                  <input
                  type="number"
                  step="any"
                  name="ion_density_cm3"
                  value={formValues.ion_density_cm3 ?? derivedDensity}
                  onChange={handleNumberChange}
                  min={1e6}
                />
                </label>
              </div>
            )}

            <div className="field-grid">
              <label>
                离子温度 (eV)
                <input
                  type="number"
                  step="any"
                  name="ion_energy_ev"
                  value={formValues.ion_energy_ev}
                  onChange={handleNumberChange}
                  min={0.1}
                />
              </label>
              <label>
                电子温度 (eV)
                <input
                  type="number"
                  step="any"
                  name="electron_energy_ev"
                  value={formValues.electron_energy_ev}
                  onChange={handleNumberChange}
                  min={0.1}
                />
              </label>
              <label>
                空间电势 φp (V)
                <input
                  type="number"
                  step="any"
                  name="plasma_potential_v"
                  value={formValues.plasma_potential_v}
                  onChange={handleNumberChange}
                  min={-50}
                />
              </label>
            </div>

            <div className="form-actions">
              <div className="presets">
                <span>常用操作:</span>
                <button
                  type="button"
                  onClick={() => setFormValues((prev) => ({ ...prev, ionization_fraction: 0.05 }))}
                >
                  低电离率
                </button>
                <button
                  type="button"
                  onClick={() => setFormValues((prev) => ({ ...prev, ionization_fraction: 0.2 }))}
                >
                  高电离率
                </button>
                <button type="button" onClick={handleReset}>
                  重置
                </button>
              </div>
            </div>
          </div>
          {error && <p className="error">{error}</p>}
        </section>

        <section className="panel animation-panel">
          <div className="panel-heading">
            <h2>PIC 粒子运动预览</h2>
            <p className="panel-subtitle">
              在探针导体上方沿垂直方向展示离子/电子的代表性运动，用以直观理解鞘层、预鞘层与 bulk plasma。
            </p>
          </div>
          <ParticleAnimation
            snapshot={picSnapshot}
            fallbackWidthM={domainWidthMeters}
            fallbackHeightM={domainHeightMeters}
            ionSpecies={formValues.ion_species}
          />
        </section>

        <section className="probe-console">
          <h2>虚拟探针操作台</h2>
          <div className="console-layout">
            <div className="iv-panel">
              <div className="panel-heading">
                <h3>I-V Curve</h3>
                <p className="panel-subtitle">由实时 PIC 仿真返回的平均电流点，将在计算完成后逐点落在曲线上。</p>
              </div>
              <IVCurve ivData={picIvData} />
            </div>
            <div className="console-side">
              <div className="console-panel">
                <h3>输入推导指标</h3>
                <ul>
                  <li>有效密度：{activeDensityCm3.toExponential(2)} cm⁻³</li>
                  <li>德拜长度：{(debyeLength * 1e3).toFixed(3)} mm</li>
                  <li>电子等离子体频率：{(electronPlasmaFrequency / 1e9).toFixed(2)} GHz</li>
                  <li>离子等离子体频率：{(ionPlasmaFrequency / 1e6).toFixed(2)} MHz</li>
                  <li>玻姆速度：{bohmVelocity.toFixed(0)} m/s</li>
                </ul>
              </div>
              <div className="console-panel">
                <h3>扫描设置</h3>
                <div className="field-grid compact">
                  <label>
                    起始电压 (V)
                    <input
                      type="number"
                      name="minVoltage"
                      value={scanSettings.minVoltage}
                      onChange={handleScanChange}
                    />
                  </label>
                  <label>
                    终止电压 (V)
                    <input
                      type="number"
                      name="maxVoltage"
                      value={scanSettings.maxVoltage}
                      onChange={handleScanChange}
                    />
                  </label>
                  <label>
                    采样点数
                    <input
                      type="number"
                      name="steps"
                      min={2}
                      value={scanSettings.steps}
                      onChange={handleScanChange}
                    />
                  </label>
                  <label>
                    每点停留 (ms)
                    <input
                      type="number"
                      name="duration_ms"
                      min={1}
                      value={scanSettings.duration_ms}
                      onChange={handleScanChange}
                    />
                  </label>
                </div>
                <p className="scan-summary">
                  预计扫过 {(scanSettings.maxVoltage - scanSettings.minVoltage).toFixed(1)} V 区间，
                  耗时约 {(scanSettings.steps * scanSettings.duration_ms / 1000).toFixed(2)} s。
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="panel pic-panel">
          <div className="panel-heading">
            <h2>二维 PIC 仿真</h2>
            <p className="panel-subtitle">
              无碰撞 PIC 核心实时求解探针偏压扫描，唯一的电流来源即来自该仿真结果。
            </p>
          </div>
          <div className="pic-controls">
            <button type="button" onClick={handleRunPic} disabled={loading || picLoading}>
              {loading
                ? "准备仿真参数..."
                : picLoading
                  ? "PIC 仿真运行中..."
                  : "启动二维 PIC 扫描"}
            </button>
            <span className={`stream-status ${picStreamConnected ? "stream-ok" : "stream-idle"}`}>
              数据流：{picStreamConnected ? "实时更新中" : "等待连接"}
            </span>
          </div>
          {picError && <p className="error">{picError}</p>}
          <div className="pic-status">
            <p>任务 ID：{picJobId ?? "尚未启动"}</p>
            <p>
              状态：{picJobStatus === "idle" ? "待机" : picJobStatus === "pending" ? "排队" : picJobStatus === "running" ? "运行中" : picJobStatus === "completed" ? "已完成" : "失败"}
            </p>
            <p>
              进度：{picProgress.completed}/{picProgress.total || Math.max(scanSettings.steps, 1)}
            </p>
            {picSnapshot ? (
              <>
                <p>
                  当前偏压：{picSnapshot.bias_value.toFixed(2)} V（阶段：{picSnapshot.phase}）
                </p>
                <p>
                  瞬时电流：{(picSnapshot.currents.total * 1e3).toFixed(2)} mA（电子{" "}
                  {(picSnapshot.currents.electrons * 1e3).toFixed(2)} mA，离子{" "}
                  {(picSnapshot.currents.ions * 1e3).toFixed(2)} mA）
                </p>
              </>
            ) : (
              <p>尚未收到实时帧。</p>
            )}
          </div>
          {picSnapshot && picFieldStats ? (
            <div className="pic-field-stats">
              <div>
                <h4>电场峰值</h4>
                <p>{picFieldStats.ePeak.toExponential(2)} V/m</p>
              </div>
              <div>
                <h4>势场范围</h4>
                <p>
                  {picFieldStats.phiMin.toFixed(2)} V ~ {picFieldStats.phiMax.toFixed(2)} V
                </p>
              </div>
              <div>
                <h4>电荷密度范围</h4>
                <p>
                  {picFieldStats.rhoMin.toExponential(2)} ~ {picFieldStats.rhoMax.toExponential(2)} C/m³
                </p>
              </div>
            </div>
          ) : (
            <p className="placeholder">启动任务后，这里会展示实时帧分析结果。</p>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;

type IVCurveProps = {
  ivData: PICIvPoint[];
};

function IVCurve({ ivData }: IVCurveProps) {
  if (!ivData || ivData.length === 0) {
    return <p className="placeholder">暂无数据，请先运行仿真</p>;
  }

  const shape = useMemo(() => {
    const width = 700;
    const height = 280;
    const pad = 50;

    const voltages = ivData.map((p) => p.voltage);
    const currents = ivData.map((p) => p.current_total);
    const minV = Math.min(...voltages);
    const maxV = Math.max(...voltages);
    const minI = Math.min(...currents, -1e-3);
    const maxI = Math.max(...currents, 1e-3);
    const spanV = maxV - minV || 1;
    const spanI = maxI - minI || 1;

    const ordered = [...ivData].sort((a, b) => a.voltage - b.voltage);

    const path = ordered
      .map((point, index) => {
        const x = pad + ((point.voltage - minV) / spanV) * (width - 2 * pad);
        const y = height - pad - ((point.current_total - minI) / spanI) * (height - 2 * pad);
        return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");

    const tickCount = 4;
    const xTicks = Array.from({ length: tickCount + 1 }, (_, i) => minV + (spanV * i) / tickCount);
    const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => minI + (spanI * i) / tickCount);

    return {
      path,
      width,
      height,
      pad,
      minV,
      maxV,
      minI,
      maxI,
      xTicks,
      yTicks,
    };
  }, [ivData]);

  return (
    <div className="iv-graph">
      <svg width={shape.width} height={shape.height}>
        <rect
          x={shape.pad}
          y={shape.pad}
          width={shape.width - 2 * shape.pad}
          height={shape.height - 2 * shape.pad}
          fill="none"
          stroke="rgba(255,255,255,0.15)"
        />
        {shape.xTicks.map((tick) => {
          const x = shape.pad + ((tick - shape.minV) / (shape.maxV - shape.minV || 1)) * (shape.width - 2 * shape.pad);
          return (
            <g key={`x-${tick}`}>
              <line
                x1={x}
                y1={shape.height - shape.pad}
                x2={x}
                y2={shape.height - shape.pad + 6}
                stroke="rgba(255,255,255,0.3)"
              />
              <text x={x} y={shape.height - shape.pad + 18} className="iv-axis-text">
                {tick.toFixed(0)}
              </text>
            </g>
          );
        })}
        {shape.yTicks.map((tick) => {
          const y =
            shape.height - shape.pad - ((tick - shape.minI) / (shape.maxI - shape.minI || 1)) * (shape.height - 2 * shape.pad);
          return (
            <g key={`y-${tick}`}>
              <line x1={shape.pad - 6} y1={y} x2={shape.pad} y2={y} stroke="rgba(255,255,255,0.3)" />
              <text x={shape.pad - 12} y={y + 4} className="iv-axis-text" textAnchor="end">
                {(tick * 1e3).toFixed(1)}
              </text>
            </g>
          );
        })}
        <path d={shape.path} stroke="#61dafb" strokeWidth={2} fill="none" />
        <text x={shape.width / 2} y={shape.height - 5} className="iv-axis-label">
          偏压 (V)
        </text>
        <text
          x={12}
          y={shape.height / 2}
          className="iv-axis-label"
          transform={`rotate(-90 12 ${shape.height / 2})`}
        >
          电流 (mA)
        </text>
      </svg>
      <div className="iv-stats">
        <span>
          V 范围：{shape.minV.toFixed(1)} ~ {shape.maxV.toFixed(1)} V
        </span>
        <span>
          I 范围：{(shape.minI * 1e3).toFixed(2)} ~ {(shape.maxI * 1e3).toFixed(2)} mA
        </span>
      </div>
    </div>
  );
}

type ParticleAnimationProps = {
  snapshot: PicSnapshotMessage | null;
  fallbackWidthM: number;
  fallbackHeightM: number;
  ionSpecies: IonSpecies;
};

function ParticleAnimation({
  snapshot,
  fallbackWidthM,
  fallbackHeightM,
  ionSpecies,
}: ParticleAnimationProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const potentialStats = useMemo(() => {
    if (!snapshot) return null;
    const phiGrid = snapshot.fields.phi;
    if (!phiGrid.length) return { min: 0, max: 0, maxAbs: 1 };
    let min = Infinity;
    let max = -Infinity;
    for (const column of phiGrid) {
      for (const value of column) {
        if (value < min) min = value;
        if (value > max) max = value;
      }
    }
    const maxAbs = Math.max(Math.abs(min), Math.abs(max), 1e-6);
    return { min, max, maxAbs };
  }, [snapshot]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!snapshot) {
      return;
    }

    const gridX = snapshot.grid.x;
    const gridY = snapshot.grid.y;
    const domainWidth = gridX.length > 0 ? gridX[gridX.length - 1] : fallbackWidthM;
    const domainHeight = gridY.length > 0 ? gridY[gridY.length - 1] : fallbackHeightM;
    const width = canvas.width;
    const height = canvas.height;
    const range = potentialStats ?? { min: 0, max: 0, maxAbs: 1 };

    const phiGrid = snapshot.fields.phi;
    const phiNx = phiGrid.length;
    const phiNy = phiNx > 0 ? phiGrid[0].length : 0;

    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
    const colorForPotential = (value: number) => {
      const normalized = Math.max(0, Math.min(1, (value + range.maxAbs) / (2 * range.maxAbs)));
      const mid = 0.5;
      let r: number;
      let g: number;
      let b: number;
      if (normalized < mid) {
        const t = normalized / mid;
        r = lerp(59, 245, t);
        g = lerp(130, 245, t);
        b = lerp(246, 245, t);
      } else {
        const t = (normalized - mid) / (1 - mid);
        r = lerp(245, 239, t);
        g = lerp(245, 68, t);
        b = lerp(245, 68, t);
      }
      return `rgb(${r.toFixed(0)}, ${g.toFixed(0)}, ${b.toFixed(0)})`;
    };

    if (phiNx && phiNy) {
      const cellWidth = width / phiNx;
      const cellHeight = height / phiNy;
      for (let ix = 0; ix < phiNx; ix += 1) {
        for (let iy = 0; iy < phiNy; iy += 1) {
          const value = phiGrid[ix][iy];
          ctx.fillStyle = colorForPotential(value);
          const xPx = ix * cellWidth;
          const yPx = height - (iy + 1) * cellHeight;
          ctx.fillRect(xPx, yPx, cellWidth + 1, cellHeight + 1);
        }
      }
    }

    const drawParticles = (points: number[][], color: string, radius: number) => {
      ctx.fillStyle = color;
      points.forEach((point) => {
        if (point.length < 2) return;
        const [xVal, yVal] = point;
        const xPx = (xVal / domainWidth) * width;
        const yPx = height - (yVal / domainHeight) * height;
        ctx.beginPath();
        ctx.arc(xPx, yPx, radius, 0, Math.PI * 2);
        ctx.fill();
      });
    };

    drawParticles(snapshot.particles.ions, "rgba(255, 149, 0, 0.85)", 2.2);
    drawParticles(snapshot.particles.electrons, "rgba(64, 182, 255, 0.9)", 1.6);
  }, [snapshot, fallbackWidthM, fallbackHeightM, potentialStats]);

  const domainWidthMm =
    snapshot && snapshot.grid.x.length > 0
      ? snapshot.grid.x[snapshot.grid.x.length - 1] * 1000
      : fallbackWidthM * 1000;
  const domainHeightMm =
    snapshot && snapshot.grid.y.length > 0
      ? snapshot.grid.y[snapshot.grid.y.length - 1] * 1000
      : fallbackHeightM * 1000;

  return (
    <div className="particle-animation">
      <p className="domain-info">
        仿真域尺寸：{domainWidthMm.toFixed(2)} mm × {domainHeightMm.toFixed(2)} mm
      </p>
      <div className="animation-canvas-wrapper">
        {snapshot ? (
          <canvas ref={canvasRef} width={720} height={720} />
        ) : (
          <div className="animation-placeholder">启动二维 PIC 任务后可实时观看粒子演化</div>
        )}
        <div className="probe-surface-strip">
          <span>探针导体</span>
        </div>
      </div>
      {snapshot && potentialStats && (
        <div className="potential-legend">
          <div className="colorbar">
            <span>电势分布 (V)</span>
            <div className="colorbar-gradient" />
            <div className="colorbar-values">
              <span>{potentialStats.min.toFixed(2)}</span>
              <span>0</span>
              <span>{potentialStats.max.toFixed(2)}</span>
            </div>
          </div>
          <div className="particle-legends">
            <span>
              <span className="particle-dot ion-dot" />
              {ionSpecies}⁺ 离子
            </span>
            <span>
              <span className="particle-dot electron-dot" />
              电子
            </span>
          </div>
        </div>
      )}
      <p className="animation-caption">上方：bulk plasma；中部：预鞘层；下方：鞘层与探针导体。</p>
    </div>
  );
}
