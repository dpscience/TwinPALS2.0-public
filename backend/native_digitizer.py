# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded evaluation of the recorded ADC codes at the actual jittered cell times."""
import ctypes as ct
from functools import lru_cache

import numpy as np

from .analog_pmt import native_library
from .native_acquisition import charge_parameters


class Pulse(ct.Structure):
    _fields_ = [('onsets', ct.c_void_p), ('count', ct.c_int32), ('order', ct.c_double),
                ('origin', ct.c_double), ('tau', ct.c_double), ('scale', ct.c_double),
                ('polarity', ct.c_double), ('factor', ct.c_double), ('cutoff', ct.c_double), ('width', ct.c_double),
                ('seed', ct.c_uint64), ('record', ct.c_uint64)]


@lru_cache(maxsize=1)
def binding():
    lib = native_library()
    if lib is None or not hasattr(lib, 'tp_adc_waveform_spe_shape'):
        return None
    fn = lib.tp_adc_waveform_spe_shape
    fn.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_int, ct.POINTER(Pulse), ct.c_int,
                   ct.c_double, ct.c_double, ct.c_double, ct.c_double, ct.c_uint,
                   ct.c_void_p, ct.POINTER(ct.c_int)]
    fn.restype = ct.c_int
    return fn


def sample_channel(fn, times, background, selected, resolved, ch, output):
    profile = resolved['profile']
    settings = profile['digitization']
    channel = profile['channels'][ch]
    factor = 10**(-channel['attenuation_dB']/20)
    if channel.get('invert', False):
        factor = -factor
    descriptors = (Pulse * len(selected))()
    arrays = []
    for i, pulse in enumerate(selected):
        library = resolved['_libraries'][int(pulse['role'])]
        response = library.responses[ch]
        onsets = np.ascontiguousarray(library.onsets(int(pulse['record']), ch), dtype=np.float64)
        arrays.append(onsets)  # retain storage until the native call returns
        descriptors[i] = Pulse(onsets.ctypes.data, len(onsets), response['order'], pulse['origin'],
                               response['tau_ns'], response['voltage_scale_mV'],
                               -1 if response['polarity']=='negative' else 1, factor,*charge_parameters(response),int(pulse['record']))
    levels = 2**resolved['digitizer']['adc_bits']
    bandwidth = settings['input_bandwidth_MHz']
    pole = 1000/(2*np.pi*bandwidth) if bandwidth else 0.
    clipped = ct.c_int()
    rc = fn(times.ctypes.data, background.ctypes.data, len(times), descriptors, len(selected),
            pole, settings['voltage_min_mV'], settings['voltage_max_mV'],
            settings['full_range_mV']/levels, levels, output.ctypes.data, ct.byref(clipped))
    if rc:
        raise ValueError(f'ADC waveform evaluation failed ({rc}).')
    return bool(clipped.value)
