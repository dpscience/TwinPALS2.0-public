# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded, CRC-checked readers and histogram analysis for TPSTRM07.

Every analysis holds file handles at their initial sizes for both passes. Appended
events are picked up by the next analysis; an incomplete last .part frame is not
invented or counted. No complete file is materialized as event objects.
"""
from __future__ import annotations

import bisect
from contextlib import ExitStack
import json
import hashlib
import math
import os
from pathlib import Path
import struct
from typing import BinaryIO, Iterator
import zlib

MAGIC = b'TPSTRM07'
PREFIX = struct.Struct('<QI15d')
DETECTOR = struct.Struct('<IQ7dQI2dQ')
EVENT_BYTES = PREFIX.size + 2*DETECTOR.size
FRAME = struct.Struct('<4sII')
MAX_HEADER = 64 * 1024 * 1024
MAX_FRAME = 16 * 1024 * 1024
METRICS = {'energy': 'keV', 'mean_arrival': 'ns', 'photon_count': 'photoelectrons',
           'depth': 'mm', 'polar_angle': 'deg', 'azimuth': 'deg',
           'track_length': 'mm', 'reflections': 'reflections', 'cathode_reflections': 'reflections', 'pulse_height': 'mV'}
ROLES = {'na22_prompt': 'Na-22 1275 keV', 'na22_annihilation': 'Na-22 511 keV pair',
         'co60_1173': 'Co-60 1173 keV', 'co60_1332': 'Co-60 1332 keV'}

class StreamError(ValueError):
    """A stream cannot be interpreted without changing or losing information."""

class AnalysisCancelled(StreamError):
    """The caller stopped a bounded analysis scan."""


def frame_crc32(payload):
    # zlib releases the GIL for >5 KiB. These tiny native checks otherwise pay a
    # thread handoff per event under live plotting. Larger buffers still release
    # it normally; the small-buffer path uses the identical IEEE polynomial.
    if 5120<len(payload)<=131072:
        from .analog_pmt import native_library
        function=getattr(native_library(),'tp_stream_crc32',None)
        if function is not None:return function(payload,len(payload))
    return zlib.crc32(payload)


def analog_payload(payload, event_id):
    """Validate paired raw PE times/onsets; return zero-copy detector arrays."""
    import numpy as np
    if len(payload)<16: raise StreamError('Incomplete analog pulse frame')
    identifier,a,b=struct.unpack_from('<QII',payload)
    if identifier!=event_id: raise StreamError('Analog pulse IDs must be ascending and match their event records')
    if len(payload)!=16+34*(a+b): raise StreamError('Analog pulse count/length mismatch')
    if not (a or b):
        empty=np.empty((0,6),dtype='<f8')
        return empty,empty
    values=np.frombuffer(payload,dtype='<f8',offset=16,count=4*(a+b)).reshape(-1,4)
    if not np.isfinite(values).all() or np.any(values[:,0]<-1e-9): raise StreamError('Invalid photoelectron arrival/onset time')
    tags=np.frombuffer(payload,dtype='u1',offset=16+32*(a+b)).reshape(-1,2)
    if np.any((tags[:,0]!=1)&(tags[:,0]!=2)):raise StreamError('Invalid photon production mechanism')
    values=np.column_stack((values,tags))
    return values[:a],values[a:]

def _check_cancel(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise AnalysisCancelled('Analysis cancelled')

def _json(data: bytes):
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StreamError(f'Invalid stream JSON: {exc}') from exc
    if not isinstance(value, dict):
        raise StreamError('Stream JSON block must be an object')
    return value

def _open_shared_read(path):
    """Let the writer rename .part on Windows while a snapshot remains open."""
    if os.name != 'nt':
        return Path(path).open('rb')
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    return os.fdopen(descriptor, 'rb')

def response_calibration(responses):
    """Two optical roles share the tube calibration but have independent charge draws."""
    return [{k:v for k,v in r.items() if k!='charge_seed'} for r in responses]


def validate_analog_responses(responses):
    """Shared M1/M2 immutable analytic-response contract."""
    if not isinstance(responses,list) or len(responses)!=2: raise StreamError('The stream requires both analog PMT response snapshots')
    from .analog_pmt import MODEL, SPE_MODEL, GAMMA_MODEL, GAMMA_SPE_MODEL, WEIGHTED_MODELS, charge_law
    for r in responses:
        if (not isinstance(r,dict) or r.get('model') not in (MODEL,SPE_MODEL,GAMMA_MODEL,GAMMA_SPE_MODEL)
                or type(r.get('order')) not in (float,int) or not 2<=r['order']<=32
                or (r['model'] in (MODEL,SPE_MODEL) and type(r['order']) is not int)
                or r.get('polarity') not in ('positive','negative')): raise StreamError('Invalid analog PMT model')
        if r['model'] in WEIGHTED_MODELS:
            spread=r.get('spe_charge_spread_percent')
            if (type(spread) not in (float,int) or not 0<spread<100 or
                    type(r.get('charge_seed')) is not int or not 0<=r['charge_seed']<2**53):
                raise StreamError('Invalid single-photoelectron charge spread or seed')
            for k,expected in zip(('charge_cutoff','charge_scale'),charge_law(spread)):
                if type(r.get(k)) not in (int,float) or not math.isclose(r[k],expected,rel_tol=1e-10,abs_tol=1e-12 if k=='charge_cutoff' else 0.):
                    raise StreamError('Invalid single-photoelectron charge distribution')
        elif any(k in r for k in ('charge_cutoff','charge_scale','charge_seed')):
            raise StreamError('Fixed-charge PMT snapshot contains parameters for a different charge model')
        for key in ('tau_ns','charge_C','load_ohm','voltage_scale_mV'):
            if not isinstance(r.get(key),(int,float)) or not math.isfinite(r[key]) or r[key]<=0: raise StreamError('Invalid analog PMT parameter: '+key)
        if not math.isclose(r['voltage_scale_mV'],r['charge_C']*r['load_ohm']*1e12,rel_tol=1e-10): raise StreamError('PMT charge and voltage/load reference disagree')


def minimum_energy(header):
    physics=header.get('physics')
    if not isinstance(physics,dict) or type(physics.get('include_cherenkov')) is not bool:
        raise StreamError('Stream physics settings are missing or invalid. Run Module 1 again.')
    value=physics.get('minimum_energy_keV')
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise StreamError('Invalid minimum deposited energy in stream physics settings')
    for settings in (header.get('profile',{}), header.get('resolved',{})):
        if 'physics' in settings and settings['physics']!=physics:
            raise StreamError('Stream physics settings disagree with the saved setup')
    return value


def _header(file: BinaryIO, limit: int):
    file.seek(0)
    if limit < 12 or file.read(8) != MAGIC:
        raise StreamError('This file is not a current TwinPALS analog stream. Generate a new Module 1 stream to record separate crystal/window and photocathode reflection counts.')
    length, = struct.unpack('<I', file.read(4))
    if length > MAX_HEADER or length + 12 > limit:
        raise StreamError('Invalid or incomplete stream header')
    header = _json(file.read(length))
    if header.get('format') != 'twinpals-stream' or header.get('version') != 7:
        raise StreamError('Unsupported stream format or version')
    components=header.get('light_components')
    if not isinstance(components,list) or not 1<=len(components)<=256 or any(not isinstance(c,dict) or c.get('id')!=i or not all(isinstance(c.get(k),str) and c[k] for k in ('volume','label','material')) for i,c in enumerate(components)):
        raise StreamError('Invalid light-origin component dictionary')
    validate_analog_responses(header.get('analog_response'))
    minimum_energy(header)
    if header.get('role') not in ROLES:
        raise StreamError('Unsupported stream primary role')
    if 'settings_sha256' in header:
        expected = header['settings_sha256']
        if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdefABCDEF' for c in expected):
            raise StreamError('Invalid settings SHA-256 in stream header')
        if not isinstance(header.get('profile'),dict):
            raise StreamError('Settings SHA-256 requires an embedded profile')
        # Same canonical JSON convention as m1_store.encode; no import cycle.
        canonical = json.dumps(header['profile'],ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
        if hashlib.sha256(canonical.encode('utf-8')).hexdigest() != expected.lower():
            raise StreamError('Embedded profile does not match its settings SHA-256')
    return header, length + 12

def _check_identities(snapshots):
    stream_ids = []
    for snapshot in snapshots:
        header = snapshot.header
        for field in ('stream_id','run_id'):
            if field in header and (not isinstance(header[field],str) or not header[field]):
                raise StreamError(f'Invalid {field} in stream header')
        if 'stream_id' in header: stream_ids.append(header['stream_id'])
    if len(set(stream_ids)) != len(stream_ids):
        raise StreamError('The same stream_id was selected more than once; copied stream files cannot be counted twice')
    for field,label in (('run_id','simulation runs'),('settings_sha256','setup profiles')):
        values = {snapshot.header[field].lower() if field=='settings_sha256' else snapshot.header[field]
                  for snapshot in snapshots if field in snapshot.header}
        if len(values)>1:
            raise StreamError(f'Cannot combine streams from different {label}')

def _completion(status='incomplete', events=None, *, verified=False, **extra):
    return {'status': status, 'events': events, 'verified': verified, **extra}

def _detector_counts(value, count):
    if not isinstance(value,dict) or set(value)!={'interaction','response'}:
        raise StreamError('Invalid detector count summary')
    for row in value.values():
        if not isinstance(row,list) or len(row)!=2 or any(type(v) is not int or not 0<=v<=count for v in row):
            raise StreamError('Invalid detector count summary')
    return value

def _origin_counts(value,count):
    if not isinstance(value,list) or len(value)!=2 or any(not isinstance(row,list) or len(row)!=4 or any(type(n) is not int or n<0 for n in row) or sum(row)!=count for row in value):
        raise StreamError('Invalid pulse origin summary')
    return value

def _response_counts(value,count):
    if not isinstance(value,list) or len(value)!=2 or any(type(n) is not int or not 0<=n<=count for n in value):
        raise StreamError('Invalid eligible response summary')
    return value

def read_done_footer(file: BinaryIO, limit: int, start: int, max_tail: int):
    """Read the CRC-checked terminal JSON frame without replaying prior events."""
    available = min(limit - start, max_tail)
    size = min(65536, available)
    while size:
        file.seek(limit - size)
        tail = file.read(size)
        offset = tail.rfind(b'DONE')
        while offset >= 0:
            begin = offset + FRAME.size
            if begin <= len(tail):
                _, length, crc = FRAME.unpack_from(tail, offset)
                if begin + length == len(tail):
                    payload = tail[begin:]
                    if zlib.crc32(payload) != crc:
                        raise StreamError('Footer CRC mismatch')
                    return _json(payload)
            offset = tail.rfind(b'DONE', 0, offset)
        if size == available:
            break
        size = min(size * 2, available)
    return None

def _tail_completion(file: BinaryIO, limit: int, start: int):
    done = read_done_footer(file, limit, start, 65536)
    if done is None:
        return _completion()
    if done.get('status') not in ('completed', 'cancelled') or type(done.get('events')) is not int or done['events'] < 0:
        raise StreamError('Invalid DONE footer')
    extra={}
    for key,check in (('pulse_origin_counts',_origin_counts),('eligible_response_counts',_response_counts)):
        if key in done:extra[key]=check(done[key],done['events'])
    for key in ('detector_counts','cascade_pair_counts'):
        if key in done:extra[key]=_detector_counts(done[key],done['events'])
    for key in ('observed_maximum_mV','eligible_maximum_mV'):
        if key in done:
            values=done[key]
            if not isinstance(values,list) or len(values)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):raise StreamError('Invalid observed anode maxima')
            extra[key]=values
    return _completion(done['status'], done['events'],**extra)

def inspect_stream(path):
    path = Path(path).resolve()
    with _open_shared_read(path) as file:
        limit = os.fstat(file.fileno()).st_size
        header, start = _header(file, limit)
        completion = _tail_completion(file, limit, start)
    if path.suffix != '.part' and completion['status'] != 'completed':
        raise StreamError('A completed .tpstream needs a valid completed DONE footer')
    return {'path': str(path), 'header': header, 'completion': completion, 'snapshot_bytes': limit}

class _Snapshot:
    def __init__(self, path: Path, file: BinaryIO):
        self.path, self.file = path, file
        self.limit = os.fstat(file.fileno()).st_size
        self.header, self.start = _header(file, self.limit)
        self.completion = _completion()
        self.digest = None

    def events(self) -> Iterator[tuple]:
        file = self.file
        if os.fstat(file.fileno()).st_size < self.limit:
            raise StreamError('Stream was truncated during analysis')
        header, start = _header(file, self.limit)
        if header != self.header or start != self.start:
            raise StreamError('Stream header changed during analysis')
        file.seek(self.start)
        count = 0
        observed=[0.,0.]
        eligible_maxima=[0.,0.]
        threshold=minimum_energy(self.header)
        detector_counts={'interaction':[0,0],'response':[0,0]}
        origin_counts=[[0]*4 for _ in range(2)];eligible_counts=[0,0]
        digest = hashlib.sha256()
        footer = None
        truncated = False
        analog = None
        provenance = None
        while file.tell() < self.limit:
            if footer is not None:
                raise StreamError('Unexpected bytes after DONE footer')
            remaining = self.limit - file.tell()
            if remaining < FRAME.size:
                truncated = True; break
            frame_header = file.read(FRAME.size)
            digest.update(frame_header)
            tag, length, crc = FRAME.unpack(frame_header)
            if length > MAX_FRAME:
                raise StreamError('Frame exceeds the 16 MiB format limit')
            if length > self.limit - file.tell():
                truncated = True; break
            payload = file.read(length)
            digest.update(payload)
            if len(payload) != length:
                raise StreamError('Stream changed or truncated during reading')
            if frame_crc32(payload) != crc:
                raise StreamError(f'CRC mismatch at frame ending byte {file.tell()}')
            if tag == b'APLS':
                if analog is not None: raise StreamError('Analog frame has no matching detector record')
                analog=analog_payload(payload,count)
                self.analog_offset=file.tell()-length
                self.analog_length=length
            elif tag == b'PROV':
                if provenance is not None or analog is None: raise StreamError('Unpaired transport ancestry')
                from .provenance import decode
                provenance=decode(payload,count,[len(a) for a in analog],len(self.header['light_components']))
                self.provenance_offset=file.tell()-length
                self.provenance_length=length
            elif tag == b'EVNT':
                if length != EVENT_BYTES:
                    raise StreamError(f'EVNT record must contain exactly {EVENT_BYTES} bytes')
                if analog is None: raise StreamError('Event has no analog pulse frame')
                prefix = PREFIX.unpack_from(payload)
                if prefix[0] != count:
                    raise StreamError('Event IDs must form an ascending sequence starting at zero')
                if prefix[1] not in (1, 3, 6) or not all(math.isfinite(v) for v in prefix[2:]):
                    raise StreamError('Invalid event primary mask or nonfinite kinematics')
                expected_mask = {'na22_prompt':1,'na22_annihilation':6,'co60_1173':3,'co60_1332':3}.get(self.header['role'])
                if expected_mask is not None and prefix[1] != expected_mask:
                    raise StreamError('Primary mask disagrees with the stream source role')
                directions = (prefix[5:8], prefix[8:11], prefix[11:14])
                for i, direction in enumerate(directions):
                    norm = sum(v*v for v in direction)
                    if (prefix[1] & (1 << i) and abs(norm-1) > 1e-7) or (not prefix[1] & (1 << i) and norm != 0):
                        raise StreamError('Primary directions must be unit vectors, inactive slots zero')
                    if prefix[14+i] < 0 or (not prefix[1] & (1 << i) and prefix[14+i] != 0):
                        raise StreamError('Invalid primary emission time')
                if prefix[1] == 6 and (any(abs(a+b)>1e-7 for a,b in zip(directions[1],directions[2])) or prefix[15] != prefix[16]):
                    raise StreamError('Na-22 annihilation-pair directions/times are inconsistent')
                ds = (DETECTOR.unpack_from(payload, PREFIX.size), DETECTOR.unpack_from(payload, PREFIX.size+DETECTOR.size))
                for i,d in enumerate(ds):
                    flags, hits = d[:2]
                    if flags & ~255 or bool(flags&48)!=bool(hits) or not all(math.isfinite(v) for v in d[2:9]):
                        raise StreamError('Invalid DetectorInfo flags or nonfinite values')
                    if d[2] < 0 or d[3] < -1e-9 or d[7] < -1e-9 or d[8] < 0:
                        raise StreamError('Negative detector energy, arrival time or path length')
                    if bool(flags & 1) != bool(hits) or bool(flags & 4) != (d[2] >= threshold):
                        raise StreamError('DetectorInfo validity flag disagrees with count/energy')
                    if not hits and (d[3] != 0 or d[8] != 0):
                        raise StreamError('Missing mean/path values must use zero and unset validity flag')
                    if not flags & 2 and any(d[4:8]):
                        raise StreamError('Missing interaction must use zero coordinates/time')
                    if len(analog[i])!=hits or (hits and not math.isclose(float(analog[i][:,0].mean()),d[3],rel_tol=1e-10,abs_tol=1e-9)):
                        raise StreamError('Photoelectron times disagree with DetectorInfo count/mean')
                    from .light_origin import validate
                    validate(analog[i],flags,self.header)
                    if not all(math.isfinite(v) for v in d[11:13]) or d[11]>0 or d[12]<0 or (not hits and any(d[11:13])):
                        raise StreamError('Invalid analog voltage extrema')
                    if (self.header['analog_response'][i]['polarity']=='negative' and d[12]!=0) or (self.header['analog_response'][i]['polarity']=='positive' and d[11]!=0):raise StreamError('Anode extrema disagree with pulse polarity')
                    observed[i]=max(observed[i],-d[11],d[12])
                    if flags&4:eligible_maxima[i]=max(eligible_maxima[i],-d[11],d[12])
                    detector_counts['interaction'][i]+=int(bool(flags&2) or d[2]>0)
                    detector_counts['response'][i]+=int(hits>0)
                    origin_counts[i][(flags>>4)&3]+=1
                    eligible_counts[i]+=int(hits>0 and bool(flags&4))
                if provenance is None: raise StreamError('Event has no transport ancestry')
                self.provenance=provenance
                provenance=None
                self.analog=analog
                analog=None
                count += 1
                yield prefix, ds
            elif tag == b'TRAK':
                _json(payload)  # sampled preview only; never retained by histogram scans
            elif tag == b'DONE':
                if analog is not None: raise StreamError('Unpaired analog pulse at completion')
                footer = _json(payload)
                if footer.get('status') not in ('completed', 'cancelled') or type(footer.get('events')) is not int or footer['events'] != count:
                    raise StreamError('DONE status/count does not match verified event records')
            else:
                raise StreamError(f'Unknown stream frame tag {tag!r}')
        if footer is None and self.path.suffix != '.part':
            raise StreamError('Completed stream has no valid DONE footer')
        if footer is not None and footer['status'] != 'completed' and self.path.suffix != '.part':
            raise StreamError('Cancelled stream must keep its .part extension')
        if self.digest is not None and self.digest != digest.digest():
            raise StreamError('Previously written stream frames changed during analysis')
        self.digest = digest.digest()
        self.completion = _completion(footer['status'] if footer else 'incomplete', count, verified=True,
                                      truncated_tail=truncated, snapshot_bytes=self.limit)
        if footer and 'detector_counts' in footer and _detector_counts(footer['detector_counts'],count)!=detector_counts:
            raise StreamError('Detector count summary disagrees with event records')
        self.completion['detector_counts']=detector_counts
        for key,value,check in (('pulse_origin_counts',origin_counts,_origin_counts),('eligible_response_counts',eligible_counts,_response_counts)):
            if footer and key in footer and check(footer[key],count)!=value:raise StreamError('Pulse origin/eligible count summary disagrees with event records')
            self.completion[key]=value
        if footer and 'eligible_maximum_mV' in footer and footer['eligible_maximum_mV']!=eligible_maxima:
            raise StreamError('Energy-selected anode maxima disagree with event records')
        self.completion['eligible_maximum_mV']=eligible_maxima
        if footer and 'cascade_pair_counts' in footer:
            self.completion['cascade_pair_counts']=_detector_counts(footer['cascade_pair_counts'],count)
        if footer and 'observed_maximum_mV' in footer:
            values=footer['observed_maximum_mV']
            if not isinstance(values,list) or len(values)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):raise StreamError('Invalid observed anode maxima')
            if any(not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12) for a,b in zip(values,observed)):raise StreamError('Observed anode maxima disagree with event records')
            self.completion['observed_maximum_mV']=values

    def info(self):
        return {'path': str(self.path), 'header': self.header, 'completion': self.completion,
                'snapshot_bytes': self.limit}

def validate_complete(path):
    path = Path(path).resolve()
    with _open_shared_read(path) as file:
        snapshot = _Snapshot(path, file)
        for _ in snapshot.events():
            pass
        if snapshot.completion['status'] != 'completed':
            raise StreamError('Stream is not complete')
        return snapshot.completion

def _pose(header, detector):
    resolved = header.get('resolved', {})
    detectors = resolved.get('detectors', [])
    if len(detectors) != 2:
        raise StreamError('Depth/angular analysis requires the embedded resolved detector poses')
    d = detectors[detector]
    front, axis = d.get('front_mm'), d.get('axis')
    if not isinstance(front, list) or not isinstance(axis, list) or len(front) != 3 or len(axis) != 3:
        raise StreamError('Missing resolved detector position or axis')
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in front + axis):
        raise StreamError('Invalid detector pose')
    length = math.sqrt(sum(x*x for x in axis))
    if length == 0:
        raise StreamError('Detector axis cannot be zero')
    return front, [x/length for x in axis]

def _selected_category(ds, category, detector=None):
    if category in ('interaction','transmission','miss'):
        d=ds[detector]
        interaction=bool(d[0]&2) or d[2]>0
        crossing=bool(d[0]&8)
        return interaction if category=='interaction' else (crossing and not interaction) if category=='transmission' else not (crossing or interaction)
    a, b = (d[1] > 0 and bool(d[0]&4) for d in ds)
    return category == 'all' or category == ('both' if a and b else 'A' if a else 'B' if b else 'none')

def _values(metric, prefix, d, role, pose, origin="all"):
    from .light_origin import selected
    if not selected(d[0],origin):return ()
    if not d[0]&4: return ()
    if metric == 'energy': return (d[2],)
    if metric == 'photon_count': return (d[1],)
    if metric == 'pulse_height': return (max(-d[11],d[12]),)
    if metric == 'reflections': return (d[9],)
    if metric == 'cathode_reflections': return (d[13],)
    if metric == 'mean_arrival': return (d[3],) if d[0] & 1 else ()
    if metric == 'track_length': return (d[8],) if d[0] & 1 else ()
    if metric == 'depth':
        return (sum((p-f)*a for p,f,a in zip(d[4:7],pose[0],pose[1])),) if d[0] & 2 else ()
    slots = [1,2] if role == 'na22_annihilation' else [1] if role == 'co60_1332' else [0]
    values = []
    for slot in slots:
        if not prefix[1] & (1 << slot): continue
        direction = prefix[5+3*slot:8+3*slot]
        if metric == 'polar_angle': values.append(math.degrees(math.acos(max(-1, min(1, sum(a*b for a,b in zip(direction,pose[1])))))))
        else: values.append(math.degrees(math.atan2(direction[1],direction[0])))
    return tuple(values)

def analyze(paths, requestdict, cancel=None):
    _check_cancel(cancel)
    metric = requestdict.get('metric','energy')
    detector = requestdict.get('detector','all')
    primary = requestdict.get('primary','all')
    category = requestdict.get('category','all')
    bins = requestdict.get('bins',120)
    if metric not in METRICS or detector not in ('all','A','B') or category not in ('all','none','A','B','both','interaction','transmission','miss'):
        raise StreamError('Unknown metric, detector or event category')
    if type(bins) is not int or not 1 <= bins <= 4096:
        raise StreamError('Histogram bins must be an integer from 1 to 4096')
    chosen_range = requestdict.get('range')
    if chosen_range is not None and (not isinstance(chosen_range,(list,tuple)) or len(chosen_range)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in chosen_range) or chosen_range[1]<=chosen_range[0]):
        raise StreamError('Histogram range must contain finite increasing limits')
    paths = [Path(p).resolve() for p in paths]
    if not paths or len(paths)>32:
        raise StreamError('Select one to 32 stream files')
    if len({os.path.normcase(str(p)) for p in paths}) != len(paths):
        raise StreamError('The same stream was selected more than once')
    indices = (0,1) if detector == 'all' else (0,) if detector == 'A' else (1,)
    warnings = ['Crystal outcome is evaluated independently for each plotted detector; optical origin and the saved minimum-energy selection are separate.']
    positions = []
    with ExitStack() as stack:
        snapshots = [_Snapshot(p, stack.enter_context(_open_shared_read(p))) for p in paths]
        _check_identities(snapshots)
        roles = {s.header['role'] for s in snapshots}
        if primary != 'all' and primary not in roles:
            raise StreamError('Selected primary type does not exist in these streams')
        active = [s for s in snapshots if primary == 'all' or s.header['role'] == primary]
        poses = {(id(s),d):_pose(s.header,d) for s in active for d in indices} if metric in ('depth','polar_angle') else {}
        series = {}
        for s in active:
            role = s.header['role']
            for d in indices:
                key = role + ':' + 'AB'[d]
                series.setdefault(key,dict(key=key,label=f'{ROLES.get(role,role)} · Detector {"AB"[d]}',detector='AB'[d],primary=role,
                    edges=[],counts=[0]*bins,events=0,valid=0,missing=0,underflow=0,overflow=0))
        low, high = math.inf, -math.inf
        total_events = 0
        # First pass validates every selected stream, even if its role is filtered.
        for s in snapshots:
            _check_cancel(cancel)
            role = s.header['role']; selected = s in active
            for prefix, ds in s.events():
                if prefix[0] % 1024 == 0: _check_cancel(cancel)
                if not selected: continue
                total_events += 1
                for d in indices:
                    if not _selected_category(ds,category,d): continue
                    row = series[role+':'+'AB'[d]]; row['events'] += 1
                    values = _values(metric,prefix,ds[d],role,poses.get((id(s),d)),requestdict.get("origin","all"))
                    row['valid'] += len(values)
                    if not values: row['missing'] += 1
                    for value in values: low=min(low,value); high=max(high,value)
                    if metric == 'depth' and values and len(positions)<5000:
                        positions.append(dict(detector='AB'[d],primary=role,event_id=prefix[0],x=ds[d][4],y=ds[d][5],z=ds[d][6],depth=values[0]))
        if chosen_range is not None: low,high=chosen_range
        elif low == math.inf: low,high=0.,1.
        elif low == high:
            half = .5 if metric in ('photon_count','reflections','cathode_reflections') else max(abs(low)*.01, .0005)
            low,high=low-half,high+half
        edges = [float(low+(high-low)*i/bins) for i in range(bins+1)]
        for row in series.values(): row['edges'] = edges
        _check_cancel(cancel)
        for s in active:
            _check_cancel(cancel)
            role=s.header['role']
            for prefix,ds in s.events():
                if prefix[0] % 1024 == 0: _check_cancel(cancel)
                for d in indices:
                    if not _selected_category(ds,category,d): continue
                    row=series[role+':'+'AB'[d]]
                    for value in _values(metric,prefix,ds[d],role,poses.get((id(s),d)),requestdict.get("origin","all")):
                        if value<low: row['underflow']+=1
                        elif value>high: row['overflow']+=1
                        else: row['counts'][min(bins-1,bisect.bisect_right(edges,value)-1)] += 1
        if any(s.completion['status']!='completed' for s in snapshots): warnings.append('Incomplete/cancelled streams: only verified complete event frames in each file-size snapshot are included.')
        if metric in ('polar_angle','azimuth') and 'na22_annihilation' in {s.header['role'] for s in active}:
            warnings.append('The intact Na-22 pair contributes two primary directions per event; valid counts directions, events counts events.')
        if metric == 'polar_angle': warnings.append('Polar angle is measured relative to each detector front-to-rear axis.')
        if metric == 'azimuth': warnings.append('Azimuth is measured in world XY from +X, in degrees [-180,180].')
        if metric == 'depth': warnings.append('Positions are a bounded first-5000 display sample in world mm; histograms use every valid first-gamma interaction. Depth is axial distance from the crystal front, not particle path length.')
        markers=[]
        if metric=='energy':
            energies=set()
            for s in active:
                energies.update({'na22_prompt':[1274.537],'na22_annihilation':[511.],'co60_1173':[1173.228],'co60_1332':[1332.492]}.get(s.header['role'],[]))
            for energy in sorted(energies):
                markers.extend([{'x':energy,'label':f'γ {energy:g} keV'}, {'x':energy*(1-1/(1+2*energy/510.99895)),'label':f'Compton edge ({energy:g} keV)'}])
        profiles=[s.header.get('profile') for s in active]
        profile=profiles[0] if profiles else None
        if any(p!=profile for p in profiles[1:]): warnings.append('Streams contain different setup profiles; each original profile remains in its stream header.')
        return dict(metric=metric,unit=METRICS[metric],series=list(series.values()),streams=[s.info() for s in snapshots],profile=profile,
                    total_events=total_events,complete=all(s.completion['status']=='completed' for s in snapshots),warnings=warnings,markers=markers,positions=positions)
