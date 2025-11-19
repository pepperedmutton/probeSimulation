import { useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchDynamicIV, fetchDynamicIVStream } from '../api'

type GasType = 'H' | 'Ar' | 'custom'
type IonModel = 'OML' | 'ABR' | 'BRL' | 'ChildLangmuir'

type DynamicIVRequest = {
  plasma: {
    ne: number
    te_eV: number
    vs: number
    gas_type: GasType
    mi_custom?: number | null
  }
  probe: {
    area: number
    radius: number
    length: number
    capacitance: number
  }
  rf: {
    frequency_hz: number
    te_amplitude_ev: number
    ne_amplitude: number
    vs_amplitude_v: number
  }
  time_range: {
    total_time_s: number
    dt_s: number
    voltage_step_rf_cycles?: number | null
  }
  vp_initial: number
  vp_final?: number | null
  model: IonModel
  integrator?: 'euler' | 'rk4'
}

type DynamicIVResponse = {
  time: number[]
  vp: number[]
  ne: number[]
  te_eV: number[]
  vs: number[]
  ie: number[]
  ii: number[]
  i_total: number[]
  metadata?: Record<string, unknown>
}

type PlasmaFormState = {
  neMantissa: number
  neExponent: number
  te_eV: number
  vs: number
  gas_type: GasType
  mi_custom?: number | null
}

type DynamicIVForm = {
  plasma: PlasmaFormState
  probe: {
    area: string | number
    radius: string | number
    length: string | number
    capacitance: string | number
  }
  rf: {
    frequency_hz: string | number
    te_amplitude_ev: number
    ne_amplitude: string | number
    vs_amplitude_v: number
  }
  time_range: {
    total_time_s: string | number
    dt_s: string | number
    voltage_step_rf_cycles: string | number | null
  }
  vp_initial: number
  vp_final: number | null
  model: IonModel
  integrator?: 'euler' | 'rk4'
}

const DEFAULT_FORM: DynamicIVForm = {
  plasma: {
    neMantissa: 5,
    neExponent: 15,
    te_eV: 3,
    vs: 0,
    gas_type: 'Ar',
    mi_custom: null,
  },
  probe: {
    area: '1e-6',
    radius: '1e-3',
    length: '5e-3',
    capacitance: '1e-12',
  },
  rf: {
    frequency_hz: '13.56e6',
    te_amplitude_ev: 0.5,
    ne_amplitude: '1e14',
    vs_amplitude_v: 2.0,
  },
  time_range: {
    total_time_s: '0.01',  // 10ms - reasonable for dt=3.69e-9
    dt_s: '1e-8',
    voltage_step_rf_cycles: null,  // null means continuous sweep
  },
  vp_initial: -30.0,
  vp_final: 20.0,
  model: 'ABR',
  integrator: 'rk4',
}

type ChartDatum = {
  time: number
  vp: number
  i_total: number
  ie: number
  ii: number
  ne: number
  te_eV: number
  vs: number
}
// (derived metrics such as ln_ie, i_square, i_43 are computed where needed)

export function LangmuirIVSimulator() {
  console.log('=== LangmuirIVSimulator component mounting ===')
  
  const [form, setForm] = useState<DynamicIVForm>(DEFAULT_FORM)
  const [result, setResult] = useState<DynamicIVResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [showElectron, setShowElectron] = useState(true)
  const [showIon, setShowIon] = useState(true)
  
  console.log('=== LangmuirIVSimulator state initialized ===')
  
  const warnings =
    result && Array.isArray(result.metadata?.warnings)
      ? (result.metadata?.warnings as string[])
      : null
  const modelLabel =
    result &&
    result.metadata &&
    'model' in result.metadata &&
    result.metadata.model !== undefined &&
    result.metadata.model !== null
      ? String(result.metadata.model)
      : '--'
  const savedFileMeta = result?.metadata ? (result.metadata as Record<string, unknown>)['saved_file'] : null
  const savedFilePath = typeof savedFileMeta === 'string' ? savedFileMeta : null

  const chartData = useMemo<ChartDatum[]>(() => {
    if (!result) {
      console.log('chartData: no result')
      return []
    }
    console.log('chartData: creating from result with', result.time.length, 'points')
    
    const rawData = result.time.map((time, idx) => ({
      time,
      vp: result.vp[idx],
      ie: result.ie[idx],
      ii: result.ii[idx],
      i_total: result.i_total[idx],
      ne: result.ne[idx],
      te_eV: result.te_eV[idx],
      vs: result.vs[idx],
    }))
    
    // Downsample to max 100,000 points for detailed chart rendering
    const maxPoints = 100000
    if (rawData.length > maxPoints) {
      const step = Math.ceil(rawData.length / maxPoints)
      const downsampled = rawData.filter((_, idx) => idx % step === 0)
      console.log(`Downsampled from ${rawData.length} to ${downsampled.length} points for chart`)
      console.log('First few vp values:', downsampled.slice(0, 5).map(d => d.vp))
      console.log('First few i_total values:', downsampled.slice(0, 5).map(d => d.i_total))
      return downsampled
    }
    
    console.log('Using all', rawData.length, 'points for chart (no downsampling needed)')
    console.log('First few vp values:', rawData.slice(0, 5).map(d => d.vp))
    console.log('First few i_total values:', rawData.slice(0, 5).map(d => d.i_total))
    return rawData
  }, [result])


  const handlePlasmaChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = event.target
    setForm((prev) => ({
      ...prev,
      plasma: {
        ...prev.plasma,
        [name]: name === 'gas_type' ? (value as GasType) : Number(value),
      },
    }))
  }

  const handleProbeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setForm((prev) => ({
      ...prev,
      probe: {
        ...prev.probe,
        [name]: value,
      },
    }))
  }

  // sweep handlers removed (dynamic simulation uses time stepping)

  const handleRFChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setForm((prev) => ({
      ...prev,
      rf: {
        ...prev.rf,
        [name]: value,
      },
    }))
  }

  // Calculate recommended dt based on RF frequency and sampling points per cycle
  const calculateRecommendedDt = (frequencyHz: number, pointsPerCycle: number): string => {
    if (!frequencyHz || frequencyHz <= 0) return '1e-8'
    const period = 1.0 / frequencyHz
    const dt = period / pointsPerCycle
    return dt.toExponential(2)
  }

  // Get current RF frequency
  const currentRfFreq = Number(form.rf.frequency_hz) || 13.56e6
  const samplingOptions = [
    { label: '10 points/cycle', points: 10 },
    { label: '20 points/cycle (推荐)', points: 20 },
    { label: '40 points/cycle', points: 40 },
    { label: '100 points/cycle', points: 100 },
  ]

  const handleTimeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setForm((prev) => ({
      ...prev,
      time_range: {
        ...prev.time_range,
        [name]: value,
      },
    }))
  }

  // model selection handled inline via form state

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    console.log('=== handleSubmit called ===')
    setIsLoading(true)
    setError(null)
    setResult(null) // Clear previous results
    setProgress(0)
    
    try {
      console.log('Building payload...')
      const payloadBody: DynamicIVRequest = {
        plasma: {
          ne: form.plasma.neMantissa * Math.pow(10, form.plasma.neExponent),
          te_eV: form.plasma.te_eV,
          vs: form.plasma.vs,
          gas_type: form.plasma.gas_type,
          mi_custom: form.plasma.mi_custom,
        },
        probe: {
          area: Number(form.probe.area),
          radius: Number(form.probe.radius),
          length: Number(form.probe.length),
          capacitance: Number(form.probe.capacitance),
        },
        rf: {
          frequency_hz: Number(form.rf.frequency_hz),
          te_amplitude_ev: form.rf.te_amplitude_ev,
          ne_amplitude: Number(form.rf.ne_amplitude),
          vs_amplitude_v: form.rf.vs_amplitude_v,
        },
        time_range: {
          total_time_s: Number(form.time_range.total_time_s),
          dt_s: Number(form.time_range.dt_s),
          voltage_step_rf_cycles: form.time_range.voltage_step_rf_cycles 
            ? Number(form.time_range.voltage_step_rf_cycles) 
            : null,
        },
        vp_initial: form.vp_initial,
        vp_final: form.vp_final,
        model: form.model,
        integrator: form.integrator,
      }
      
      console.log('📦 Payload built:', payloadBody)
      console.log('⏱️  dt_s being sent to backend:', payloadBody.time_range.dt_s)
      console.log('   Form dt_s value:', form.time_range.dt_s)
      console.log('   Form dt_s type:', typeof form.time_range.dt_s)
      
      // Use streaming API for real-time updates
      const accumulatedData: DynamicIVResponse = {
        time: [],
        vp: [],
        ne: [],
        te_eV: [],
        vs: [],
        ie: [],
        ii: [],
        i_total: [],
        metadata: {},
      }
      
      console.log('Starting streaming simulation...')
      
      for await (const chunk of fetchDynamicIVStream(payloadBody)) {
        console.log('Received chunk:', chunk.progress ? `Progress: ${Math.round(chunk.progress * 100)}%` : 'Metadata', 
                    'Points in chunk:', chunk.time?.length || 0)
        
        if (chunk.error) {
          throw new Error(chunk.error)
        }
        
        if (chunk.metadata) {
          accumulatedData.metadata = chunk.metadata
        } else {
          // Append chunk data to accumulated arrays
          accumulatedData.time.push(...chunk.time)
          accumulatedData.vp.push(...chunk.vp)
          accumulatedData.ne.push(...chunk.ne)
          accumulatedData.te_eV.push(...chunk.te_eV)
          accumulatedData.vs.push(...chunk.vs)
          accumulatedData.ie.push(...chunk.ie)
          accumulatedData.ii.push(...chunk.ii)
          accumulatedData.i_total.push(...chunk.i_total)
          
          // Update progress
          if (chunk.progress !== undefined) {
            setProgress(chunk.progress)
          }
          
          // Create a completely new object to force React to detect the change
          console.log('About to setResult with', accumulatedData.time.length, 'points')
          console.log('Sample data - vp[0]:', accumulatedData.vp[0], 'i_total[0]:', accumulatedData.i_total[0])
          setResult({
            time: [...accumulatedData.time],
            vp: [...accumulatedData.vp],
            ne: [...accumulatedData.ne],
            te_eV: [...accumulatedData.te_eV],
            vs: [...accumulatedData.vs],
            ie: [...accumulatedData.ie],
            ii: [...accumulatedData.ii],
            i_total: [...accumulatedData.i_total],
            metadata: { ...accumulatedData.metadata },
          })
          console.log('Updated chart with', accumulatedData.time.length, 'total points')
        }
      }
      
      // Final update with all data
      setResult({ ...accumulatedData })
      console.log('Streaming complete! Total points:', accumulatedData.time.length)
      
    } catch (err) {
      console.error('Simulation error:', err)
      const message = err instanceof Error ? err.message : 'Simulation failed'
      setError(message)
      setResult(null)
    } finally {
      setIsLoading(false)
      setProgress(0)
    }
  }

  return (
    <section className="panel">
      <h1>Langmuir I-V Simulator</h1>
      <p className="subtitle">
        Configure plasma, probe, and model assumptions. The backend returns the full I-V branch
        plus diagnostics such as ln(Ie), I^2, and I^(4/3).
      </p>

      <form className="iv-form" onSubmit={handleSubmit}>
        <div className="iv-grid">
          <fieldset>
            <legend>Plasma</legend>
            <label>
              Electron density mantissa
              <input
                type="number"
                name="neMantissa"
                value={form.plasma.neMantissa}
                onChange={handlePlasmaChange}
                min={0.1}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Electron density exponent (10^x)
              <input
                type="number"
                name="neExponent"
                value={form.plasma.neExponent}
                onChange={handlePlasmaChange}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Electron temperature (eV)
              <input
                type="number"
                name="te_eV"
                value={form.plasma.te_eV}
                onChange={handlePlasmaChange}
                min={0.1}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Space potential Vs (V)
              <input
                type="number"
                name="vs"
                value={form.plasma.vs}
                onChange={handlePlasmaChange}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Ion species
              <select name="gas_type" value={form.plasma.gas_type} onChange={handlePlasmaChange}>
                <option value="H">H+</option>
                <option value="Ar">Ar+</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            {form.plasma.gas_type === 'custom' && (
              <label>
                Ion mass (kg)
                <input
                  type="number"
                  name="mi_custom"
                  value={form.plasma.mi_custom ?? ''}
                  onChange={handlePlasmaChange}
                  min={1e-30}
                  step="any"
                  inputMode="decimal"
                  required
                />
              </label>
            )}
          </fieldset>

          <fieldset>
            <legend>Probe</legend>
            <label>
              Area (m^2)
              <input
                type="text"
                name="area"
                value={form.probe.area}
                onChange={handleProbeChange}
                placeholder="e.g., 1e-6"
                required
              />
            </label>
            <label>
              Radius (m)
              <input
                type="text"
                name="radius"
                value={form.probe.radius}
                onChange={handleProbeChange}
                placeholder="e.g., 1e-3"
                required
              />
            </label>
            <label>
              Length (m)
              <input
                type="text"
                name="length"
                value={form.probe.length}
                onChange={handleProbeChange}
                placeholder="e.g., 5e-3"
                required
              />
            </label>
            <label>
              Capacitance (F)
              <input
                type="text"
                name="capacitance"
                value={form.probe.capacitance}
                onChange={handleProbeChange}
                placeholder="e.g., 1e-12"
                required
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>RF Modulation</legend>
            <label>
              Frequency (Hz)
              <input
                type="text"
                name="frequency_hz"
                value={form.rf.frequency_hz}
                onChange={handleRFChange}
                placeholder="e.g., 13.56e6"
                required
              />
            </label>
            <label>
              Te amplitude (eV)
              <input
                type="number"
                name="te_amplitude_ev"
                value={form.rf.te_amplitude_ev}
                onChange={handleRFChange}
                min={0}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Ne amplitude (m^-3)
              <input
                type="text"
                name="ne_amplitude"
                value={form.rf.ne_amplitude}
                onChange={handleRFChange}
                placeholder="e.g., 1e14"
                required
              />
            </label>
            <label>
              Vs amplitude (V)
              <input
                type="number"
                name="vs_amplitude_v"
                value={form.rf.vs_amplitude_v}
                onChange={handleRFChange}
                min={0}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>Sweep Settings</legend>
            <label>
              Sweep duration (s)
              <input
                type="text"
                name="total_time_s"
                value={form.time_range.total_time_s}
                onChange={handleTimeChange}
                placeholder="e.g., 0.1 or 1e-4"
                required
              />
            </label>
            <label>
              Time step (s)
              <input
                type="text"
                name="dt_s"
                value={form.time_range.dt_s}
                onChange={handleTimeChange}
                placeholder="e.g., 1e-8"
                required
              />
            </label>
            <div style={{
              marginTop: '10px',
              padding: '10px',
              backgroundColor: '#f5f5f5',
              borderRadius: '4px',
              fontSize: '13px'
            }}>
              <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#555' }}>
                RF采样建议 (基于频率 {(currentRfFreq / 1e6).toFixed(2)} MHz):
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {samplingOptions.map(option => {
                  const recommendedDt = calculateRecommendedDt(currentRfFreq, option.points)
                  return (
                    <button
                      key={option.points}
                      type="button"
                      onClick={() => {
                        setForm(prev => ({
                          ...prev,
                          time_range: {
                            ...prev.time_range,
                            dt_s: recommendedDt
                          }
                        }))
                      }}
                      style={{
                        padding: '6px 10px',
                        fontSize: '12px',
                        backgroundColor: form.time_range.dt_s === recommendedDt ? '#3b82f6' : '#fff',
                        color: form.time_range.dt_s === recommendedDt ? '#fff' : '#333',
                        border: '1px solid #ddd',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => {
                        if (form.time_range.dt_s !== recommendedDt) {
                          e.currentTarget.style.backgroundColor = '#e5e7eb'
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (form.time_range.dt_s !== recommendedDt) {
                          e.currentTarget.style.backgroundColor = '#fff'
                        }
                      }}
                    >
                      {option.label}<br/>
                      <span style={{ fontSize: '11px', opacity: 0.8 }}>
                        dt={recommendedDt}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Voltage Range</legend>
            <label>
              Start voltage (V)
              <input
                type="number"
                name="vp_initial"
                value={form.vp_initial}
                onChange={(e) => setForm((prev) => ({ ...prev, vp_initial: Number(e.target.value) }))}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              End voltage (V)
              <input
                type="number"
                name="vp_final"
                value={form.vp_final ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, vp_final: e.target.value ? Number(e.target.value) : null }))}
                step="any"
                inputMode="decimal"
                placeholder="Leave empty for floating potential"
              />
            </label>
            <label>
              电压阶梯 (RF周期数/步)
              <input
                type="text"
                name="voltage_step_rf_cycles"
                value={form.time_range.voltage_step_rf_cycles ?? ''}
                onChange={(e) => {
                  const value = e.target.value
                  setForm(prev => ({
                    ...prev,
                    time_range: {
                      ...prev.time_range,
                      voltage_step_rf_cycles: value ? value : null
                    }
                  }))
                }}
                placeholder="留空表示连续扫描，如: 10"
              />
              <span style={{ fontSize: '12px', color: '#666', marginTop: '4px', display: 'block' }}>
                每个电压步长持续的RF周期数。留空=连续线性扫描，填入数字(如10)=阶梯扫描
              </span>
            </label>
          </fieldset>

          <fieldset>
            <legend>Solver Settings</legend>
            <label>
              Integrator
              <select
                name="integrator"
                value={form.integrator}
                onChange={(e) => setForm((prev) => ({ ...prev, integrator: e.target.value as 'euler' | 'rk4' }))}
              >
                <option value="rk4">RK4 (recommended)</option>
                <option value="euler">Euler</option>
              </select>
            </label>
          </fieldset>
        </div>
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Running...' : 'Run simulation'}
        </button>
        {isLoading && progress > 0 && (
          <div style={{ marginTop: '1rem' }}>
            <div style={{ 
              width: '100%', 
              height: '20px', 
              backgroundColor: '#e0e0e0', 
              borderRadius: '10px',
              overflow: 'hidden'
            }}>
              <div style={{
                width: `${progress * 100}%`,
                height: '100%',
                backgroundColor: '#38bdf8',
                transition: 'width 0.3s ease'
              }} />
            </div>
            <div style={{ textAlign: 'center', marginTop: '0.5rem', fontSize: '0.9rem' }}>
              {Math.round(progress * 100)}% complete
            </div>
          </div>
        )}
      </form>

      {error && <div className="alert">{error}</div>}

      {result && (
        <>
          <div className="results">
            <h2>Derived metrics</h2>
            <div className="stats-grid">
              <article>
                <span className="label">Final probe potential (V)</span>
                <span className="value">
                  {Array.isArray(result.vp) && result.vp.length > 0
                    ? result.vp[result.vp.length - 1].toFixed(3)
                    : '--'}
                </span>
              </article>
              <article>
                <span className="label">Ion model</span>
                <span className="value">{modelLabel}</span>
              </article>
              <article>
                <span className="label">Simulation frequency (Hz)</span>
                <span className="value">{String(result.metadata?.frequency_hz ?? '--')}</span>
              </article>
            </div>
            {warnings && (
              <div className="alert">
                {warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            )}
            {savedFilePath && (
              <div className="alert success">
                数据文件已保存到 <code>{savedFilePath}</code>
              </div>
            )}
          </div>

          <div className="chart-card">
            <div className="chart-header">
              <h3>I-V Characteristic Curve</h3>
              {chartData.length > 0 && (
                <div style={{fontSize: '12px', color: '#888', marginBottom: '8px'}}>
                  📊 {chartData.length} points | Vp: [{Math.min(...chartData.map(d => d.vp)).toFixed(2)}, {Math.max(...chartData.map(d => d.vp)).toFixed(2)}] V | 
                  I: [{Math.min(...chartData.map(d => d.i_total)).toExponential(2)}, {Math.max(...chartData.map(d => d.i_total)).toExponential(2)}] A
                </div>
              )}
              <div className="chart-toggles">
                <label>
                  <input
                    type="checkbox"
                    checked={showElectron}
                    onChange={() => setShowElectron((prev) => !prev)}
                  />
                  Show Ie
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={showIon}
                    onChange={() => setShowIon((prev) => !prev)}
                  />
                  Show Ii
                </label>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart 
                data={chartData} 
                margin={{ left: 16, right: 16 }}
                key={chartData.length}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#233" />
                <XAxis 
                  dataKey="vp"
                  label={{ value: 'Probe Voltage Vp (V)', position: 'insideBottom', offset: -5 }}
                  allowDataOverflow={false}
                />
                <YAxis
                  label={{ value: 'Current (A)', angle: -90, position: 'insideLeft' }}
                  width={80}
                  allowDataOverflow={false}
                />
                <Tooltip />
                <Legend />
                <Line 
                  type="monotone" 
                  dataKey="i_total" 
                  stroke="#38bdf8" 
                  name="I_total" 
                  dot={false} 
                  strokeWidth={2}
                  animationDuration={0}
                  isAnimationActive={false}
                />
                {showElectron && (
                  <Line 
                    type="monotone" 
                    dataKey="ie" 
                    stroke="#f97316" 
                    name="Ie (electron)" 
                    dot={false} 
                    strokeWidth={2}
                    animationDuration={0}
                    isAnimationActive={false}
                  />
                )}
                {showIon && (
                  <Line 
                    type="monotone" 
                    dataKey="ii" 
                    stroke="#22c55e" 
                    name="Ii (ion)" 
                    dot={false} 
                    strokeWidth={2}
                    animationDuration={0}
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>

        </>
      )}
    </section>
  )
}
