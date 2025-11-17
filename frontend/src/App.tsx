import { useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import type { IonSpecies, PlasmaInput, SheathResult, IVPoint } from "./lib/api";
import { calculateIVCurve } from "./lib/api";
import "./App.css";

const CM3_TO_M3 = 1e6;
const BOLTZMANN = 1.380649e-23;
const GAS_TEMPERATURE_K = 300;

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
  const [result, setResult] = useState<SheathResult | null>(null);
  const [ivCurveData, setIvCurveData] = useState<IVPoint[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setLoading(true);

    const payload: PlasmaInput = {
      ...formValues,
      ion_density_cm3:
        densityMode === "ion" ? formValues.ion_density_cm3 ?? derivedDensity : null,
      electron_density_cm3:
        densityMode === "electron" ? formValues.electron_density_cm3 ?? derivedDensity : null,
    };

    try {
      // 调用后端计算 I-V 曲线（包含鞘层参数）
      const ivResult = await calculateIVCurve({
        plasma_params: payload,
        min_voltage: scanSettings.minVoltage,
        max_voltage: scanSettings.maxVoltage,
        steps: scanSettings.steps,
      });
      
      setResult(ivResult.sheath_params);
      setIvCurveData(ivResult.iv_curve);
      
      console.log(`从后端获取 ${ivResult.iv_curve.length} 个 I-V 数据点`);
      const currents = ivResult.iv_curve.map(p => p.current);
      console.log(`电流范围: ${Math.min(...currents).toExponential(2)} ~ ${Math.max(...currents).toExponential(2)} A`);
    } catch (err) {
      setResult(null);
      setIvCurveData(null);
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFormValues(DEFAULT_FORM);
    setDensityMode("derived");
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
          <form onSubmit={handleSubmit} className="probe-form">
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
              <button type="submit" disabled={loading}>
                {loading ? "计算中..." : "求解鞘层"}
              </button>
            </div>
          </form>
          {error && <p className="error">{error}</p>}
        </section>

        <section className="probe-console">
          <h2>虚拟探针操作台</h2>
          <div className="console-layout">
            <div className="iv-panel">
              <div className="panel-heading">
                <h3>I-V Curve</h3>
                <p className="panel-subtitle">根据当前等离子体参数快速合成的 I-V 扫描曲线。</p>
              </div>
              <IVCurve ivData={ivCurveData} />
            </div>
            <div className="console-side">
              <div className="console-panel">
                <h3>解算物理量</h3>
                {result ? (
                  <ul>
                    <li>浮动电位：{result.floating_potential_v.toFixed(2)} V</li>
                    <li>探针温度：{result.probe_temperature_k.toFixed(1)} K</li>
                    <li>离子饱和电流：{(result.ion_saturation_current_a * 1e3).toFixed(2)} mA</li>
                    <li>德拜长度：{(result.electron_debye_length_m * 1e3).toFixed(3)} mm</li>
                  </ul>
                ) : (
                  <p>求解完成后，这里展示探针关键指标。</p>
                )}
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
      </main>
    </div>
  );
}

export default App;

type IVCurveProps = {
  ivData: IVPoint[] | null;
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
    const currents = ivData.map((p) => p.current);
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
        const y = height - pad - ((point.current - minI) / spanI) * (height - 2 * pad);
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
