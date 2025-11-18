"""Ion collection models for Langmuir probes."""

from __future__ import annotations

import enum
import math

from .core import ELEMENTARY_CHARGE, debye_length, ion_sound_speed, te_ev_to_j


class IonModel(str, enum.Enum):
    OML = "OML"
    ABR = "ABR"
    BRL = "BRL"
    CHILD_LANGMUIR = "ChildLangmuir"


def ion_saturation_current(
    ne: float,
    te_ev: float,
    mi: float,
    area: float,
    alpha: float = 0.6,
) -> float:
    """Return Bohm ion-saturation current (negative sign applied later)."""
    if ne <= 0 or area <= 0:
        return 0.0
    cs = ion_sound_speed(te_ev, mi)
    return alpha * ELEMENTARY_CHARGE * area * ne * cs


def _cylindrical_area(radius: float, length: float) -> float:
    return max(2.0 * math.pi * max(radius, 0.0) * max(length, 0.0), 0.0)


def ii_oml(
    vp: float,
    vs: float,
    ne: float,
    mi: float,
    radius: float,
    length: float,
) -> float:
    """Orbital-motion-limited ion current for a cylindrical probe."""
    bias = vs - vp
    if bias <= 0 or ne <= 0:
        return 0.0
    area = _cylindrical_area(radius, length)
    if area <= 0 or mi <= 0:
        return 0.0
    velocity = math.sqrt(2.0 * ELEMENTARY_CHARGE * bias / mi)
    return -ELEMENTARY_CHARGE * ne * area * velocity


def _geometry_factor(radius: float, te_ev: float, ne: float, scale: float) -> float:
    """Simple logarithmic factor mimicking ξ_p dependence."""
    ld = debye_length(ne, te_ev)
    if ld <= 0:
        return 1.0
    xi = max(radius, 1e-6) / ld
    return 1.0 + scale * math.log1p(xi)


def ii_abr(
    vp: float,
    vs: float,
    ne: float,
    mi: float,
    radius: float,
    length: float,
    te_ev: float,
) -> float:
    return _geometry_factor(radius, te_ev, ne, 0.1) * ii_oml(vp, vs, ne, mi, radius, length)


def ii_brl(
    vp: float,
    vs: float,
    ne: float,
    mi: float,
    radius: float,
    length: float,
    te_ev: float,
) -> float:
    return _geometry_factor(radius, te_ev, ne, 0.2) * ii_oml(vp, vs, ne, mi, radius, length)


def ii_child_langmuir(
    vp: float,
    vf: float,
    area: float,
) -> float:
    """Simplified Child-Langmuir scaling (placeholder)."""
    if vp >= vf:
        return 0.0
    delta = vf - vp
    k_cl = max(area, 1e-12) ** 0.25  # weak area dependence to keep units reasonable
    i_43 = k_cl * (delta**1.5)
    return -abs(i_43) ** (3.0 / 4.0)


def ii_current(
    vp: float,
    vs: float,
    vf_guess: float,
    ne: float,
    te_ev: float,
    mi: float,
    area: float,
    radius: float,
    length: float,
    model: IonModel,
) -> float:
    """Dispatch to the requested ion collection model."""
    if model == IonModel.OML:
        return ii_oml(vp, vs, ne, mi, radius, length)
    if model == IonModel.ABR:
        return ii_abr(vp, vs, ne, mi, radius, length, te_ev)
    if model == IonModel.BRL:
        return ii_brl(vp, vs, ne, mi, radius, length, te_ev)
    if model == IonModel.CHILD_LANGMUIR:
        return ii_child_langmuir(vp, vf_guess, area)
    return -ion_saturation_current(ne, te_ev, mi, area)
