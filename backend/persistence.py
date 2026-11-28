# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Charge-normalized analog persistence; bounded RAM, no preview subsampling."""
import math
from collections import OrderedDict
import tempfile
import threading
import weakref
import numpy as np
from .analog_pmt import spe_weights, evaluate, tail_span, kernel, native_library

class PulseCloud:
    def __init__(self):
        self.cache=OrderedDict();self.compute_lock=threading.Lock();self.rows=[];self.events={};self.lock=threading.RLock()
        self.directory=tempfile.TemporaryDirectory(prefix='twinpals-persistence-')
        path=self.directory.name+'/photoelectrons.bin'
        self.file=open(path,'wb',buffering=1024*1024)
        self.reader=open(path,'rb',buffering=1024*1024)
        self.finalizer=weakref.finalize(self,self._cleanup,self.file,self.reader,self.directory)
        self.read_lock=threading.Lock()
        self.bounds=None;self.origin_index={};self.axis_bounds=None
    def append(self,onsets,event_id=None,arrivals=None,origins=None):
        if not len(onsets):return
        a=np.asarray(onsets,dtype='<f8')
        raw=None if arrivals is None else np.asarray(arrivals,dtype='<f8')
        if raw is not None and (raw.shape!=a.shape or not np.isfinite(raw).all()):
            raise ValueError('Cathode arrivals must match the stored photoelectrons')
        with self.lock:
            offset=self.file.tell();self.file.write(a.tobytes())
            arrival_offset=None
            if raw is not None:
                arrival_offset=self.file.tell();self.file.write(raw.tobytes())
            code=int(np.bitwise_or.reduce(np.asarray(origins,dtype="u1")[:,0],initial=0)) if origins is not None else 1
            self.rows.append((offset,len(a),float(a.min()),float(a.max()),arrival_offset,code,event_id if event_id is not None else 0))
            lo,hi=self.rows[-1][2:4]
            self.bounds=(lo,hi) if self.bounds is None else (min(lo,self.bounds[0]),max(hi,self.bounds[1]))
            # Only the first 20 nonempty pulses choose the display range. Later
            # optical outliers must not invalidate every accumulated density.
            if len(self.rows)<=20:
                self.axis_bounds=(lo,hi) if self.axis_bounds is None else (min(lo,self.axis_bounds[0]),max(hi,self.axis_bounds[1]))
            if event_id is not None:
                self.events[event_id]=self.rows[-1]
                if origins is not None:
                    self.origin_index[event_id]=(self.file.tell(),len(a))
                    self.file.write(np.asarray(origins,dtype="u1").tobytes())
    def event(self,event_id):
        with self.lock:
            row=self.events.get(event_id)
            self.file.flush()
            return self.read(row) if row is not None else np.empty(0)

    def append_batch(self,ids,counts,onsets,arrivals,tags):
        """Publish a channel's consecutive pulses in one write per column."""
        if not len(ids):return
        offsets=np.cumsum(counts)-counts
        lows=np.minimum.reduceat(onsets,offsets).tolist()
        highs=np.maximum.reduceat(onsets,offsets).tolist()
        origins=np.bitwise_or.reduceat(tags[:,0],offsets).tolist()
        with self.lock:
            base=self.file.tell()
            self.file.write(np.ascontiguousarray(onsets,'<f8'))
            arrivals_at=self.file.tell()
            self.file.write(np.ascontiguousarray(arrivals,'<f8'))
            tags_at=self.file.tell()
            self.file.write(np.ascontiguousarray(tags,'u1'))
            first=len(self.rows)
            for event,n,k,lo,hi,origin in zip(ids.tolist(),counts.tolist(),offsets.tolist(),lows,highs,origins):
                row=(base+8*k,n,lo,hi,arrivals_at+8*k,origin,event)
                self.rows.append(row)
                self.events[event]=row
                self.origin_index[event]=(tags_at+2*k,n)
            lo,hi=min(lows),max(highs)
            self.bounds=(lo,hi) if self.bounds is None else (min(lo,self.bounds[0]),max(hi,self.bounds[1]))
            if first<20:
                lo,hi=min(lows[:20-first]),max(highs[:20-first])
                self.axis_bounds=(lo,hi) if self.axis_bounds is None else (min(lo,self.axis_bounds[0]),max(hi,self.axis_bounds[1]))
    def event_arrivals(self,event_id):
        with self.lock:
            row=self.events.get(event_id)
            if row is None:return np.empty(0)
            if row[4] is None:raise ValueError('Cathode arrival times are unavailable for this event')
            self.file.flush()
            return self.read((row[4],row[1]))
    def event_origins(self,event_id):
        with self.lock:
            row=self.origin_index.get(event_id)
            if row is None:return np.empty((0,2),dtype="u1")
            self.file.flush()
            with self.read_lock:
                self.reader.seek(row[0]);return np.frombuffer(self.reader.read(row[1]*2),dtype="u1").reshape(-1,2).copy()
    def close(self):
        with self.lock,self.read_lock:
            self.finalizer()
    @staticmethod
    def _cleanup(writer,reader,directory):
        try:writer.close()
        finally:
            try:reader.close()
            finally:directory.cleanup()
    def snapshot(self,start=0,stop=None):
        with self.lock:
            self.file.flush()
            return self.rows[start:stop]
    def read(self,row):
        with self.read_lock:
            self.reader.seek(row[0]);return np.frombuffer(self.reader.read(row[1]*8),dtype='<f8').copy()

ORIGINS = ("all", "scintillation", "cherenkov", "mixed")


def axes(groups, bins):
    limits = [(cloud.axis_bounds[0], cloud.axis_bounds[1] + tail_span(r['order'], r['tau_ns']))
              for cloud, r in groups if cloud.axis_bounds is not None]
    start = min((x[0] for x in limits), default=0.)
    end = max((x[1] for x in limits), default=1.)
    padding = max(1., (end-start)*.15)
    low = 8*math.floor((start-padding)/8)
    high = max(low+8, 8*math.ceil((end+padding)/8))
    ymax = max(float(kernel(np.array([(r['order']-1)*r['tau_ns']]), r['order'], r['tau_ns'])[0])
               for _, r in groups)*1.001
    edges = np.linspace(low, high, bins+1)
    return low, high, ymax, (edges[:-1]+edges[1:])/2


def accumulate(cloud, response, bins, axis, stop, cancel, batched):
    low, high, ymax, centers = axis
    key = (bins, low, high, ymax, response['order'], response['tau_ns'], response['charge_C'],
           response.get('charge_cutoff'), response.get('charge_scale'), response.get('charge_seed'))
    with cloud.compute_lock:
        if key not in cloud.cache:
            cloud.cache[key] = [np.zeros((3,bins,bins),dtype=np.int64), 0, np.zeros(3,dtype=np.int64)]
            while len(cloud.cache)>4:
                cloud.cache.popitem(last=False)
        cloud.cache.move_to_end(key)
        cached = cloud.cache[key]
        grids, seen, totals = cached
        law = tuple(response[k] for k in ('charge_cutoff','charge_scale','charge_seed')) if response.get('charge_scale') else ()
        function = 'tp_persistence_spe_batch_shape' if law else 'tp_persistence_batch_shape'
        native = getattr(native_library(), function, None) if batched else None
        try:
            while seen < stop:
                if cancel.is_set():
                    raise ValueError('Persistence cancelled')
                rows = cloud.snapshot(seen, min(seen+128, stop))
                if native:
                    # Limit each read independently of the event count. A single
                    # large pulse is evaluated whole, as on the single-view path.
                    offset = rows[0][0]
                    for i, row in enumerate(rows[1:], 1):
                        if row[0]+8*row[1]-offset > 2**20:
                            rows = rows[:i]
                            break
                    length = rows[-1][0]+8*rows[-1][1]-offset
                    with cloud.read_lock:
                        cloud.reader.seek(offset)
                        raw = cloud.reader.read(length)
                    descriptors = np.array([(row[0]-offset, row[1], max(0,row[5]-1), row[6]) for row in rows], dtype=np.uint64)
                    if not law:
                        descriptors = np.ascontiguousarray(descriptors[:,:3])
                    if native(raw, len(raw), descriptors, len(rows), centers, bins, response['order'],
                              response['tau_ns'], response['charge_C'], ymax, grids, *law):
                        raise ValueError('Could not evaluate pulse density batch')
                    totals += np.bincount(descriptors[:,2].astype(int), minlength=3)
                else:
                    for row in rows:
                        onsets=cloud.read(row)
                        weights=spe_weights(onsets,response,row[6])
                        norm=row[1] if weights is None else weights.sum()
                        v = np.abs(evaluate(onsets, response, centers, current=True,event=row[6],weights=weights))/(norm*response['charge_C']*1e12)
                        occupied = v > ymax*1e-12
                        yi = np.minimum(bins-1, np.floor(v[occupied]/ymax*bins).astype(int))
                        index = max(0,row[5]-1)
                        grids[index,yi,np.flatnonzero(occupied)] += 1
                        totals[index] += 1
                seen += len(rows)
                cached[1] = seen
        except BaseException:
            # A native or scalar batch may have made partial increments.
            del cloud.cache[key]
            raise
        return grids.copy(), totals.copy()


def view(detector, primary, origin, axis, grids, totals):
    if origin == 'all':
        counts, count = grids.sum(axis=0), totals.sum()
    else:
        index = ORIGINS.index(origin)-1
        counts, count = grids[index], totals[index]
    low, high, ymax, centers = axis
    return dict(detector=detector, primary=primary, origin=origin, bins=len(centers), count=int(count),
                counts=counts.tolist(), x_range=[low, high], y_range=[0, ymax])


def histogram(buffers, detector, primary, bins, cancel, origin="all"):
    if origin not in ORIGINS:
        raise ValueError("Choose all, scintillation, Cherenkov or mixed pulses.")
    if detector not in ('A','B') or type(bins) is not int or not 10<=bins<=1000:
        raise ValueError('Choose A/B and 10–1000 bins.')
    if not any(primary in ('all',b.header['role']) for b in buffers):
        raise ValueError('Choose a loaded primary type.')
    ch = 'AB'.index(detector)
    groups = [(b.pulses[ch], b.header['analog_response'][ch]) for b in buffers]
    axis = axes(groups, bins)
    parts = [accumulate(cloud, response, bins, axis, len(cloud.rows), cancel, False)
             for b,(cloud,response) in zip(buffers, groups) if primary in ('all',b.header['role'])]
    grids, totals = map(sum, zip(*parts))
    return view(detector, primary, origin, axis, grids, totals)


def histogram_bank(buffers, detector, bins, cancel):
    ch = 'AB'.index(detector)
    groups = [(b.pulses[ch], b.header['analog_response'][ch]) for b in buffers]
    axis = axes(groups, bins)
    stops = [len(cloud.rows) for cloud, _ in groups]
    parts = []
    views = []
    for b, (cloud,response), stop in zip(buffers, groups, stops):
        grids, totals = accumulate(cloud, response, bins, axis, stop, cancel, True)
        parts.append((grids, totals))
        views.extend(view(detector, b.header['role'], origin, axis, grids, totals) for origin in ORIGINS)
    grids, totals = map(sum, zip(*parts))
    return [view(detector, 'all', origin, axis, grids, totals) for origin in ORIGINS] + views
