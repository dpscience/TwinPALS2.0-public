# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Current Module 2 contracts. Units are ns, mV, GS/s and effective decays/s."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Reference(Model):
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=1000)
    fields: list[str] = Field(default_factory=list, max_length=40)
    comment: str = Field('', max_length=3000)

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            raise ValueError('References require an http:// or https:// source URL.')
        return value


class Component(Model):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')
    name: str = Field(min_length=1, max_length=160)
    category: Literal['digitizer']
    revision: int = Field(1, ge=1)
    builtin: bool = False
    description: str = Field('', max_length=4000)
    references: list[Reference] = Field(default_factory=list, max_length=30)
    architecture: Literal['uniform_adc', 'switched_capacitor'] = 'uniform_adc'
    adc_bits: int = Field(14, ge=2, le=24)
    voltage_min_mV: float = Field(-500, ge=-50000, le=50000)
    voltage_max_mV: float = Field(500, ge=-50000, le=50000)
    default_rate: float = Field(5, gt=0, le=100)
    default_samples: int = Field(1024, ge=16, le=65536)
    default_dead_ns: float = Field(0, ge=0, le=1e12)
    default_fixed_jitter_ps: float = Field(0, ge=0, le=10000)
    default_random_jitter_ps: float = Field(0, ge=0, le=10000)
    default_irf_sigma_ps: float = Field(0, ge=0, le=10000)
    default_noise_sigma_mV: float = Field(0, ge=0, le=10000)
    baseline_mV: float = Field(0, ge=-50000, le=50000)
    input_bandwidth_MHz: float = Field(0, ge=0, le=100000)
    input_impedance_ohm: float = Field(50, gt=0, le=100000)
    cell_alternation_ps: float = Field(0, ge=0, le=1e6)

    @model_validator(mode='after')
    def coherent(self):
        if not self.voltage_min_mV < self.voltage_max_mV or not self.voltage_min_mV <= self.baseline_mV < self.voltage_max_mV:
            raise ValueError('Voltage: minimum must be below maximum; baseline must lie inside the input range.')
        if self.architecture == 'uniform_adc':
            if self.cell_alternation_ps or self.default_fixed_jitter_ps or self.default_random_jitter_ps:
                raise ValueError('Uniform sampling requires zero cell timing variations and zero cell alternation.')
        if self.cell_alternation_ps and self.default_samples % 2:
            raise ValueError('Alternating short/long cell intervals require an even sample count.')
        width=(2*(self.default_fixed_jitter_ps**2+self.default_random_jitter_ps**2))**.5
        if 1000/self.default_rate-self.cell_alternation_ps <= 5*width:
            raise ValueError('Cell timing: the shortest mean interval must exceed five times the combined interval jitter. Reduce alternation or jitter.')
        if max(self.default_fixed_jitter_ps,self.default_random_jitter_ps)>=150/self.default_rate:
            raise ValueError('Cell timing variation must be less than 15% of the sampling interval.')
        return self


class Lifetime(Model):
    name: str = Field('Sample', min_length=1, max_length=80)
    origin: Literal['sample', 'source'] = 'sample'
    tau_ns: float = Field(.158, ge=0, le=1e6)
    intensity: float = Field(1, gt=0, le=1)
    distribution: Literal['discrete', 'gaussian', 'lorentzian', 'lognormal'] = 'discrete'
    spread: float = Field(.02, gt=0, le=1e6)
    lower_ns: float = Field(0, ge=0, le=1e6)
    upper_ns: float = Field(10, gt=0, le=1e6)
    grid_points: int = Field(2001, ge=21, le=10001)

    @model_validator(mode='after')
    def distribution_support(self):
        if self.distribution != 'discrete':
            if self.lower_ns >= self.upper_ns or not self.lower_ns <= self.tau_ns <= self.upper_ns:
                raise ValueError('Lifetime distribution: its centre must lie between the lower and upper limits.')
            if self.distribution == 'lognormal' and (self.tau_ns <= 0 or self.spread > 5):
                raise ValueError('Lognormal lifetime: use a positive median and a logarithmic width up to 5.')
        return self


class Channel(Model):
    invert: bool = False
    attenuation_dB: float = Field(30, ge=0, le=120)
    cable_delay_ns: float = Field(0, ge=0, le=1e6)
    threshold_mV: float = Field(10, gt=0, le=100000)


class Digitization(Model):
    digitizer_id: str = 'psi-drs4-v5'
    rate_GSps: float = Field(5, gt=0, le=100)
    samples: int = Field(1024, ge=16, le=65536)
    full_range_mV: float = Field(1000, gt=0, le=100000)
    voltage_min_mV: float = -500
    voltage_max_mV: float = 500
    baseline_mV: float = Field(0, ge=-50000, le=50000)
    noise_sigma_mV: float = Field(.48, ge=0, le=10000)
    fixed_jitter_ns: float = Field(0, ge=0, le=10)
    aperture_jitter_ns: float = Field(.005, ge=0, le=10)
    irf_sigma_ns: float = Field(.0025, ge=0, le=10)
    input_bandwidth_MHz: float = Field(0, ge=0, le=100000)
    input_impedance_ohm: float = Field(50, gt=0, le=100000)


class DeviceSelection(Model):
    digitizer_id: str = 'psi-drs4-v5'


class Acquisition(Model):
    trigger: Literal['either', 'A', 'B', 'coincidence'] = 'coincidence'
    coincidence_ns: float = Field(40, gt=0, le=1e6)
    trigger_delay_ns: float = Field(184.8, ge=0, le=1e6)
    trigger_step_ns: float = Field(.05, ge=.001, le=1)


class RecordedProfile(Model):
    format: Literal['twinpals-module2-profile'] = 'twinpals-module2-profile'
    version: Literal[4] = 4
    input_paths: list[str] = Field(default_factory=lambda: ['', ''], min_length=2, max_length=2)
    threads: int = Field(0, ge=0, le=256, strict=True)
    activity_Bq: float = Field(925000, gt=0, le=1e9)
    waveform_pairs: int = Field(10000, ge=1, le=2**53-1, strict=True)
    maximum: bool = False
    shuffle: bool = True
    seed: int = Field(12345, ge=1, le=2**63-1)
    auto_seed: bool = True
    lifetimes: list[Lifetime] = Field(default_factory=lambda: [
        Lifetime(name='Sample', tau_ns=.158, intensity=.825),
        Lifetime(name='Source support', origin='source', tau_ns=.380, intensity=.172),
        Lifetime(name='Long component', origin='source', tau_ns=2.750, intensity=.003)], min_length=1, max_length=5)
    channels: list[Channel] = Field(default_factory=lambda: [Channel(), Channel()], min_length=2, max_length=2)
    digitization: DeviceSelection = Field(default_factory=DeviceSelection)
    acquisition: Acquisition = Field(default_factory=Acquisition)
    output_path: str = 'runs/pulses.tppulses'
    output_mode: Literal['combined', 'classes'] = 'combined'
    preview_limit: int = Field(64, ge=1, le=1000)


class Profile(RecordedProfile):
    output_mode: Literal['combined'] = 'combined'

    @field_validator('output_mode',mode='before')
    @classmethod
    def migrate_layout(cls,value):
        return 'combined' if value=='classes' else value


class RuntimeAcquisition(Acquisition):
    dead_ns: float = Field(0, ge=0, le=1e12)

class RuntimeProfile(RecordedProfile):
    digitization: Digitization
    acquisition: RuntimeAcquisition

def reference_profile(raw):
    """Export the current run's settings without duplicating database properties."""
    result=dict(raw)
    result['digitization']={'digitizer_id':raw['digitization']['digitizer_id']}
    result['acquisition']={k:v for k,v in raw['acquisition'].items() if k in Acquisition.model_fields}
    return Profile.model_validate(result).model_dump(mode='json')

def validate_lifetime_mixture(components):
    from .m2_lifetimes import lifetime_grid
    if abs(sum(c['intensity'] for c in components)-1)>1e-8:
        raise ValueError('Setup → Sample → Component intensities must add up to 100%.')
    for component in components:
        lifetime_grid(component)


def resolve(raw, entries, *, check_mixture=True):
    p = Profile.model_validate(raw)
    by_id = {e['id']: Component.model_validate(e) for e in entries if not e.get('missing')}
    device=by_id.get(p.digitization.digitizer_id)
    if device is None:
        raise ValueError('Setup → Digitizer: the selected entry is missing. Import it or choose another digitizer.')
    d=Digitization(digitizer_id=device.id,rate_GSps=device.default_rate,samples=device.default_samples,
        full_range_mV=device.voltage_max_mV-device.voltage_min_mV,
        voltage_min_mV=device.voltage_min_mV,voltage_max_mV=device.voltage_max_mV,
        baseline_mV=device.baseline_mV,noise_sigma_mV=device.default_noise_sigma_mV,
        fixed_jitter_ns=device.default_fixed_jitter_ps/1000,aperture_jitter_ns=device.default_random_jitter_ps/1000,
        irf_sigma_ns=device.default_irf_sigma_ps/1000,
        input_bandwidth_MHz=device.input_bandwidth_MHz,input_impedance_ohm=device.input_impedance_ohm)
    window=d.samples/d.rate_GSps
    if p.acquisition.trigger_delay_ns>window:
        raise ValueError(f'Setup → DAQ → Common trigger delay: enter 0 to {window:g} ns to keep the trigger inside the saved window.')
    if not p.output_path.lower().endswith('.tppulses'):
        raise ValueError('Setup → Run → Choose an output filename ending in .tppulses.')
    if len(set(p.input_paths))!=2:
        raise ValueError('Setup → Inputs: choose two different primary streams from one Module 1 run.')
    if check_mixture:
        validate_lifetime_mixture([c.model_dump() for c in p.lifetimes])
    warnings=[]
    pretrigger=window-p.acquisition.trigger_delay_ns
    if p.acquisition.trigger=='coincidence' and pretrigger+1e-9<p.acquisition.coincidence_ns:
        remedy=(f'reduce Common trigger delay to {window-p.acquisition.coincidence_ns:g} ns or less'
                if window>=p.acquisition.coincidence_ns else 'select a digitizer with a longer acquisition window')
        warnings.append(f'Setup → DAQ: AND permits crossings up to {p.acquisition.coincidence_ns:g} ns apart, '
            f'but only {pretrigger:g} ns before the accepted trigger is saved. The earlier qualifying pulse may be outside the waveform. '
            f'To include both crossings, {remedy}, or reduce Coincidence interval to {pretrigger:g} ns or less. '
            'Leave additional margin for the pulse leading edge and tail; covering both crossings does not guarantee both complete pulses.')
    if not device.default_dead_ns:warnings.append('Digitizer readout uses zero dead time. This is an ideal model; no acquisition-rate limit has been supplied.')
    runtime=p.model_dump(mode='json');runtime['digitization']=d.model_dump(mode='json')
    runtime['acquisition']['dead_ns']=device.default_dead_ns
    from .cell_timing import generate_cell_intervals
    snapshot=device.model_dump(mode='json')
    return {'profile':runtime,'digitizer':snapshot,'cell_intervals_ns':generate_cell_intervals(snapshot,p.seed),'window_ns':window,
        'sample_span_ns':(d.samples-1)/d.rate_GSps,'quantization_mV':d.full_range_mV/2**device.adc_bits,'warnings':warnings}
