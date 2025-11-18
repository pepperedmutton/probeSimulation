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
import { fetchDynamicIV } from '../api'

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
  probe: DynamicIVRequest['probe']
  rf: DynamicIVRequest['rf']
  time_range: DynamicIVRequest['time_range']
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
    area: 1e-6,
    radius: 1e-3,
    length: 5e-3,
    capacitance: 1e-12,
  },
  rf: {
    frequency_hz: 13.56e6,
    te_amplitude_ev: 0.5,
    ne_amplitude: 1e14,
    vs_amplitude_v: 2.0,
  },
  time_range: {
    total_time_s: 0.1,
    dt_s: 1e-8,
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
  const [form, setForm] = useState<DynamicIVForm>(DEFAULT_FORM)
  const [result, setResult] = useState<DynamicIVResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [showElectron, setShowElectron] = useState(true)
  const [showIon, setShowIon] = useState(true)
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

  const chartData = useMemo<ChartDatum[]>(() => {
    if (!result) return []
    return result.time.map((time, idx) => {
      const vp = result.vp[idx]
      const ie = result.ie[idx]
      const ii = result.ii[idx]
      const total = result.i_total[idx]
      const ne = result.ne[idx]
      const te_eV = result.te_eV[idx]
      const vs = result.vs[idx]

      return {
        time,
        vp,
        ie,
        ii,
        i_total: total,
        ne,
        te_eV,
        vs,
      }
    })
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
        [name]: Number(value),
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
        [name]: Number(value),
      },
    }))
  }

  const handleTimeChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setForm((prev) => ({
      ...prev,
      time_range: {
        ...prev.time_range,
        [name]: Number(value),
      },
    }))
  }

  // model selection handled inline via form state

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setIsLoading(true)
    setError(null)
    try {
      const payloadBody: DynamicIVRequest = {
        plasma: {
          ne: form.plasma.neMantissa * Math.pow(10, form.plasma.neExponent),
          te_eV: form.plasma.te_eV,
          vs: form.plasma.vs,
          gas_type: form.plasma.gas_type,
          mi_custom: form.plasma.mi_custom,
        },
        probe: form.probe,
        rf: form.rf,
        time_range: form.time_range,
        vp_initial: form.vp_initial,
        vp_final: form.vp_final,
        model: form.model,
        integrator: form.integrator,
      }
      const payload = await fetchDynamicIV<DynamicIVResponse>(payloadBody)
      setResult(payload)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Simulation failed'
      setError(message)
      setResult(null)
    } finally {
      setIsLoading(false)
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
                type="number"
                name="area"
                value={form.probe.area}
                onChange={handleProbeChange}
                min={1e-10}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Radius (m)
              <input
                type="number"
                name="radius"
                value={form.probe.radius}
                onChange={handleProbeChange}
                min={1e-5}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Length (m)
              <input
                type="number"
                name="length"
                value={form.probe.length}
                onChange={handleProbeChange}
                min={1e-5}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Capacitance (F)
              <input
                type="number"
                name="capacitance"
                value={form.probe.capacitance}
                onChange={handleProbeChange}
                min={1e-15}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>RF Modulation</legend>
            <label>
              Frequency (Hz)
              <input
                type="number"
                name="frequency_hz"
                value={form.rf.frequency_hz}
                onChange={handleRFChange}
                min={1}
                step="any"
                inputMode="decimal"
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
                type="number"
                name="ne_amplitude"
                value={form.rf.ne_amplitude}
                onChange={handleRFChange}
                min={0}
                step="any"
                inputMode="decimal"
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
                type="number"
                name="total_time_s"
                value={form.time_range.total_time_s}
                onChange={handleTimeChange}
                min={1e-10}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
            <label>
              Time step (s)
              <input
                type="number"
                name="dt_s"
                value={form.time_range.dt_s}
                onChange={handleTimeChange}
                min={1e-15}
                step="any"
                inputMode="decimal"
                required
              />
            </label>
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
                placeholder="Leave empty for floating"
                required
              />
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
          </div>

          <div className="chart-card">
            <div className="chart-header">
              <h3>I-V Characteristic Curve</h3>
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
              <LineChart data={chartData} margin={{ left: 16, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#233" />
                <XAxis 
                  dataKey="vp" 
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  label={{ value: 'Probe Voltage Vp (V)', position: 'insideBottom', offset: -5 }} 
                />
                <YAxis
                  label={{ value: 'Current (A)', angle: -90, position: 'insideLeft' }}
                  width={80}
                />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="i_total" stroke="#38bdf8" name="I_total" dot={false} strokeWidth={2} />
                {showElectron && (
                  <Line type="monotone" dataKey="ie" stroke="#f97316" name="Ie (electron)" dot={false} strokeWidth={2} />
                )}
                {showIon && (
                  <Line type="monotone" dataKey="ii" stroke="#22c55e" name="Ii (ion)" dot={false} strokeWidth={2} />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="chart-card">
            <div className="chart-header">
              <h3>Time Evolution</h3>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData} margin={{ left: 16, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#233" />
                <XAxis dataKey="time" label={{ value: 'Time (s)', position: 'insideBottom', offset: -5 }} />
                <YAxis
                  label={{ value: 'Current (A)', angle: -90, position: 'insideLeft' }}
                  width={80}
                />
                <YAxis
                  yAxisId="voltage"
                  orientation="right"
                  label={{ value: 'Voltage (V)', angle: 90, position: 'insideRight' }}
                  width={80}
                />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="i_total" stroke="#38bdf8" name="I_total" dot={false} />
                <Line type="monotone" dataKey="vp" stroke="#ef4444" name="Vp" dot={false} yAxisId="voltage" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  )
}
