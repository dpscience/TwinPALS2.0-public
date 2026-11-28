# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

from __future__ import annotations

import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Curve(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    x_unit: str
    y_unit: str
    semantics: str
    points: list[tuple[float, float]] = Field(max_length=20000)

    @model_validator(mode="after")
    def validate_points(self):
        optical = self.name in ('refractive_index','absorption_length','quantum_efficiency','reflectivity','transmittance','cathode_n','cathode_k') or self.name.startswith('emission')
        if optical and self.x_unit not in ('nm','eV'):
            raise ValueError('Optical curves use wavelength in nm or photon energy in eV')
        if self.name.startswith('emission') and self.y_unit in ('1/nm','1/eV') and self.y_unit != '1/'+self.x_unit:
            raise ValueError('Emission density units must match the wavelength or energy axis')
        xs = [p[0] for p in self.points]
        if len(xs) < 2 and self.name not in ('cathode_n', 'cathode_k'):
            raise ValueError("A curve requires at least two points")
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError("Curve x values must be strictly increasing and unique")
        if xs and self.x_unit in ("eV", "nm", "keV", "MeV") and min(xs) <= 0:
            raise ValueError("Energy/wavelength values must be positive")
        ys = [p[1] for p in self.points]
        if self.name == 'gain_hv' and (self.x_unit != 'V' or self.y_unit != '1' or min(xs)<=0 or min(ys)<=0):
            raise ValueError('PMT gain curves require positive voltage magnitudes in V and positive dimensionless gain.')
        if self.name in ("quantum_efficiency", "reflectivity", "transmittance"):
            if self.y_unit not in ("1", "probability", "%", "percent"):
                raise ValueError("Probability curves require explicit unit 1 or %")
            upper=100 if self.y_unit in ("%","percent") else 1
            if not all(0 <= y <= upper for y in ys):
                raise ValueError(f"Probability values must be in [0,{upper}] for {self.y_unit}")
        if self.name=="refractive_index" and self.y_unit not in ("1","dimensionless"):
            raise ValueError("Refractive index must be dimensionless (unit 1)")
        if self.name=="absorption_length" and self.y_unit not in ("nm","um","µm","μm","mm","cm","m"):
            raise ValueError("Absorption length requires an explicit length unit")
        if self.name.startswith("emission") and self.y_unit not in ("1","relative","1/eV","1/nm"):
            raise ValueError("Emission must declare relative ordinates or photon spectral-density units")
        if self.name in ("absorption_length", "refractive_index") and min(ys) <= 0:
            raise ValueError("Optical lengths and refractive index must be positive")
        if self.name.startswith("emission") and (min(ys) < 0 or max(ys) <= 0):
            raise ValueError("Emission must be nonnegative with nonzero support")
        return self


MaterialCategory = Literal['scintillator','coupling','window','pmt','digitizer','wrapping','sample','foil','shield']


class Entry(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=200)
    category: MaterialCategory
    builtin: bool = False
    description: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    curves: list[Curve] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_properties(self):
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Entry values must be finite")
            if isinstance(value, dict):
                for child in value.values(): finite(child)
            elif isinstance(value, (list, tuple)):
                for child in value: finite(child)
        finite(self.properties)
        finite(self.provenance)
        components=self.properties.get('components')
        if components is not None:
            if not isinstance(components,list) or len(components)>3 or any(not isinstance(c,dict) for c in components):
                raise ValueError('Scintillation components must be a list with at most three objects')
            for component in components:
                if not isinstance(component.get('curve'),str) or not component['curve'].startswith('emission'):
                    raise ValueError('Each scintillation component must name its emission curve')
                for key in ('fraction','rise_time_ns','decay_time_ns'):
                    value=component.get(key)
                    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
                        raise ValueError(f'Component {key} must be a finite number')
        if self.category == 'pmt' and self.properties.get('cathode_reflections'):
            for curve in self.curves:
                if curve.name in ('cathode_n', 'cathode_k'):
                    if len(curve.points) < 2:
                        raise ValueError("Enabled cathode optics require at least two points per curve")
                    minimum = min(y for _, y in curve.points)
                    if curve.y_unit not in ('1', 'dimensionless') or minimum < 0 or (curve.name == 'cathode_n' and minimum == 0):
                        raise ValueError('Cathode optics require dimensionless n > 0 and k ≥ 0.')
        if len({c.name for c in self.curves}) != len(self.curves):
            raise ValueError("Curve names must be unique in one entry")
        for key, value in self.properties.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Non-finite property: {key}")
        numeric = ("density_g_cm3", "light_yield_per_MeV", "decay_time_ns", "absorption_length_mm", "refractive_index", "rise_time_ns", "resolution_scale", "reflectivity", "sigma_alpha_rad", "birks_mm_per_MeV")
        for key in numeric:
            if key in self.properties and (not isinstance(self.properties[key], (int,float)) or isinstance(self.properties[key], bool)):
                raise ValueError(f"{key} must be a scalar number; use a named curve for spectral values")
        for key in ("density_g_cm3", "light_yield_per_MeV", "decay_time_ns", "absorption_length_mm", "refractive_index"):
            if key in self.properties and float(self.properties[key]) <= 0:
                raise ValueError(f"{key} must be positive")
        if "rise_time_ns" in self.properties and float(self.properties["rise_time_ns"]) < 0:
            raise ValueError("rise_time_ns cannot be negative")
        if "resolution_scale" in self.properties and not 0<=float(self.properties["resolution_scale"])<=10:
            raise ValueError("resolution_scale must be in [0,10]")
        for key in ('reflectivity','sigma_alpha_rad'):
            if key in self.properties and not 0<=self.properties[key]<=1:
                raise ValueError(f'{key} must be in [0,1]')
        return self

