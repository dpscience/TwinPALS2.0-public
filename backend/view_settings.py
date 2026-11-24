# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Durable interface choices stored only in the application settings file."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .m3_models import MonitorView, SpectrumAnalysis

Metric = Literal['pulse_height','energy','photon_count','mean_arrival','depth','polar_angle','azimuth','track_length','reflections']

class ViewModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class Selection(ViewModel):
    basis: Literal['crystal','anode']='anode'
    detector: Literal['all','A','B']='all'
    primary: Literal['all','na22_prompt','na22_annihilation','co60_1173','co60_1332']='all'
    category: Literal['all','interaction','transmission','miss']='all'
    origin: Literal['all','none','scintillation','cherenkov','mixed']='all'
    split_origin: bool=False
    bins: int=Field(120,ge=10,le=1000)
    suppress_zero: list[Literal['energy','photon_count','mean_arrival','pulse_height','depth','polar_angle','azimuth','track_length','reflections']]=Field(default_factory=lambda:['energy','photon_count','mean_arrival','pulse_height'],max_length=9)

class Camera(ViewModel):
    position: tuple[float,float,float]
    target: tuple[float,float,float]
    up: tuple[float,float,float]

class SceneView(ViewModel):
    transparent: bool=True
    camera: Camera|None=None
    tree: dict[str,bool]=Field(default_factory=dict,max_length=40)

class PlotView(ViewModel):
    x: tuple[float,float]|None=None
    y: tuple[float,float]|None=None
    hidden: list[str]=Field(default_factory=list,max_length=64)

    @model_validator(mode='after')
    def ordered(self):
        if any(bounds is not None and bounds[0]>=bounds[1] for bounds in (self.x,self.y)):
            raise ValueError('Plot bounds must be increasing')
        return self

class PreviewFilter(ViewModel):
    interaction: bool=True
    transmission: bool=False
    miss: bool=False

class DetectorInset(ViewModel):
    origin: Literal["all","scintillation","cherenkov","mixed"]="all"
    contributions: bool=False
    tab: Literal['current','map','persistence','arrivals']='current'
    detector: Literal['A','B']='A'
    primary: Literal['all','na22_prompt','na22_annihilation','co60_1173','co60_1332']='all'

class CurveImport(ViewModel):
    decimalComma: bool=False
    delimiter: Literal['auto','comma','semicolon','tab','space']='auto'
    xColumn: int=Field(1,ge=1,le=10000)
    yColumn: int=Field(2,ge=1,le=10000)
    header: bool=False

class PulseViews(ViewModel):
    persistence_detector: Literal['A','B']='A'
    autoscale_voltage: bool=False
    tab: Literal['setup','simulation']='setup'
    section: Literal['inputs','sample','A','B','digitizer','acquisition','run']='inputs'
    panel: Literal['monitoring','settings']='monitoring'
    bins: int=Field(120,ge=10,le=1000)
    analysis_paths: list[str]=Field(default_factory=list,max_length=8)

class LifetimeViews(ViewModel):
    tab: Literal['setup','analysis']='setup'
    section: Literal['Input','Pulse','PHS','Filters']='Input'
    monitor: MonitorView=Field(default_factory=MonitorView)
    analysis: SpectrumAnalysis=Field(default_factory=SpectrumAnalysis)

    @model_validator(mode='before')
    @classmethod
    def migrate_sections(cls,value):
        if not isinstance(value,dict):return value
        v=dict(value)
        if v.get('tab')=='simulation' or v.get('section')=='Spectra':v['tab']='analysis'
        if v.get('section') in ('A','B'):v['section']='PHS'
        if v.get('section') in ('Inputs','Run','Spectra'):v['section']='Input'
        if v.get('section')=='Timing':v['section']='Pulse'
        return v
    bin_ps: float=Field(5,ge=1,le=10000)
    zero_ps: float=0
    low_ns: float=-5
    high_ns: float=50
    category: str='all'
    categories: list[str]|None=Field(default=None,max_length=7)
    individual: bool=False
    origin: str='all'
    scatter: str='all'

class ViewSettings(ViewModel):
    module3: LifetimeViews=Field(default_factory=LifetimeViews)
    preview_level: Literal['crystal','anode']='crystal'
    preview_origin: Literal['all','none','scintillation','cherenkov','mixed']='all'
    outcome_level: Literal['crystal','anode']='crystal'
    outcome_detector: Literal['A','B']='A'
    module2: PulseViews=Field(default_factory=PulseViews)
    activity_unit: Literal['Bq','uCi']='Bq'
    module: Literal[1,2,3,4]=1
    tab: Literal['setup','simulation','analysis']='setup'
    material_category: Literal['scintillator','coupling','pmt','digitizer','wrapping','sample','foil','shield']='scintillator'
    material_selected: str='bc422q-05'
    material_search: str=Field('',max_length=200)
    material_curve: str=Field('emission',max_length=80)
    last_session_paths: list[str]=Field(default_factory=list,max_length=16)
    material_editor_tab: Literal['general','optical','emission','curves','references','window','timing','sampling','voltage','lifetime']='general'
    dialog_paths: dict[str,str]=Field(default_factory=dict,max_length=32)
    section: Literal['source','A','B','shield','physics','run']='A'
    simulation_panel: Literal['monitoring','settings']='monitoring'
    simulation_section: Literal['source','A','B','shield','physics','run']='source'
    simulation_sample_side: Literal['left','right']='left'
    sample_side: Literal['left','right']='left'
    selection: Selection=Field(default_factory=Selection)
    analysis_paths: list[str]=Field(default_factory=list,max_length=16)
    detector_inset: DetectorInset=Field(default_factory=DetectorInset)
    preview_filter: PreviewFilter=Field(default_factory=PreviewFilter)
    preview_detector: Literal['all','A','B']='all'
    setup_details: dict[str,bool]=Field(default_factory=dict,max_length=32)
    scene_setup: SceneView=Field(default_factory=SceneView)
    scene_simulation: SceneView=Field(default_factory=SceneView)
    plots: dict[str,PlotView]=Field(default_factory=dict,max_length=160)
    curve_import: CurveImport=Field(default_factory=CurveImport)

def view_settings(raw=None):
    return ViewSettings.model_validate({} if raw is None else raw).model_dump(mode='json')
