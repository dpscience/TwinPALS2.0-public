# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded waveform reader and replayable lifetime acquisition.

Only compact extracted features are retained on disk. Histogram views use an
additive bank of exclusive truth categories; raw waveforms never accumulate.
"""
from collections import OrderedDict, deque
from collections.abc import MutableMapping
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import copy
import json
import math
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
import numpy as np
from .m3_models import Profile, View, SpectrumAnalysis
from .execution import resolve_threads
from .m3_signal import process, CATEGORIES, transport_support
from .m2_stream import Reader
from .m1_store import Conflict
from .m3_context import adc_channels,selection_error
from .m3_monitor import FeatureJournal
from .m3_spectra import SpectrumJournal, enabled_directions

ORIGINS=['scintillation','cherenkov','mixed','unknown']
DIRECTIONS=['AB','BA','SS']
from .m3_blocks import NativeTransportIndex, measured_blocks, library as lifetime_library, REASONS
from .m3_measurements import POSITION,TIMING,Diagnostics,PulseHeights,accumulate,classify,empty_bank,rejection_counts,scalar_rows


class TransportIndex(MutableMapping):
    def __init__(self,db,file,lock):self.db=db;self.file=file;self.lock=lock
    def __getitem__(self,key):
        with self.lock:row=self.db.execute('select at,n,crc from transports where file=? and role=? and record=?',(self.file,*key)).fetchone()
        if row is None:raise KeyError(key)
        return row
    def __setitem__(self,key,value):
        with self.lock:self.db.execute('insert into transports values(?,?,?,?,?,?)',(self.file,*key,*value))
    def __delitem__(self,key):
        with self.lock:self.db.execute('delete from transports where file=? and role=? and record=?',(self.file,*key))
    def __iter__(self):
        with self.lock:return iter(self.db.execute('select role,record from transports where file=?',(self.file,)).fetchall())
    def __len__(self):
        with self.lock:return self.db.execute('select count(*) from transports where file=?',(self.file,)).fetchone()[0]
    def clear(self):
        with self.lock:self.db.execute('delete from transports where file=?',(self.file,))


def batch_process(items):return [process(item) for item in items]


def pulse_stream_size(path):
    try:return path.stat().st_size
    except FileNotFoundError:
        if path.suffix!='.part':raise
        return path.with_suffix('').stat().st_size

def open_snapshot(path,limit):
    reader=Reader(path)
    if reader.limit<limit:
        reader.close()
        raise ValueError('Pulse stream became shorter after acquisition started.')
    if reader.limit>limit and path.suffix=='.part':
        # The pending file can be finalized before its turn. Its captured prefix
        # still has partial-frame semantics in both the scalar and block readers.
        reader.path=path
    reader.limit=limit
    return reader


class Acquisition:
    def __init__(self,profile,paths,headers):
        if len(paths)>1 or len(paths)!=len(headers):raise ValueError('Select one Module 2 pulse stream.')
        self.profile=profile;self.paths=paths;self.headers=headers;self.id=uuid.uuid4().hex
        self.lock=threading.RLock();self.cancel=threading.Event();self.run_gate=threading.Event();self.run_gate.set()
        self.temporary=tempfile.TemporaryDirectory(prefix='twinpals-m3-')
        root=Path(self.temporary.name)
        self.db=sqlite3.connect(str(root/'transport.sqlite'),check_same_thread=False)
        # This private seek index lives only as long as the job. All source records remain in the input file.
        self.db.executescript('pragma journal_mode=WAL; pragma synchronous=OFF; create table transports(file integer,role integer,record integer,at integer,n integer,crc integer,primary key(file,role,record)) without rowid;')
        self.native_index=None
        self.positions=open(root/'positions.bin','w+b');self.timings=open(root/'timings.bin','w+b')
        self.timing_count=0;self.timing_start=0;self.epoch=0;self.seen=0;self.accepted=0
        self.rejected={};self.preview=deque(maxlen=profile['preview_count']);self.diagnostics=Diagnostics()
        self.phs=PulseHeights(headers);self.banks=OrderedDict();self.views={}
        self.adc=[adc_channels(h) for h in headers]
        maximum=[max((a[i]['height'] for a in self.adc),default=500.) for i in (0,1)]
        self.features=FeatureJournal(root,self.lock,maximum,profile['channels'])
        self.comparison=SpectrumJournal(root,headers[0] if headers else {},maximum)
        self.direction_floor=[0]*3;self.direction_first=[1]*3;self.bank_revision=0
        self.file_index=0;self.file_limits=[pulse_stream_size(p) for p in paths];self.file_seen=[0]*len(paths)
        self.revision=0;self.revision_first=1;self.profiles=[profile];self.pending=None;self.history=[]
        self.preview_generation=0;self.paused_at=None;self.paused_seconds=0.
        self.status='running';self.error='';self.started=time.monotonic();self.bytes=0
        self.total_bytes=sum(self.file_limits);self.measurement_ns=0.;self.reset_at=0
        self.ensure_bank(View().model_dump())
        self.thread=threading.Thread(target=self.run,name='M3 acquisition',daemon=True);self.thread.start()

    @staticmethod
    def bank_key(v):
        return (v['bin_ps'],v['zero_ps'],v['low_ns'],v['high_ns'],v['scatter'])

    def ensure_bank(self,v):
        key=self.bank_key(v)
        while True:
            with self.lock:
                if key in self.banks:
                    self.banks.move_to_end(key);return self.banks[key]
                revision=self.bank_revision;floors=np.array(self.direction_floor);first=min(floors);last=self.timing_count
                self.timings.flush()
            h=empty_bank(v,len(CATEGORIES),len(ORIGINS))
            # Build new binning outside the acquisition lock. Only the final small
            # tail is added under the same lock as the ordered writer.
            with open(self.timings.name,'rb') as source:
                source.seek(first*TIMING.itemsize);at=first
                while True:
                    while at<last:
                        rows=np.fromfile(source,dtype=TIMING,count=min(65536,last-at))
                        if not len(rows):raise IOError('Truncated Module 3 timing journal')
                        if np.any(floors>at):accumulate(h,v,rows[np.arange(at,at+len(rows))>=floors[rows['d']]])
                        else:accumulate(h,v,rows)
                        at+=len(rows)
                    with self.lock:
                        if self.bank_revision!=revision:break
                        if key in self.banks:return self.banks[key]
                        last=self.timing_count;self.timings.flush()
                        if last-at>4096:continue
                        if last>at:accumulate(h,v,np.fromfile(source,dtype=TIMING,count=last-at))
                        self.banks[key]=h;self.views[key]=v
                        while len(self.banks)>1 and sum(b.nbytes for b in self.banks.values())>96*1024*1024:
                            old,_=self.banks.popitem(last=False);self.views.pop(old)
                        return h

    def _new_epoch(self,reason):
        self.history.append(dict(epoch=self.epoch,revision=self.revision,first=self.reset_at+1,last=self.seen,
                                 processed=self.seen-self.reset_at,accepted=self.accepted,reason=reason))
        self.epoch+=1;self.reset_at=self.seen;self.timing_start=self.timing_count;self.accepted=0;self.rejected={}
        self.preview.clear();self.preview_generation+=1;self.diagnostics.clear();self.phs.counts.fill(0);self.phs.overflow.fill(0)
        self.direction_floor=[self.timing_count]*3;self.direction_first=[self.seen+1]*3;self.bank_revision+=1
        for kind in ('phs','area','shape'):
            for ch in (0,1):self.features.reset(kind,ch)
        for key in self.comparison.floors:self.comparison.floors[key]=self.comparison.count
        for h in self.banks.values():h.fill(0)

    def reset(self):
        with self.lock:self._new_epoch('Counts reset');return self.state()

    def reset_plot(self,kind,target):
        with self.lock:
            if kind == 'spectrum' and (target == 'all' or target in self.comparison.floors):
                directions = tuple(self.comparison.floors) if target == 'all' else (target,)
                for key in directions:
                    self.comparison.floors[key] = self.comparison.count
                    if key != 'merged':
                        d = DIRECTIONS.index(key)
                        self.direction_floor[d] = self.timing_count
                        self.direction_first[d] = self.seen + 1
                        for histogram in self.banks.values():
                            histogram[d].fill(0)
                if target != 'merged':
                    self.bank_revision += 1
            elif kind in ('phs','area','shape') and target in ('A','B'):
                ch='AB'.index(target);self.features.reset(kind,ch)
                if kind=='phs':self.phs.counts[ch].fill(0);self.phs.overflow[ch].fill(0)
            else:raise ValueError('Choose one detector plot or lifetime spectrum.')
            return self.state()

    def set_workers(self,workers):
        if type(workers) is not int or not 0<=workers<=32:raise ValueError('Choose Auto or 1–32 CPU workers.')
        with self.lock:
            if self.status not in ('running','pausing','paused'):raise Conflict('Reading has ended.')
            self.profile={**self.profile,'workers':workers}
            return self.state()

    def configure(self,raw,expected=None,pulse_selection=None,preview_count=None):
        from .m3_models import Channel
        if len(raw)!=2:raise ValueError('Choose settings for both channels.')
        channels=[Channel.model_validate(ch).model_dump() for ch in raw]
        with self.lock:
            if self.status not in ('running','pausing','paused'):raise Conflict('Reading has ended. Restart from the beginning to process the stream with these settings.')
            if expected is not None and expected!=self.revision:
                raise Conflict('Live processing settings have already changed. Refresh the active settings.')
            rule=self.profile.get('pulse_selection','highest') if pulse_selection is None else pulse_selection
            if rule not in ('first','highest'):raise ValueError('Choose First pulse or Highest pulse.')
            count=self.preview.maxlen if preview_count is None else preview_count
            if type(count) is not int or not 1<=count<=256:raise ValueError('Retain between 1 and 256 waveform pairs.')
            active=(self.profile['channels'],self.profile.get('pulse_selection','highest'))
            if (channels,rule)!=(self.pending or active) or count!=self.preview.maxlen:
                self.preview_generation+=1
                self.preview=deque(maxlen=count)
                self.profile={**self.profile,'preview_count':count}
            self.pending=(channels,rule) if (channels,rule)!=active else None
            return self.state()

    def _begin_batch(self):
        with self.lock:
            if self.pending is not None:
                self.history.append(dict(revision=self.revision,first=self.revision_first,last=self.seen,
                                         reason='Processing settings changed'))
                channels,rule=self.pending
                self.profile={**self.profile,'channels':channels,'pulse_selection':rule}
                self.profiles.append(self.profile);self.revision+=1;self.pending=None;self.revision_first=self.seen+1
            return self.effective(self.profile,self.file_index)

    def effective(self,profile,file):
        if not self.adc:return profile
        return {**profile,'channels':[{**c,'polarity':self.adc[file][i]['polarity']} for i,c in enumerate(profile['channels'])]}

    def _record(self,offsets,rows,direction,reasons,file):
        n=len(rows)
        if not n:return
        with self.lock:
            pos=np.empty(n,dtype=POSITION);pos['offset']=offsets;pos['file']=file;pos['revision']=self.revision
            self.positions.write(pos.tobytes())
            accepted=direction>=0
            timings=np.empty(np.count_nonzero(accepted),dtype=TIMING)
            dt=rows['values'][:,1,4]-rows['values'][:,0,4]
            self.comparison.append(rows,direction,reasons,dt,self.profile['channels'])
            timings['dt']=np.where(direction==1,-dt,dt)[accepted];timings['d']=direction[accepted]
            for key,source in [('c','category'),('o','origin'),('s','scatter')]:timings[key]=rows[source][accepted]
            self.timings.write(timings.tobytes());self.timing_count+=len(timings)
            for key,h in self.banks.items():accumulate(h,self.views[key],timings)
            for label,count in rejection_counts(reasons,~accepted).items():self.rejected[label]=self.rejected.get(label,0)+count
            self.phs.add(rows,accepted);self.diagnostics.append(rows);self.features.append(rows)
            for i in range(n if self.pending else max(0,n-self.preview.maxlen),n):
                self.preview.append(dict(sequence=self.seen+i+1,id=int(rows['id'][i]),direction=DIRECTIONS[direction[i]] if accepted[i] else None,category=CATEGORIES[rows['category'][i]]))
            self.accepted+=len(timings);self.seen+=n
            if self.paths:self.file_seen[file]+=n
            self.measurement_ns=max(self.measurement_ns,float(np.max(rows['start'])))

    def commit(self,items,file):
        rows=scalar_rows(items,CATEGORIES,ORIGINS)
        directions=np.array([DIRECTIONS.index(r['direction']) if r['direction'] else -1 for r in items],dtype='i1')
        reasons=np.array([[REASONS.index(g[1]) for g in r['gates']] for r in items],dtype='u1')
        self._record([r['offset'] for r in items],rows,directions,reasons,file)

    def _enrich(self,reader,meta,cache,transport=None):
        transport=transport or reader.transport
        for p in meta['pulses']:
            key=(p['role'],p['record'],p['channel'])
            if key not in cache:
                tr=transport(*key[:2])
                cache[key]=transport_support(tr,key[2],reader.header['resolved']['analog_response'][key[2]],
                    reader.header['profile']['digitization']['input_bandwidth_MHz'],reader.header['inputs'][key[0]]['header']['light_components'])
                if len(cache)>2048:cache.popitem(last=False)
            s=cache[key];p.update(end_ns=p['onset_ns']+s['span'],primary_ids=s['primaries'],scatter_mask=s['scatter_mask'],
                                  local_primaries=s['local_primaries'],direct_primaries=s['direct_primaries'],
                                  backscatter_primaries=s['backscatter_primaries'],external_scatter=s['external_scatter'])

    def _scalar(self,reader,file,base,cancel):
        reader.transports=TransportIndex(self.db,file,self.lock)
        support=OrderedDict();items=[];executor=None;current_workers=1
        try:
            def commit_batch():
                nonlocal executor,current_workers
                # Small files are quicker inline than starting a Windows process pool.
                workers=resolve_threads(profile['workers'],len(items)) if profile['workers'] or reader.limit>=8*1024*1024 else 1
                if workers!=current_workers:
                    if executor:executor.shutdown(wait=True,cancel_futures=True)
                    executor=ProcessPoolExecutor(max_workers=workers) if workers>1 else None
                    current_workers=workers
                if executor:
                    stride=max(1,math.ceil(len(items)/workers))
                    jobs=[executor.submit(batch_process,items[i:i+stride]) for i in range(0,len(items),stride)]
                    results=[r for job in jobs for r in job.result()]
                else:results=batch_process(items)
                self.commit(results,file);self.bytes=base+reader.file.tell()
            for offset,meta,data in reader.records(cancel=cancel):
                cancel()
                if not items:profile=self._begin_batch()
                self._enrich(reader,meta,support)
                items.append((offset,meta,data,profile,reader.header['isotope']))
                if len(items)>=32:commit_batch();items=[]
            if items:commit_batch()
        finally:
            if executor:executor.shutdown(wait=True,cancel_futures=True)

    def _native(self, reader, file, base, cancel):
        # Native extraction of the next block can overlap writing the current one.
        # Only the ordered writer publishes counts, preview rows and file progress.
        pending_write = None
        self.native_index = NativeTransportIndex()

        def drain():
            nonlocal pending_write
            if pending_write is not None:
                pending_write.result()
                pending_write = None

        def settings():
            if self.pending is not None:
                # The preceding rows still belong to the previous processing revision.
                drain()
                return self._begin_batch()
            return self.effective(self.profile, file)

        def commit_block(offsets, rows, last, channels):
            direction, reasons = classify(rows, channels)
            with self.lock:
                self._record(offsets, rows, direction, reasons, file)
                self.bytes = base + last

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='M3-journal') as writer:
            try:
                for offsets, rows, last in measured_blocks(reader, None, settings, lambda:cancel(drain), self.native_index):
                    drain()
                    pending_write = writer.submit(commit_block, offsets, rows, last, self.profile['channels'])
            finally:
                drain()

    def run(self):
        def cancel(drain=None):
            if self.cancel.is_set():raise InterruptedError('Acquisition stopped.')
            if not self.run_gate.is_set():
                if drain:drain()
                with self.lock:
                    if not self.run_gate.is_set():
                        self.status='paused';self.paused_at=time.monotonic()
                self.run_gate.wait()
                if self.cancel.is_set():raise InterruptedError('Acquisition stopped.')
        result='failed'
        try:
            base=0
            for file,path in enumerate(self.paths):
                with self.lock:self.file_index=file
                reader=open_snapshot(path,self.file_limits[file])
                try:
                    if reader.header!=self.headers[file]:raise ValueError('Pulse stream changed after input selection.')
                    if reader.limit>=8*1024*1024 and lifetime_library() is not None:
                        self._native(reader,file,base,cancel)
                    else:self._scalar(reader,file,base,cancel)
                    base+=reader.limit;self.bytes=base
                finally:reader.close()
            result='stopped' if self.cancel.is_set() else 'completed'
        except InterruptedError:result='stopped'
        except Exception as exc:self.error=str(exc);result='failed'
        finally:
            with self.lock:
                try:
                    self.positions.flush()
                    self.timings.flush()
                    for channel_file in self.features.files:channel_file.flush()
                except OSError as exc:
                    self.error=str(exc);result='failed'
                self.finished=time.monotonic();self.pending=None;self.status=result

    def state(self):
        with self.lock:
            now=getattr(self,'finished',time.monotonic())
            elapsed=now-self.started
            reading=elapsed-self.paused_seconds-(now-self.paused_at if self.paused_at is not None else 0)
            progress=1. if self.status=='completed' else min(1,self.bytes/max(1,self.total_bytes))
            eta=reading*(1-progress)/progress if self.status=='running' and reading>=2 and 0<progress<1 else None
            return dict(id=self.id,stream_id=self.headers[0].get('stream_id') if self.headers else None,status=self.status,error=self.error,processed=self.seen-self.reset_at,total_processed=self.seen,accepted=self.accepted,
                        rejected=dict(self.rejected),epoch=self.epoch,epoch_start=self.reset_at+1,revision=self.revision,pending=self.pending is not None,
                        progress=progress,elapsed=elapsed,eta_s=eta,estimated_finish=datetime.fromtimestamp(time.time()+eta,timezone.utc).isoformat() if eta is not None else None,measurement_ns=self.measurement_ns,preview_generation=self.preview_generation,
                        preview=list(self.preview),profile=self.profile,file_index=self.file_index,file_pairs=self.file_seen.copy(),
                        file_sizes=self.file_limits,bytes_read=self.bytes,spectrum_first=self.direction_first.copy(),revision_first=self.revision_first)

    def monitor(self,plots,share_cells=False):
        while True:
            prepared=self.features.prepare_many(plots)
            with self.lock:
                captured=self.features.capture(prepared)
                if captured is not None:
                    state=self.state();break
        return dict(**state,plots=self.features.render(captured,share_cells))

    def spectra(self, displays):
        with self.lock:
            state=self.state()
            capture=self.comparison.capture()
        return dict(**state,**self._comparisons(displays,capture,state['profile']['channels']))

    def _comparisons(self,displays,capture,channels):
        flags=enabled_directions(channels)
        available=[c for c in CATEGORIES if c!='annihilation_pair' or not self.headers or self.headers[0]['isotope']=='na22']
        spectra={}
        for direction,view in displays.items():
            result=self.comparison.query(capture,direction,view,available)
            result['filter_active']=bool(result['gated_pairs']) or (any(flags[:2]) if direction=='merged' else flags[DIRECTIONS.index(direction)])
            spectra[direction]=result
        return dict(comparisons=spectra,categories=available,adc_heights=self.comparison.maxima,
                    cable_delays_ns=self.comparison.delays)

    def query(self,raw):
        raw=dict(raw);compact=raw.pop('compact',False);individual=raw.get('individual',False)
        comparison_views=SpectrumAnalysis(displays=raw.pop('comparison_displays',{})).displays
        include_all_paths = raw.pop('report_all_paths', False)
        requested=raw.pop('diagnostic_channels',[]);plots=raw.pop('plots',[])
        area_views=raw.pop('area_views',False);share_cells=raw.pop('share_cells',False)
        if not isinstance(requested,list) or len(requested)>2 or any(x not in (0,1) for x in requested):raise ValueError('Choose diagnostic channels A or B.')
        v=View.model_validate(raw).model_dump()
        categories=v['categories'] if v['categories'] is not None else (CATEGORIES if v['category']=='all' else [v['category']])
        available=[name for name in CATEGORIES if name!='annihilation_pair' or not self.headers or self.headers[0]['isotope']=='na22']
        cs=[CATEGORIES.index(name) for name in categories if name in available]
        origins=list(range(len(ORIGINS))) if v['origin']=='all' else [ORIGINS.index(v['origin'])]
        while True:
            h=self.ensure_bank(v)
            prepared=self.features.prepare_many(plots,area_views)
            with self.lock:
                if self.banks.get(self.bank_key(v)) is not h:continue
                captured=self.features.capture(prepared)
                if captured is None:continue
                by_class=np.take(h,origins,axis=2).sum(axis=2);state=self.state()
                phs=self.phs.snapshot();diagnostics=[(ch,self.diagnostics.channel(ch)) for ch in requested]
                capture=self.comparison.capture() if comparison_views else None
                history=list(self.history);profiles=list(self.profiles);break
        grids=self.features.render(captured,share_cells);spectra=[]
        x=v['low_ns']+(np.arange(h.shape[-1])+.5)*v['bin_ps']/1000
        def points(counts):
            nonzero=counts>0 if compact else slice(None)
            return np.column_stack((x[nonzero],counts[nonzero])).tolist()
        for d in range(3):
            counts=by_class[d,cs,:].sum(axis=0)
            series=[dict(category=CATEGORIES[c],points=points(by_class[d,c]),counts=int(by_class[d,c].sum())) for c in cs] if individual else []
            spectra.append(dict(direction=DIRECTIONS[d],points=points(counts),counts=int(counts.sum()),contributions=series))
        per_direction=by_class.sum(axis=2)
        comparison = {}
        if comparison_views:
            result = self._comparisons(comparison_views, capture, state['profile']['channels'])
            if include_all_paths:
                uncut = {d: display.model_copy(update={'origin':'all', 'scatter':'all'})
                         for d, display in comparison_views.items() if display.origin != 'all' or display.scatter != 'all'}
                if uncut:
                    result['all_paths'] = self._comparisons(uncut, capture, state['profile']['channels'])['comparisons']
            comparison['comparison'] = result
        return dict(**state,spectra=spectra,view=v,categories=available,origins=ORIGINS,phs=phs,plots=grids,
                    category_counts={name:int(per_direction[:,i].sum()) for i,name in enumerate(CATEGORIES)},
                    direction_counts={direction:{name:int(per_direction[d,c]) for c,name in enumerate(CATEGORIES)} for d,direction in enumerate(DIRECTIONS)},
                    diagnostics=[dict(channel='AB'[ch],area=f[:,:2].tolist(),shape=f[:,[2,3,0]].tolist()) for ch,f in diagnostics],
                    history=history,processing_profiles=profiles,
                    **comparison,
                    note='Each spectrum includes accepted pairs since its own reset. PHS and filter maps include every channel pulse with valid CF timing since their respective resets.')

    def waveform(self,seq,channels=None,traces=None,pulse_selection=None):
        with self.lock:
            if not 1<=seq<=self.seen:raise ValueError('Selected waveform is unavailable.')
            self.positions.flush()
            with open(self.positions.name,'rb') as source:
                source.seek((seq-1)*POSITION.itemsize);row=np.fromfile(source,dtype=POSITION,count=1)[0]
            file=int(row['file']);offset=int(row['offset']);revision=int(row['revision']);profile=self.effective(self.profiles[revision],file)
        reader=Reader(self.paths[file])
        try:
            if reader.header!=self.headers[file]:raise ValueError('Pulse stream changed since acquisition.')
            meta,data=reader.record(offset)
            reader.transports=self.native_index if self.native_index is not None else TransportIndex(self.db,file,self.lock)
            transport=lru_cache(maxsize=16)(reader.transport)
            self._enrich(reader,meta,OrderedDict(),transport);r=process((offset,meta,data,profile,reader.header['isotope']))
            recorded=r
            if channels is not None:
                from .m3_models import Channel
                if len(channels)!=2:raise ValueError('Choose settings for both waveform channels.')
                rule=profile.get('pulse_selection','highest') if pulse_selection is None else pulse_selection
                if rule not in ('first','highest'):raise ValueError('Choose First pulse or Highest pulse.')
                profile=self.effective({**profile,'channels':[Channel.model_validate(ch).model_dump() for ch in channels],'pulse_selection':rule},file)
                r=process((offset,meta,data,profile,reader.header['isotope']))
            smoothed=[];interpolated=[]
            for ch,settings in enumerate(profile['channels']):
                width=settings['median_samples'];values=data[2*ch+1]
                smoothed.append(np.median(np.lib.stride_tricks.sliding_window_view(np.pad(values,width//2,mode='edge'),width),axis=1).tolist() if width>1 else None)
                from .m3_interpolation import trace
                interpolated.append(trace(data[2*ch],smoothed[-1] if width>1 else values,settings.get('interpolation','linear'),settings.get('intra_steps',8)) if traces and traces[ch] else None)
                feature=r['features'][ch]
                if 'baseline' in feature:
                    count=settings['baseline_samples']
                    times=data[2*ch]
                    start=feature['baseline_start']
                    feature['baseline_region']={'count':count, 'start_ns':float(times[start]), 'end_ns':float(times[start+count-1])}
                if feature['valid']:
                    sign=1 if settings['polarity']=='positive' else -1
                    feature['cfd_percent']=settings['cfd_percent']
                    feature['cfd_level_mV']=feature['baseline']+sign*feature['height']*settings['cfd_percent']/100
            from .provenance import preview_summary,pulse_routes
            truths=[]
            for role,record in sorted({(p['role'],p['record']) for value in (r,recorded) for channel in value['truth']['selected'] for p in channel}):
                tr=transport(role,record);h=reader.header['inputs'][role]['header']
                cutoffs=[{p['decay']:r['features'][ch]['cfd_ns']-p['origin_ns'] for p in pulses
                          if (p['role'],p['record'])==(role,record)} for ch,pulses in enumerate(r['truth']['selected'])]
                truths.append(dict(role=role,record=record,provenance=preview_summary(tr['provenance'],h['light_components'],h['role']),
                                   volumes=[c['volume'] for c in h['light_components']],
                                   paths=pulse_routes(tr['provenance'],h['light_components'],tr['photoelectrons'],cutoffs)))
            return dict(**r,sequence=seq,revision=revision,file_index=file,primary_roles=[v['header']['role'] for v in reader.header['inputs']],adc=self.adc[file],measured_direction=recorded['direction'],measured_truth=recorded['truth'],smoothed=smoothed,interpolated=interpolated,samples=data.tolist(),meta=meta,transport_truth=truths)
        finally:reader.close()


    def autofit(self,ch,window,kind,limits=None,options=None,include_counts=False):
        with self.lock:
            limits=limits or self.profile['channels'][ch][window]['phs']
        return self.features.fit(ch,kind,limits,options,include_counts)

    def close(self):
        self.cancel.set();self.run_gate.set();self.thread.join()
        if self.native_index is not None:self.native_index.close()
        self.db.close();self.positions.close();self.timings.close();self.comparison.file.close();self.features.close();self.temporary.cleanup()


class LifetimeManager:
    def __init__(self):
        self.session=None
        self.lock=threading.RLock()
        self.readers={}

    def active(self):
        with self.lock:return self.session is not None and self.session.thread.is_alive()

    def current(self):
        with self.lock:return self.session.state() if self.session else None

    def check_selection(self,store,paths):
        with self.lock:
            if self.active() and self.session.status!='paused':
                if [store.resolve_path(p) for p in paths if p]!=self.session.paths:
                    raise Conflict('Stop the stream before selecting another input.')

    @contextmanager
    def borrow(self):
        # A waveform or rebin request may still use the old journal during restart.
        with self.lock:
            job=self.session
            if job is None:raise ValueError('Open a pulse stream and start Module 3 first.')
            self.readers[job]=self.readers.get(job,0)+1
        try:
            yield job
        finally:
            with self.lock:
                self.readers[job]-=1
                close=False
                if not self.readers[job]:
                    del self.readers[job]
                    close=self.session is not job
            if close:job.close()
    def check(self,store,raw):
        profile=Profile.model_validate(raw).model_dump();paths=[store.resolve_path(v) for v in profile['input_paths']]
        if not paths:raise ValueError('Choose one Module 2 pulse stream.')
        headers=[]
        for path in paths:
            if not (path.name.endswith('.tppulses') or path.name.endswith('.tppulses.part')):
                raise ValueError('Choose .tppulses or .tppulses.part files.')
            r=Reader(path)
            try:headers.append(r.header)
            finally:r.close()
        conflict=selection_error(headers)
        if conflict:raise ValueError(conflict)
        return profile,paths,headers
    def start(self,store,raw,restart=None):
        with self.lock:
            if restart is not None and (not self.session or self.session.id!=restart):raise Conflict('The active Module 3 stream has changed.')
            reading=self.active() and self.session.status!='paused'
            if restart is None and reading:raise Conflict('Module 3 is already reading.')
            args=self.check(store,raw)
            previous=self.session
            if reading and args[1]!=previous.paths:raise Conflict('Stop the stream before selecting another input.')
            if previous and previous.thread.is_alive():
                previous.cancel.set();previous.run_gate.set();previous.thread.join()
            self.session=Acquisition(*args)
            close=previous is not None and previous not in self.readers
            state=self.session.state()
        if close:previous.close()
        return state
    def hold(self,job_id,resume=False):
        with self.lock:
            job=self.session
            if not job or job.id!=job_id:raise Conflict('The active Module 3 stream has changed.')
            with job.lock:
                if resume and job.status in ('paused','pausing'):
                    if job.paused_at is not None:
                        job.paused_seconds+=time.monotonic()-job.paused_at;job.paused_at=None
                    job.status='running';job.run_gate.set()
                elif not resume and job.status=='running':
                    job.run_gate.clear();job.status='pausing'
                return job.state()

    def stop(self):
        with self.lock:
            if self.session:
                with self.session.lock:
                    if self.session.thread.is_alive():
                        self.session.cancel.set();self.session.run_gate.set();self.session.status='stopping'
            return self.current()
    def shutdown(self):
        with self.lock:
            previous=self.session;self.session=None
            if previous:previous.cancel.set();previous.run_gate.set()
            close=previous is not None and previous not in self.readers
        if close:previous.close()

