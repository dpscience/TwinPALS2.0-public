# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Independent cancellable Module 2 job and in-memory pulse analysis."""
from array import array
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import threading
import time
import uuid
import numpy as np
from .m1_store import encode, Conflict
from .m2_models import resolve,validate_lifetime_mixture
from .m2_physics import input_info, load_libraries, SourceBatches, acquire_batched, CLASS_NAMES, CLASS_LABELS
from .m2_stream import Writer, Reader
from .acquired_persistence import AcquiredPersistence


class Cancelled(Exception): pass


def wave_json(meta,data,limit=2048):
    # The record/export keeps every sample. Only the live thumbnail is reduced.
    step=max(1,math.ceil(data.shape[1]/limit))
    if hasattr(meta,'full'):meta=meta.full()
    return {**meta,'waveform':data[:,::step].tolist(),'samples':data.shape[1],'display_stride':step}


class PulseAnalysis:
    def __init__(self,header):
        self.header=header; self.lock=threading.RLock()
        self.features=array('d'); self.classes=array('B');self.ids=array('Q')
        self.offsets=array('Q');self.files=array('I');self.paths=[]
        self.counts=Counter();self.preview=deque(maxlen=header['profile']['preview_limit'])
        self._last_record=None;self._last_json=None;self.version=0
        self.persistence=AcquiredPersistence(header["profile"])
        self.query_lock=threading.Lock()
        self._indexed=0;self._groups={};self._query_cache=None

    @property
    def last(self):
        # JSON conversion belongs to display polling, not the acquisition loop.
        # Keep exactly one immutable record; every pair still enters statistics.
        with self.lock:
            if self._last_record is None:return None
            if self._last_json is None:self._last_json=wave_json(*self._last_record)
            return self._last_json

    def append(self,meta,data,path,offset):
        baseline=meta['baseline_mV']
        prepared=getattr(data,'monitor_features',None)
        if prepared is None:
            magnitudes=[np.abs(data[i+1].astype(float)-baseline[ch]) for ch,i in enumerate((0,2))]
            peaks=[float(np.max(v)) for v in magnitudes]
            areas=[float(np.trapezoid(v,data[ch*2])) for ch,v in enumerate(magnitudes)]
            delta=float(data[2,int(np.argmax(magnitudes[1]))]-data[0,int(np.argmax(magnitudes[0]))])
        else:peaks=prepared[:2];areas=prepared[2:4];delta=float(prepared[4]);magnitudes=None
        with self.lock:
            self._record(meta,data,path,offset,peaks,areas,delta,magnitudes)

    def _record(self,meta,data,path,offset,peaks,areas,delta,magnitudes):
        if path not in self.paths:self.paths.append(path)
        self.persistence.append(meta,data,magnitudes,areas)
        self.features.extend((*peaks,*areas,delta,meta['start_ns']))
        self.classes.append(CLASS_NAMES.index(meta['class']));self.ids.append(meta['id'])
        self.files.append(self.paths.index(path));self.offsets.append(offset)
        self.counts[meta['class']]+=1
        self._last_record=(meta,data);self._last_json=None
        self.preview.append({'id':meta['id'],'index':len(self.ids)-1,'class':meta['class']})
        self.version+=1

    def publish_import(self,rows):
        if not rows:return
        samples=np.stack([row[1] for row in rows])
        times=samples[:,::2,:]
        baselines=np.array([row[0]['baseline_mV'] for row in rows],dtype=float)
        magnitudes=np.abs(samples[:,1::2,:].astype(float)-baselines[:,:,None])
        peaks=magnitudes.max(axis=2)
        areas=np.trapezoid(magnitudes,times,axis=2)
        maxima=np.take_along_axis(times,magnitudes.argmax(axis=2)[:,:,None],axis=2)[:,:,0]
        deltas=maxima[:,1]-maxima[:,0]
        with self.lock:
            for i,row in enumerate(rows):
                self._record(*row,peaks[i],areas[i],deltas[i],magnitudes[i])

    def query(self,selection):
        # Serialize readers, not acquisition. Only the newly appended compact
        # feature rows are copied under the writer lock.
        with self.query_lock:return self._query(selection)

    def publish(self,rows):
        if not rows:return
        if not all(hasattr(data,'transport_keys') for _,data,_,_ in rows):
            for row in rows:self.append(*row)
            return
        features=np.empty((len(rows),6),dtype=np.float64)
        features[:,:5]=[r[1].monitor_features for r in rows]
        summaries=[r[0].summary for r in rows]
        features[:,5]=[m['start_ns'] for m in summaries]
        with self.lock:
            if not self.persistence.prepared_batch(rows,features):
                for i,(meta,data,_,_) in enumerate(rows):
                    self.persistence.append(meta,data,None,features[i,2:4])
            first=len(self.ids)
            self.features.frombytes(features.tobytes())
            self.classes.extend(CLASS_NAMES.index(m['class']) for m in summaries)
            self.ids.extend(m['id'] for m in summaries)
            self.counts.update(m['class'] for m in summaries)
            self.offsets.extend(r[3] for r in rows)
            for _,_,path,_ in rows:
                if path not in self.paths:self.paths.append(path)
                self.files.append(self.paths.index(path))
            self.preview.extend({'id':m['id'],'index':first+i,'class':m['class']} for i,m in enumerate(summaries))
            self._last_record=rows[-1][:2];self._last_json=None;self.version+=len(rows)

    def publish_sweeps(self,batch,path,offsets):
        n=len(batch.rows)
        codes=batch.rows['classification'].astype('u1')
        features=np.column_stack((batch.features,(batch.crossings[:,0]+batch.delay)-batch.window))
        ids=np.arange(batch.first,batch.first+n,dtype=np.uint64)
        self.publish_monitor(batch,path,offsets,features,codes,ids)

    def publish_monitor(self,batch,path,offsets,features,codes,ids):
        n=len(ids)
        last=batch.record(n-1)
        with self.lock:
            self.persistence.prepared_sweeps(batch)
            first=len(self.ids)
            self.features.frombytes(features.tobytes());self.classes.frombytes(codes.tobytes())
            self.ids.frombytes(ids.tobytes());self.offsets.frombytes(offsets.tobytes())
            if path not in self.paths:self.paths.append(path)
            self.files.frombytes(np.full(n,self.paths.index(path),dtype=np.uint32).tobytes())
            # Preserve the first appearance order used by the live class counts.
            if len(self.counts)<len(CLASS_NAMES):
                for code in dict.fromkeys(codes.tolist()):
                    self.counts.setdefault(CLASS_NAMES[code],0)
            for kind,count in enumerate(np.bincount(codes)):
                if count:self.counts[CLASS_NAMES[kind]]+=int(count)
            self.preview.extend({'id':int(ids[i]),'index':first+i,'class':CLASS_NAMES[codes[i]]}
                                for i in range(max(0,n-self.preview.maxlen),n))
            self._last_record=last;self._last_json=None;self.version+=n

    def _query(self,selection):
        from .histogram_index import SortedValues
        bins=selection.get('bins',120);category=selection.get('category','all')
        if type(bins) is not int or not 10<=bins<=1000 or category not in ('all',*CLASS_NAMES):
            raise ValueError('Choose 10–1000 bins and an available pulse class.')
        with self.lock:
            total=len(self.ids)
            key=(self.version,bins,category)
            if self._query_cache is not None and self._query_cache[0]==key:return self._query_cache[1]
            data=np.frombuffer(self.features,dtype=np.float64,offset=self._indexed*6*8).reshape(-1,6).copy()
            classes=np.frombuffer(self.classes,dtype=np.uint8,offset=self._indexed).copy()
            counts=dict(self.counts);version=self.version
            persistence=self.persistence.snapshot()
        for code in np.unique(classes):
            group=self._groups.setdefault(int(code),[SortedValues() for _ in range(5)])
            rows=data[classes==code]
            for column,index in enumerate(group):index.append(rows[:,column],0)
        self._indexed=total
        groups=list(self._groups.values()) if category=='all' else ([self._groups[CLASS_NAMES.index(category)]] if CLASS_NAMES.index(category) in self._groups else [])
        selected=sum(g[0].count for g in groups)
        plots=[]
        for title,unit,columns in [('Pulse height','mV',[0,1]),('Pulse area','mV ns',[2,3]),('Peak-time difference · B − A','ns',[4])]:
            if selected:
                limits=[g[c].bounds(False) for g in groups for c in columns]
                lo,hi=min(x[0] for x in limits),max(x[1] for x in limits)
                if lo==hi:lo-=.5;hi+=.5
            else:lo,hi=0.,1.
            edges=np.linspace(lo,hi,bins+1)
            series=[]
            for i,col in enumerate(columns):
                c=np.zeros(bins,dtype=np.int64)
                for group in groups:c+=group[col].histogram(edges,lo,hi,False)[0]
                series.append({'name':'AB'[i] if len(columns)>1 else 'B − A','edges':edges.tolist(),'counts':c.tolist()})
            plots.append({'title':title,'unit':unit,'series':series})
        result={'version':version,'total':total,'selected':selected,'counts':counts,'plots':plots,'persistence':persistence}
        self._query_cache=(key,result)
        return result

    def waveform(self,index):
        with self.lock:
            if not 0<=index<len(self.ids): raise ValueError('Choose an existing waveform index.')
            path=self.paths[self.files[index]];offset=self.offsets[index]
        path=Path(path)
        if not path.exists() and path.suffix=='.part':path=path.with_suffix('')
        reader=Reader(path)
        try:return wave_json(*reader.record(offset),limit=65536)
        finally:reader.close()


class PulseManager:
    def __init__(self):
        self.lock=threading.RLock();self.job=None;self.thread=None
        self.cancel_event=threading.Event();self.analysis=None

    def active(self):
        with self.lock:return self.job is not None and self.job['status'] in ('queued','loading','running','cancelling')

    def shutdown(self):
        self.cancel_event.set()
        if self.thread and self.thread.is_alive():self.thread.join(timeout=15)

    def cancel(self):
        if self.cancel_event.is_set():raise Cancelled()

    def stop(self,identifier):
        with self.lock:
            if not self.job or self.job['id']!=identifier:raise ValueError('This Module 2 job is no longer current.')
            if self.active():self.job['status']='cancelling';self.cancel_event.set()
        return self.current()

    def current(self):
        with self.lock:
            if not self.job:return None
            value=copy.deepcopy(self.job)
            elapsed=time.monotonic()-value.pop('_started') if value['status'] in ('queued','loading','running','cancelling') else value.get('elapsed_s',0)
            value['elapsed_s']=elapsed
            acquisition_started=value.pop('_acquisition_started',None)
            acquisition_elapsed=max(0,time.monotonic()-acquisition_started) if acquisition_started else elapsed
            analysis=self.analysis
        if analysis:
            with analysis.lock:
                value.update(waveforms=len(analysis.ids),counts=dict(analysis.counts),preview=list(analysis.preview),latest=analysis.last,version=analysis.version)
            # Show the same committed count in the counter and progress bar.
            # The worker can already hold further records in its write buffer.
            if value.get('kind')=='simulation' and value.get('target_pairs'):
                value['progress']=min(1.,value['waveforms']/value['target_pairs'])
            exposure=max(value.get('source_duration_ns',0),value['latest']['busy_until_ns'] if value['latest'] else 0)
            value['acquisition_rate_Hz']=value['waveforms']*1e9/exposure if exposure>0 else 0.
        fraction=value['progress']
        # A fixed pair target may exceed what the input libraries can produce.
        # Acquisition ends at the target OR source exhaustion, whichever is first.
        completion_fraction=fraction
        if value.get('kind')=='simulation' and value.get('total_decays',0):
            completion_fraction=max(fraction,value.get('processed_decays',0)/value['total_decays'])
        value['eta_s']=acquisition_elapsed*(1-completion_fraction)/completion_fraction if .000001<completion_fraction<1 and value['status']=='running' and acquisition_elapsed>=2 else None
        if value.get('kind')=='import' and value['status']=='loading' and .001<fraction<1:
            value['eta_s']=elapsed*(1-fraction)/fraction
        value['estimated_finish']=datetime.fromtimestamp(time.time()+value['eta_s'],timezone.utc).isoformat() if value['eta_s'] is not None else None
        return value

    def update(self,**values):
        with self.lock:self.job.update(values)

    def check(self,store,raw):
        resolved=resolve(raw,store.components.entries(),check_mixture=False)
        p=resolved['profile']
        p['input_paths']=[str(store.resolve_path(v)) for v in p['input_paths']]
        p['output_path']=str(store.resolve_path(p['output_path']))
        info=input_info(p['input_paths'])
        if info['isotope']=='na22':
            validate_lifetime_mixture(p['lifetimes'])
        responses=info['streams'][0]['header']['analog_response']
        if any(i['header']['analog_response']!=responses for i in info['streams']):
            raise ValueError('Module 1 streams have different PMT response snapshots. Select the two outputs of one run.')
        resolved['analog_response']=responses
        for ch,r in enumerate(responses):
            peak=info['observed_maximum_mV'][ch]*10**(-p['channels'][ch]['attenuation_dB']/20)
            d=p['digitization']
            positive=(r['polarity']=='positive') != p['channels'][ch].get('invert',False)
            rail=(d['voltage_max_mV']-d['baseline_mV']) if positive else (d['baseline_mV']-d['voltage_min_mV'])
            if rail<=0:
                resolved['warnings'].append(f'Channel {"AB"[ch]}: the {"positive" if positive else "negative"} pulse after the inverter has no ADC headroom at baseline {d["baseline_mV"]:g} mV in the input range {d["voltage_min_mV"]:g} to {d["voltage_max_mV"]:g} mV. Change Setup → {"AB"[ch]} → Invert polarity or select a digitizer with a compatible input range. These pulses will be clipped; attenuation cannot correct the sign.')
            elif p['channels'][ch]['threshold_mV']>=rail:
                raise ValueError(f'Setup → DAQ → Threshold {"AB"[ch]} must be below {rail:g} mV, the available input range for this pulse polarity.')
            if rail>0 and peak>=rail:
                needed=20*math.log10(info['observed_maximum_mV'][ch]/max(rail,1e-9))
                resolved['warnings'].append(f'Channel {"AB"[ch]}: the largest stored isolated pulse is {peak:.3g} mV after attenuation. Available headroom is {rail:.3g} mV. Use more than {needed:.2f} dB attenuation for isolated pulses; pile-up and noise can require additional headroom. Input bandwidth can reduce the peak.')
            if not math.isclose(r['load_ohm'],p['digitization']['input_impedance_ohm'],rel_tol=1e-8):
                resolved['warnings'].append(f'Channel {"AB"[ch]}: M1 voltage is defined across {r["load_ohm"]:g} ohm; this digitizer input is {p["digitization"]["input_impedance_ohm"]:g} ohm. Use a matched output/load or regenerate M1. Voltage is not rescaled a second time; cable and termination changes are not simulated.')
        maximum=info['max_decays'] if p['shuffle'] else min(info['counts'])
        resolved['source_capacity']=maximum
        if info['isotope']=='co60':
            resolved['warnings'].append('Co-60 uses prompt correlated cascades. Positron lifetime components are ignored.')
        return resolved,info

    def create(self,store,raw,overwrite=False):
        with self.lock:
            if self.active():raise Conflict('Module 2 is already running or importing. Stop it before starting another Module 2 job.')
            resolved,info=self.check(store,raw)
            p=resolved['profile'];path=Path(p['output_path'])
            paths=[path]
            exists=[str(v) for v in paths if v.exists() or v.with_name(v.name+'.part').exists()]
            if exists and not overwrite:raise Conflict('File already exists: '+', '.join(exists)+'. Confirm replacement first.')
            if p['auto_seed']:p['seed']=time.time_ns() % (2**63-2)+1
            from .cell_timing import generate_cell_intervals
            resolved['cell_intervals_ns']=generate_cell_intervals(resolved['digitizer'],p['seed'])
            identifier=uuid.uuid4().hex
            header={'format':'twinpals-pulse-stream','version':6,'run_id':identifier,
                    'created_utc':datetime.now(timezone.utc).isoformat(),'isotope':info['isotope'],
                    'profile':p,'settings_sha256':hashlib.sha256(encode(p).encode()).hexdigest(),
                    'resolved':resolved,'inputs':info['streams'],'class_names':list(CLASS_NAMES),
                    'model':{'pulse':'Stored M1 analog Erlang superposition; no additional PMT effects','trigger':'signal-magnitude threshold; voltage noise does not trigger',
                             'rng_policy':'separate source/acquisition generators; ordered per-waveform seeds; global trigger grid v2','tail_charge_fraction':1e-12,'input_filter':'causal one-pole or ideal (0 MHz)','dead_time':'non-paralyzable after window end','time_axis':'N/fs window; (N-1)/fs uniform span'}}
            self.analysis=PulseAnalysis(header);self.cancel_event=threading.Event()
            self.job={'id':identifier,'kind':'simulation','status':'queued','phase':'Reading input streams','progress':0.,
                      'processed_decays':0,'total_decays':resolved['source_capacity'],'target_pairs':None if p['maximum'] else p['waveform_pairs'],'paths':[str(v)+'.part' for v in paths],
                      'header':header,'message':'','_started':time.monotonic()}
            self.thread=threading.Thread(target=self._run,args=(resolved,info,paths,overwrite),daemon=True,name='TwinPALS-M2')
            self.thread.start()
        return self.current()

    def _run(self,resolved,info,paths,overwrite):
        resolved=copy.deepcopy(resolved)  # Runtime mmap libraries never enter the immutable header/UI snapshot.
        writers=[];status='completed';summary={};pending=[];pending_bytes=0;libraries=[]
        early_workers=None;writer_pool=None;history_pool=None;writes=deque()
        write_error=None;copies=[];copy_bytes=0;last_copy=time.monotonic()
        from .native_sweeps import SweepBatch
        def commit(rows):
            writer=writers[0];path=str(writer.part)
            offsets=writer.write_group(rows,libraries);writer.flush()
            published=[(meta,data,path,offset) for (meta,data),offset in zip(rows,offsets)]
            self.analysis.publish(published)
        def commit_prepared(groups):
            nonlocal write_error
            if write_error is not None:raise write_error
            try:
                writer=writers[0]
                prepared=[(batch,*future.result()) for batch,future in groups]
                positions=[writer.write_prepared(data,offsets) for _,data,offsets in prepared]
                writer.flush()
                for (batch,_,_),offsets in zip(prepared,positions):
                    self.analysis.publish_sweeps(batch,str(writer.part),offsets)
            except BaseException as exc:
                write_error=exc
                raise
        def submit_copies():
            nonlocal copies,copy_bytes,last_copy
            if not copies:return
            # At most three groups of four bounded batches may be in flight.
            if len(writes)>=2:writes.popleft().result()
            writes.append(writer_pool.submit(commit_prepared,copies))
            copies=[];copy_bytes=0;last_copy=time.monotonic()
        def enqueue(rows):
            nonlocal copy_bytes
            if history_pool is not None:
                if isinstance(rows,SweepBatch):
                    prepared=writers[0].prepare_sweeps(rows,libraries,history_pool)
                    if prepared is not None:
                        copies.append((rows,prepared));copy_bytes+=len(rows.frames)
                        if rows.first==0 or len(copies)>=4 or copy_bytes>=4*1024**2 or time.monotonic()-last_copy>.04:
                            submit_copies()
                        return
                # Reference jobs can contain a large history or a dense timeline.
                # Complete earlier claims before inserting their records.
                submit_copies()
                while writes:writes.popleft().result()
                if write_error is not None:raise write_error
                if isinstance(rows,SweepBatch):
                    rows=[rows.record(i) for i in range(len(rows.rows))]
                commit(rows)
                return
            if isinstance(rows,SweepBatch):
                rows=[rows.record(i) for i in range(len(rows.rows))]
            if writer_pool is None:
                commit(rows);return
            # Only one group may precede the one being handed off. A previous
            # write must succeed before scheduling another on the same stream.
            if writes:writes.popleft().result()
            writes.append(writer_pool.submit(commit,rows))
        def publish():
            nonlocal pending
            if pending:
                rows=pending;pending=[];enqueue(rows)
        def drain():
            publish()
            submit_copies()
            while writes:writes.popleft().result()
        try:
            p=resolved['profile'];self.update(status='loading')
            resolved['_monitor_persistence']=self.analysis.persistence
            resolved['_stream_batches']=True
            from .execution import resolve_threads
            from .native_acquisition import binding as scan_binding
            from .waveform_workers import WaveformWorkers,process_count
            threads=resolve_threads(p.get('threads',0),max(info['counts']))
            step=min(p['acquisition']['trigger_step_ns'],1/p['digitization']['rate_GSps']/4)
            if threads>1 and min(info['counts'])>=8192 and p['acquisition']['dead_ns']>=2048*step and scan_binding() is not None:
                workers=process_count(threads,p['digitization']['samples'])
                early_workers=WaveformWorkers(resolved,workers,self.cancel,responses=[s['header']['analog_response'] for s in info['streams']])
                early_workers.warm(workers);resolved['_waveform_workers']=early_workers
            libraries=load_libraries({**info,'_threads':p.get('threads',0),'_pack_onsets':p['shuffle'],
                                      '_retain_input_maps':True},self.cancel,lambda f:self.update(input_progress=f))
            self.cancel();self.update(status='running',phase='Generating source decays',progress=0.,input_progress=1.,_acquisition_started=time.monotonic())
            source_seed,acquisition_seed=np.random.SeedSequence(p['seed']).spawn(2)
            source=SourceBatches(resolved,info,libraries,np.random.default_rng(source_seed),self.cancel)
            rng=np.random.default_rng(acquisition_seed)
            self.update(phase='Acquiring waveform pairs',progress=0.)
            for index,path in enumerate(paths):
                header=copy.deepcopy(self.analysis.header)
                header['stream_id']=uuid.uuid4().hex
                header['class_filter']='all'
                writers.append(Writer(path,header,overwrite))
            if early_workers is not None and threads>=4:
                writer_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='M2-stream-writer')
                if early_workers.direct:
                    history_pool=ThreadPoolExecutor(max_workers=min(4,threads-2),thread_name_prefix='M2-history')
            last_flush=time.monotonic()
            saved=0;last_busy=0.
            def progress(f):
                fraction=f if p['maximum'] else saved/p['waveform_pairs']
                projected=round(saved/f) if f>0 and source.processed>=1024 and saved>=10 else None
                if projected is not None and not p['maximum']:projected=min(projected,p['waveform_pairs'])
                self.update(progress=min(1.,fraction),processed_decays=source.processed,estimated_total_pairs=projected)
            rows=acquire_batched(source,resolved,rng,self.cancel,progress)
            try:
                for meta,data in rows:
                    self.cancel()
                    if isinstance(data,SweepBatch):
                        publish();enqueue(data);pending_bytes=0
                        saved+=len(data.rows);last_busy=meta['busy_until_ns']
                        progress(source.processed/source.capacity);last_flush=time.monotonic()
                        continue
                    pending.append((meta,data));pending_bytes+=data.nbytes
                    saved+=1;last_busy=meta['busy_until_ns']
                    if time.monotonic()-last_flush>.25 or pending_bytes>=1024*1024 or len(pending)>=64:
                        publish();pending_bytes=0;progress(source.processed/source.capacity)
                        last_flush=time.monotonic()
            finally:rows.close()
            drain();self.cancel()
            reached=not p['maximum'] and saved>=p['waveform_pairs']
            # A target-limited exposure ends after its final complete readout;
            # generation may already hold a bounded lookahead batch in memory.
            exposure=last_busy if reached else max(source.clock,last_busy)
            summary.update(source_duration_ns=exposure,generated_decays=source.generated,
                           source_capacity=source.capacity,first_record_ids=source.first_record_ids,
                           stop_reason='target_reached' if reached else 'input_exhausted',
                           waveform_pairs=saved,counts=dict(self.analysis.counts))
            self.update(progress=(1. if p['maximum'] else min(1.,saved/p['waveform_pairs'])),processed_decays=source.processed,estimated_total_pairs=saved,source_duration_ns=exposure,
                        stop_reason=summary['stop_reason'])
        except Cancelled:status='cancelled'
        except Exception as exc:
            status='failed';self.update(message=str(exc))
        finally:
            resolved.pop('_libraries',None)
            if early_workers is not None:early_workers.close()
            try:drain()
            except Exception as exc:status='failed';self.update(message=f'Could not publish saved waveforms: {exc}')
            finally:
                if writer_pool is not None:writer_pool.shutdown(wait=True)
                if history_pool is not None:history_pool.shutdown(wait=True)
            for library in libraries: library.close()
            for writer in writers:
                try:writer.finish(status,summary)
                except Exception as exc:status='failed';self.update(message=f'Could not finalize pulse stream: {exc}')
            paths=[str(w.path if w.path.exists() and not w.part.exists() else w.part) for w in writers]
            self.update(status=status,phase=status.title(),paths=paths,elapsed_s=time.monotonic()-self.job['_started'])

    def import_streams(self,store,paths,workers=0):
        from .execution import import_workers
        workers=import_workers(workers)
        with self.lock:
            if self.active():raise Conflict('Stop Module 2 or wait for its import before opening a pulse stream.')
            if not isinstance(paths,list) or len(paths)!=1 or not isinstance(paths[0],str) or not paths[0].strip():
                raise ValueError('Select exactly one pulse stream.')
            reader=Reader(store.resolve_path(paths[0]))
            try:
                header=reader.header
                self.analysis=PulseAnalysis(header);self.cancel_event=threading.Event()
                self.job={'id':uuid.uuid4().hex,'kind':'import','status':'loading','phase':'Reading pulse stream','progress':0.,
                          'workers':workers,'processed_decays':0,'total_decays':header['resolved']['source_capacity'],
                          'target_pairs':None if header['profile']['maximum'] else header['profile']['waveform_pairs'],
                          'paths':[str(reader.path)],'header':header,'message':'','_started':time.monotonic()}
                self.thread=threading.Thread(target=self._import,args=(reader,workers),daemon=True,name='TwinPALS-M2-import')
                self.thread.start()
            except BaseException:
                reader.close()
                raise
        return self.current()

    def _import(self,reader,workers):
        from .m2_import import read_stream
        status='completed'
        try:
            read_stream(reader,self.analysis,workers,self.cancel,lambda at:self.update(progress=at/reader.limit))
            partial=reader.completion is None or reader.completion['status']!='completed'
            summary=(reader.completion or {}).get('summary',{})
            self.update(progress=1.,processed_decays=summary.get('generated_decays',0),
                        source_duration_ns=summary.get('source_duration_ns',0),
                        phase='Partial stream' if partial else 'Completed')
            if partial:status='partial'
        except Cancelled:status='cancelled'
        except Exception as exc:status='failed';self.update(message=str(exc))
        finally:
            reader.close()
            self.update(status=status,elapsed_s=time.monotonic()-self.job['_started'])
