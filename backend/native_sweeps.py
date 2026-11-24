# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded native digitization, provenance and monitoring for accepted windows."""
import ctypes as ct
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
import sys
import threading
import weakref

import numpy as np

from .native_acquisition import Response


class FrameBuffers:
    """Reuse bounded frame storage only after its final buffer view is gone."""
    def __init__(self, budget=32*1024**2):
        self.budget=budget
        self.available={}
        self.retained=0
        self.lock=threading.Lock()

    def acquire(self, size):
        capacity=1 << (size-1).bit_length()
        if capacity>self.budget:
            return np.empty(size,dtype='u1')
        with self.lock:
            bucket=self.available.get(capacity)
            storage=bucket.pop() if bucket else None
            if storage is not None:
                self.retained-=capacity
        if storage is None:
            storage=np.empty(capacity,dtype='u1')
        # All NumPy slices and memoryviews retain this buffer exporter. A
        # writer can finish asynchronously after the originating worker exits.
        lease=(ct.c_ubyte*capacity).from_buffer(storage)
        weakref.finalize(lease,self._release,storage)
        return np.frombuffer(lease,dtype='u1',count=size)

    def _release(self, storage):
        size=storage.nbytes
        with self.lock:
            if self.retained+size<=self.budget:
                self.available.setdefault(size,[]).append(storage)
                self.retained+=size


class Input(ct.Structure):
    _fields_ = [('data', ct.c_void_p), ('size', ct.c_uint64), ('stride', ct.c_int)]


class Settings(ct.Structure):
    _fields_ = [(s, ct.c_int) for s in ('samples', 'switched', 'levels', 'coincidence')] + [
        (s, ct.c_double) for s in ('window', 'delay', 'dead', 'gate', 'pole', 'baseline',
                                   'jitter', 'irf', 'noise', 'low', 'high', 'lsb')]


ROW = np.dtype([('begin', '<u8'), ('end', '<u8'), ('keys_begin', '<u8'), ('keys_end', '<u8'),
                ('meta_size', '<u4'), ('classification', '<u4'), ('channels','<u4'), ('reserved','<u4')])


@lru_cache(maxsize=1)
def binding():
    root = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path = root / '.runtime/bin/twinpals-sweeps.dll'
    if not path.is_file():
        return None
    try:
        library = ct.CDLL(str(path))
        fn = library.tp_accepted_sweeps_v2
        library.tp_sweep_histories
        library.tp_copy_sweeps
        fn._dll = library
    except (OSError, AttributeError):
        return None
    ptr = ct.c_void_p
    library.tp_sweep_cache_create.argtypes=[]
    library.tp_sweep_cache_create.restype=ptr
    library.tp_sweep_cache_destroy.argtypes=[ptr]
    library.tp_sweep_cache_destroy.restype=None
    fn.argtypes = [ct.POINTER(Settings), ct.POINTER(Input), ct.POINTER(Response), ptr, ptr, ct.c_int,
                   ptr, ct.c_double, ct.c_double, ct.c_double, ptr, ptr, ct.c_uint64, ct.c_int,
                   ptr, ptr, ct.c_int, ptr, ct.c_uint64, ptr, ptr, ct.c_uint64, ptr, ptr,ptr]
    fn.restype = ct.c_int
    return fn


def configuration(resolved):
    p, device = resolved['profile'], resolved['digitizer']
    d, acq = p['digitization'], p['acquisition']
    levels = 2**device['adc_bits']
    pole = 1000/(2*np.pi*d['input_bandwidth_MHz']) if d['input_bandwidth_MHz'] else 0.
    settings = Settings(d['samples'], device['architecture']=='switched_capacitor', levels,
                        acq['trigger']=='coincidence', resolved['window_ns'], acq['trigger_delay_ns'],
                        acq['dead_ns'], acq['coincidence_ns'], pole, d['baseline_mV'],
                        d['aperture_jitter_ns'], d['irf_sigma_ns'], d['noise_sigma_mV'],
                        d['voltage_min_mV'], d['voltage_max_mV'], d['full_range_mV']/levels)
    responses = []
    for library in resolved['_libraries']:
        for r, ch in zip(library.responses, p['channels']):
            gain = 10**(-ch['attenuation_dB']/20)
            responses.append(Response(r['order'], -1 if r['polarity']=='negative' else 1,
                                      r['tau_ns'], r['voltage_scale_mV'], -gain if ch.get('invert') else gain))
    return settings, (Response*4)(*responses)


@dataclass
class SweepBatch:
    first: int
    rows: np.ndarray
    keys: np.ndarray
    crossings: np.ndarray
    features: np.ndarray
    densities: np.ndarray
    ranges: list
    frames: object
    window: float
    delay: float
    dead: float
    baseline: float
    coincidence: bool

    def record(self, i):
        from .waveform_workers import FrameMetadata, PreparedWaveform
        from .m2_physics import CLASS_NAMES
        begin,end,k0,k1,size,classification,_,_=self.rows[i].tolist()
        frame=bytes(memoryview(self.frames)[begin:end])
        at,ch,ca,cb=self.crossings[i].tolist()
        finish=at+self.delay
        accepted=[ca,cb] if self.coincidence else [at if k==ch else None for k in (0,1)]
        summary={'id':self.first+i,'class':CLASS_NAMES[classification],'start_ns':finish-self.window,
                 'trigger_ns':at,'busy_until_ns':finish+self.dead,'baseline_mV':[self.baseline]*2,
                 'accepted_crossings_ns':accepted}
        meta=FrameMetadata(summary,frame,size)
        data=np.frombuffer(frame,'<f4',offset=16+size).reshape(4,-1).view(PreparedWaveform)
        data.monitor_features=self.features[i]
        data.monitor_density=(self.ranges,[self.densities[i,ch] if r is not None else None
                                          for ch,r in enumerate(self.ranges)])
        data.stream_frame=frame
        data.transport_keys=self.keys[k0:k1].tolist()
        return meta,data


def sample_windows(resolved, arena, first, crossings, seeds, pulses, addresses, maximum_tail,
                   filter_tail, known, ranges, slot):
    from .m2_physics import CLASS_NAMES
    fn = binding()
    axes = resolved.get('_cell_axes')
    if fn is None or axes is None or len(crossings)==0:
        return None
    if '_sweep_config' not in resolved:
        resolved['_sweep_config'] = configuration(resolved)
    settings, responses = resolved['_sweep_config']
    maps = (Input*2)(*(Input(l.mapped.ctypes.data, l.mapped.nbytes, l.stride) for l in resolved['_libraries']))
    batch = len(seeds)
    rows = np.empty(batch, ROW)
    keys = np.empty((max(batch*8, len(pulses)), 3), dtype=np.uint64)
    features = np.empty((batch, 5))
    bins = next((r[2] for r in ranges if r is not None), 120)
    densities = np.full((batch, 2, bins), np.nan)
    coords = [None if r is None else r[0]+(np.arange(bins)+.5)*(r[1]-r[0])/bins for r in ranges]
    if slot is None:
        size=batch*(16*settings.samples+8192)
        pool=resolved.get('_frame_buffers')
        buffer=pool.acquire(size) if pool is not None else np.empty(size,dtype='u1')
    else:
        buffer = np.frombuffer(arena.buf, dtype='u1', count=slot[1]-slot[0], offset=slot[0])
    rc = fn(ct.byref(settings), maps, responses, axes.ctypes.data, pulses.ctypes.data, len(pulses),
            addresses.ctypes.data, maximum_tail, filter_tail, known, crossings.ctypes.data, seeds.ctypes.data,
            first, batch, *(v.ctypes.data if v is not None else None for v in coords), bins,
            buffer.ctypes.data, buffer.nbytes, rows.ctypes.data, keys.ctypes.data, len(keys),
            features.ctypes.data, densities.ctypes.data,resolved.get('_sweep_cache'))
    if rc>0:
        return None
    if rc<0:
        raise ValueError('Invalid waveform batch or transport data.')
    if resolved.get('_stream_batches'):
        used=int(rows[-1]['end'])
        frames=(slot[0],slot[0]+used) if slot is not None else buffer[:used]
        return SweepBatch(first,rows,keys[:int(rows[-1]['keys_end'])],crossings,features,densities,ranges,
                          frames,settings.window,settings.delay,settings.dead,settings.baseline,bool(settings.coincidence))
    details = []
    base = [settings.baseline]*2
    key_list = list(map(tuple, keys[:int(rows[-1]['keys_end'])].tolist()))
    for i, (begin, end, key_begin, key_end, size, classification, _, _) in enumerate(rows.tolist()):
        at, ch, ca, cb = crossings[i].tolist()
        finish = at+settings.delay
        accepted = [ca, cb] if settings.coincidence else [at if k==ch else None for k in (0, 1)]
        summary = dict(id=first+i, start_ns=finish-settings.window, trigger_ns=at,
                       busy_until_ns=finish+settings.dead, baseline_mV=base, accepted_crossings_ns=accepted)
        summary['class'] = CLASS_NAMES[classification]
        location = (slot[0]+begin, slot[0]+end) if slot is not None else buffer[begin:end].tobytes()
        details.append((summary, key_list[key_begin:key_end], size, location))
    return None, details, features, [densities[:, ch] if r is not None else None
                                    for ch, r in enumerate(ranges)], ranges
