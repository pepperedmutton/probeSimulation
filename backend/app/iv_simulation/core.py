"""Core physical helpers for Langmuir I-V modelling."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Literal


ELEMENTARY_CHARGE = 1.602176634e-19  # Coulombs
KBOLTZMANN = 1.380649e-23  # J/K
ELECTRON_MASS = 9.10938356e-31  # kg
EPSILON_0 = 8.8541878128e-12  # F/m
PROTON_MASS = 1.67262192369e-27  # kg
AMU = 1.66053906660e-27  # kg

GasType = Literal["H", "Ar", "custom"]


def te_ev_to_j(te_ev: float) -> float:
    """Convert electron temperature from eV to Joules."""
    return max(te_ev, 0.0) * ELEMENTARY_CHARGE


def debye_length(ne: float, te_ev: float) -> float:
    """Return Debye length in meters."""
    ne_safe = max(ne, 1e6)
    te_joules = te_ev_to_j(te_ev)
    if te_joules <= 0:
        return 1e-6
    return math.sqrt(EPSILON_0 * te_joules / (ne_safe * ELEMENTARY_CHARGE**2))


def ion_sound_speed(te_ev: float, mi: float) -> float:
    """Ion acoustic speed using Te only (cold ions assumption)."""
    te_joules = te_ev_to_j(te_ev)
    if te_joules <= 0 or mi <= 0:
        return 0.0
    return math.sqrt(te_joules / mi)


@lru_cache(maxsize=None)
def ion_mass(gas_type: GasType, mi_custom: float | None = None) -> float:
    """Return ion mass in kg based on gas type."""
    if gas_type == "H":
        return PROTON_MASS
    if gas_type == "Ar":
        return 39.948 * AMU
    if gas_type == "custom" and mi_custom is not None and mi_custom > 0:
        return mi_custom
    raise ValueError("Unsupported gas_type or missing Mi_custom")


def estimate_vf(vs: float, te_ev: float, gas_type: GasType) -> float:
    """Rough floating-potential estimate using Chen's rule-of-thumb."""
    if te_ev <= 0:
        return vs
    if gas_type == "H":
        return vs - 3.5 * te_ev
    if gas_type == "Ar":
        return vs - 5.4 * te_ev
    return vs - 4.5 * te_ev


def rf_modulate_parameter(base: float, amplitude: float, frequency: float, time: float) -> float:
    """Apply sinusoidal modulation to a parameter."""
    return base + amplitude * math.sin(2.0 * math.pi * frequency * time)
