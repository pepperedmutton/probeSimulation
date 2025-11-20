"""Pydantic schemas for the Langmuir I-V API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .ion import IonModel


class PlasmaParams(BaseModel):
    ne: float = Field(..., gt=0, description="Electron density [m^-3]")
    te_eV: float = Field(..., gt=0, description="Electron temperature [eV]")
    vs: float = Field(..., description="Space (plasma) potential [V]")
    gas_type: Literal["H", "Ar", "custom"] = Field("Ar")
    mi_custom: float | None = Field(None, description="Ion mass [kg] when gas_type=custom")

    @field_validator("mi_custom")
    @classmethod
    def _check_mass(cls, value: float | None, info):  # type: ignore[override]
        if info.data.get("gas_type") == "custom" and (value is None or value <= 0):
            raise ValueError("mi_custom must be provided for gas_type=custom")
        return value


class ProbeParams(BaseModel):
    area: float = Field(..., gt=0, description="Exposed area [m^2]")
    radius: float = Field(..., gt=0, description="Probe radius [m]")
    length: float = Field(..., gt=0, description="Probe length [m]")
    capacitance: float = Field(1e-12, gt=0, description="Probe capacitance [F]")


# Static sweep schemas removed — dynamic time-domain API only


class RFParams(BaseModel):
    frequency_hz: float = Field(..., gt=0, description="RF frequency [Hz]")
    te_amplitude_ev: float = Field(0.0, ge=0, description="Amplitude of Te modulation [eV]")
    ne_amplitude: float = Field(0.0, ge=0, description="Amplitude of ne modulation [m^-3]")
    vs_amplitude_v: float = Field(0.0, ge=0, description="Amplitude of Vs modulation [V]")


class TimeParams(BaseModel):
    total_time_s: float = Field(..., gt=0, description="Total simulation time [s]")
    dt_s: float = Field(..., gt=0, description="Time step [s]")
    voltage_step_rf_cycles: float | None = Field(
        None, 
        ge=0, 
        description="Number of RF cycles per voltage step (for staircase sweep). If None, uses continuous sweep."
    )

    @field_validator("dt_s")
    @classmethod
    def _check_dt(cls, value: float, info):  # type: ignore[override]
        total_time = info.data.get("total_time_s")
        if total_time is not None and value > total_time:
            raise ValueError("dt_s must be less than total_time_s")
        return value


class IVDynamicRequest(BaseModel):
    plasma: PlasmaParams
    probe: ProbeParams
    rf: RFParams
    time_range: TimeParams
    vp_initial: float = Field(..., description="Initial probe potential [V]")
    vp_final: float | None = Field(None, description="Final probe potential [V] for voltage sweep")
    model: IonModel = Field(IonModel.ABR)
    integrator: Literal["euler", "rk4"] = Field("rk4", description="Time integrator to use")


class IVDynamicResponse(BaseModel):
    time: list[float]
    vp: list[float]
    ne: list[float]
    te_eV: list[float]
    vs: list[float]
    ie: list[float]
    ii: list[float]
    i_total: list[float]
    metadata: dict | None = None
