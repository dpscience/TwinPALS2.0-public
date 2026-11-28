# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Source-clock superposition of stored analog M1 events and generic acquisition.
No scintillation draw, photocathode acceptance, PMT shape, gain or TTS occurs here.
"""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from copy import copy
from .execution import resolve_threads
import math
from .analog_pmt import evaluate, tail_span
from pathlib import Path
import numpy as np
from .streams import _Snapshot, _open_shared_read, _check_identities, inspect_stream, StreamError

CLASS_NAMES = ('single', 'true_A_start', 'true_B_start', 'same_primary_1',
               'same_primary_2', 'mixed_same_decay', 'accidental', 'pileup')
CLASS_LABELS = ('Single channel', 'True pair · A start', 'True pair · B start',
                'Primary 1 in A + B', 'Primary 2 in A + B', 'Mixed · same decay',
                'Accidental pair', 'Pile-up')
TAIL_FRACTION = 1e-12
PULSE_DTYPE = np.dtype([('time', '<f8'), ('height', '<f8'), ('channel', 'u1'),
                       ('role', 'u1'), ('decay', '<u8'), ('record', '<u8'),
                       ('source_time', '<f8'), ('lifetime', '<f8'), ('component', '<u2'), ('origin', '<f8'), ('span', '<f8'), ('peak_time', '<f8'), ('light_origin','u1')])


def input_info(paths):
    paths = [Path(p).resolve() for p in paths]
    if len(paths) != 2 or len(set(paths)) != 2:
        raise ValueError('Input streams: choose two different Module 1 streams from one run.')
    info = [inspect_stream(p) for p in paths]
    if any(i['completion']['status'] != 'completed' for i in info):
        raise ValueError('Input streams must be completed .tpstream files. Wait for Module 1 to finish.')
    by_role = {i['header']['role']: i for i in info}
    if set(by_role) == {'na22_prompt', 'na22_annihilation'}:
        isotope, roles = 'na22', ['na22_prompt', 'na22_annihilation']
    elif set(by_role) == {'co60_1173', 'co60_1332'}:
        isotope, roles = 'co60', ['co60_1173', 'co60_1332']
    else:
        raise ValueError('Input streams: select Na-22 1275 + 511, or Co-60 1173 + 1332. Do not mix isotopes or duplicate primary types.')
    ordered = [by_role[r] for r in roles]
    for field in ('run_id', 'settings_sha256'):
        values = [i['header'].get(field) for i in ordered]
        if not all(values) or values[0] != values[1]:
            raise ValueError(f'Input streams have different or missing {field}. Choose both outputs of the same Module 1 run.')
    if ordered[0]['header'].get('stream_id') == ordered[1]['header'].get('stream_id'):
        raise ValueError('The same stream cannot be selected twice.')
    counts = [i['completion']['events'] for i in ordered]
    if not all(counts): raise ValueError('Both input streams must contain events.')
    if isotope == 'co60' and counts[0] != counts[1]:
        raise ValueError('Co-60 cascade streams must have equal event counts and matching event IDs.')
    maxima=[max(s['completion'].get('eligible_maximum_mV',s['completion'].get('observed_maximum_mV',[0.,0.]))[ch] for s in ordered) for ch in range(2)]
    detector_counts=[s['completion'].get('detector_counts') for s in ordered]
    eligible=[s['completion'].get('eligible_response_counts', c['response'] if c else None)
              for s,c in zip(ordered,detector_counts)]
    directional=None
    if isotope=='na22' and all(detector_counts):
        directional={k:[detector_counts[0][k][d]*detector_counts[1][k][1-d] for d in range(2)] for k in ('interaction','response')}
        directional['response']=[eligible[0][d]*eligible[1][1-d] for d in range(2)]
    elif isotope=='co60':
        a,b=[s['completion'].get('cascade_pair_counts') for s in ordered]
        if a!=b:raise ValueError('Co-60 input summaries disagree on matched cascade pairs.')
        directional=a
    return {'isotope': isotope, 'streams': ordered, 'counts': counts,'observed_maximum_mV':maxima,
            'detector_counts':detector_counts,'eligible_response_counts':eligible,'directional_combinations':directional,
            'physics':ordered[0]['header']['physics'],
            'pulse_origin_counts':[s['completion'].get('pulse_origin_counts') for s in ordered],
            'max_decays': counts[0]*counts[1] if isotope == 'na22' else counts[0]}


class AnalogLibrary:
    """Summary array plus read-only memory-mapped analytic pulses. No waveform pool."""
    def __init__(self, path, count, responses):
        self.values=np.zeros((count,4),dtype=float)
        self.index=np.zeros((count,3),dtype=np.uint64)
        self.provenance_index=np.zeros((count,2),dtype=np.uint64)
        self.start=np.zeros((count,2));self.span=np.zeros((count,2));self.peaks=np.zeros((count,2))
        self.responses=responses;self.path=path;self.map=None
        self.onset_map=None;self.onset_offsets=None;self.onset_folder=None
        self.light_origins=np.zeros((count,2),dtype="u1")
    def __len__(self):return len(self.values)
    def __getitem__(self,key):return self.values[key]
    def onsets(self,row,ch):
        if not self.values[row,2*ch]: return np.empty(0,dtype='<f8')
        offset,a,b=(int(v) for v in self.index[row])
        if self.map is None:self.map=np.memmap(self.path,mode='r',dtype='u1')
        values=np.ndarray((a+b,4),dtype='<f8',buffer=self.map,offset=offset+16)
        return values[:a,1] if ch==0 else values[a:,1]
    def close(self):
        if self.map is not None:self.map._mmap.close();self.map=None
        if self.onset_map is not None:self.onset_map._mmap.close();self.onset_map=None
        if self.onset_folder is not None:self.onset_folder.cleanup();self.onset_folder=None

    def transport(self,row):
        if self.map is None:self.map=np.memmap(self.path,mode='r',dtype='u1')
        offset,a,b=map(int,self.index[row]);size=16+34*(a+b)
        at,n=map(int,self.provenance_index[row])
        return bytes(self.map[offset:offset+size]),bytes(self.map[at:at+n])


def load_libraries(info, cancel, progress):
    """CRC-validate summaries and analog frames; retain offsets, not every PE in RAM."""
    if not info.get('_reference_reader',False):
        from .native_transport_index import binding,load,ReferenceValidation
        if binding() is not None:
            try:return load(info,cancel,progress)
            except ReferenceValidation:
                # Preserve original validation at floating-point boundaries and
                # for precise corrupt-file diagnostics. Valid common cases stay
                # inside the bounded native reader.
                return load_libraries({**info,'_reference_reader':True},cancel,progress)
    libraries = []
    total = sum(info['counts'])
    done = 0
    cascade_counts={'interaction':[0,0],'response':[0,0]}
    with ExitStack() as stack:
        snapshots = [_Snapshot(Path(i['path']), stack.enter_context(_open_shared_read(i['path']))) for i in info['streams']]
        _check_identities(snapshots)
        for index, snapshot in enumerate(snapshots):
            if snapshot.header != info['streams'][index]['header']:
                raise StreamError('An input stream changed after setup validation. Check the input files again.')
            library=AnalogLibrary(info['streams'][index]['path'],info['counts'][index],snapshot.header['analog_response'])
            values=library.values
            # Co-60 prefixes carry the complete correlated cascade kinematics.
            prefixes = np.empty((len(values), 15), dtype=np.float64) if info['isotope'] == 'co60' and index == 0 else None
            interactions=np.zeros((len(values),2),dtype=bool) if info['isotope']=='co60' and index==0 else None
            for row, (prefix, ds) in enumerate(snapshot.events()):
                if row >= len(values): raise StreamError('Input count changed after checking.')
                if row % 2048 == 0:
                    cancel(); progress(done / total)
                values[row] = tuple(v for d in ds for v in ((d[1],d[3]) if d[0]&4 else (0.,0.)))
                library.light_origins[row]=[(int(d[0])>>4)&3 for d in ds]
                library.index[row]=snapshot.analog_offset,len(snapshot.analog[0]),len(snapshot.analog[1])
                library.provenance_index[row]=snapshot.provenance_offset,snapshot.provenance_length
                for ch in range(2):
                    if not ds[ch][0]&4: continue
                    q=snapshot.analog[ch][:,1];r=library.responses[ch]
                    if len(q):
                        library.start[row,ch]=q.min()
                        library.span[row,ch]=q.max()-q.min()+tail_span(r['order'],r['tau_ns'])
                    library.peaks[row,ch]=max(-ds[ch][11],ds[ch][12])
                if info['isotope'] == 'co60':
                    if index == 0:
                        prefixes[row] = prefix[2:]
                        interactions[row]=[bool(d[0]&2) or d[2]>0 for d in ds]
                    elif not np.array_equal(first_prefixes[row], prefix[2:]):
                        raise StreamError(f'Co-60 event {row}: cascade kinematics disagree between streams. Do not shuffle unpaired cascade files.')
                    else:
                        for ch in range(2):
                            cascade_counts['interaction'][ch]+=int(first_interactions[row,ch] and (bool(ds[1-ch][0]&2) or ds[1-ch][2]>0))
                            # Response combinations include only energy-eligible pulses.
                            cascade_counts['response'][ch]+=int(first_responses[row,ch] and ds[1-ch][1]>0 and bool(ds[1-ch][0]&4))
                done += 1
            if snapshot.completion['status'] != 'completed' or snapshot.completion['events'] != len(values):
                raise StreamError('Input stream is incomplete or its verified event count changed.')
            if prefixes is not None:first_prefixes=prefixes;first_interactions=interactions;first_responses=library.values[:,[0,2]]>0
            libraries.append(library)
        if info['isotope']=='co60' and info.get('directional_combinations') is not None and info['directional_combinations']!=cascade_counts:
            raise StreamError('Co-60 cascade pair summary does not match the recorded events.')
    progress(1.)
    return libraries


def pair_indices(n1, n2, count, isotope, shuffle, rng):
    limit = n1*n2 if isotope == 'na22' and shuffle else min(n1, n2)
    if count > limit: raise ValueError(f'Requested {count:,} source decays; these streams allow at most {limit:,} with the selected shuffling mode.')
    k = np.arange(count, dtype=np.int64)
    if isotope == 'co60':
        index = rng.permutation(n1)[:count] if shuffle else k
        return index, index.copy()
    if not shuffle: return k, k.copy()
    a, b = rng.permutation(n1), rng.permutation(n2)
    # Each fixed row gets every column exactly once, including unequal pools.
    return a[k % n1], b[(k % n1 + k // n1) % n2]


def source_pulses(resolved, info, libraries, rng, cancel, count):
    p = resolved['profile']; n = count
    a, b = pair_indices(*info['counts'], n, info['isotope'], p['shuffle'], rng)
    times = np.cumsum(rng.exponential(1e9 / p['activity_Bq'], n))
    lifetime = np.zeros(n); component = np.zeros(n, dtype=np.uint16)
    if info['isotope'] == 'na22':
        from .m2_lifetimes import sample_lifetimes
        lifetime, component = sample_lifetimes(p['lifetimes'], n, rng)
    pulses = []
    for role, (indices, library) in enumerate(zip((a,b), libraries)):
        cancel()
        values = library[indices]
        for channel in range(2):
            c = p['channels'][channel]
            valid = values[:, 2*channel] > 0
            records=indices[valid]
            arr = np.zeros(np.count_nonzero(valid), dtype=PULSE_DTYPE)
            arr['origin']=times[valid]+c['cable_delay_ns']+(lifetime[valid] if role==1 else 0)
            arr['time']=arr['origin']+library.start[records,channel]
            arr['span']=library.span[records,channel]
            arr['light_origin']=library.light_origins[records,channel]
            arr['height']=library.peaks[records,channel]*10**(-c['attenuation_dB']/20)
            # Timeline marks event start; peak amplitude is measured from M1.
            arr['peak_time']=arr['time']
            arr['channel'], arr['role'] = channel, role
            arr['decay'] = np.flatnonzero(valid); arr['record'] = indices[valid]
            arr['source_time'], arr['lifetime'], arr['component'] = times[valid], lifetime[valid], component[valid]
            pulses.append(arr)
    resolved['_libraries']=libraries
    merged = np.concatenate(pulses)
    merged.sort(order='time', kind='stable')
    return merged, float(times[-1]), {'first_record_ids': [int(a[0]), int(b[0])], 'source_decays': n}



class SourceBatches:
    """Unique source combinations with bounded event generation and causal watermark.

    The Cartesian product is indexed algebraically; only the two input permutations
    are retained. Future batches cannot contribute before watermark_ns.
    """
    def __init__(self, resolved, info, libraries, rng, cancel, batch_size=4096):
        self.resolved=resolved; self.info=info; self.libraries=libraries
        self.rng=rng; self.cancel=cancel; self.batch_size=batch_size
        self.p=resolved['profile']; self.n1,self.n2=info['counts']
        components=self.p.get('lifetimes',[])
        self.discrete_taus=(np.array([c['tau_ns'] for c in components])
                            if all(c.get('distribution','discrete')=='discrete' for c in components) else None)
        self.capacity=info['max_decays'] if self.p['shuffle'] else min(info['counts'])
        self.generated=0; self.clock=0.; self.watermark_ns=-math.inf
        self.processed=0;self._source_times=deque();self._retired=0
        self.first_record_ids=None
        self.a=rng.permutation(self.n1) if self.p['shuffle'] else np.arange(self.n1)
        self.b=rng.permutation(self.n2) if self.p['shuffle'] else np.arange(self.n2)
        self.minimum_offset=min(float(lib.start[:,ch].min())+self.p['channels'][ch]['cable_delay_ns'] for lib in libraries for ch in range(2))
        self.emitter=None
        if all(isinstance(lib,AnalogLibrary) for lib in libraries):
            from .native_acquisition import binding,SourceEmitter
            fn=getattr(binding(),'tp_source_pulses',None)
            if fn is not None:self.emitter=SourceEmitter(fn,libraries,self.p['channels'])
        resolved['_libraries']=libraries

    def mark_processed(self, horizon):
        while self._source_times and self._source_times[0][-1]<=horizon:
            self._retired+=len(self._source_times.popleft())
        partial=int(np.searchsorted(self._source_times[0],horizon,side='right')) if self._source_times else 0
        self.processed=max(self.processed,self._retired+partial)
        return self.processed/self.capacity

    def __iter__(self):return self

    def prefetched(self):
        # Source and acquisition have separate RNGs. Only consumed batches
        # advance the recorded exposure, even when the pair target is reached.
        producer=copy(self);producer._source_times=deque()
        def generate():
            group=[]
            for _ in range(4):
                if producer.generated==producer.capacity:break
                batch=next(producer)
                group.append((batch,producer._source_times.pop(),producer.generated,
                              producer.watermark_ns,producer.first_record_ids))
            return group
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='M2-source') as executor:
            future=executor.submit(generate) if self.generated<self.capacity else None
            while future is not None:
                group=future.result()
                future=executor.submit(generate) if group[-1][2]<self.capacity else None
                for batch,times,self.generated,self.watermark_ns,self.first_record_ids in group:
                    self.clock=float(times[-1]);self._source_times.append(times)
                    yield batch

    def __next__(self):
        self.cancel()
        n=min(self.batch_size,self.capacity-self.generated)
        if not n:raise StopIteration
        k=np.arange(self.generated,self.generated+n,dtype=np.int64)
        if self.info['isotope']=='co60':a=self.a[k];b=a.copy()
        elif not self.p['shuffle']:a=k;b=k.copy()
        else:a=self.a[k%self.n1];b=self.b[(k%self.n1+k//self.n1)%self.n2]
        if self.first_record_ids is None:self.first_record_ids=[int(a[0]),int(b[0])]
        times=self.clock+np.cumsum(self.rng.exponential(1e9/self.p['activity_Bq'],n))
        self._source_times.append(times)
        lifetime=np.zeros(n);component=np.zeros(n,dtype=np.uint16)
        if self.info['isotope']=='na22':
            from .m2_lifetimes import sample_lifetimes
            lifetime,component=sample_lifetimes(self.p['lifetimes'],n,self.rng,discrete_taus=self.discrete_taus)
        if self.emitter is not None:
            batch=self.emitter.generate(self.generated,a,b,times,lifetime,component)
            self.generated+=n;self.clock=float(times[-1]);self.watermark_ns=self.clock+self.minimum_offset
            return batch
        pieces=[]
        for role,(indices,library) in enumerate(zip((a,b),self.libraries)):
            values=library[indices]
            for ch in range(2):
                valid=values[:,2*ch]>0;records=indices[valid]
                arr=np.zeros(len(records),dtype=PULSE_DTYPE)
                arr['origin']=times[valid]+self.p['channels'][ch]['cable_delay_ns']+(lifetime[valid] if role==1 else 0)
                arr['time']=arr['origin']+library.start[records,ch]
                arr['span']=library.span[records,ch]
                arr['light_origin']=library.light_origins[records,ch]
                arr['height']=library.peaks[records,ch]*10**(-self.p['channels'][ch]['attenuation_dB']/20)
                arr['peak_time']=arr['time'];arr['channel']=ch;arr['role']=role
                arr['decay']=k[valid];arr['record']=records
                arr['source_time']=times[valid];arr['lifetime']=lifetime[valid];arr['component']=component[valid]
                pieces.append(arr)
        self.generated+=n;self.clock=float(times[-1])
        self.watermark_ns=self.clock+self.minimum_offset
        merged=_time_order(np.concatenate(pieces))
        return merged


def _time_order(pulses):
    if len(pulses)<2:return pulses
    order=np.argsort(pulses['time'],kind='stable')
    sorted_pulses=pulses[order]
    # The legacy structured sort uses the other fields as tie breakers.
    if np.any(sorted_pulses['time'][1:]==sorted_pulses['time'][:-1]):
        sorted_pulses.sort(order='time',kind='stable')
    return sorted_pulses


def acquire_batched(source, resolved, rng, cancel, progress):
    # Reuse workers across source chunks. Opening/closing a pool for every few
    # thousand decays serialized otherwise independent waveform calculations.
    workers=resolve_threads(resolved['profile'].get('threads',0),max(1,source.capacity))
    p=resolved['profile'];step=min(p['acquisition']['trigger_step_ns'],1/p['digitization']['rate_GSps']/4)
    from .native_acquisition import binding
    if (workers>1 and not resolved.get('_reference_trigger_scan',False) and p['acquisition']['dead_ns']>=step*2048
            and len(resolved.get('_libraries',[]))==2 and all(isinstance(v,AnalogLibrary) for v in resolved['_libraries']) and binding() is not None):
        from .waveform_workers import WaveformWorkers,process_count
        runtime={**resolved,'_defer_waveforms':True,'_batch_windows':True}
        dispatcher=resolved.get('_waveform_workers')
        if dispatcher is None:dispatcher=WaveformWorkers(resolved,process_count(workers,p['digitization']['samples']),cancel)
        else:dispatcher.attach(source.libraries)
        # Trigger decisions remain chronological; only accepted waveform jobs
        # cross process boundaries. Bound outstanding batches across source chunks.
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='M2-unused-fallback') as pool:
            rows=_acquire_batched(source,runtime,rng,dispatcher.check_running,progress,pool)
            try:
                yield from dispatcher.ordered(rows)
            finally:rows.close();dispatcher.close()
        return
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='M2-analog') as pool:
        yield from _acquire_batched(source,resolved,rng,cancel,progress,pool)


def _acquire_batched(source, resolved, rng, cancel, progress, pool):
    """Carry discriminator, busy time and fixed cell pattern across source batches."""
    state={};pending=np.empty(0,dtype=PULSE_DTYPE)
    p=resolved['profile'];target=None if p['maximum'] else p['waveform_pairs']
    window=resolved['window_ns'];delay=p['acquisition']['trigger_delay_ns']
    d=p['digitization'];filter_tail=0. if not d['input_bandwidth_MHz'] else -math.log(TAIL_FRACTION)*1000/(2*np.pi*d['input_bandwidth_MHz'])
    parallel_source=resolved.get('_batch_windows') and isinstance(source,SourceBatches) and resolve_threads(p.get('threads',0),source.capacity)>=3
    for batch in (source.prefetched() if parallel_source else source):
        cancel()
        if len(pending):
            ordered=isinstance(source,SourceBatches) and (not len(batch) or pending['time'][-1]<batch['time'][0])
            pending=np.concatenate((pending,batch))
            if not ordered:pending=_time_order(pending)
        else:
            pending=batch if isinstance(source,SourceBatches) else _time_order(batch)
        exhausted=source.generated==source.capacity
        # Every future pulse begins beyond watermark. Leave the complete post-
        # trigger window (and a little display context) available to acquisition.
        cutoff=math.inf if exhausted else source.watermark_ns-delay-window*.2
        resolved['_timeline_known_until_ns']=math.inf if exhausted else source.watermark_ns
        for meta,data in acquire(pending,resolved,rng,cancel,lambda _:None,state=state,stop_at=cutoff,pair_limit=target,on_horizon=lambda t:progress(source.mark_processed(t-source.minimum_offset)),pool=pool):
            progress(source.mark_processed(meta['trigger_ns']-source.minimum_offset))
            yield meta,data
            if target is not None and meta['id']+1>=target:return
        progress(source.mark_processed(cutoff-source.minimum_offset))
        # Keep tails and the pretrigger history needed by the next saved sweep.
        cursor=max(state.get('cursor',-math.inf),min(cutoff,state.get('busy_until',-math.inf)-p['acquisition']['coincidence_ns']-2*p['acquisition']['trigger_step_ns']))
        pending=pending[pending['time']+pending['span']+filter_tail>=cursor-window]
    progress(1.)

def event_voltage(times, pulse, resolved):
    ch=int(pulse['channel']);library=resolved['_libraries'][int(pulse['role'])]
    onsets=library.onsets(int(pulse['record']),ch);response=library.responses[ch]
    factor=10**(-resolved['profile']['channels'][ch]['attenuation_dB']/20)
    if resolved['profile']['channels'][ch].get('invert',False):factor=-factor
    relative=np.asarray(times)-pulse['origin']
    bandwidth=resolved['profile']['digitization']['input_bandwidth_MHz']
    tau=1000/(2*np.pi*bandwidth) if bandwidth else 0.
    return factor*evaluate(onsets,response,relative,filter_tau_ns=tau,event=int(pulse['record']))


def analogue(times,pulses,resolved):
    values=np.zeros((2,len(times)))
    for pulse in pulses:
        ch=int(pulse['channel']);voltage=event_voltage(times,pulse,resolved)
        # Noise-free leading edge trigger uses the stored pulse's magnitude.
        sign=-1 if resolved['_libraries'][int(pulse['role'])].responses[ch]['polarity']=='negative' else 1
        if resolved['profile']['channels'][ch].get('invert',False):sign=-sign
        values[ch]+=sign*voltage
    return values


def calibrated_axes(d, architecture, trigger_cell=0):
    n, dt = d['samples'], 1/d['rate_GSps']
    if architecture != 'switched_capacitor' or d.get('cell_widths_ns') is None or not len(d['cell_widths_ns']):
        return np.tile(np.arange(n)*dt, (2,1))
    widths = np.asarray(d['cell_widths_ns'])
    rotate = (np.arange(n)+trigger_cell) % n
    axes = np.column_stack((np.zeros(2), np.cumsum(widths[:, rotate[:-1]], axis=1)))
    physical_zero = (-trigger_cell) % n
    axes[1] += axes[0, physical_zero]-axes[1, physical_zero]
    return axes


def quantize(values, full_range, bits, minimum=None):
    """Signed two's-complement code range; positive top code is one LSB below rail."""
    step = full_range / 2**bits
    if minimum is not None:
        code=np.clip(np.floor((values-minimum)/step+.5),0,2**bits-1)
        return minimum+code*step
    code = np.sign(values) * np.floor(np.abs(values)/step + .5)
    code = np.clip(code, -(2**(bits-1)), 2**(bits-1)-1)
    return code*step


def aperture_errors(d, architecture, cell, rng, fixed_pattern):
    """DLT sampling-coordinate variation; fixed patterns belong to physical cells."""
    fixed = fixed_pattern
    if architecture == 'switched_capacitor':
        fixed = fixed_pattern[:, (np.arange(d['samples'])+cell) % d['samples']]
    return fixed + rng.normal(0, d['aperture_jitter_ns'], fixed.shape)


def digitize(start, pulses, resolved, rng, fixed_pattern):
    p = resolved['profile']; d = p['digitization']; device = resolved['digitizer']
    cell = int(rng.integers(d['samples'])) if device['architecture'] == 'switched_capacitor' else 0
    table = resolved.get('_cell_axes')
    if table is None:
        base_axes = calibrated_axes({**d, 'cell_widths_ns': resolved['cell_intervals_ns']}, device['architecture'], cell)
    else:
        base_axes = table[cell]
    # The archived DLT generator saves the varied sample coordinates and
    # evaluates the waveform at those same coordinates. They are not an extra
    # unobserved timing error. The independent channel IRF below models that.
    for _ in range(32):
        variation = (rng.normal(0, d['aperture_jitter_ns'], base_axes.shape) if fixed_pattern is None
                     else aperture_errors(d, device['architecture'], cell, rng, fixed_pattern))
        axes = base_axes + variation
        if np.all(np.diff(axes.astype('<f4'), axis=1) > 0): break
    else:
        raise ValueError('Digitizer sampling coordinates overlap. Reduce aperture variation or correct the cell intervals.')
    channel_shift = rng.normal(0, d['irf_sigma_ns'], 2)
    from .native_digitizer import binding as adc_binding,sample_channel
    adc=adc_binding() if not resolved.get('_reference_digitizer',False) else None
    if adc is not None:
        result=np.empty((4,d['samples']),dtype='<f4');result[::2]=axes
        clipped=[]
        for ch in range(2):
            background=d['baseline_mV']+rng.normal(0,d['noise_sigma_mV'],d['samples'])
            times=start+axes[ch]-channel_shift[ch]
            clipped.append(sample_channel(adc,times,background,pulses[pulses['channel']==ch],
                                          resolved,ch,result[2*ch+1]))
        return result,cell,[d['baseline_mV']]*2,clipped
    output = np.zeros_like(axes)
    baseline = np.full(2, d['baseline_mV'])
    for ch in range(2):
        c = p['channels'][ch]
        for pulse in pulses[pulses['channel'] == ch]:
            output[ch] += event_voltage(start+axes[ch]-channel_shift[ch],pulse,resolved)
        output[ch] += baseline[ch] + rng.normal(0, d['noise_sigma_mV'], d['samples'])
    clipped = [bool(np.any((v < d['voltage_min_mV']) | (v >= d['voltage_max_mV']))) for v in output]
    output = quantize(output, d['full_range_mV'], device['adc_bits'],d['voltage_min_mV'])
    return np.array([axes[0],output[0],axes[1],output[1]], dtype='<f4'), cell, baseline.tolist(), clipped


def classify(pulses):
    a, b = pulses[pulses['channel']==0], pulses[pulses['channel']==1]
    decays = set(int(p['decay']) for p in pulses)
    flags = {'multiple_decays': len(decays)>1, 'pileup_A': len(a)>1, 'pileup_B': len(b)>1,
             'mixed_primaries': len(set(int(p['role']) for p in pulses))>1}
    if len(a)>1 or len(b)>1:
        label = 'pileup' if len(decays)>1 else 'mixed_same_decay'
    elif not len(a) or not len(b): label = 'single'
    elif len(decays)>1: label = 'accidental'
    elif a[0]['role'] == b[0]['role']: label = 'same_primary_'+str(int(a[0]['role'])+1)
    else: label = 'true_A_start' if a[0]['role']==0 else 'true_B_start'
    return label, flags


def pulse_truth(pulses, start):
    if isinstance(pulses,np.ndarray) and pulses.dtype==PULSE_DTYPE:
        origins=('none','scintillation','cherenkov','mixed')
        return [{'channel':ch,'role':role,'decay':decay,'record':record,'light_origin':origins[light],
                 'onset_ns':t-start,'origin_ns':origin-start,'source_time_ns':source,
                 'lifetime_ns':life,'component':component,'height_mV':height}
                for t,height,ch,role,decay,record,source,life,component,origin,_,_,light in pulses.tolist()]
    return [{'channel':int(q['channel']),'role':int(q['role']),'decay':int(q['decay']),
             'record':int(q['record']),'light_origin':('none','scintillation','cherenkov','mixed')[int(q['light_origin'])],'onset_ns':float(q['time']-start),
             'origin_ns':float(q['origin']-start),
             'source_time_ns':float(q['source_time']),'lifetime_ns':float(q['lifetime']),
             'component':int(q['component']),'height_mV':float(q['height'])} for q in pulses]


def timeline_context(pulses, start, finish, busy_end, known_until=math.inf, *, raw=False,bounds=None):
    """A bounded display snapshot, independent of waveform selection/physics.

    All contributions inside the sweep remain in `pulses`. The surrounding
    timeline can be decimated during very long dead times, with an exact total.
    No random draws: enabling this display must never change the simulation.
    """
    margin = (finish-start)*.2
    low, high = start-margin, busy_end+margin
    observed_until=max(finish,min(high,known_until))
    lo, hi = bounds if bounds is not None else np.searchsorted(pulses['time'], [low,observed_until], side='left')
    count = int(hi-lo)
    if count<=256:
        indices=slice(lo,hi)
    else:
        # The saved window is the useful part of a folded dead-time preview.
        # Never let dense surrounding events displace its contributions.
        a,b=np.searchsorted(pulses['time'],[max(low,start),min(observed_until,finish)],side='left')
        inside=np.arange(a,b)
        if len(inside)>=256:
            indices=inside[np.linspace(0,len(inside)-1,256,dtype=np.int64)]
        else:
            outside=np.concatenate((np.arange(lo,a),np.arange(b,hi)))
            selected=outside[np.linspace(0,len(outside)-1,256-len(inside),dtype=np.int64)]
            indices=np.sort(np.concatenate((inside,selected)))
    return {'low_ns':float(low),'high_ns':float(high),'known_until_ns':float(observed_until),'total':count,
            'pulses':pulses[indices] if raw else pulse_truth(pulses[indices],start)}


def acquire(pulses, resolved, rng, cancel, progress, *, state=None, stop_at=math.inf, pair_limit=None, on_horizon=None, pool=None):
    """Scan only occupied analogue time regions; bounded trigger-grid chunks.

    Trigger uses baseline-free, noise-free pulse magnitude. It is an explicit
    signal trigger model: dark/noise-only triggering is not simulated. Baseline,
    voltage noise, ADC rails and aperture errors belong to recorded samples.
    """
    p = resolved['profile']; acq = p['acquisition']; d = p['digitization']
    window = resolved['window_ns']; channels = p['channels']
    if not len(pulses): progress(1.); return
    step = min(acq['trigger_step_ns'], 1/d['rate_GSps']/4)
    if not resolved.get('_reference_trigger_scan',False) and acq['dead_ns']>=step*2048 and all(isinstance(v,AnalogLibrary) for v in resolved.get('_libraries',[])) and len(resolved.get('_libraries',[]))==2:
        from .native_acquisition import binding,acquire as native_acquire
        if binding() is not None:
            yield from native_acquire(pulses,resolved,rng,cancel,progress,state=state,stop_at=stop_at,pair_limit=pair_limit,on_horizon=on_horizon,pool=pool)
            return
    filter_tail=0. if not d['input_bandwidth_MHz'] else -math.log(TAIL_FRACTION)*1000/(2*np.pi*d['input_bandwidth_MHz'])
    tails=pulses['span']+filter_tail
    end=pulses['time']+tails
    maximum_tail=float(np.max(tails))
    step = min(acq['trigger_step_ns'], 1/d['rate_GSps']/4)
    state={} if state is None else state
    fixed=state.get('fixed')
    # Fixed variation is already in the run's generated physical-cell intervals.
    if fixed is None:fixed=np.zeros((2,d['samples']));state['fixed']=fixed
    threshold = np.array([c['threshold_mV'] for c in channels])
    busy_until=state.get('busy_until',-math.inf)
    last_trigger=state.get('last_trigger',-math.inf)
    last_cross=state.get('last_cross',[-math.inf,-math.inf])
    previous=state.get('previous',np.zeros(2))
    cursor=state.get('cursor',(math.floor(float(pulses[0]['time'])/step)-1)*step)
    serial=state.get('serial',0)
    last_time=min(float(np.max(end)),stop_at)
    workers=resolve_threads(p.get('threads',0),max(1,len(pulses)))
    opposite_times=[pulses['time'][pulses['channel']!=ch] for ch in range(2)]
    def cannot_coincide(times,candidates,base):
        # Conservative exclusion of an isolated single-channel block. No
        # discriminator value in this block can pair with an opposite crossing:
        # none is active, none occurred recently, none can arrive soon. Protect
        # the batch boundary, where future source pulses are not yet available.
        if acq['trigger']!='coincidence' or base is not None or not len(candidates) or resolved.get('_reference_trigger_scan',False):return False
        ch=int(candidates['channel'][0])
        if np.any(candidates['channel']!=ch):return False
        margin=acq['coincidence_ns']+2*step
        if times[0]-last_cross[1-ch]<=margin or times[-1]+margin>=stop_at:return False
        future=opposite_times[ch];index=int(np.searchsorted(future,times[0],side='left'))
        return index==len(future) or future[index]>times[-1]+margin
    def blocks():
        position=cursor; lo=0; hi=0
        while position<last_time:
            cancel()
            while lo<len(pulses) and end[lo]<position:lo+=1
            if lo>=len(pulses):break
            jump=position < busy_until-acq['coincidence_ns']-2*step
            if jump:
                position=min(last_time,math.floor((busy_until-acq['coincidence_ns']-2*step)/step)*step)
                if position>=last_time:break
                while lo<len(pulses) and end[lo]<position:lo+=1
                if lo>=len(pulses):break
            reset=pulses[lo]['time']>position+step
            if reset:position=(math.floor(float(pulses[lo]['time'])/step)-1)*step
            stop=min(position+step*2048,last_time+step)
            hi=max(hi,int(np.searchsorted(pulses['time'],stop,side='right')))
            first=math.floor(position/step+.25)+1
            last=math.floor(stop/step+.1)
            times=np.arange(first,last+1,dtype=np.int64)*step
            if not len(times):break
            yield times,pulses[lo:hi],reset,position if jump and not reset else None
            position=float(times[-1])
    def scan(pool):
        queue=deque(); iterator=iter(blocks())
        def push():
            block=next(iterator,None)
            if block is None:return False
            times,candidates,reset,base=block
            sampled_times=np.r_[base,times] if base is not None else times
            queue.append((times,reset,base,pool.submit(analogue,sampled_times,candidates,resolved)));return True
        # Long readout dead time invalidates speculative trigger-grid work.
        # Let the chronological consumer advance busy_until before requesting
        # the next block. Waveform sampling still uses the shared worker pool.
        lookahead = 1 if acq['dead_ns'] >= step*2048 else max(1,workers*2)
        if lookahead==1:
            # No independent work exists between submit() and result() here.
            # The native evaluation releases the GIL; digitization still runs
            # concurrently in the persistent pool. Keep the exact block grid.
            for times,candidates,reset,base in iterator:
                sampled_times=np.r_[base,times] if base is not None else times
                yield times,reset,base,((sampled_times,candidates) if cannot_coincide(times,candidates,base) else analogue(sampled_times,candidates,resolved))
            return
        for _ in range(lookahead):
            if not push():break
        while queue:
            cancel();times,reset,base,result=queue.popleft()
            values=result.result();yield times,reset,base,values
            push()
    def sampled(meta,start,chosen,seed):
        data,cell,baseline,clipped=digitize(start,chosen,resolved,np.random.default_rng(seed),fixed)
        return {**meta,'trigger_cell':cell,'baseline_mV':baseline,'clipped':clipped},data
    owns_pool=pool is None
    if owns_pool:pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='M2-analog')
    waiting=deque()
    deferred_previous=None
    try:
      for times,reset,base,values in scan(pool):
        if isinstance(values,tuple):
            # Preserve the exact preceding grid for a later non-reset boundary.
            # Most isolated regions reset before the next opposite pulse, so
            # their unused voltages never need to be calculated.
            deferred_previous=values;cursor=float(times[-1])
            if on_horizon:on_horizon(cursor)
            progress(min(1.,cursor/last_time))
            continue
        if deferred_previous is not None:
            if not reset and base is None:previous=analogue(*deferred_previous,resolved)[:,-1]
            deferred_previous=None
        if base is not None:
            previous=values[:,0];values=values[:,1:];last_cross=[-math.inf,-math.inf]
        elif reset:previous[:]=0
        before = np.column_stack((previous, values[:,:-1]))
        crosses = (before < threshold[:,None]) & (values >= threshold[:,None])
        for point in np.flatnonzero(np.any(crosses,axis=0)):
            fired = np.flatnonzero(crosses[:,point])
            crossing_times = [(int(ch),float(times[point]-step+step*(threshold[ch]-before[ch,point])/(values[ch,point]-before[ch,point]))) for ch in fired]
            for ch, at in sorted(crossing_times,key=lambda item:item[1]):
                last_cross[ch] = at
                selected = (acq['trigger']=='either' or acq['trigger']=='AB'[ch]
                            or acq['trigger']=='coincidence' and abs(at-last_cross[1-ch])<=acq['coincidence_ns'])
                # One logical OR edge when both discriminators cross together,
                # including the ideal zero-delay / zero-readout-time limit.
                if not selected or at < busy_until or at <= last_trigger: continue
                last_trigger = at
                finish = at+acq['trigger_delay_ns']
                start = finish-window
                # Include tails from earlier pulses and later photons inside the sweep.
                high = int(np.searchsorted(pulses['time'],finish,side='left'))
                low = int(np.searchsorted(pulses['time'],start-maximum_tail,side='left'))
                chosen = pulses[low:high]
                chosen = chosen[(chosen['time']+chosen['span']+filter_tail)>start]
                seed=int(rng.integers(0,2**63-1))
                label, flags = classify(chosen)
                truth = pulse_truth(chosen,start)
                busy_until = finish + acq['dead_ns']
                meta={'id':serial,'start_ns':start,'trigger_ns':at,
                       'end_ns':finish,'busy_until_ns':busy_until,'trigger_channel':ch,
                       'accepted_crossings_ns':list(last_cross) if acq['trigger']=='coincidence' else [at if i==ch else None for i in range(2)],
                       'coincidence_window_ns':[min(last_cross),min(last_cross)+acq['coincidence_ns']] if acq['trigger']=='coincidence' else None,
                       'acquisition_rate_Hz':(serial+1)*1e9/max(busy_until,1e-9),
                       'timeline':timeline_context(pulses,start,finish,busy_until,resolved.get('_timeline_known_until_ns',math.inf)),
                       'class':label,'flags':flags,'pulses':truth}
                waiting.append(pool.submit(sampled,meta,start,chosen,seed))
                if len(waiting)>=workers*2:
                    cancel();yield waiting.popleft().result()
                serial += 1
                if pair_limit is not None and serial>=pair_limit:
                    while waiting:
                        cancel();yield waiting.popleft().result()
                    return
        previous = values[:,-1]
        cursor = float(times[-1])
        if on_horizon:on_horizon(cursor)
        progress(min(1.,cursor/last_time))
      while waiting:
        cancel();yield waiting.popleft().result()
    finally:
      for task in waiting:task.cancel()
      if owns_pool:pool.shutdown(wait=True,cancel_futures=True)
      if deferred_previous is not None:previous=analogue(*deferred_previous,resolved)[:,-1]
      state.update(fixed=fixed,busy_until=busy_until,last_trigger=last_trigger,last_cross=last_cross,previous=previous,cursor=cursor,serial=serial)
    progress(1.)
