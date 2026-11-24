# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Charge-normalized effective PMT response, independent of any digitizer.

The stored representation is a sum of Erlang kernels with double-precision PE
onsets, not sampled voltages. Its tail is infinite and its integral is exactly
N_PE e G. The dynode-count/order identification is an explicit model convention.
"""
from functools import lru_cache
import math
import numpy as np
from pathlib import Path
import ctypes
import sys

E_CHARGE = 1.602176634e-19
FWHM_SIGMA = math.sqrt(8 * math.log(2))
MODEL = 'erlang-fixed-charge-v1'


@lru_cache(maxsize=1)
def native_library():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path=root/'.runtime/bin/twinpals-analog.dll'
    if not path.exists(): return None
    lib=ctypes.CDLL(str(path))
    vector=np.ctypeslib.ndpointer(dtype=np.float64,ndim=1,flags='C_CONTIGUOUS')
    lib.tp_analog_evaluate.argtypes=[vector,ctypes.c_int,vector,ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_double,vector]
    lib.tp_analog_evaluate.restype=ctypes.c_int
    lib.tp_analog_peak.argtypes=[vector,ctypes.c_int,ctypes.c_int,ctypes.c_double]
    lib.tp_analog_peak.restype=ctypes.c_double
    if hasattr(lib,'tp_persistence_batch'):
        lib.tp_persistence_batch.argtypes=[
            ctypes.c_char_p,ctypes.c_size_t,np.ctypeslib.ndpointer(np.uint64,ndim=2,flags='C_CONTIGUOUS'),ctypes.c_int,
            vector,ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_double,ctypes.c_double,
            np.ctypeslib.ndpointer(np.int64,ndim=3,flags='C_CONTIGUOUS')]
        lib.tp_persistence_batch.restype=ctypes.c_int
    if hasattr(lib,'tp_stream_crc32'):
        lib.tp_stream_crc32=ctypes.PYFUNCTYPE(ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t)(('tp_stream_crc32',lib))
    if hasattr(lib,'tp_transport_validate'):
        raw=np.ctypeslib.ndpointer(dtype=np.uint8,ndim=1,flags='C_CONTIGUOUS')
        # This small per-record check takes microseconds. A GIL handoff on every
        # record can instead wait milliseconds behind monitoring work. Keep the
        # GIL for validation only; expensive analog evaluations remain CDLL calls
        # and execute concurrently on the acquisition workers.
        lib.tp_transport_validate=ctypes.PYFUNCTYPE(ctypes.c_int,raw,ctypes.c_int,raw,ctypes.c_int,ctypes.c_int,ctypes.c_int)(('tp_transport_validate',lib))
    return lib

RESPONSE_FIELDS = ('dynodes', 'gain', 'gain_hv_V', 'rise_ns', 'rise_hv_V',
    'transit_ns', 'transit_hv_V', 'tts_ns', 'tts_hv_V', 'tts_convention',
    'hv_min_V', 'hv_max_V', 'hv_absolute_max_V', 'reference_load_ohm',
    'calibration_flash_fwhm_ns')


def kernel(t, order, tau):
    """Unit-area density, in 1/ns; onset at zero."""
    t = np.asarray(t, dtype=float)
    result = np.zeros_like(t)
    valid = t > 0
    u = t[valid] / tau
    result[valid] = np.exp((order-1)*np.log(u)-u-math.lgamma(order)) / tau
    return result


def pulse_metrics(t, y):
    k = int(np.argmax(y)); peak = float(y[k])
    if not peak > 0: raise ValueError('The reference response has no positive peak.')
    def cross(fraction, rising):
        hits = np.flatnonzero(y[:k+1] >= peak*fraction) if rising else k+np.flatnonzero(y[k:] <= peak*fraction)
        if not len(hits) or hits[0] == 0: raise ValueError('Incomplete reference response support.')
        i = int(hits[0])
        return float(t[i-1]+(peak*fraction-y[i-1])*(t[i]-t[i-1])/(y[i]-y[i-1]))
    peak_t = float(t[k])
    if 0 < k < len(y)-1:
        denominator = y[k-1]-2*y[k]+y[k+1]
        if denominator: peak_t += float(.5*(y[k-1]-y[k+1])/denominator*(t[k+1]-t[k]))
    return dict(rise_ns=cross(.9,True)-cross(.1,True), fwhm_ns=cross(.5,False)-cross(.5,True), peak_ns=peak_t)


@lru_cache(maxsize=256)
def calibrate(order, rise_ns, tts_sigma_ns, flash_fwhm_ns):
    """Fit intrinsic tau after Gaussian reference TTS and reference-flash folding.

    Calibration uses a fixed fine relative grid and padded FFT. The flash is
    ONLY a measurement condition; it is never added to physical event times.
    """
    sigma = math.hypot(tts_sigma_ns, flash_fwhm_ns / FWHM_SIGMA)
    gaussian_rise = sigma*(math.sqrt(2*math.log(10))-math.sqrt(2*math.log(10/9)))
    if gaussian_rise >= rise_ns:
        raise ValueError('PMT rise time is too short for the specified TTS and calibration flash. Check their definitions and reference conditions.')
    # Dimensionless computation gives the same relative precision for every PMT.
    t = np.linspace(-16, 112, 65536, endpoint=False)
    dt = t[1]-t[0]
    omega = 2*np.pi*np.fft.rfftfreq(len(t),dt)
    transfer = np.exp(-.5*(omega*sigma/rise_ns)**2)
    def measured(tau):
        shape = kernel(t,order,tau)
        return np.fft.irfft(np.fft.rfft(shape)*transfer,n=len(t))
    lo, hi = .002, 3.
    if pulse_metrics(t,measured(lo))['rise_ns'] > 1.001:
        raise ValueError('PMT rise time is too short for the specified TTS and calibration flash. Check their definitions and reference conditions.')
    for _ in range(40):
        mid = (lo+hi)/2
        if pulse_metrics(t,measured(mid))['rise_ns'] < 1.: lo = mid
        else: hi = mid
    tau = (lo+hi)/2
    metrics = pulse_metrics(t,measured(tau))
    return dict(tau_ns=tau*rise_ns, calibration_peak_ns=metrics['peak_ns']*rise_ns,
                calibrated_rise_ns=metrics['rise_ns']*rise_ns,
                calibrated_fwhm_ns=metrics['fwhm_ns']*rise_ns)


def validate_response(p):
    """Validate supplied fields; drafts may omit required fields."""
    numeric = set(RESPONSE_FIELDS)-{'tts_convention'} | {'gain_exponent','published_fwhm_ns'}
    for key in numeric:
        if key not in p: continue
        value = p[key]
        allow_zero = key in ('tts_ns','calibration_flash_fwhm_ns')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0 or (not allow_zero and value==0):
            raise ValueError(f'PMT response → {key.replace("_"," ")}: enter a finite {"nonnegative" if allow_zero else "positive"} value.')
    if 'dynodes' in p and (int(p['dynodes']) != p['dynodes'] or not 2 <= p['dynodes'] <= 32):
        raise ValueError('PMT response → Dynodes: enter an integer from 2 to 32.')
    if p.get('tts_convention','fwhm') not in ('fwhm','sigma'):
        raise ValueError('PMT response → TTS: select sigma or FWHM.')
    if all(k in p for k in ('hv_min_V','hv_max_V','hv_absolute_max_V')) and not p['hv_min_V'] <= p['hv_max_V'] <= p['hv_absolute_max_V']:
        raise ValueError('PMT response → HV: the model range must be ordered and stay within the absolute maximum.')
    if all(k in p for k in RESPONSE_FIELDS):
        for key in ('gain_hv_V','rise_hv_V','transit_hv_V','tts_hv_V'):
            if not 0 < p[key] <= p['hv_absolute_max_V']: raise ValueError(f'PMT response → {key}: reference voltage exceeds the absolute maximum.')
        sigma = p['tts_ns'] / (FWHM_SIGMA if p['tts_convention']=='fwhm' else 1)
        sigma *= math.sqrt(p['tts_hv_V']/p['rise_hv_V'])
        calibrate(int(p['dynodes']),p['rise_ns'],sigma,p['calibration_flash_fwhm_ns'])


def operating_point(entry, hv=None, load_ohm=50., polarity='negative'):
    p = entry['properties']
    missing = [key for key in RESPONSE_FIELDS if key not in p]
    if missing: raise ValueError(f'{entry["name"]}: missing PMT response fields: '+', '.join(missing))
    validate_response(p)
    voltage = abs(float(p['gain_hv_V'] if hv is None else hv))
    if not p['hv_min_V'] <= voltage <= p['hv_max_V']:
        raise ValueError(f'{entry["name"]}: select |HV| between {p["hv_min_V"]:g} and {p["hv_max_V"]:g} V in Setup → PMT. The absolute rating is not an extrapolation range.')
    if not math.isfinite(load_ohm) or not 0 < load_ohm <= 100000:
        raise ValueError('PMT output load must be a finite effective resistance greater than zero.')
    if polarity not in ('positive','negative'): raise ValueError('Choose positive or negative PMT polarity.')
    curve = next((c for c in entry['curves'] if c['name']=='gain_hv'), None)
    if curve:
        points = np.asarray(curve['points'],dtype=float)
        if not points[0,0] <= voltage <= points[-1,0]: raise ValueError('PMT gain curve does not cover this operating voltage.')
        gain = float(np.exp(np.interp(np.log(voltage),np.log(points[:,0]),np.log(points[:,1]))))
    else:
        if not p.get('gain_exponent'): raise ValueError('PMT response needs a gain-versus-HV curve or a documented gain exponent.')
        gain = p['gain']*(voltage/p['gain_hv_V'])**p['gain_exponent']
    rise = p['rise_ns']*math.sqrt(p['rise_hv_V']/voltage)
    transit = p['transit_ns']*math.sqrt(p['transit_hv_V']/voltage)
    sigma = p['tts_ns']/(FWHM_SIGMA if p['tts_convention']=='fwhm' else 1)*math.sqrt(p['tts_hv_V']/voltage)
    # Calibrate at the rise-time measurement HV, then scale the intrinsic tube
    # response. A fixed laboratory flash must not scale with operating HV.
    ref_sigma = p['tts_ns']/(FWHM_SIGMA if p['tts_convention']=='fwhm' else 1)*math.sqrt(p['tts_hv_V']/p['rise_hv_V'])
    cal = calibrate(int(p['dynodes']),p['rise_ns'],ref_sigma,p['calibration_flash_fwhm_ns'])
    scale = math.sqrt(p['rise_hv_V']/voltage)
    return dict(model=MODEL, pmt_id=entry['id'], hv_V=voltage, gain=gain,
        order=int(p['dynodes']), tau_ns=cal['tau_ns']*scale,
        transit_ns=transit, tts_sigma_ns=sigma, rise_ns=rise,
        onset_delay_ns=transit-cal['calibration_peak_ns']*scale,
        charge_C=E_CHARGE*gain, load_ohm=float(load_ohm), polarity=polarity,
        voltage_scale_mV=E_CHARGE*gain*load_ohm*1e12,
        timing_model='inverse-square-root-HV approximation',
        calibration_flash_fwhm_ns=p['calibration_flash_fwhm_ns'],
        calibrated_fwhm_ns=cal['calibrated_fwhm_ns']*scale)


@lru_cache(maxsize=256)
def tail_span(order, tau, fraction=1e-12):
    """Time containing 1-fraction of each PE's charge; representation stays exact."""
    def survival(x): return math.exp(-x)*sum(x**k/math.factorial(k) for k in range(order))
    lo,hi = float(order),max(100.,order*4.)
    for _ in range(60):
        mid = (lo+hi)/2
        if survival(mid)>fraction: lo=mid
        else: hi=mid
    return (lo+hi)/2*tau


def evaluate(onsets, response, times, *, current=False, filter_tau_ns=0.):
    """Exact kernel sum at arbitrary requested coordinates; bounded temporary RAM."""
    times = np.asarray(times,dtype=float)
    out = np.zeros_like(times)
    onsets = np.asarray(onsets,dtype=float)
    lib=native_library()
    if lib is not None and len(times)>0 and np.all(np.diff(times)>=0):
        rc=lib.tp_analog_evaluate(np.ascontiguousarray(onsets),len(onsets),np.ascontiguousarray(times),len(times),response['order'],response['tau_ns'],filter_tau_ns,out)
        if rc: raise ValueError('Analog response evaluation failed: '+str(rc))
    else:
        if filter_tau_ns: raise ValueError('The native analog library is required for the digitizer input filter. Build the current native runtime.')
        for first in range(0,len(onsets),128):
            out += kernel(times[:,None]-onsets[None,first:first+128],response['order'],response['tau_ns']).sum(axis=1)
    scale = response['charge_C']*1e12 if current else response['voltage_scale_mV']
    return out*scale*(-1 if response['polarity']=='negative' else 1)  # mA or mV


def pulse_plot(onsets_by_detector, responses, event_id, role, points=800):
    nonempty = [(np.asarray(a),r) for a,r in zip(onsets_by_detector,responses) if len(a)]
    if not nonempty:
        start,end = 0.,max(r['transit_ns'] for r in responses)*1.5
    else:
        start = min(float(a.min()) for a,r in nonempty)
        end = max(float(a.max())+tail_span(r['order'],r['tau_ns']) for a,r in nonempty)
        pad = max(.1,(end-start)*.03); start-=pad;end+=pad
    x = np.linspace(start,end,points)
    return dict(title='Anode current I(t)',xLabel='Time after gamma emission (ns)',yLabel='Anode current (mA)',
        event_id=event_id,role=role,series=[dict(name=f'Detector {"AB"[i]}',color=('#198f8c','#688aca')[i],dashed=bool(i),
        points=np.column_stack((x,evaluate(a,r,x,current=True))).tolist()) for i,(a,r) in enumerate(zip(onsets_by_detector,responses))])
