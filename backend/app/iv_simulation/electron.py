"""Electron branch utilities."""

from __future__ import annotations

import math

from .core import ELECTRON_MASS, ELEMENTARY_CHARGE, te_ev_to_j


def electron_saturation_current(ne: float, te_ev: float, area: float) -> float:
    """Return electron saturation current (positive)."""
    te_joules = te_ev_to_j(te_ev)
    if te_joules <= 0 or ne <= 0 or area <= 0:
        return 0.0
    thermal_factor = math.sqrt(te_joules / (2.0 * math.pi * ELECTRON_MASS))
    return ELEMENTARY_CHARGE * area * ne * thermal_factor


def ie_maxwellian(vp: float, vs: float, ne: float, te_ev: float, area: float) -> float:
    """Maxwell-Boltzmann electron current with soft saturation."""
    ies = electron_saturation_current(ne, te_ev, area)
    te_joules = te_ev_to_j(te_ev)
    if te_joules <= 0 or ies <= 0:
        return 0.0

    exponent = ELEMENTARY_CHARGE * (vp - vs) / te_joules
    exponent = max(min(exponent, 50.0), -50.0)
    current = ies * math.exp(exponent)

    if vp > vs:
        delta = vp - vs
        saturation = 1.0 + 0.2 * (1.0 - math.exp(-delta / max(te_ev, 1e-6)))
        return ies * saturation
    return current
