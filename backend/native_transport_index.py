# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Validated file streaming into compact M2 indexes; no PE/ancestry pool in RAM."""
import ctypes as ct
from concurrent.futures import ThreadPoolExecutor
import json
import math
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .analog_pmt import native_library,tail_span
from .execution import resolve_threads
from .streams import StreamError,_detector_counts,_origin_counts,_response_counts,_check_identities

class Arrays(ct.Structure):
    _fields_=[(name,ct.c_void_p) for name in ('values','starts','spans','peaks','prefixes','index','provenance','flags','origins')]
class Summary(ct.Structure):
    _fields_=[('interaction',ct.c_uint64*2),('response',ct.c_uint64*2),('origins',ct.c_uint64*8),('eligible',ct.c_uint64*2),('maximum',ct.c_double*2),('eligible_maximum',ct.c_double*2)]

class ReferenceValidation(Exception):pass

def read_windows(source,size,header_end):
    """Read sequentially while a validated window is being consumed."""
    block_size=min(64*1024*1024,size)
    buffers=[np.empty(block_size,dtype=np.uint8) for _ in range(2)]
    def read(offset,buffer):
        source.seek(offset)
        length=source.readinto(buffer)
        if length!=min(block_size,size-offset):raise ReferenceValidation('Incomplete transport stream')
        return buffer,length
    offset=header_end//block_size*block_size
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='M2-input') as executor:
        slot=0;pending=executor.submit(read,offset,buffers[slot])
        while offset<size:
            buffer,length=pending.result()
            next_offset=offset+length;slot=1-slot
            if next_offset<size:pending=executor.submit(read,next_offset,buffers[slot])
            yield offset,buffer,length
            offset=next_offset

def binding():
    lib=native_library()
    if lib is None or not hasattr(lib,'tp_transport_index_sorted_onsets'):return None
    if not getattr(lib,'_transport_index_bound',False):
        lib.tp_transport_index_map.argtypes=[ct.c_void_p,ct.c_uint64,ct.c_char_p,ct.POINTER(Arrays)];lib.tp_transport_index_map.restype=ct.c_void_p
        lib.tp_transport_index_window.argtypes=[ct.c_void_p,ct.c_void_p,ct.c_uint64,ct.c_uint,ct.POINTER(ct.c_uint64),ct.POINTER(ct.c_uint64),ct.POINTER(Summary)]
        lib.tp_transport_index_window.restype=ct.c_int
        lib.tp_transport_index_sorted_onsets.argtypes=[ct.c_void_p,ct.c_uint64,ct.c_void_p,ct.c_uint64]
        lib.tp_transport_index_sorted_onsets.restype=ct.c_int
        for name in ('footer','error'):
            fn=getattr(lib,'tp_transport_index_'+name);fn.argtypes=[ct.c_void_p];fn.restype=ct.c_char_p
        lib.tp_transport_index_destroy.argtypes=[ct.c_void_p];lib.tp_transport_index_destroy.restype=None
        lib._transport_index_bound=True
    return lib

def check_footer(footer,summary,count):
    detectors={'interaction':list(summary.interaction),'response':list(summary.response)}
    origins=[list(summary.origins[:4]),list(summary.origins[4:])]
    for key,actual,check in (('detector_counts',detectors,_detector_counts),('pulse_origin_counts',origins,_origin_counts),('eligible_response_counts',list(summary.eligible),_response_counts)):
        if key in footer and check(footer[key],count)!=actual:raise StreamError(f'{key} summary disagrees with event records')
    if 'eligible_maximum_mV' in footer and footer['eligible_maximum_mV']!=list(summary.eligible_maximum):raise StreamError('Energy-selected anode maxima disagree with event records')
    if 'cascade_pair_counts' in footer:_detector_counts(footer['cascade_pair_counts'],count)
    if 'observed_maximum_mV' in footer:
        values=footer['observed_maximum_mV']
        if not isinstance(values,list) or len(values)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):raise StreamError('Invalid observed anode maxima')
        if any(not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12) for a,b in zip(values,summary.maximum)):raise StreamError('Observed anode maxima disagree with event records')

def load(info,cancel,progress):
    from .m2_physics import AnalogLibrary
    _check_identities([SimpleNamespace(header=s['header']) for s in info['streams']])
    lib=binding();total=sum(info['counts'])
    budget=resolve_threads(info.get('_threads',0),max(1,total//1024))
    parallel=budget>=4 and min(info['counts'])>=8192 and info.get('_retain_input_maps',False)
    if parallel:budget=max(1,budget//2)
    libraries=[AnalogLibrary(Path(s['path']),n,s['header']['analog_response'])
               for s,n in zip(info['streams'],info['counts'])]
    processed=[0]*len(libraries);lock=threading.Lock();abort=threading.Event()
    def publish(role,count):
        with lock:
            processed[role]=count;progress(sum(processed)/total)
    def read_stream(role):
        stream=info['streams'][role];library=libraries[role]
        path=library.path;count=len(library);header=stream['header']
        flags=np.empty((count,2),dtype=np.uint32)
        prefixes=np.empty((count,15),dtype=np.float64) if info['isotope']=='co60' else None
        arrays=Arrays(library.values.ctypes.data,library.start.ctypes.data,library.span.ctypes.data,library.peaks.ctypes.data,prefixes.ctypes.data if prefixes is not None else None,library.index.ctypes.data,library.provenance_index.ctypes.data,flags.ctypes.data,library.light_origins.ctypes.data)
        config=json.dumps(dict(header=header,count=count,tails=[tail_span(r['order'],r['tau_ns']) for r in library.responses]),allow_nan=False).encode()
        workers=min(16,budget, max(1,count//1024))
        with path.open('rb',buffering=0) as source:
            library.map=np.memmap(source,mode='r',dtype='u1')
            handle=lib.tp_transport_index_map(library.map.ctypes.data,library.map.nbytes,config,ct.byref(arrays))
            if not handle:raise ReferenceValidation('Native input initialization requires reference validation')
            packed=None
            try:
                if info.get('_pack_onsets') and count>=8192:
                    try:
                        library.onset_folder=tempfile.TemporaryDirectory(prefix='twinpals-m2-')
                        packed_path=Path(library.onset_folder.name)/'onsets.bin'
                        packed=packed_path.open('wb',buffering=0)
                        library.onset_offsets=np.empty(count,dtype=np.uint64)
                    except OSError:packed=None
                seen=ct.c_uint64();offset=ct.c_uint64();summary=Summary()
                header_end=12+int.from_bytes(library.map[8:12].tobytes(),'little')
                for start,buffer,size in read_windows(source,library.map.nbytes,header_end):
                    cancel()
                    if abort.is_set():raise ReferenceValidation('Input preparation stopped')
                    if offset.value>=start+size:continue
                    offset.value=start
                    first=seen.value
                    code=lib.tp_transport_index_window(handle,buffer.ctypes.data,size,workers,ct.byref(offset),ct.byref(seen),ct.byref(summary))
                    publish(role,seen.value)
                    if code<0:raise ReferenceValidation(lib.tp_transport_index_error(handle).decode('utf-8',errors='replace'))
                    if packed is not None and seen.value>first:
                        counts=library.index[first:seen.value,1:].sum(axis=1)
                        ends=np.cumsum(counts,dtype=np.uint64)
                        total_hits=int(ends[-1])
                        if packed.tell()+total_hits*8>512*1024*1024:
                            packed.close();packed=None
                        else:
                            library.onset_offsets[first:seen.value]=packed.tell()+(ends-counts)*8
                            onsets=np.empty(total_hits,dtype='<f8')
                            if lib.tp_transport_index_sorted_onsets(handle,first,onsets.ctypes.data,total_hits):
                                raise ReferenceValidation('Inconsistent analog onset counts')
                            try:
                                if packed.write(onsets)!=onsets.nbytes:raise OSError('Incomplete optional onset cache')
                            except OSError:packed.close();packed=None
                    if code==1:break
                else:raise ReferenceValidation('Incomplete transport stream')
                footer=json.loads(lib.tp_transport_index_footer(handle))
                check_footer(footer,summary,count)
                library.verified_frame_crcs=bool(info.get('_retain_input_maps'))
                if packed is not None and packed.tell():
                    try:
                        packed.close();packed=None
                        library.onset_map=np.memmap(packed_path,mode='r',dtype='u1')
                    except OSError:pass
            finally:
                if packed is not None:packed.close()
                lib.tp_transport_index_destroy(handle)
                if library.onset_map is None and library.onset_folder is not None:
                    library.onset_folder.cleanup();library.onset_folder=None;library.onset_offsets=None
        # A caller inspecting summaries alone must be able to replace its
        # file. Only a running acquisition keeps the validated mapping.
        if not library.verified_frame_crcs:
            library.map._mmap.close();library.map=None
        return prefixes,flags
    try:
        if parallel:
            with ThreadPoolExecutor(max_workers=2,thread_name_prefix='M2-transport') as pool:
                futures=[pool.submit(read_stream,role) for role in range(len(libraries))]
                try:metadata=[f.result() for f in futures]
                except BaseException:
                    abort.set()
                    raise
        else:
            metadata=[read_stream(role) for role in range(len(libraries))]
        if info['isotope']=='co60':
            (first_prefixes,first_flags),(prefixes,flags)=metadata
            if not np.array_equal(first_prefixes,prefixes):raise StreamError('Co-60 cascade kinematics disagree between streams. Do not shuffle unpaired cascade files.')
            counts={'interaction':[int(np.count_nonzero((first_flags[:,ch]&258).astype(bool)&(flags[:,1-ch]&258).astype(bool))) for ch in range(2)],
                    'response':[int(np.count_nonzero((libraries[0].values[:,2*ch]>0)&(libraries[1].values[:,2*(1-ch)]>0))) for ch in range(2)]}
            if info.get('directional_combinations') is not None and info['directional_combinations']!=counts:raise StreamError('Co-60 cascade pair summary does not match the recorded events.')
        progress(1.);return libraries
    except BaseException:
        for library in libraries:library.close()
        raise
