# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Reference-only Module 1 setup; material properties live in the database."""
from typing import Literal
from pydantic import Field, model_validator
from .models import StrictModel


class Dimensions(StrictModel):
    length_mm: float = Field(27.9, ge=.01, le=500)
    diameter_mm: float = Field(40, gt=0, le=1000)
    front_diameter_mm: float = Field(19, gt=0, le=1000)
    rear_diameter_mm: float = Field(40, gt=0, le=1000)
    width_mm: float = Field(40, gt=0, le=1000)
    height_mm: float = Field(40, gt=0, le=1000)
    front_width_mm: float = Field(19, gt=0, le=1000)
    front_height_mm: float = Field(19, gt=0, le=1000)
    rear_width_mm: float = Field(40, gt=0, le=1000)
    rear_height_mm: float = Field(40, gt=0, le=1000)


class Wrapping(StrictModel):
    enabled: bool = True
    side_mm: float = Field(.5, gt=0, le=100)
    front_mm: float = Field(.4, ge=0, le=100)


class Detector(StrictModel):
    id: Literal['A', 'B']
    shape: Literal['cone', 'cylinder', 'box', 'pyramid'] = 'cone'
    dimensions: Dimensions = Field(default_factory=Dimensions)
    distance_mm: float = Field(30, gt=0, le=10000)
    azimuth_deg: float = Field(0, ge=-360, le=360)
    vertical_offset_mm: float = Field(0, ge=-10000, le=10000)
    tilt_deg: float = Field(0, ge=-90, le=90)
    scintillator_id: str = 'bc422q-05'
    coupling_id: str = 'silicone-coupling'
    pmt_id: str = 'hamamatsu-r3377'
    pmt_cathode_reflections: bool = True
    pmt_shape_enabled: bool = False
    pmt_shape_factor: float = Field(1., gt=0)
    pmt_hv_V: float | None = Field(None, description='Magnitude or signed HV; None uses the PMT reference voltage')
    pmt_load_ohm: float = Field(50, gt=0, le=100000)
    pmt_polarity: Literal['positive','negative'] = 'negative'
    surface_id: str = 'ptfe-lut'
    coupling_mm: float = Field(.1, ge=0, le=100)
    wrapping: Wrapping = Field(default_factory=Wrapping)



class SourceGeometry(StrictModel):
    radius_mm: float = Field(0, ge=0, le=100)
    thickness_mm: float = Field(0, ge=0, le=100)


class Assembly(StrictModel):
    azimuth_deg: float = Field(0, ge=-360, le=360)
    tilt_deg: float = Field(0, ge=-90, le=90)


class SampleSide(StrictModel):
    shape: Literal['box', 'cylinder'] = 'cylinder'
    diameter_mm: float = Field(10, gt=0, le=1000)
    width_mm: float = Field(10, gt=0, le=1000)
    height_mm: float = Field(10, gt=0, le=1000)
    thickness_mm: float = Field(1, ge=0, le=1000)
    material_id: str = 'aluminium'


class Sample(StrictModel):
    enabled: bool = True
    left: SampleSide = Field(default_factory=SampleSide)
    right: SampleSide = Field(default_factory=SampleSide)
    foil_thickness_mm: float = Field(.0075, ge=0, le=100)
    foil_material_id: str = 'kapton'
    foil_enabled: bool = True
    foil_diameter_mm: float = Field(10, gt=0, le=1000)


class Shield(StrictModel):
    id: str = Field('shield1', pattern=r'^[A-Za-z0-9_-]{1,60}$')
    enabled: bool = False
    shape: Literal['box', 'cylinder'] = 'box'
    material_id: str = 'lead'
    width_mm: float = Field(30, gt=0, le=1000)
    height_mm: float = Field(40, gt=0, le=1000)
    diameter_mm: float = Field(30, gt=0, le=1000)
    thickness_mm: float = Field(1, gt=0, le=1000)
    position_mm: tuple[float, float, float] = (10, 0, 0)
    azimuth_deg: float = Field(0, ge=-360, le=360)
    tilt_deg: float = Field(0, ge=-90, le=90)
    reference: Literal['source', 'A', 'B'] = 'source'


class Run(StrictModel):
    events: int = Field(1000, ge=1, le=2147483646, strict=True)
    secondary_events: int = Field(1000, ge=1, le=2147483646, strict=True)
    seed: int = Field(12345, ge=1, le=2147483646, strict=True)
    auto_seed: bool = True
    threads: int = Field(0, ge=0, le=256, strict=True)
    output_paths: list[str] = Field(default_factory=lambda: ['runs/run_na22_1275.tpstream', 'runs/run_na22_511.tpstream'], min_length=2, max_length=2)
    trajectory_sample_limit: int = Field(24, ge=0, le=10000, strict=True)
    optical_tracks_per_detector: int = Field(24, ge=0, le=256, strict=True)
    counts_linked: bool = True
    outputs_linked: bool = True


class Physics(StrictModel):
    include_cherenkov: bool = True
    minimum_energy_keV: float = Field(0, ge=0)


class Profile(StrictModel):
    format: Literal['twinpals-module1-profile'] = 'twinpals-module1-profile'
    version: Literal[8] = 8
    name: str = Field('Module 1', min_length=1, max_length=160)
    source: Literal['na22', 'co60'] = 'na22'
    source_geometry: SourceGeometry = Field(default_factory=SourceGeometry)
    assembly: Assembly = Field(default_factory=Assembly)
    detectors: list[Detector] = Field(default_factory=lambda: [Detector(id='A'), Detector(id='B', azimuth_deg=180)], min_length=2, max_length=2)
    sample: Sample = Field(default_factory=Sample)
    shields: list[Shield] = Field(default_factory=lambda: [Shield()], max_length=32)
    run: Run = Field(default_factory=Run)
    physics: Physics = Field(default_factory=Physics)

    @model_validator(mode='after')
    def unique(self):
        if [d.id for d in self.detectors] != ['A', 'B']:
            raise ValueError('Detectors must be ordered A, B')
        if len({x.id for x in self.shields}) != len(self.shields):
            raise ValueError('Each shielding block needs its own identifier.')
        return self


def material_references(profile):
    fields={'scintillator_id':('scintillator','Scintillator'),'coupling_id':('coupling','Coupling'),
            'pmt_id':('pmt','Photomultiplier'),'surface_id':('wrapping','Wrapping')}
    for d in profile['detectors']:
        for key,(category,label) in fields.items():
            yield d[key],category,f'Setup → Detector {d["id"]} → {label}'
    for side in ('left','right'):
        yield profile['sample'][side]['material_id'],'sample',f'Setup → Source → {side.title()} sample → Material'
    yield profile['sample']['foil_material_id'],'foil','Setup → Source → Encapsulation foil'
    for i,s in enumerate(profile['shields']):
        yield s['material_id'],'shield',f'Setup → Shield → Block {i+1} → Material'


def referenced_ids(profile):
    return {key for key,_,_ in material_references(profile)}
