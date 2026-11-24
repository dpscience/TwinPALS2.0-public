# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Incremental event ingestion and vectorized, memory-only histogram queries.

Live and imported data are read from committed stream frames in background
threads. Immutable packed chunks make queries independent of ingestion.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import zlib
import struct
from .storage_health import exhausted,space_message,StorageSpaceError

import numpy as np
from .histograms import histogram

from .streams import (FRAME, MAX_FRAME, METRICS, ROLES, StreamError, _header, frame_crc32,
                      _json, _open_shared_read, _check_identities, _pose, _check_cancel, analog_payload, EVENT_BYTES, minimum_energy)

DETECTOR_DTYPE = np.dtype([('flags','<u4'),('hits','<u8'),('energy','<f8'),
    ('mean','<f8'),('position','<f8',(3,)),('time','<f8'),('length','<f8'),
    ('reflections','<u8'),('reentries','<u4'),('minimum_mV','<f8'),('maximum_mV','<f8')])
EVENT_DTYPE = np.dtype([('id','<u8'),('mask','<u4'),('source','<f8',(3,)),
    ('directions','<f8',(3,3)),('emission','<f8',(3,)),('detectors',DETECTOR_DTYPE,(2,))])
assert EVENT_DTYPE.itemsize == EVENT_BYTES


def checked_events(payload, role, start, minimum_energy_keV=0):
    if not payload or len(payload) % EVENT_BYTES:
        raise StreamError('Invalid event batch size')
    rows = np.frombuffer(payload, dtype=EVENT_DTYPE)
    if not np.array_equal(rows['id'], np.arange(start, start+len(rows), dtype=np.uint64)):
        raise StreamError('Event IDs must be contiguous')
    mask = {'na22_prompt':1,'na22_annihilation':6,'co60_1173':3,'co60_1332':3}[role]
    if np.any(rows['mask'] != mask): raise StreamError('Invalid primary mask')
    for field in ('source','directions','emission'):
        if not np.isfinite(rows[field]).all(): raise StreamError('Nonfinite event values')
    for slot in range(3):
        norm = np.sum(rows['directions'][:,slot,:]**2, axis=1)
        if mask & (1 << slot):
            if np.any(np.abs(norm-1)>1e-7) or np.any(rows['emission'][:,slot]<0):
                raise StreamError('Invalid primary direction/time')
        elif np.any(norm) or np.any(rows['emission'][:,slot]):
            raise StreamError('Inactive primary slot must be zero')
    if mask == 6 and (np.any(np.abs(rows['directions'][:,1]+rows['directions'][:,2])>1e-7)
                      or np.any(rows['emission'][:,1] != rows['emission'][:,2])):
        raise StreamError('Invalid annihilation pair')
    d = rows['detectors']; flags = d['flags']; hits = d['hits'] > 0
    for field in ('energy','mean','position','time','length','minimum_mV','maximum_mV'):
        if not np.isfinite(d[field]).all(): raise StreamError('Nonfinite detector values')
    if (np.any(flags & np.uint32(0xffffff00)) or np.any(((flags & 1)>0) != hits) or np.any(((flags & 48)>0) != hits)
            or np.any(((flags & 4)>0) != (d['energy']>=minimum_energy_keV))
            or np.any(d['energy']<0) or np.any(d['mean'] < -1e-9)
            or np.any(d['time'] < -1e-9) or np.any(d['length']<0)
            or np.any(d['mean'][~hits]) or np.any(d['length'][~hits])
            or np.any(d['minimum_mV']>0) or np.any(d['maximum_mV']<0)
            or np.any(d['minimum_mV'][~hits]) or np.any(d['maximum_mV'][~hits])
            or np.any(d['position'][(flags & 2)==0]) or np.any(d['time'][(flags & 2)==0])):
        raise StreamError('Invalid detector summary')
    return rows


class EventBuffer:
    def __init__(self, header, path):
        self.header = header
        self.minimum_energy = minimum_energy(header)
        self.path = str(path)
        self.chunks = []
        self._block = None
        self._block_used = 0
        self.count = 0
        self.loaded_bytes = 0
        self.total_bytes = 0
        self.status = 'incomplete'
        self.verified = False
        self.loading = False
        self.error = None
        self.revision = 0
        self.lock = threading.RLock()
        self.previews = []
        from .persistence import PulseCloud
        self.pulses=[PulseCloud(),PulseCloud()]
        from .cathode_map import HitCloud, aperture
        self.hits=[HitCloud(aperture(header,d)) for d in range(2)]
        self.outcome_counts = np.zeros(3, dtype=np.int64)
        self.pulse_counts=np.zeros((2,4),dtype=np.int64)
        self.birth_counts=[{},{}]
        self.pending_births=[{},{}]
        self.birth_events=[{},{}]
        self.pending_birth_events=[{},{}]
        self.maxima=np.zeros(2)
        self.eligible_maxima=np.zeros(2)
        self.eligible_response_counts=np.zeros(2,dtype=np.int64)
        self.joint_counts=np.zeros((2,4),dtype=np.int64)

    def add_origins(self,analog,detector):
        if not len(analog):return
        components,counts=np.unique(analog[analog[:,4]==2,5].astype(int),return_counts=True)
        for c,n in zip(components,counts):
            c=int(c)
            self.pending_births[detector][c]=self.pending_births[detector].get(c,0)+int(n)
            self.pending_birth_events[detector][c]=self.pending_birth_events[detector].get(c,0)+1

    def prepare_preview(self,preview,event,analog,tree,row):
        from .provenance import preview_summary
        if (preview.get('role')!=self.header['role'] or preview.get('event_id')!=event
                or not isinstance(preview.get('analog_onsets_ns'),list) or len(preview['analog_onsets_ns'])!=2
                or any(not np.array_equal(preview['analog_onsets_ns'][i],analog[i][:,1]) for i in range(2))):
            raise StreamError('Pulse preview disagrees with the stored photoelectrons')
        preview['ancestry']=preview_summary(tree,self.header['light_components'],self.header['role'])
        preview['cathode_arrivals_ns']=[a[:,0].tolist() for a in analog]
        preview['light_origins']=[a[:,4:6].astype(int).tolist() for a in analog]
        preview['pulse_origins']=[int(np.bitwise_or.reduce(a[:,4].astype('u1'),initial=0)) for a in analog]
        preview['energy_accepted']=[bool(d['flags']&4) for d in row['detectors']]
        return preview

    def append(self, payload, hits=None):
        with self.lock:
            rows = checked_events(payload, self.header['role'], self.count, self.minimum_energy)
            if hits is None:raise StreamError('Event batch is missing photocathode positions')
            counts=rows['detectors']['hits'].sum(axis=0)
            for d in range(2):
                if len(hits[d])!=counts[d]:raise StreamError('Hit-map count differs from accepted-photoelectron count')
                self.hits[d].validate(hits[d])
                forbidden='maximum_mV' if self.header['analog_response'][d]['polarity']=='negative' else 'minimum_mV'
                if np.any(rows['detectors'][forbidden][:,d]):raise StreamError('Anode extrema disagree with pulse polarity')
            for d in range(2):
                accepted=(rows['detectors']['flags'][:,d]&4)!=0
                if accepted.all():
                    self.hits[d].append(hits[d])
                else:
                    mask=np.repeat(accepted,rows['detectors']['hits'][:,d].astype(np.int64))
                    self.hits[d].append(hits[d][mask])
            # Per generated event, across both crystals. Never histogram cuts.
            d = rows['detectors']
            for i in range(2):
                self.pulse_counts[i]+=np.bincount(((d['flags'][:,i]>>4)&3).astype(int),minlength=4)
                for c,n in self.pending_births[i].items():self.birth_counts[i][c]=self.birth_counts[i].get(c,0)+n
                self.pending_births[i].clear()
                for c,n in self.pending_birth_events[i].items():self.birth_events[i][c]=self.birth_events[i].get(c,0)+n
                self.pending_birth_events[i].clear()
            self.eligible_response_counts+=np.count_nonzero((d['flags']&5)==5,axis=0)
            interaction = ((d['flags'] & 2) != 0) | (d['energy'] > 0)
            for level,mask in enumerate((interaction,d['hits']>0)):
                self.joint_counts[level]+=np.bincount(mask[:,0].astype(int)+2*mask[:,1].astype(int),minlength=4)
            entered = (d['flags'] & 8) != 0
            hit = interaction.any(axis=1)
            entry = entered.any(axis=1)
            self.outcome_counts += [np.count_nonzero(hit),
                np.count_nonzero(~hit & entry), np.count_nonzero(~hit & ~entry)]
            # Immutable snapshot views into append-only 8192-event blocks.
            # Tiny native/import batches must not become thousands of NumPy
            # histogram calls on every refresh. Never rewrite a published row.
            offset=0
            while offset<len(rows):
                if self._block is None or self._block_used==8192:
                    self._block=np.empty(8192,dtype=EVENT_DTYPE);self._block_used=0
                    self.chunks.append(self._block[:0])
                take=min(8192-self._block_used,len(rows)-offset)
                self._block[self._block_used:self._block_used+take]=rows[offset:offset+take]
                self._block_used+=take;offset+=take
                self.chunks[-1]=self._block[:self._block_used]
            self.maxima=np.maximum(self.maxima,np.maximum(-rows['detectors']['minimum_mV'],rows['detectors']['maximum_mV']).max(axis=0))
            self.eligible_maxima=np.maximum(self.eligible_maxima,np.where((rows['detectors']['flags']&4)!=0,np.maximum(-rows['detectors']['minimum_mV'],rows['detectors']['maximum_mV']),0).max(axis=0))
            self.count += len(rows)
            self.revision += 1

    def snapshot(self):
        with self.lock:
            if self.error: raise StreamError(self.error)
            return SimpleNamespace(header=self.header, path=self.path, chunks=tuple(self.chunks),
                count=self.count, loaded_bytes=self.loaded_bytes, total_bytes=self.total_bytes,
                status=self.status, verified=self.verified, loading=self.loading, revision=self.revision,
                outcomes=self.outcomes())

    def outcomes(self):
        with self.lock:
            from .light_origin import NAMES
            components=self.header.get('light_components',[])
            pulse={ch:dict(total=self.count,**{name:dict(count=int(n),percent=100*int(n)/self.count if self.count else 0.) for name,n in zip(NAMES,self.pulse_counts[i])},births=[dict(**components[c],photons=n,events=self.birth_events[i].get(c,0),percent=100*self.birth_events[i].get(c,0)/self.count if self.count else 0.) for c,n in sorted(self.birth_counts[i].items()) if c<len(components)]) for i,ch in enumerate('AB')}
            joint={level:{name:dict(count=int(n),percent=100*int(n)/self.count if self.count else 0.) for name,n in zip(('neither','A','B','both'),self.joint_counts[i])} for i,level in enumerate(('crystal','anode'))}
            return dict(total=self.count,pulses=pulse,joint=joint, **{
                outcome: dict(count=int(count), percent=100*int(count)/self.count if self.count else 0.)
                for outcome, count in zip(('interaction', 'transmission', 'miss'), self.outcome_counts)})


class AnalysisStore:
    def __init__(self):
        self.buffers = OrderedDict()
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.import_cancel = threading.Event()
        self.threads = []
        self.query_lock = threading.Lock()
        self.persistence_lock = threading.Lock()
        self.persistence_cache = None
        self.density_requests = OrderedDict()
        self.density_results = {}
        self.density_errors = {}
        self.density_active = set()
        self.density_condition = threading.Condition()
        self.density_thread = None
        self.density_bank_result = None
        self.density_bins = 120
        self.density_version = 0
        self.cached_key = None
        self.cached_result = None
        from .histogram_index import HistogramIndex
        self.histogram_index=HistogramIndex()
        self.histogram_thread=None
        self.followers={}
        self.storage_error=None

    def follow(self, role):
        """Tail the durable native stream, never the worker's stdout pipe.

        The started protocol message follows the flushed native headers. The
        open handle permits the final Windows rename while a reader catches up.
        """
        b=self.buffers[role]
        with _open_shared_read(Path(b.path)) as file:
            header,start=_header(file,os.fstat(file.fileno()).st_size)
        if header['role']!=role or minimum_energy(header)!=b.minimum_energy:
            raise StreamError('Native stream header changed its identity or energy threshold')
        with b.lock:
            b.header=header;b.loaded_bytes=start;b.loading=True
        done=threading.Event()
        thread=threading.Thread(target=self._load,args=(b,done),daemon=True,name='TwinPALS-live-reader')
        self.followers[role]=(done,thread)
        self.threads.append(thread);thread.start()

    def drain(self, roles):
        """Writer has exited: consume the committed tail, including cancellation.

        No simulation/manager lock is held while waiting for analysis. Errors
        are raised only after every reader has stopped, also on native failure.
        """
        for role in roles:
            if role in self.followers:self.followers[role][0].set()
        for role in roles:
            if role in self.followers:self.followers[role][1].join()
        errors=[self.buffers[r].error for r in roles if self.buffers[r].error]
        if errors:raise StreamError('\n'.join(errors))

    def register(self, header, path):
        with self.lock:
            role = header['role']
            if role in self.buffers: raise StreamError('Duplicate primary stream')
            self.buffers[role] = EventBuffer(header, path)
            _check_identities([SimpleNamespace(header=b.header) for b in self.buffers.values()])
            if self.histogram_thread is None:
                self.histogram_thread=threading.Thread(target=self._histogram_worker,name='m1-histograms',daemon=True)
                self.histogram_thread.start()

    def _density_worker(self):
        # The browser requests a bank every 750 ms. Coalesce faster ingestion
        # instead of spending the entire reader budget serializing unseen banks.
        while not self.cancel.wait(.35):
            if self.storage_error:return
            with self.density_condition:
                if not self.density_requests:
                    self.density_condition.wait(timeout=.5)
                    continue
                key, request = self.density_requests.popitem(last=False)
                self.density_active.add(key)
            target = request.pop('_target')
            try:
                bins=request['bins']
                roles,revision,densities,maps=self._build_density_bank(bins)
                result=next(v for v in densities if (v['detector'],v['primary'])==key[:2] and v['origin']=='all')
                with self.density_condition:
                    for item in densities:
                        if item['origin']=='all':self.density_results[(item['detector'],item['primary'],bins)]=item
                    self.density_version+=1
                    # A conservative source-record watermark captured before the
                    # bank is built. New arrivals can only increase coverage.
                    self.density_bank_result=dict(version=self.density_version,bins=bins,revision=revision,
                        processed_events=dict(zip(roles,revision)),persistence=densities,maps=maps)
                    self.density_results[key] = result
                    self.density_errors.pop(key, None)
                    while len(self.density_results)>12:self.density_results.pop(next(iter(self.density_results)))
            except Exception as exc:
                if self.cancel.is_set():return
                if exhausted(exc):self.storage_error=space_message()
                with self.density_condition:
                    self.density_errors[key] = (target, str(exc))
                    while len(self.density_errors)>12:self.density_errors.pop(next(iter(self.density_errors)))
            finally:
                with self.density_condition:self.density_active.discard(key)

    def _build_density_bank(self, bins):
        from .persistence import histogram_bank
        with self.persistence_lock:
            with self.lock:
                buffers = list(self.buffers.values())
            roles = [b.header['role'] for b in buffers]
            revision = tuple(b.count for b in buffers)
            densities, maps = [], []
            for detector in ('A','B'):
                densities.extend(histogram_bank(buffers, detector, bins, self.cancel))
                maps.extend(self._cathode_views(buffers, detector, bins, include_components=True))
            return roles, revision, densities, maps

    def persistence_preview(self, request):
        if self.storage_error:raise StorageSpaceError(self.storage_error)
        key=(request.get('detector','A'),request.get('primary','all'),request.get('bins',120))
        if key[0] not in ('A','B') or type(key[2]) is not int or not 10<=key[2]<=1000:
            raise StreamError('Choose A/B and 10–1000 bins.')
        with self.lock:
            buffers=[b for b in self.buffers.values() if key[1] in ('all',b.header['role'])]
            if not buffers:raise StreamError('Choose a loaded primary type.')
            target=sum(len(b.pulses['AB'.index(key[0])].rows) for b in buffers)
        with self.density_condition:
            failure = self.density_errors.get(key)
            if failure and failure[0] == target:
                raise StreamError('Pulse persistence could not be calculated: ' + failure[1])
            result=self.density_results.get(key)
            pending=result is None or result['count']<target
            if pending and key not in self.density_active:
                self.density_requests[key]=dict(detector=key[0],primary=key[1],bins=key[2],_target=target)
                while len(self.density_requests)>12:self.density_requests.popitem(last=False)
                if self.density_thread is None:
                    self.density_thread=threading.Thread(target=self._density_worker,daemon=True,name='M1-density')
                    self.density_thread.start()
                self.density_condition.notify()
            origin=request.get('origin','all')
            if origin not in ('all','scintillation','cherenkov','mixed'):raise StreamError('Choose a valid anode origin.')
            if origin!='all':
                bank=self.density_bank_result
                result=next((v for v in (bank or {}).get('persistence',[]) if (v['detector'],v['primary'],v['bins'],v['origin'])==(*key,origin)),None)
            return dict(data=result,loading=pending or result is None)

    def _prewarm_density(self):
        if self.storage_error:return
        with self.lock:
            if not self.buffers:return
            target=sum(len(b.pulses[0].rows) for b in self.buffers.values())
        key=('A','all',self.density_bins)
        with self.density_condition:
            if self.density_errors.get(key,(None,))[0]==target:return
            # Coalesce incoming batches into one pending refresh.
            self.density_requests[key]=dict(detector='A',primary='all',bins=self.density_bins,_target=target)
            if self.density_thread is None:
                self.density_thread=threading.Thread(target=self._density_worker,daemon=True,name='M1-density')
                self.density_thread.start()
            self.density_condition.notify()

    def density_bank(self, request):
        if self.storage_error:raise StorageSpaceError(self.storage_error)
        bins=request.get('bins',120)
        if type(bins) is not int or not 10<=bins<=1000:raise StreamError('Choose 10–1000 bins.')
        with self.density_condition:
            self.density_bins=bins
            result=self.density_bank_result
            ready=result is not None and result['bins']==bins
            failure=self.density_errors.get(('A','all',bins))
        if not ready:self._prewarm_density()
        if failure:raise StreamError('Density views could not be calculated: '+failure[1])
        return dict(data=result if ready and result['version']!=request.get('since') else None,
                    loading=not ready,version=result['version'] if ready else 0)

    def feed(self, message):
        role = message['role']
        if message['type'] == 'analysis_header':
            with self.buffers[role].lock:
                if minimum_energy(message['header'])!=self.buffers[role].minimum_energy:
                    raise StreamError('Live stream changed its energy threshold')
                self.buffers[role].header = message['header']
                self.buffers[role].revision += 1
            return
        if len(message['data']) > 2*1024*1024: raise StreamError('Live batch is too large')
        payload = base64.b64decode(message['data'], validate=True)
        if len(payload) != message['count']*EVENT_BYTES: raise StreamError('Live batch count mismatch')
        buffer = self.buffers[role]
        with buffer.lock:
            if message['first'] != buffer.count: raise StreamError('Missing live event batch')
            points=[]
            for field in ('hit_a','hit_b'):
                if len(message.get(field,''))>48*1024*1024:raise StreamError('Live hit batch is too large')
                points.append(np.frombuffer(base64.b64decode(message.get(field,''),validate=True),dtype='<f4').reshape(-1,2))
            raw=base64.b64decode(message['analog'],validate=True);offset=0
            rows=checked_events(payload,role,message['first'],buffer.minimum_energy)
            for event in range(message['first'],message['first']+message['count']):
                _,a,b=struct.unpack_from('<QII',raw,offset);size=16+(a+b)*34
                analog=analog_payload(raw[offset:offset+size],event)
                for d in range(2):
                    from .light_origin import validate
                    validate(analog[d],rows['detectors']['flags'][event-message['first'],d],buffer.header)
                    buffer.add_origins(analog[d],d)
                    if rows['detectors']['flags'][event-message['first'],d]&4:
                        buffer.pulses[d].append(analog[d][:,1],event,analog[d][:,0],analog[d][:,4:6])
                offset+=size
            if offset!=len(raw):raise StreamError('Invalid live analog batch')
            buffer.append(payload,points)
        # Precompute without holding ingestion locks or waiting for a tab click.
        self._prewarm_density()

    def finish(self, role, status, expected, path=None):
        b = self.buffers[role]
        with b.lock:
            if b.count != expected: raise StreamError('Live data count differs from written stream')
            b.status = status
            if path is not None: b.path = str(path)
            b.revision += 1

    def open_files(self, paths, workers=0):
        from .execution import import_workers
        budget=import_workers(workers)
        for path in paths:
            path = Path(path)
            with _open_shared_read(path) as file:
                size = os.fstat(file.fileno()).st_size
                header, start = _header(file, size)
            self.register(header, path)
            b=self.buffers[header['role']]
            b.loaded_bytes=start; b.total_bytes=size
        lanes=min(budget,max(1,len(self.buffers)))
        gate=threading.Semaphore(lanes)
        def read(buffer,worker_count):
            if buffer.path.endswith('.part'):
                self._load(buffer,read_slot=gate)
            else:
                with gate:self._load(buffer,workers=worker_count)
        for i,buffer in enumerate(self.buffers.values()):
            buffer.loading = True
            worker_count=budget//lanes+int(i%lanes<budget%lanes)
            thread = threading.Thread(target=read, args=(buffer,worker_count), daemon=True, name='TwinPALS-import')
            self.threads.append(thread); thread.start()

    def progress(self):
        """Small progress snapshot; never copy event chunks or run histograms."""
        streams=[]
        with self.lock:
            for b in self.buffers.values():
                with b.lock:
                    streams.append(dict(path=b.path,role=b.header['role'],completed=b.count,
                        expected_events=b.header.get('events',0),loaded_bytes=b.loaded_bytes,
                        total_bytes=b.total_bytes,loading=b.loading,status='failed' if b.error else b.status,
                        verified=b.verified,error=b.error,outcomes=b.outcomes(),preview_count=len(b.previews)))
        return dict(streams=streams,loading=any(s['loading'] for s in streams),
                    total_events=sum(s['completed'] for s in streams),
                    loaded_bytes=sum(s['loaded_bytes'] for s in streams),
                    total_bytes=sum(s['total_bytes'] for s in streams),
                    error='\n'.join(s['error'] for s in streams if s['error']) or None)

    def _load(self, b, writer_done=None,workers=None,read_slot=None):
        slot_held=False
        try:
            if workers is not None and b.total_bytes>=8*1024*1024 and not self.import_cancel.is_set():
                from .m1_import import import_completed
                if import_completed(self,b,workers):return
            with _open_shared_read(b.path) as file:
                header, start = _header(file, os.fstat(file.fileno()).st_size)
                if header != b.header: raise StreamError('Stream changed before import')
                if b.count:start=b.loaded_bytes
                file.seek(start); buffer = bytearray(); pending = bytearray(); footer = None
                consumed = start; analog = None;provenance = False;hit_chunks=[[],[]];last_analog=None;last_tree=None
                def commit():
                    if pending:
                        hits=[np.concatenate(v) if v else np.empty((0,2),dtype='<f4') for v in hit_chunks]
                        b.append(bytes(pending),hits);pending.clear();hit_chunks[0].clear();hit_chunks[1].clear()
                        self._prewarm_density()
                while not self.import_cancel.is_set():
                    if read_slot is not None and not slot_held:
                        read_slot.acquire()
                        slot_held=True
                    if self.storage_error:raise StorageSpaceError(self.storage_error)
                    size = os.fstat(file.fileno()).st_size
                    if size < consumed+len(buffer): raise StreamError('Stream truncated during import')
                    block = file.read(2*1024*1024)
                    if block:
                        with b.lock: b.loading=True
                    buffer.extend(block)
                    offset = 0
                    while len(buffer)-offset >= FRAME.size:
                        _check_cancel(self.import_cancel)
                        tag,n,crc = FRAME.unpack_from(buffer, offset)
                        if n > MAX_FRAME: raise StreamError('Frame exceeds format limit')
                        if len(buffer)-offset < FRAME.size+n: break
                        if footer is not None: raise StreamError('Bytes after stream footer')
                        payload = bytes(buffer[offset+12:offset+12+n])
                        if frame_crc32(payload) != crc: raise StreamError('Stream frame CRC mismatch')
                        offset += FRAME.size+n
                        if tag == b'APLS':
                            if analog is not None: raise StreamError('Unpaired analog frame')
                            analog=analog_payload(payload,b.count+len(pending)//EVENT_BYTES)
                        elif tag == b'PROV':
                            from .provenance import decode
                            if analog is None or provenance: raise StreamError('Unpaired transport ancestry')
                            last_tree=decode(payload,b.count+len(pending)//EVENT_BYTES,[len(a) for a in analog],len(b.header['light_components']))
                            provenance=True
                        elif tag == b'EVNT':
                            if n != EVENT_BYTES: raise StreamError('Invalid event record size')
                            if analog is None: raise StreamError('Event has no analog response')
                            if not provenance: raise StreamError('Event has no transport ancestry')
                            # Validate summaries together at commit, as on the
                            # original native analysis-batch path. Per-record
                            # NumPy validation otherwise dominates sparse runs.
                            rows=np.frombuffer(payload,dtype=EVENT_DTYPE)
                            for i in range(2):
                                d=rows['detectors'][0,i]
                                if len(analog[i])!=d['hits'] or (len(analog[i]) and not math.isclose(float(analog[i][:,0].mean()),d['mean'],rel_tol=1e-10,abs_tol=1e-9)): raise StreamError('Photoelectron count/mean mismatch')
                                from .light_origin import validate
                                validate(analog[i],d['flags'],b.header)
                                if len(analog[i]):
                                    hit_chunks[i].append(analog[i][:,2:4].astype('<f4'))
                                    b.add_origins(analog[i],i)
                                    if d['flags']&4:b.pulses[i].append(analog[i][:,1],b.count+len(pending)//EVENT_BYTES,analog[i][:,0],analog[i][:,4:6])
                            last_analog=analog
                            analog=None;provenance=False
                            pending.extend(payload)
                            if len(pending) >= 4096*EVENT_BYTES:
                                commit()
                        elif tag == b'TRAK':
                            preview=_json(payload)
                            if last_tree is None or last_analog is None: raise StreamError('Preview has no preceding event ancestry')
                            b.prepare_preview(preview,b.count+len(pending)//EVENT_BYTES-1,last_analog,last_tree,rows[0])
                            with b.lock:
                                if len(b.previews)<30000: b.previews.append(preview)
                        elif tag == b'DONE':
                            if analog is not None: raise StreamError('Unpaired analog pulse at completion')
                            footer = _json(payload)
                            commit()
                            if (footer.get('status') not in ('completed','cancelled')
                                    or type(footer.get('events')) is not int or footer['events'] != b.count):
                                raise StreamError('Footer count/status mismatch')
                            if 'pulse_origin_counts' in footer and not np.array_equal(footer['pulse_origin_counts'],b.pulse_counts):
                                raise StreamError('Pulse-origin counts disagree with event records')
                            if 'eligible_response_counts' in footer and not np.array_equal(footer['eligible_response_counts'],b.eligible_response_counts):
                                raise StreamError('Eligible pulse counts disagree with event records')
                            if 'observed_maximum_mV' in footer:
                                maximum=np.asarray(footer['observed_maximum_mV'])
                                if maximum.shape!=(2,) or not np.allclose(maximum,b.maxima,rtol=1e-10,atol=1e-12):raise StreamError('Anode maxima disagree with event records')
                            if 'eligible_maximum_mV' in footer:
                                maximum=np.asarray(footer['eligible_maximum_mV'])
                                if maximum.shape!=(2,) or not np.allclose(maximum,b.eligible_maxima,rtol=1e-10,atol=1e-12):raise StreamError('Eligible anode maxima disagree with event records')
                        else: raise StreamError('Unknown stream frame')
                    consumed += offset; del buffer[:offset]
                    commit()
                    with b.lock:
                        b.loaded_bytes=consumed; b.total_bytes=size; b.revision+=1
                    if block: continue
                    if footer is not None:
                        if buffer: raise StreamError('Incomplete bytes after footer')
                        if Path(b.path).suffix != '.part' and footer['status'] != 'completed':
                            raise StreamError('Cancelled stream must retain .part extension')
                        with b.lock: b.status=footer['status']; b.verified=True; b.loading=False; b.revision+=1
                        break
                    if Path(b.path).suffix != '.part': raise StreamError('Completed stream has no valid footer')
                    with b.lock: b.loading=False
                    # A growing file can wait indefinitely at EOF. Its unused
                    # CPU slot is available to the other selected stream.
                    if slot_held:
                        read_slot.release()
                        slot_held=False
                    # A killed/cancelled native worker may leave a partial last
                    # frame. Only EVNT-committed records enter the statistics.
                    if writer_done is not None and writer_done.is_set():break
                    if self.import_cancel.wait(.25): break
        except Exception as exc:
            if exhausted(exc):self.storage_error=space_message()
            if not self.import_cancel.is_set():
                with b.lock: b.error=str(exc); b.loading=False; b.revision+=1
        finally:
            if slot_held:read_slot.release()
            if self.import_cancel.is_set() and 'commit' in locals():
                # Publish complete records from the last block before stopping;
                # their pulse clouds were already appended with those records.
                commit()
            with b.lock:
                b.loading=False
                if self.import_cancel.is_set() and b.status=='incomplete':
                    b.status='stopped'; b.revision+=1

    def stop_import(self):
        """Stop file readers, retaining already committed events for analysis."""
        self.import_cancel.set()
        for thread in self.threads: thread.join()
        return self.progress()

    def close(self):
        self.cancel.set()
        self.stop_import()
        with self.density_condition:self.density_condition.notify_all()
        if self.density_thread:self.density_thread.join(timeout=10)
        if self.histogram_thread:self.histogram_thread.join(timeout=10)
        with self.persistence_lock:
            errors=[]
            for b in self.buffers.values():
                for h in [*b.hits,*b.pulses]:
                    try:h.close()
                    except OSError as exc:errors.append(exc)
            for exc in errors:
                if not exhausted(exc):raise exc

    def persistence(self, request):
        from .persistence import histogram
        detector=request.get('detector','A');primary=request.get('primary','all');bins=request.get('bins',120)
        with self.persistence_lock:
            buffers=list(self.buffers.values())
            origin=request.get("origin","all")
            key=(detector,primary,bins,origin,tuple(b.count for b in buffers))
            if self.persistence_cache is not None and self.persistence_cache[0]==key:return self.persistence_cache[1]
            result=histogram(buffers,detector,primary,bins,self.cancel,origin)
            self.persistence_cache=(key,result)
            return result

    def hit_map(self, request):
        detector=request.get('detector','A')
        if detector not in ('A','B'):raise StreamError('Choose detector A or B for the photocathode map.')
        bins=request.get('bins',120);primary=request.get('primary','all')
        selected=[b for role,b in self.buffers.items() if primary in ('all',role)]
        if not selected:raise StreamError('Choose an available primary stream.')
        return self._cathode_views(selected, detector, bins, primary=primary)[0]

    def _cathode_views(self, selected, detector, bins, primary='all', include_components=False):
        d = 'AB'.index(detector)
        geometry = selected[0].hits[d].geometry
        views, roles = [], []
        total, events = None, 0
        for b in selected:
            if b.hits[d].geometry != geometry:
                raise StreamError('Cathode shapes differ between these streams.')
            event_count = b.count
            grid, count = b.hits[d].histogram(bins, self.cancel)
            role = dict(role=b.header['role'], count=count)
            roles.append(role)
            total = grid if total is None else total+grid
            events += event_count
            if include_components:
                views.append(dict(detector=detector, bins=bins, primary=role['role'], geometry=geometry,
                                  counts=grid.tolist(), count=count, events=event_count, roles=[role]))
        combined = dict(detector=detector, bins=bins, primary=primary, geometry=geometry, counts=total.tolist(),
                        count=sum(r['count'] for r in roles), events=events, roles=roles)
        return [combined, *views]

    def _histogram_worker(self):
        while not self.cancel.wait(.35):
            try:
                with self.query_lock:
                    with self.lock:snapshots=[b.snapshot() for b in self.buffers.values()]
                    self.histogram_index.prepare(snapshots,self.cancel)
            except StreamError:
                if self.cancel.is_set():return
                # Query/import surfaces the underlying stream error.

    def query(self, request, cancel=None):
        metrics=request.get('metrics') or [request.get('metric','energy')]
        if not isinstance(metrics,list) or not 1<=len(metrics)<=9 or any(m not in METRICS for m in metrics):
            raise StreamError('Select one to nine valid quantities')
        with self.query_lock:
            with self.lock:snapshots=[b.snapshot() for b in self.buffers.values()]
            if not snapshots:raise StreamError('No stream data available')
            key=(tuple((s.path,s.revision) for s in snapshots),json.dumps(request,sort_keys=True))
            if self.cached_key==key:return self.cached_result
            self.histogram_index.prepare(snapshots,cancel)
            result=[histogram(snapshots,{**request,'metric':metric},cancel,index=self.histogram_index) for metric in metrics]
            self.cached_key=key;self.cached_result=result
            return result


def selected_rows(rows, category, detector=None):
    if category == 'all': return rows
    if category in ('interaction','transmission','miss'):
        d=rows['detectors'][:,detector]
        interaction=((d['flags']&2)!=0)|(d['energy']>0)
        entered=(d['flags']&8)!=0
        return rows[{'interaction':interaction,'transmission':entered&~interaction,'miss':~entered&~interaction}[category]]
    a,b=((rows['detectors']['hits']>0)&((rows['detectors']['flags']&4)!=0)).T
    masks={'none':~a&~b,'A':a&~b,'B':~a&b,'both':a&b}
    return rows[masks[category]]


def values(rows, metric, detector, role, pose, origin="all", basis=None):
    from .analysis_basis import selected
    rows=rows[selected(rows["detectors"]["flags"][:,detector],origin,basis)]
    d=rows['detectors'][:,detector]
    if metric == 'pulse_height': return np.maximum(-d['minimum_mV'],d['maximum_mV']),0
    if metric in ('energy','photon_count','reflections'):
        return d[{'energy':'energy','photon_count':'hits','reflections':'reflections'}[metric]], 0
    if metric in ('mean_arrival','track_length','depth'):
        valid=(d['flags'] & (2 if metric=='depth' else 1)) != 0
        selected=d[valid]
        if metric=='depth': result=np.sum((selected['position']-pose[0])*pose[1],axis=1)
        else: result=selected['mean' if metric=='mean_arrival' else 'length']
        return result, int(len(d)-np.count_nonzero(valid))
    slots=[1,2] if role=='na22_annihilation' else [1] if role=='co60_1332' else [0]
    directions=rows['directions'][:,slots,:].reshape(-1,3)
    if metric=='polar_angle': return np.degrees(np.arccos(np.clip(np.sum(directions*pose[1],axis=1),-1,1))),0
    return np.degrees(np.arctan2(directions[:,1],directions[:,0])),0


def histogram_reference(snapshots, request, cancel=None):
    metric=request.get('metric','energy'); detector=request.get('detector','all')
    primary=request.get('primary','all'); category=request.get('category','all'); bins=request.get('bins',120)
    suppressed=request.get('suppress_zero',[])
    if not isinstance(suppressed,list) or any(m not in METRICS for m in suppressed):
        raise StreamError('Hide zeros is available for deposited energy, photocathode counts and mean arrival time')
    suppress=metric in suppressed
    if detector not in ('all','A','B') or category not in ('all','none','A','B','both','interaction','transmission','miss'):
        raise StreamError('Invalid detector/category')
    if type(bins) is not int or not 1<=bins<=4096: raise StreamError('Bins must be from 1 to 4096')
    chosen=request.get('range')
    if chosen is not None and (not isinstance(chosen,(list,tuple)) or len(chosen)!=2
            or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in chosen) or chosen[1]<=chosen[0]):
        raise StreamError('Invalid histogram range')
    active=[s for s in snapshots if primary=='all' or s.header['role']==primary]
    if not active: raise StreamError('Selected primary does not exist')
    indices=(0,1) if detector=='all' else (0,) if detector=='A' else (1,)
    series={}; bounds=[math.inf,-math.inf]; positions=[]
    for s in active:
        role=s.header['role']
        for i in indices:
            key=role+':'+'AB'[i]
            row=dict(key=key,label=f'{ROLES[role]} · Detector {"AB"[i]}',detector='AB'[i],primary=role,
                     edges=[],counts=[],events=0,valid=0,missing=0,underflow=0,overflow=0)
            pose=_pose(s.header,i) if metric in ('depth','polar_angle') else None
            for chunk in s.chunks:
                _check_cancel(cancel); selected=selected_rows(chunk,category,i)
                v,missing=values(selected,metric,i,role,pose,request.get("origin","all"))
                if suppress:
                    row['suppressed_zero']=row.get('suppressed_zero',0)+int(np.count_nonzero(v==0))
                    v=v[v!=0]
                from .light_origin import selected as origin_selected
                keep=((selected['detectors']['flags'][:,i]&4)!=0)&origin_selected(selected['detectors']['flags'][:,i],request.get('origin','all'))
                excluded=int(np.count_nonzero(~keep))
                row['events']+=len(selected); row['valid']+=len(v); row['missing']+=missing+excluded
                if len(v): bounds=[min(bounds[0],float(v.min())),max(bounds[1],float(v.max()))]
                if metric=='depth' and len(positions)<5000:
                    valid=selected[keep & ((selected['detectors'][:,i]['flags'] & 6)==6)][:5000-len(positions)]
                    xyz=valid['detectors'][:,i]['position']
                    depths=np.sum((xyz-pose[0])*pose[1],axis=1)
                    positions.extend(dict(detector='AB'[i],primary=role,event_id=int(r['id']),x=float(p[0]),y=float(p[1]),z=float(p[2]),depth=float(depth)) for r,p,depth in zip(valid,xyz,depths))
            series[key]=row
    low,high=chosen or bounds
    if not math.isfinite(low): low,high=0.,1.
    elif low==high:
        half=.5 if metric in ('photon_count','reflections') else max(abs(low)*.01,.0005)
        low,high=low-half,high+half
    edges=np.array([float(low+(high-low)*i/bins) for i in range(bins+1)])
    for s in active:
        role=s.header['role']
        for i in indices:
            row=series[role+':'+'AB'[i]]; counts=np.zeros(bins,dtype=np.int64)
            pose=_pose(s.header,i) if metric in ('depth','polar_angle') else None
            for chunk in s.chunks:
                _check_cancel(cancel); v,_=values(selected_rows(chunk,category,i),metric,i,role,pose,request.get("origin","all"))
                if suppress: v=v[v!=0]
                # Arithmetic used to construct the final edge may round one ULP
                # below high. Classify against the requested bounds first, then
                # clamp the right-inclusive maximum into the last bin, matching
                # the independent stream reader without losing endpoint events.
                inside=v[(v>=low)&(v<=high)]
                indices_in_bins=np.clip(np.searchsorted(edges,inside,side='right')-1,0,bins-1)
                counts+=np.bincount(indices_in_bins,minlength=bins)
                row['underflow']+=int(np.count_nonzero(v<low)); row['overflow']+=int(np.count_nonzero(v>high))
            row['edges']=edges.tolist(); row['counts']=counts.tolist()
    markers=[]
    if metric=='energy':
        energies=sorted({{'na22_prompt':1274.537,'na22_annihilation':511.,'co60_1173':1173.228,'co60_1332':1332.492}[s.header['role']] for s in active})
        for energy in energies: markers.extend([{'x':energy,'label':f'γ {energy:g} keV'}, {'x':energy*(1-1/(1+2*energy/510.99895)),'label':f'Compton edge ({energy:g} keV)'}])
    return dict(metric=metric,unit=METRICS[metric],series=list(series.values()),
        streams=[dict(path=s.path,header=s.header,completion=dict(status=s.status,events=s.count,verified=s.verified),snapshot_bytes=s.loaded_bytes,outcomes=s.outcomes) for s in snapshots],
        profile=active[0].header.get('profile'),total_events=sum(s.count for s in active),
        complete=all(s.status=='completed' for s in snapshots),warnings=[],markers=markers,positions=positions,
        loading=any(s.loading for s in snapshots),loaded_bytes=sum(s.loaded_bytes for s in snapshots),total_bytes=sum(s.total_bytes for s in snapshots))
