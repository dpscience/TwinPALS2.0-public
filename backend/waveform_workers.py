# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded, ordered waveform batches with independent process-local RNG seeds."""
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor,TimeoutError
import copy
import json
import os
import queue
import struct
import threading
from multiprocessing import get_context
from multiprocessing.shared_memory import SharedMemory
import numpy as np

_local=threading.local()
EXECUTOR=ProcessPoolExecutor
class _BatchLibrary:
    def __init__(self,responses,path=None):
        self.responses=responses;self.values={}
        self.stride=path[1] if path else 32
        self.mapped=np.memmap(path[0],mode='r',dtype='u1') if path else None
    def onsets(self,row,ch):return self.values[(row,ch)]

def initialize(resolved,responses,paths=(None,None),arena_name=None,startup_gate=None,shared_axes=None,frame_buffers=None):
    from .m2_physics import calibrated_axes
    _local.resolved=copy.deepcopy(resolved)
    if frame_buffers is not None:_local.resolved['_frame_buffers']=frame_buffers
    _local.resolved['_libraries']=[_BatchLibrary(r,path) for r,path in zip(responses,paths)]
    _local.arena=SharedMemory(name=arena_name) if arena_name else None
    _local.startup_gate=startup_gate
    # This calibration is immutable for the entire acquisition. Bound the
    # per-process table to 16 MiB, including digitizers with long records.
    d=resolved['profile']['digitization'];architecture=resolved['digitizer']['architecture']
    cells=d['samples'] if architecture=='switched_capacitor' else 1
    widths=np.asarray(resolved['cell_intervals_ns'])
    _local.resolved['cell_intervals_ns']=widths
    if shared_axes is not None:
        _local.resolved['_cell_axes']=shared_axes
    elif cells*2*d['samples']*8<=16*1024**2:
        settings={**d,'cell_widths_ns':widths}
        axes=np.empty((cells,2,d['samples']),dtype=np.float64)
        for cell in range(cells):axes[cell]=calibrated_axes(settings,architecture,cell)
        _local.resolved['_cell_axes']=axes

class PreparedWaveform(np.ndarray):
    """Unchanged samples with transient monitoring values; never serialized to stream."""

class FrameMetadata(Mapping):
    """Keep one canonical JSON payload. Only a displayed record needs decoding."""
    def __init__(self,summary,frame,size):
        self.summary=summary;self.frame=frame;self.size=size;self.decoded=None

    def full(self):
        from .m2_stream import FRAME
        if self.decoded is None:
            start=FRAME.size+4
            self.decoded=json.loads(self.frame[start:start+self.size])
        return self.decoded

    def __getitem__(self,key):
        if key in self.summary:return self.summary[key]
        return self.full()[key]
    def __iter__(self):return iter(self.full())
    def __len__(self):return len(self.full())


def sample_batch(jobs,onsets,ranges,metadata=None,compact=False,slot=None):
    from .m2_physics import digitize,classify,pulse_truth
    from .m1_store import encode
    from .m2_stream import FRAME,MAX_FRAME
    from .streams import frame_crc32
    _resolved=_local.resolved
    for role,values in enumerate(onsets):_resolved['_libraries'][role].values=values
    arrays=[];baselines=[];details=[]
    cursor,stop=slot if slot is not None else (0,0)
    for index,(start,chosen,seed,trigger_offset) in enumerate(jobs):
        data,cell,baseline,clipped=digitize(start,chosen,_resolved,np.random.default_rng(seed),None)
        arrays.append(data);baselines.append(baseline)
        if metadata is None:details.append((cell,baseline,clipped))
        else:
            label,flags=classify(chosen)
            meta=metadata[index]
            meta['timeline']['pulses']=pulse_truth(meta['timeline']['pulses'],start)
            meta.update({'class':label,'flags':flags,'pulses':pulse_truth(chosen,start),'trigger_cell':cell,'baseline_mV':baseline,'clipped':clipped})
            encoded=encode(meta).encode('utf-8')
            payload=struct.pack('<I',len(encoded))+encoded+data.tobytes()
            if len(payload)>MAX_FRAME:raise ValueError('Too many overlapping pulses for one 32 MiB waveform frame. Reduce activity or the sweep duration.')
            frame=FRAME.pack(b'WAVE',len(payload),frame_crc32(payload))+payload
            if compact:
                summary={key:meta[key] for key in ('id','class','start_ns','trigger_ns','busy_until_ns','baseline_mV','accepted_crossings_ns')}
                keys=tuple((p['role'],p['record'],p['channel']) for p in meta['pulses'])
                if cursor+len(frame)<=stop:
                    end=cursor+len(frame)
                    _local.arena.buf[cursor:end]=frame
                    location=(cursor,end);cursor=end
                else:location=frame
                details.append((summary,keys,len(encoded),location))
            else:details.append((meta,frame))
    for library in _resolved['_libraries']:library.values={}
    samples=np.stack(arrays)
    axes=samples[:,::2]
    magnitudes=np.abs(samples[:,1::2].astype(float)-np.asarray(baselines)[:,:,None])
    peaks=magnitudes.max(axis=2)
    areas=np.trapezoid(magnitudes,axes,axis=2)
    peak_times=np.take_along_axis(axes,magnitudes.argmax(axis=2)[:,:,None],axis=2)[:,:,0]
    features=np.column_stack((peaks,areas,peak_times[:,1]-peak_times[:,0]))
    densities=[[None,None] for _ in jobs]
    for ch,limits in enumerate(ranges):
        if limits is None:continue
        lo,hi,bins=limits
        coordinates=lo+(np.arange(bins)+.5)*(hi-lo)/bins
        for j in np.flatnonzero(np.isfinite(areas[:,ch])&(areas[:,ch]>0)):
            # Match the archived subtraction even at a large source clock.
            t=axes[j,ch].astype(float)-jobs[j][3]
            densities[j][ch]=np.interp(coordinates,t,magnitudes[j,ch]/areas[j,ch],left=np.nan,right=np.nan)
    if compact:
        densities=[np.asarray([row[ch] if row[ch] is not None else np.full(ranges[ch][2],np.nan)
                               for row in densities]) if ranges[ch] is not None else None for ch in range(2)]
    return None if compact else samples,details,features,densities,ranges


def _warm_worker():
    from . import m2_stream
    from .native_digitizer import binding
    binding()
    if _local.startup_gate is not None:_local.startup_gate.wait()

def process_count(workers,samples):
    count=max(1,workers-2)
    if samples<=2048:
        # Short sweeps share CPU and memory bandwidth with the discriminator
        # and writer. Larger workstations can still use more waveform workers.
        count=min(count,max(10,workers//2))
    # ProcessPoolExecutor uses Windows wait handles and accepts at most 61.
    return min(count,61) if os.name=='nt' else count

def sample_windows(first_id,crossings,seeds,pulses,addresses,maximum_tail,filter_tail,known,ranges,slot,sources):
    from .m2_physics import timeline_context
    resolved=_local.resolved
    for library,(path,stride) in zip(resolved['_libraries'],sources):
        if library.mapped is None:
            library.mapped=np.memmap(path,mode='r',dtype='u1');library.stride=stride
    from . import native_sweeps
    native=native_sweeps.sample_windows(resolved,_local.arena,first_id,crossings,seeds,pulses,addresses,
                                       maximum_tail,filter_tail,known,ranges,slot)
    if native is not None:return native
    acq=resolved['profile']['acquisition'];window=resolved['window_ns']
    ends=crossings[:,0]+acq['trigger_delay_ns'];starts=ends-window
    busy=ends+acq['dead_ns'];margin=(ends-starts)*.2
    times=np.ascontiguousarray(pulses['time'])
    first=np.searchsorted(times,starts-maximum_tail);last=np.searchsorted(times,ends)
    tl_first=np.searchsorted(times,starts-margin)
    tl_last=np.searchsorted(times,np.maximum(ends,np.minimum(busy+margin,known)))
    pulse_ends=pulses['time']+pulses['span']+filter_tail
    jobs=[];metas=[];onsets=[{},{}]
    for i,(at,ch,ca,cb) in enumerate(crossings):
        start=float(starts[i]);finish=float(ends[i]);busy_until=float(busy[i]);at=float(at);ch=int(ch)
        indices=np.flatnonzero(pulse_ends[first[i]:last[i]]>start)+first[i]
        chosen=pulses[indices]
        for j in indices:
            pulse=pulses[j];role=int(pulse['role']);key=int(pulse['record']),int(pulse['channel'])
            if key not in onsets[role]:
                offset,count=map(int,addresses[j])
                onsets[role][key]=np.ndarray((count,),dtype='<f8',buffer=resolved['_libraries'][role].mapped,
                                             offset=offset,strides=(resolved['_libraries'][role].stride,))
        crosses=[float(ca),float(cb)];coinc=acq['trigger']=='coincidence';serial=first_id+i
        meta={'id':serial,'start_ns':start,'trigger_ns':at,'end_ns':finish,'busy_until_ns':busy_until,'trigger_channel':ch,
              'accepted_crossings_ns':crosses if coinc else [at if k==ch else None for k in range(2)],
              'coincidence_window_ns':[min(crosses),min(crosses)+acq['coincidence_ns']] if coinc else None,
              'acquisition_rate_Hz':(serial+1)*1e9/max(busy_until,1e-9),
              'timeline':timeline_context(pulses,start,finish,busy_until,known,raw=True,bounds=(tl_first[i],tl_last[i]))}
        metas.append(meta);jobs.append((start,chosen,int(seeds[i]),at-start))
    return sample_batch(jobs,onsets,ranges,metas,compact=True,slot=slot)

class WaveformWorkers:
    def __init__(self,resolved,workers,cancel,batch_size=64,responses=None):
        self.cancel=cancel;self.monitor=resolved.get('_monitor_persistence')
        self.starter=None;self.start_error=None
        from .native_sweeps import FrameBuffers,binding as sweep_binding
        d=resolved['profile']['digitization']
        switched=resolved['digitizer']['architecture']=='switched_capacitor'
        cells=d['samples'] if switched else 1
        self.direct=bool(resolved.get('_stream_batches') and sweep_binding() is not None
                         and d['samples']<=8192 and cells*2*d['samples']*8<=16*1024**2)
        self.startup_gate=get_context().Event() if responses is not None and not self.direct else None
        self.limit=max(2,workers*2);self.stopped=threading.Event()
        self.window=resolved['window_ns']
        self.acquisition=resolved['profile']['acquisition']
        # Bound queued sample/frame copies also for 65,536-cell digitizers.
        bytes_per_pair=resolved['profile']['digitization']['samples']*16*2
        self.batch_size=min(batch_size,max(1,128*1024*1024//(self.limit*bytes_per_pair)))
        # One producer and one ordered consumer, plus at most limit queued
        # futures and one blocked send. No slot can wrap before its reader exits.
        self.slots=self.limit+3;self.sequence=0
        self.slot_bytes=min(96*1024*1024//self.slots,self.batch_size*(bytes_per_pair//2+8192))
        try:self.arena=None if self.direct else SharedMemory(create=True,size=self.slots*self.slot_bytes)
        except OSError:self.arena=None
        snapshot={k:copy.deepcopy(resolved[k]) for k in ('profile','digitizer','cell_intervals_ns','window_ns')}
        snapshot['_stream_batches']=resolved.get('_stream_batches',False)
        self.shape_cache=None
        responses=responses if responses is not None else [l.responses for l in resolved['_libraries']]
        table=None
        if self.direct:
            from .m2_physics import calibrated_axes
            table=np.empty((cells,2,d['samples']),dtype=np.float64)
            settings={**d,'cell_widths_ns':np.asarray(resolved['cell_intervals_ns'])}
            for cell in range(cells):table[cell]=calibrated_axes(settings,resolved['digitizer']['architecture'],cell)
            table.flags.writeable=False
            self.shape_cache=sweep_binding()._dll.tp_sweep_cache_create()
            snapshot['_sweep_cache']=self.shape_cache
        try:
            executor=ThreadPoolExecutor if self.direct else EXECUTOR
            self.pool=executor(max_workers=workers,initializer=initialize,
                               initargs=(snapshot,responses,(None,None),self.arena.name if self.arena else None,
                                         self.startup_gate,table,FrameBuffers() if self.direct else None))
        except BaseException:
            if self.shape_cache:
                sweep_binding()._dll.tp_sweep_cache_destroy(self.shape_cache);self.shape_cache=None
            if self.arena is not None:
                self.arena.close();self.arena.unlink()
            raise
        self.sources=None
        if '_libraries' in resolved:self.attach(resolved['_libraries'])

    def attach(self,libraries):
        if self.starter is not None:
            self.starter.join()
            if self.start_error is not None:raise self.start_error
        self.sources=[(lib.onset_map.filename,8) if lib.onset_map is not None else (lib.path,32) for lib in libraries]

    def warm(self,workers):
        # Windows spawns interpreters individually. An idle warm-up task
        # otherwise finishes before the next worker is even requested.
        if self.direct:return
        def start():
            try:
                for _ in range(workers):
                    if self.stopped.is_set():break
                    self.pool.submit(_warm_worker)
            except Exception as exc:self.start_error=exc
            finally:self.startup_gate.set()
        self.starter=threading.Thread(target=start,name='M2-worker-startup')
        self.starter.start()

    def submit_windows(self,plan):
        first,rows,seeds,pulses,descriptors,maximum_tail,filter_tail,known=plan
        ranges=[(*self.monitor.ranges[ch],self.monitor.bins) if self.monitor is not None and self.monitor.range_frozen[ch] else None for ch in range(2)]
        addresses=np.column_stack((descriptors['offset'],descriptors['count']))
        times=np.ascontiguousarray(pulses['time'])
        for offset in range(0,len(rows),self.batch_size):
            batch=slice(offset,offset+self.batch_size)
            # Use wide bounds only for dispatch. The worker applies the exact
            # original expressions for both the saved sweep and timeline.
            begin=rows[batch][0,0]+self.acquisition['trigger_delay_ns']-self.window
            end=rows[batch][-1,0]+self.acquisition['trigger_delay_ns']
            low=begin-max(maximum_tail,self.window)-self.window
            high=(end+self.acquisition['dead_ns'])+self.window
            span=slice(np.searchsorted(times,low),np.searchsorted(times,high,side='right'))
            start_slot=self.sequence%self.slots*self.slot_bytes;self.sequence+=1
            slot=(start_slot,start_slot+self.slot_bytes) if self.arena else None
            yield self.pool.submit(sample_windows,first+offset,rows[batch],seeds[batch],
                                   pulses[span],addresses[span],maximum_tail,filter_tail,known,ranges,slot,self.sources)

    def receive(self,future):
        from .native_sweeps import SweepBatch
        while True:
            self.cancel()
            try:result=future.result(timeout=.1);break
            except TimeoutError:continue
        if isinstance(result,SweepBatch):
            if isinstance(result.frames,tuple):
                begin,end=result.frames
                result.frames=bytes(self.arena.buf[begin:end])
            at=float(result.crossings[-1,0])
            yield {'id':result.first+len(result.rows)-1,'busy_until_ns':(at+result.delay)+result.dead},result
            return
        _,details,features,densities,ranges=result
        from .m2_stream import FRAME
        for i,((summary,keys,size,location),feature) in enumerate(zip(details,features)):
            frame=location if isinstance(location,bytes) else bytes(self.arena.buf[location[0]:location[1]])
            density=[d[i] if d is not None else None for d in densities]
            self.cancel();meta=FrameMetadata(summary,frame,size)
            array=np.frombuffer(frame,'<f4',offset=FRAME.size+4+size).reshape(4,-1).view(PreparedWaveform)
            array.monitor_features=feature;array.monitor_density=(ranges,density)
            array.stream_frame=frame;array.transport_keys=keys
            yield meta,array
    def check_running(self):
        self.cancel()
        if self.stopped.is_set():raise RuntimeError('Acquisition consumer stopped')

    def ordered(self,plans):
        # A busy output device or a live plot must not hold the discriminator
        # idle. Only the consumer publishes, in original acquisition order.
        ready=queue.Queue(self.limit);stopped=self.stopped
        def send(value):
            while not stopped.is_set():
                try:ready.put(value,timeout=.1);return True
                except queue.Full:continue
            return False
        def produce():
            try:
                for _,plan in plans:
                    if stopped.is_set():break
                    for task in self.submit_windows(plan):
                        if not send(task):return
            except BaseException as exc:send(exc)
            finally:
                try:plans.close()
                finally:send(None)
        producer=threading.Thread(target=produce,name='M2-discriminator')
        producer.start()
        try:
            while True:
                self.cancel()
                try:task=ready.get(timeout=.1)
                except queue.Empty:continue
                if task is None:break
                if isinstance(task,BaseException):raise task
                yield from self.receive(task)
        finally:
            stopped.set();producer.join()

    def close(self):
        if self.pool is None:return
        self.stopped.set()
        if self.starter is not None:self.starter.join()
        try:self.pool.shutdown(wait=True,cancel_futures=True)
        finally:
            self.pool=None
            if self.shape_cache:
                from .native_sweeps import binding
                binding()._dll.tp_sweep_cache_destroy(self.shape_cache);self.shape_cache=None
            if self.arena is not None:
                self.arena.close();self.arena.unlink()
