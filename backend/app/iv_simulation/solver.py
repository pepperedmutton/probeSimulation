"""Numerical solvers for Langmuir probe I-V curves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import math
import numpy as np

from .core import GasType, estimate_vf, ion_mass, rf_modulate_parameter, debye_length, EPSILON_0
from .electron import ie_maxwellian
from .ion import IonModel, ii_current, ion_saturation_current


@dataclass(slots=True)
class DynamicIVResult:
    time: np.ndarray
    vp: np.ndarray
    ne: np.ndarray
    te_eV: np.ndarray
    vs: np.ndarray
    ie: np.ndarray
    ii: np.ndarray
    i_total: np.ndarray
    metadata: dict[str, Any]


@dataclass(slots=True)
class DynamicIVResult:
    time: np.ndarray
    vp: np.ndarray
    ne: np.ndarray
    te_eV: np.ndarray
    vs: np.ndarray
    ie: np.ndarray
    ii: np.ndarray
    i_total: np.ndarray
    metadata: dict[str, Any]


def compute_dynamic_iv(
    *,
    ne_base: float,
    te_ev_base: float,
    vs_base: float,
    gas_type: GasType,
    mi_custom: float | None,
    area: float,
    radius: float,
    length: float,
    capacitance: float,
    model: IonModel,
    frequency_hz: float,
    te_amplitude_ev: float,
    ne_amplitude: float,
    vs_amplitude_v: float,
    total_time_s: float,
    dt_s: float,
    vp_initial: float,
    vp_final: float | None = None,
    voltage_step_rf_cycles: float | None = None,
    integrator: Literal["euler", "rk4"] = "rk4",
) -> DynamicIVResult:
    """Time-stepping simulation of Langmuir probe with RF modulation.
    
    If vp_final is provided, performs a voltage sweep from vp_initial to vp_final.
    - If voltage_step_rf_cycles is None: continuous linear sweep
    - If voltage_step_rf_cycles is provided: staircase sweep with each step lasting that many RF cycles
    Otherwise, integrates the floating potential dynamics.
    """
    mi = ion_mass(gas_type, mi_custom)
    vf_guess = estimate_vf(vs_base, te_ev_base, gas_type)
    
    # Nyquist check
    nyquist_dt = 1.0 / (2.0 * frequency_hz)
    if dt_s > nyquist_dt:
        raise ValueError(f"Time step {dt_s:.2e} s violates Nyquist criterion (max {nyquist_dt:.2e} s for f={frequency_hz} Hz)")
    
    num_steps = int(total_time_s / dt_s)
    time_grid = np.arange(0, total_time_s, dt_s)
    if len(time_grid) > num_steps:
        time_grid = time_grid[:num_steps]
    
    vp_values = np.zeros_like(time_grid)
    ne_values = np.zeros_like(time_grid)
    te_values = np.zeros_like(time_grid)
    vs_values = np.zeros_like(time_grid)
    ie_values = np.zeros_like(time_grid)
    ii_values = np.zeros_like(time_grid)
    
    vp = vp_initial
    # Check if we're doing a voltage sweep
    voltage_sweep = vp_final is not None
    if voltage_sweep:
        if voltage_step_rf_cycles is not None and voltage_step_rf_cycles > 0:
            # Staircase sweep mode
            rf_period = 1.0 / frequency_hz
            step_duration = voltage_step_rf_cycles * rf_period  # seconds per voltage step
            num_voltage_steps = int(total_time_s / step_duration)
            voltage_step_size = (vp_final - vp_initial) / num_voltage_steps if num_voltage_steps > 0 else 0
            print(f"\n=== Staircase Voltage Sweep Mode ===")
            print(f"Vp range: {vp_initial:.2f}V → {vp_final:.2f}V")
            print(f"RF cycles per step: {voltage_step_rf_cycles:.1f} ({step_duration*1e6:.3f} μs)")
            print(f"Number of voltage steps: {num_voltage_steps}")
            print(f"Voltage step size: {voltage_step_size:.3f} V")
        else:
            # Continuous linear sweep
            voltage_rate = (vp_final - vp_initial) / total_time_s  # V/s
            voltage_step_rf_cycles = None  # Ensure it's None for continuous mode
            print(f"\n=== Continuous Voltage Sweep Mode ===")
            print(f"Vp range: {vp_initial:.2f}V → {vp_final:.2f}V")
            print(f"Sweep rate: {voltage_rate:.2f} V/s")
    
    print(f"Total time: {total_time_s}s, dt: {dt_s}s, steps: {num_steps}")
    print(f"RF frequency: {frequency_hz/1e6:.2f} MHz, period: {1.0/frequency_hz*1e6:.3f} μs")
    print(f"Plasma: ne={ne_base:.2e} m⁻³, Te={te_ev_base:.2f} eV")
    
    if voltage_sweep:
        rf_period = 1.0 / frequency_hz
        samples_per_rf_cycle = rf_period / dt_s
        nyquist_ratio = samples_per_rf_cycle / 2.0
        print(f"Time step dt: {dt_s*1e9:.3f} ns")
        print(f"Samples per RF cycle: {samples_per_rf_cycle:.1f} (Nyquist factor: {nyquist_ratio:.1f}x)")
        if nyquist_ratio < 1:
            print(f"⚠️  WARNING: Nyquist criterion NOT satisfied! Need dt < {rf_period/2.0:.2e} s")
        else:
            print(f"✓ Nyquist criterion satisfied - RF oscillations will be visible")
    
    # choose internal substep resolution: target samples per RF period
    target_samples_per_period = 60

    def sheath_capacitance(ne_local: float, te_ev_local: float, area_local: float, vp_local: float, vs_local: float) -> float:
        """Estimate a simple voltage-dependent sheath capacitance (F).

        We use Debye-length-based sheath thickness with a modest voltage dependence.
        This is a crude phenomenological model intended to introduce frequency-dependent
        response (smaller sheath -> larger C, and vice versa).
        """
        # Debye length (m)
        ld = debye_length(ne_local, te_ev_local)
        # normalized bias (positive when probe repels electrons)
        bias = max(vs_local - vp_local, 0.0)
        # add modest voltage dependence: sheath thickness grows slowly with sqrt(bias/Te)
        scale = 1.0 + math.sqrt(max(bias / max(te_ev_local, 1e-6), 0.0))
        d = max(ld * scale, ld * 0.1)
        return EPSILON_0 * max(area_local, 1e-18) / d
    def i_total_at(vp_local: float, time_local: float) -> float:
        """Compute total current (Ie + Ii) for a given probe voltage and time."""
        ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, time_local)
        te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, time_local)
        vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, time_local)
        ie_local = ie_maxwellian(vp_local, vs_mod, ne_mod, te_mod, area)
        ii_local = ii_current(
            vp=vp_local,
            vs=vs_mod,
            vf_guess=vf_guess,
            ne=ne_mod,
            te_ev=te_mod,
            mi=mi,
            area=area,
            radius=radius,
            length=length,
            model=model,
        )
        return ie_local + ii_local

    for idx, t in enumerate(time_grid):
        # If voltage sweep mode, set Vp directly from sweep and compute currents only
        if voltage_sweep:
            if voltage_step_rf_cycles is not None and voltage_step_rf_cycles > 0:
                # Staircase mode: calculate which voltage step we're in
                rf_period = 1.0 / frequency_hz
                step_duration = voltage_step_rf_cycles * rf_period
                step_index = int(t / step_duration)
                num_voltage_steps = int(total_time_s / step_duration)
                voltage_step_size = (vp_final - vp_initial) / num_voltage_steps if num_voltage_steps > 0 else 0
                vp = vp_initial + step_index * voltage_step_size
                # Clamp to final voltage
                vp = min(max(vp, min(vp_initial, vp_final)), max(vp_initial, vp_final))
            else:
                # Continuous linear sweep
                vp = vp_initial + voltage_rate * t
            
            # Directly sample at this time instant to show RF oscillations
            ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t)
            te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t)
            vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t)
            
            ie_step = ie_maxwellian(vp, vs_mod, ne_mod, te_mod, area)
            ii_step = ii_current(
                vp=vp, vs=vs_mod, vf_guess=vf_guess, ne=ne_mod, te_ev=te_mod,
                mi=mi, area=area, radius=radius, length=length, model=model,
            )
            ne_step = ne_mod
            te_step = te_mod
            vs_step = vs_mod
            
        else:
            # Floating potential mode - integrate dVp/dt = I/C
            # subdivide the user timestep to resolve RF if needed
            period = 1.0 / max(frequency_hz, 1e-12)
            sub_dt = min(dt_s, period / target_samples_per_period)
            nsub = max(1, int(math.ceil(dt_s / sub_dt)))
            sub_dt = dt_s / nsub

            # storage for reporting: we will record the state at the end of the full dt
            ie_step = 0.0
            ii_step = 0.0
            ne_step = 0.0
            te_step = 0.0
            vs_step = 0.0

            for s in range(nsub):
                t_sub = t + s * sub_dt
                ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t_sub)
                te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t_sub)
                vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t_sub)

                # compute instantaneous total capacitance (probe + sheath)
                cs = sheath_capacitance(ne_mod, te_mod, area, vp, vs_mod)
                c_total = max(capacitance + cs, 1e-24)

                # instantaneous total current function using local capacitance
                def f_local(vp_loc: float, t_loc: float) -> float:
                    # compute currents at vp_loc,t_loc
                    return i_total_at(vp_loc, t_loc)

                if integrator == "euler":
                    i_tot = f_local(vp, t_sub)
                    ie_inst = ie_maxwellian(vp, vs_mod, ne_mod, te_mod, area)
                    ii_inst = ii_current(
                        vp=vp,
                        vs=vs_mod,
                        vf_guess=vf_guess,
                        ne=ne_mod,
                        te_ev=te_mod,
                        mi=mi,
                        area=area,
                        radius=radius,
                        length=length,
                        model=model,
                    )
                    vp = vp + (i_tot / c_total) * sub_dt
                else:
                    # RK4 over the substep using dynamic capacitance evaluated at each sub-evaluation
                    def f_for_rk(vp_loc: float, t_loc: float) -> float:
                        # use instantaneous sheath capacitance for the given vp_loc and time
                        ne_l = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t_loc)
                        te_l = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t_loc)
                        vs_l = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t_loc)
                        cs_l = sheath_capacitance(ne_l, te_l, area, vp_loc, vs_l)
                        c_tot_l = max(capacitance + cs_l, 1e-24)
                        # return dVp/dt
                        return i_total_at(vp_loc, t_loc) / c_tot_l

                    k1 = f_for_rk(vp, t_sub)
                    k2 = f_for_rk(vp + 0.5 * sub_dt * k1, t_sub + 0.5 * sub_dt)
                    k3 = f_for_rk(vp + 0.5 * sub_dt * k2, t_sub + 0.5 * sub_dt)
                    k4 = f_for_rk(vp + sub_dt * k3, t_sub + sub_dt)
                    vp = vp + (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0)

                    # compute currents at start of substep for reporting
                    ie_inst = ie_maxwellian(vp - (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0), vs_mod, ne_mod, te_mod, area)
                    ii_inst = ii_current(
                        vp=vp - (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0),
                        vs=vs_mod,
                        vf_guess=vf_guess,
                        ne=ne_mod,
                        te_ev=te_mod,
                        mi=mi,
                        area=area,
                        radius=radius,
                        length=length,
                        model=model,
                    )

                # accumulate last substep values (will end up being end-of-dt values)
                ie_step = ie_inst
                ii_step = ii_inst
                ne_step = ne_mod
                te_step = te_mod
                vs_step = vs_mod

        # record end-of-dt quantities
        vp_values[idx] = vp
        ne_values[idx] = ne_step
        te_values[idx] = te_step
        vs_values[idx] = vs_step
        
        # Print progress every 10%
        if idx % max(1, num_steps // 10) == 0:
            progress_pct = (idx / num_steps) * 100
            print(f"Progress: {progress_pct:.1f}% | t={time_grid[idx]:.6f}s | Vp={vp:.3f}V | Ie={ie_step:.6e}A | Ii={ii_step:.6e}A")
        ie_values[idx] = ie_step
        ii_values[idx] = ii_step
    
    total = ie_values + ii_values
    
    # For voltage sweep mode, downsample to max 100k points for efficient plotting
    if voltage_sweep and len(time_grid) > 100000:
        downsample_factor = len(time_grid) // 100000
        indices = np.arange(0, len(time_grid), downsample_factor)
        time_grid = time_grid[indices]
        vp_values = vp_values[indices]
        ne_values = ne_values[indices]
        te_values = te_values[indices]
        vs_values = vs_values[indices]
        ie_values = ie_values[indices]
        ii_values = ii_values[indices]
        total = total[indices]
    
    metadata: dict[str, Any] = {
        "model": model.value,
        "frequency_hz": frequency_hz,
        "nyquist_dt_s": nyquist_dt,
        "actual_dt_s": dt_s,
        "capacitance_f": capacitance,
        "integrator": integrator,
        "voltage_sweep": voltage_sweep,
        "vp_initial": vp_initial,
        "vp_final": vp_final if voltage_sweep else None,
    }
    return DynamicIVResult(
        time=time_grid,
        vp=vp_values,
        ne=ne_values,
        te_eV=te_values,
        vs=vs_values,
        ie=ie_values,
        ii=ii_values,
        i_total=total,
        metadata=metadata,
    )


async def compute_dynamic_iv_streaming(
    *,
    ne_base: float,
    te_ev_base: float,
    vs_base: float,
    gas_type: GasType,
    mi_custom: float | None,
    area: float,
    radius: float,
    length: float,
    capacitance: float,
    model: IonModel,
    frequency_hz: float,
    te_amplitude_ev: float,
    ne_amplitude: float,
    vs_amplitude_v: float,
    total_time_s: float,
    dt_s: float,
    vp_initial: float,
    vp_final: float | None = None,
    voltage_step_rf_cycles: float | None = None,
    integrator: Literal["euler", "rk4"] = "rk4",
    chunk_size: int = 1000,
):
    """Streaming version that yields chunks of data as simulation progresses."""
    import asyncio
    
    print(f"\n{'🔧 '*30}")
    print(f"compute_dynamic_iv_streaming() STARTED")
    print(f"   dt_s = {dt_s} (type: {type(dt_s)})")
    print(f"   total_time_s = {total_time_s}")
    print(f"   frequency_hz = {frequency_hz}")
    print(f"{'🔧 '*30}\n")
    
    mi = ion_mass(gas_type, mi_custom)
    vf_guess = estimate_vf(vs_base, te_ev_base, gas_type)
    
    # Nyquist check
    nyquist_dt = 1.0 / (2.0 * frequency_hz)
    print(f"Nyquist check: dt_s={dt_s}, nyquist_dt={nyquist_dt}")
    if dt_s > nyquist_dt:
        raise ValueError(f"Time step {dt_s:.2e} s violates Nyquist criterion (max {nyquist_dt:.2e} s for f={frequency_hz} Hz)")
    
    num_steps = int(total_time_s / dt_s)
    print(f"Calculated num_steps = {num_steps}")
    time_grid = np.arange(0, total_time_s, dt_s)
    if len(time_grid) > num_steps:
        time_grid = time_grid[:num_steps]
    print(f"Time grid length = {len(time_grid)}")
    
    vp = vp_initial
    voltage_sweep = vp_final is not None
    if voltage_sweep:
        if voltage_step_rf_cycles is not None and voltage_step_rf_cycles > 0:
            voltage_rate = None  # Not used in staircase mode
        else:
            voltage_rate = (vp_final - vp_initial) / total_time_s
    
    target_samples_per_period = 60
    
    def sheath_capacitance(ne_local: float, te_ev_local: float, area_local: float, vp_local: float, vs_local: float) -> float:
        ld = debye_length(ne_local, te_ev_local)
        bias = max(vs_local - vp_local, 0.0)
        scale = 1.0 + math.sqrt(max(bias / max(te_ev_local, 1e-6), 0.0))
        d = max(ld * scale, ld * 0.1)
        return EPSILON_0 * max(area_local, 1e-18) / d
    
    def i_total_at(vp_local: float, time_local: float) -> float:
        ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, time_local)
        te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, time_local)
        vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, time_local)
        ie_local = ie_maxwellian(vp_local, vs_mod, ne_mod, te_mod, area)
        ii_local = ii_current(
            vp=vp_local, vs=vs_mod, vf_guess=vf_guess, ne=ne_mod, te_ev=te_mod,
            mi=mi, area=area, radius=radius, length=length, model=model,
        )
        return ie_local + ii_local
    
    # Accumulate data in chunks
    chunk_times = []
    chunk_vps = []
    chunk_nes = []
    chunk_tes = []
    chunk_vss = []
    chunk_ies = []
    chunk_iis = []
    
    for idx, t in enumerate(time_grid):
        if voltage_sweep:
            if voltage_step_rf_cycles is not None and voltage_step_rf_cycles > 0:
                # Staircase mode
                rf_period = 1.0 / frequency_hz
                step_duration = voltage_step_rf_cycles * rf_period
                step_index = int(t / step_duration)
                num_voltage_steps = int(total_time_s / step_duration)
                voltage_step_size = (vp_final - vp_initial) / num_voltage_steps if num_voltage_steps > 0 else 0
                vp = vp_initial + step_index * voltage_step_size
                vp = min(max(vp, min(vp_initial, vp_final)), max(vp_initial, vp_final))
            else:
                # Continuous linear sweep
                vp = vp_initial + voltage_rate * t
            
            # Directly sample at this instant to show RF oscillations
            ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t)
            te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t)
            vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t)
            
            ie_step = ie_maxwellian(vp, vs_mod, ne_mod, te_mod, area)
            ii_step = ii_current(
                vp=vp, vs=vs_mod, vf_guess=vf_guess, ne=ne_mod, te_ev=te_mod,
                mi=mi, area=area, radius=radius, length=length, model=model,
            )
            ne_step = ne_mod
            te_step = te_mod
            vs_step = vs_mod
        else:
            # Floating potential integration logic (same as before)
            period = 1.0 / max(frequency_hz, 1e-12)
            sub_dt = min(dt_s, period / target_samples_per_period)
            nsub = max(1, int(math.ceil(dt_s / sub_dt)))
            sub_dt = dt_s / nsub
            
            ie_step = 0.0
            ii_step = 0.0
            ne_step = 0.0
            te_step = 0.0
            vs_step = 0.0
            
            for s in range(nsub):
                t_sub = t + s * sub_dt
                ne_mod = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t_sub)
                te_mod = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t_sub)
                vs_mod = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t_sub)
                cs = sheath_capacitance(ne_mod, te_mod, area, vp, vs_mod)
                c_total = max(capacitance + cs, 1e-24)
                
                if integrator == "euler":
                    i_tot = i_total_at(vp, t_sub)
                    ie_inst = ie_maxwellian(vp, vs_mod, ne_mod, te_mod, area)
                    ii_inst = ii_current(
                        vp=vp, vs=vs_mod, vf_guess=vf_guess, ne=ne_mod, te_ev=te_mod,
                        mi=mi, area=area, radius=radius, length=length, model=model,
                    )
                    vp = vp + (i_tot / c_total) * sub_dt
                else:
                    def f_for_rk(vp_loc: float, t_loc: float) -> float:
                        ne_l = rf_modulate_parameter(ne_base, ne_amplitude, frequency_hz, t_loc)
                        te_l = rf_modulate_parameter(te_ev_base, te_amplitude_ev, frequency_hz, t_loc)
                        vs_l = rf_modulate_parameter(vs_base, vs_amplitude_v, frequency_hz, t_loc)
                        cs_l = sheath_capacitance(ne_l, te_l, area, vp_loc, vs_l)
                        c_tot_l = max(capacitance + cs_l, 1e-24)
                        return i_total_at(vp_loc, t_loc) / c_tot_l
                    
                    k1 = f_for_rk(vp, t_sub)
                    k2 = f_for_rk(vp + 0.5 * sub_dt * k1, t_sub + 0.5 * sub_dt)
                    k3 = f_for_rk(vp + 0.5 * sub_dt * k2, t_sub + 0.5 * sub_dt)
                    k4 = f_for_rk(vp + sub_dt * k3, t_sub + sub_dt)
                    vp = vp + (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0)
                    ie_inst = ie_maxwellian(vp - (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0), vs_mod, ne_mod, te_mod, area)
                    ii_inst = ii_current(
                        vp=vp - (sub_dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0),
                        vs=vs_mod, vf_guess=vf_guess, ne=ne_mod, te_ev=te_mod,
                        mi=mi, area=area, radius=radius, length=length, model=model,
                    )
                
                ie_step = ie_inst
                ii_step = ii_inst
                ne_step = ne_mod
                te_step = te_mod
                vs_step = vs_mod
        
        # Accumulate data
        chunk_times.append(float(t))
        chunk_vps.append(float(vp))
        chunk_nes.append(float(ne_step))
        chunk_tes.append(float(te_step))
        chunk_vss.append(float(vs_step))
        chunk_ies.append(float(ie_step))
        chunk_iis.append(float(ii_step))
        
        # Send chunk when ready
        if len(chunk_times) >= chunk_size or idx == len(time_grid) - 1:
            # NO downsampling - we need all points to preserve RF oscillations
            # The frontend will handle downsampling for display if needed
            
            chunk_data = {
                "time": chunk_times,
                "vp": chunk_vps,
                "ne": chunk_nes,
                "te_eV": chunk_tes,
                "vs": chunk_vss,
                "ie": chunk_ies,
                "ii": chunk_iis,
                "i_total": [ie + ii for ie, ii in zip(chunk_ies, chunk_iis)],
                "progress": (idx + 1) / len(time_grid),
            }
            
            yield chunk_data
            await asyncio.sleep(0)  # Allow other tasks to run
            
            # Reset chunk buffers
            chunk_times = []
            chunk_vps = []
            chunk_nes = []
            chunk_tes = []
            chunk_vss = []
            chunk_ies = []
            chunk_iis = []
    
    # Send final metadata
    metadata = {
        "complete": True,
        "model": model.value,
        "frequency_hz": frequency_hz,
        "voltage_sweep": voltage_sweep,
        "vp_initial": vp_initial,
        "vp_final": vp_final if voltage_sweep else None,
    }
    yield {"metadata": metadata}
