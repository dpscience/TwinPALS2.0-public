# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Waveform-only lifetime acquisition settings. Units are explicit at the boundary."""
from typing import Annotated, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Window(Model):
    low: float = Field(100, ge=0)
    high: float = Field(500, gt=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.high <= self.low: raise ValueError('PHS upper limit must exceed its lower limit.')
        return self


class Band(Model):
    enabled: bool = False
    slope: float = 10
    intercept: float = 0
    below: float = Field(100, ge=0)
    above: float = Field(100, ge=0)


class Ellipse(Model):
    enabled: bool = False
    rise: float = Field(2, ge=0)
    fall: float = Field(8, ge=0)
    radius_rise: float = Field(1, gt=0)
    radius_fall: float = Field(3, gt=0)
    angle_deg: float = 0


class Gate(Model):
    phs: Window = Field(default_factory=Window)
    area: Band = Field(default_factory=Band)
    shape: Ellipse = Field(default_factory=Ellipse)


class Channel(Model):
    polarity: Literal['negative', 'positive'] = 'negative'
    cfd_percent: float = Field(25, gt=0, lt=100)
    baseline_samples: int = Field(32, ge=4, le=4096)
    baseline_mode: Literal['readout','pre_pulse'] = 'readout'
    baseline_gap: int = Field(4, ge=0, le=4096)
    median_samples: int = Field(1, ge=1, le=31)
    interpolation: Literal['linear','cubic','akima'] = 'linear'
    intra_steps: int = Field(8, ge=1, le=64)
    minimum_height_mV: float = Field(5, gt=0)
    reject_clipped: bool = True
    start: Gate = Field(default_factory=lambda: Gate(phs=Window(low=100, high=500)))
    stop: Gate = Field(default_factory=lambda: Gate(phs=Window(low=10, high=100)))

    @model_validator(mode='after')
    def valid(self):
        if self.median_samples % 2 != 1: raise ValueError('Median width must be odd (1 disables smoothing).')
        if max(self.start.phs.low,self.stop.phs.low) < min(self.start.phs.high,self.stop.phs.high):
            raise ValueError('Start and stop PHS windows must not overlap. The upper boundary is excluded.')
        return self


class Profile(Model):
    format: Literal['twinpals-module3'] = 'twinpals-module3'
    version: Literal[1] = 1
    input_paths: list[str] = Field(default_factory=list, max_length=1)
    channels: list[Channel] = Field(default_factory=lambda:[Channel(),Channel()], min_length=2, max_length=2)
    workers: int = Field(0, ge=0, le=32)  # Zero follows the workstation's recommended count.
    pulse_selection: Literal['highest','first']='highest'
    preview_count: int = Field(24, ge=1, le=256)

    @staticmethod
    def from_saved(raw):
        """A legacy playlist requires a new, explicit single-file choice."""
        paths=raw.get('input_paths') if isinstance(raw,dict) else None
        if isinstance(paths,list) and len(paths)>1:
            raw={**raw,'input_paths':[]}
        return Profile.model_validate(raw)


class View(Model):
    bin_ps: float = Field(5, ge=1, le=10000)
    zero_ps: float = Field(0, ge=-1e9, le=1e9)
    low_ns: float = Field(-5, ge=-1e6, le=1e6)
    high_ns: float = Field(50, ge=-1e6, le=1e6)
    category: str = 'all'
    categories: list[str] | None = Field(default=None, max_length=7)
    individual: bool = False
    origin: Literal['all','scintillation','cherenkov','mixed','unknown'] = 'all'
    scatter: Literal['all','none','any','shield','sample','other_detector'] = 'all'

    @model_validator(mode='after')
    def bounded(self):
        from .m3_signal import CATEGORIES
        if self.category not in ('all',*CATEGORIES) or (self.categories is not None and
            (len(set(self.categories))!=len(self.categories) or any(c not in CATEGORIES for c in self.categories))):
            raise ValueError('Choose distinct lifetime contribution classes.')
        if not 1 <= (self.high_ns-self.low_ns)*1000/self.bin_ps <= 100000:
            raise ValueError('Choose an increasing spectrum range with at most 100,000 bins.')
        return self


class FitPercentiles(Model):
    low: float = Field(2.5, ge=0, le=100)
    high: float = Field(97.5, ge=0, le=100)

    @model_validator(mode='after')
    def ordered(self):
        if self.low >= self.high:
            raise ValueError('The lower fit percentile must precede the upper percentile.')
        return self


class ShapeFit(FitPercentiles):
    low: float = Field(25, ge=0, le=100)
    high: float = Field(75, ge=0, le=100)
    fence: float = Field(1.5, ge=0)
    coverage: float = Field(95, gt=0, le=100)


class DensityView(Model):
    nx:int=Field(256,ge=8,le=512)
    ny:int=Field(256,ge=8,le=512)
    axes:tuple[float,float,float,float]|None=None

    @model_validator(mode='after')
    def ordered(self):
        if self.axes and (min(self.axes)<0 or self.axes[0]>=self.axes[1] or self.axes[2]>=self.axes[3]):
            raise ValueError('Fixed plot axes must be nonnegative and increasing.')
        return self


PulseHeightBins = Annotated[int, Field(ge=8, le=2048)]
FitWindow = Literal['A-start','A-stop','B-start','B-stop']


SpectrumDirection = Literal['merged', 'AB', 'BA', 'SS']


class HeightViewport(Model):
    mode: Literal['full', 'start', 'stop', 'custom'] = 'full'
    limits: tuple[float, float] | None = None

    @model_validator(mode='after')
    def ordered(self):
        if self.mode == 'custom' and self.limits is None:
            raise ValueError('Enter both pulse-height limits.')
        if self.limits and not 0 <= self.limits[0] < self.limits[1]:
            raise ValueError('Pulse-height limits must be nonnegative and increasing.')
        return self


class SpectrumDisplay(View):
    # The buffered pair count is bounded by View.bounded. A recorded cable
    # delay and a display zero can move a whole cohort outside the legacy range.
    bin_ps: float = Field(5, ge=1)
    low_ns: float = -5
    high_ns: float = 50
    phs_bins: tuple[PulseHeightBins, PulseHeightBins] = (512, 512)
    time_view: tuple[float, float] | None = None
    log_scale: bool = True  # Read older .tpm3 files with a stored scale preference.
    show_total: bool = True
    show_superimposed: bool = False
    subtype_overlays: list[str] = Field(default_factory=list, validation_alias=AliasChoices('subtype_overlays','boras_overlays'))
    phs_views: tuple[HeightViewport, HeightViewport] = Field(default_factory=lambda: (HeightViewport(), HeightViewport()))


    @model_validator(mode='after')
    def time_view_within_spectrum(self):
        if self.time_view and not self.low_ns <= self.time_view[0] < self.time_view[1] <= self.high_ns:
            raise ValueError('The lifetime plot limits must lie within the configured spectrum range.')
        return self

    @field_validator('subtype_overlays')
    @classmethod
    def known_subtypes(cls, keys):
        from .m3_subtypes import migrate_overlays
        return migrate_overlays(keys)


class SpectrumAnalysis(Model):
    direction: SpectrumDirection = 'merged'
    displays: dict[SpectrumDirection, SpectrumDisplay] = Field(default_factory=dict)


class MonitorView(Model):
    filter_kind:Literal['area','shape']='area'
    plots:dict[Literal['area-A-start','area-B-start','area-A-stop','area-B-stop','shape-A-start','shape-B-start','shape-A-stop','shape-B-stop'],DensityView]=Field(default_factory=dict)
    traces:tuple[bool,bool]=(False,False)
    autoscale:tuple[bool,bool]=(False,False)
    show_baseline:bool | tuple[bool,bool]=False
    phs_bins:tuple[PulseHeightBins,PulseHeightBins]=(512,512)
    area_fit:dict[FitWindow,FitPercentiles]=Field(default_factory=dict)
    shape_fit:dict[FitWindow,ShapeFit]=Field(default_factory=dict)


class Settings(Model):
    format: Literal['twinpals-lifetime-settings'] = 'twinpals-lifetime-settings'
    version: Literal[1] = 1
    processing: Profile = Field(default_factory=Profile)
    display: View = Field(default_factory=View)
    analysis: SpectrumAnalysis = Field(default_factory=SpectrumAnalysis)
    monitor: MonitorView = Field(default_factory=MonitorView)
