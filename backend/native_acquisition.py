# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded native discriminator batches; waveform RNG and truth stay in Python."""
import ctypes as ct
import math
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import numpy as np
from .analog_pmt import native_library
from .execution import resolve_threads

PULSE = np.dtype([('time','<f8'),('origin','<f8'),('span','<f8'),('offset','<u8'),('count','<u8'),('role','<u4'),('channel','<u4')])

class Response(ct.Structure):
    _fields_=[('order',ct.c_int32),('polarity',ct.c_int32),('tau',ct.c_double),('scale',ct.c_double),('factor',ct.c_double)]
class Config(ct.Structure):
    _fields_=[(k,ct.c_double) for k in ('step','filter_tau','filter_tail','coincidence','delay','dead','stop_at','threshold_a','threshold_b')]+[('logic',ct.c_int32),('prune',ct.c_int32),('stride',ct.c_int32*2)]
class State(ct.Structure):
    _fields_=[(k,ct.c_double) for k in ('busy','trigger','cross_a','cross_b','previous_a','previous_b','cursor')]

class SourceLibrary(ct.Structure):
    _fields_=[(k,ct.c_void_p) for k in ('eligible','starts','spans','peaks','light')]+[('size',ct.c_uint64)]

class ScanLibraryIndex(ct.Structure):
    _fields_=[('index',ct.c_void_p),('onsets',ct.c_void_p),('records',ct.c_uint64)]

class SourceEmitter:
    def __init__(self,fn,libraries,channels):
        self.fn=fn
        self.masks=[(lib.values[:,0]>0).astype(np.uint8)+2*(lib.values[:,2]>0).astype(np.uint8) for lib in libraries]
        self.libraries=(SourceLibrary*2)(*(SourceLibrary(mask.ctypes.data,lib.start.ctypes.data,lib.span.ctypes.data,
                        lib.peaks.ctypes.data,lib.light_origins.ctypes.data,len(lib)) for mask,lib in zip(self.masks,libraries)))
        self.delays=(ct.c_double*2)(*(ch['cable_delay_ns'] for ch in channels))
        self.gains=(ct.c_double*2)(*(10**(-ch['attenuation_dB']/20) for ch in channels))

    def generate(self,first,a,b,times,lifetime,components):
        from .m2_physics import PULSE_DTYPE
        components=np.ascontiguousarray(components,dtype=np.uint16)
        output=np.empty(4*len(a),dtype=PULSE_DTYPE)
        count=self.fn(self.libraries,self.delays,self.gains,first,len(a),a.ctypes.data,b.ctypes.data,times.ctypes.data,
                      lifetime.ctypes.data,components.ctypes.data,output.ctypes.data)
        if count<0:raise ValueError('Source record index outside the transport library')
        return output[:count]

def binding():
    lib=native_library()
    if lib is None or not hasattr(lib,'tp_acquisition_scan_create'):return None
    if not getattr(lib,'_acquisition_bound',False):
        if hasattr(lib,'tp_scan_descriptors'):
            lib.tp_scan_descriptors.argtypes=[ct.c_void_p,ct.c_size_t,ct.POINTER(ScanLibraryIndex),
                                              ct.c_double,ct.c_void_p,ct.POINTER(ct.c_double)]
            lib.tp_scan_descriptors.restype=ct.c_int
        if hasattr(lib,'tp_source_pulses'):
            lib.tp_source_pulses.argtypes=[ct.POINTER(SourceLibrary),ct.POINTER(ct.c_double),ct.POINTER(ct.c_double),
                                           ct.c_uint64,ct.c_int]+[ct.c_void_p]*6
            lib.tp_source_pulses.restype=ct.c_int
        lib.tp_acquisition_scan_create.argtypes=[ct.c_void_p,ct.c_uint64,ct.c_void_p,ct.c_uint64,ct.c_void_p,ct.c_uint64,ct.POINTER(Response),ct.POINTER(Config),ct.POINTER(State),ct.c_uint64]
        lib.tp_acquisition_scan_create.restype=ct.c_void_p
        if hasattr(lib,'tp_acquisition_independent'):
            lib.tp_acquisition_independent.argtypes=lib.tp_acquisition_scan_create.argtypes+[ct.c_void_p,ct.c_int,ct.c_uint]
            lib.tp_acquisition_independent.restype=ct.c_int
        lib.tp_acquisition_scan_next.argtypes=[ct.c_void_p,ct.c_int,ct.c_void_p,ct.c_int,ct.POINTER(State),ct.POINTER(ct.c_int)]
        lib.tp_acquisition_scan_next.restype=ct.c_int
        lib.tp_acquisition_scan_destroy.argtypes=[ct.c_void_p]
        lib.tp_acquisition_scan_destroy.restype=None
        lib._acquisition_bound=True
    return lib

def acquire(pulses,resolved,rng,cancel,progress,*,state=None,stop_at=math.inf,pair_limit=None,on_horizon=None,pool=None):
    from .m2_physics import digitize,classify,pulse_truth,timeline_context,TAIL_FRACTION,PULSE_DTYPE
    p=resolved['profile'];acq=p['acquisition'];d=p['digitization'];libraries=resolved['_libraries']
    window=resolved['window_ns'];step=min(acq['trigger_step_ns'],1/d['rate_GSps']/4)
    filter_tau=1000/(2*np.pi*d['input_bandwidth_MHz']) if d['input_bandwidth_MHz'] else 0.
    filter_tail=0. if not d['input_bandwidth_MHz'] else -math.log(TAIL_FRACTION)*1000/(2*np.pi*d['input_bandwidth_MHz'])
    state={} if state is None else state
    fixed=state.get('fixed')
    if fixed is None:fixed=np.zeros((2,d['samples']));state['fixed']=fixed
    serial=state.get('serial',0);previous=state.get('previous',np.zeros(2));cross=state.get('last_cross',[-math.inf,-math.inf])
    native_state=State(state.get('busy_until',-math.inf),state.get('last_trigger',-math.inf),*cross,*previous,state.get('cursor',(math.floor(float(pulses[0]['time'])/step)-1)*step))
    config=Config(step,filter_tau,filter_tail,acq['coincidence_ns'],acq['trigger_delay_ns'],acq['dead_ns'],stop_at,p['channels'][0]['threshold_mV'],p['channels'][1]['threshold_mV'],('coincidence','either','A','B').index(acq['trigger']),not resolved.get('_reference_trigger_scan',False))
    descriptors=np.empty(len(pulses),dtype=PULSE)
    lib=binding()
    fast=getattr(lib,'tp_scan_descriptors',None) if pulses.dtype==PULSE_DTYPE and pulses.flags.c_contiguous else None
    if not fast:
        maximum_tail=float(np.max(pulses['span']+filter_tail))
        for key in ('time','origin','span','role','channel'):descriptors[key]=pulses[key]
    indexes=(ScanLibraryIndex*2)()
    responses=[];maps=[]
    for role,library in enumerate(libraries):
        if library.map is None:library.map=np.memmap(library.path,mode='r',dtype='u1')
        packed=library.onset_map is not None;stride=8 if packed else 32
        config.stride[role]=stride;maps.append(library.onset_map if packed else library.map)
        if fast:
            indexes[role]=ScanLibraryIndex(library.index.ctypes.data,library.onset_offsets.ctypes.data if packed else None,len(library.index))
        else:
            mask=pulses['role']==role;records=pulses['record'][mask].astype(np.intp)
            index=library.index[records];ch=pulses['channel'][mask]
            base=library.onset_offsets[records] if packed else index[:,0]+24
            descriptors['offset'][mask]=base+np.where(ch==0,0,index[:,1]*stride)
            descriptors['count'][mask]=np.where(ch==0,index[:,1],index[:,2])
        for channel,r in enumerate(library.responses):
            c=p['channels'][channel];factor=10**(-c['attenuation_dB']/20)
            if c.get('invert',False):factor=-factor
            responses.append(Response(r['order'],-1 if r['polarity']=='negative' else 1,r['tau_ns'],r['voltage_scale_mV'],factor))
    if fast:
        tail=ct.c_double()
        if fast(pulses.ctypes.data,len(pulses),indexes,filter_tail,descriptors.ctypes.data,ct.byref(tail)):
            raise ValueError('Invalid source record in trigger scan')
        maximum_tail=tail.value
    maximum=2**64-1 if pair_limit is None else max(0,pair_limit-serial)
    if not maximum:return
    args=(descriptors.ctypes.data,len(descriptors),maps[0].ctypes.data,maps[0].nbytes,maps[1].ctypes.data,maps[1].nbytes,
          (Response*4)(*responses),ct.byref(config),ct.byref(native_state),maximum)
    workers=resolve_threads(p.get('threads',0),max(1,len(pulses)))
    if resolved.get('_batch_windows') and workers>=6 and hasattr(lib,'tp_acquisition_independent'):
        output=np.empty((512,4),dtype=np.float64)
        partitions=min(4,workers//3)
        count=lib.tp_acquisition_independent(*args,output.ctypes.data,len(output),partitions)
        if count==-1:raise ValueError('Native acquisition scan failed')
        if count>=0:
            rows=output[:count]
            state.update(fixed=fixed,busy_until=native_state.busy,last_trigger=native_state.trigger,last_cross=[native_state.cross_a,native_state.cross_b],previous=np.array([native_state.previous_a,native_state.previous_b]),cursor=native_state.cursor,serial=serial+count)
            if on_horizon:on_horizon(native_state.cursor)
            if count:
                yield {'id':serial+count-1,'trigger_ns':float(rows[-1,0])},(serial,rows,rng.integers(0,2**63-1,size=count),
                       pulses,descriptors,maximum_tail,filter_tail,resolved.get('_timeline_known_until_ns',math.inf))
            progress(1.);return
    handle=lib.tp_acquisition_scan_create(*args)
    if not handle:raise ValueError('Native acquisition scanner could not initialize.')
    owns_pool=pool is None
    if owns_pool:pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='M2-analog')
    batch_windows=resolved.get('_batch_windows',False)
    # Plan a bounded source chunk in one GIL-free call. The interactive and
    # non-batched paths retain their finer cancellation and update interval.
    blocks=512 if batch_windows else 64
    waiting=deque();output=np.empty((blocks,4),dtype=np.float64);done=ct.c_int()
    crossings=[];first_id=serial
    def sampled(meta,start,chosen,seed):
        data,cell,baseline,clipped=digitize(start,chosen,resolved,np.random.default_rng(seed),fixed)
        return {**meta,'trigger_cell':cell,'baseline_mV':baseline,'clipped':clipped},data
    try:
        while not done.value:
            cancel();count=lib.tp_acquisition_scan_next(handle,blocks,output.ctypes.data,blocks,ct.byref(native_state),ct.byref(done))
            if count<0:raise ValueError(f'Native acquisition scan failed ({count}).')
            if batch_windows and count:
                crossings.append(output[:count].copy());serial+=count
            for at,ch,ca,cb in (() if batch_windows else output[:count]):
                at=float(at);ch=int(ch);last_cross=[float(ca),float(cb)]
                finish=at+acq['trigger_delay_ns'];start=finish-window
                high=int(np.searchsorted(pulses['time'],finish,side='left'));low=int(np.searchsorted(pulses['time'],start-maximum_tail,side='left'))
                chosen=pulses[low:high];chosen=chosen[(chosen['time']+chosen['span']+filter_tail)>start]
                seed=int(rng.integers(0,2**63-1));deferred=resolved.get('_defer_waveforms',False)
                busy_until=finish+acq['dead_ns']
                meta={'id':serial,'start_ns':start,'trigger_ns':at,'end_ns':finish,'busy_until_ns':busy_until,'trigger_channel':ch,
                      'accepted_crossings_ns':last_cross if acq['trigger']=='coincidence' else [at if i==ch else None for i in range(2)],
                      'coincidence_window_ns':[min(last_cross),min(last_cross)+acq['coincidence_ns']] if acq['trigger']=='coincidence' else None,
                      'acquisition_rate_Hz':(serial+1)*1e9/max(busy_until,1e-9),
                      'timeline':timeline_context(pulses,start,finish,busy_until,resolved.get('_timeline_known_until_ns',math.inf),raw=deferred)}
                serial+=1
                if deferred:
                    yield meta,(start,chosen,seed)
                else:
                    label,flags=classify(chosen)
                    meta.update({'class':label,'flags':flags,'pulses':pulse_truth(chosen,start)})
                    waiting.append(pool.submit(sampled,meta,start,chosen,seed))
                    if len(waiting)>=workers*2:cancel();yield waiting.popleft().result()
            if on_horizon:on_horizon(native_state.cursor)
            last_time=min(float(np.max(pulses['time']+(pulses['span']+filter_tail))),stop_at)
            progress(min(1.,native_state.cursor/last_time))
        while waiting:cancel();yield waiting.popleft().result()
        if crossings:
            rows=np.concatenate(crossings)
            seeds=rng.integers(0,2**63-1,size=len(rows))
            end=serial-1
            yield {'id':end,'trigger_ns':float(rows[-1,0])},(first_id,rows,seeds,pulses,descriptors,
                  maximum_tail,filter_tail,resolved.get('_timeline_known_until_ns',math.inf))
    finally:
        for task in waiting:task.cancel()
        if owns_pool:pool.shutdown(wait=True,cancel_futures=True)
        lib.tp_acquisition_scan_destroy(handle)
        state.update(fixed=fixed,busy_until=native_state.busy,last_trigger=native_state.trigger,last_cross=[native_state.cross_a,native_state.cross_b],previous=np.array([native_state.previous_a,native_state.previous_b]),cursor=native_state.cursor,serial=serial)
    progress(1.)
