# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exact incremental hit histograms; bounded RAM, no repeated transport-stream scan."""
import tempfile
import threading
import numpy as np


def aperture(header, detector):
    setting=header['profile']['detectors'][detector]
    pmt=next(e for e in header['pmt_snapshot'] if e['id']==setting['pmt_id'])
    p=pmt['properties'];shape=p['photocathode_shape']
    w=p['photocathode_width_mm'] if shape=='rect' else p['photocathode_diameter_mm']
    h=p['photocathode_height_mm'] if shape=='rect' else w
    return dict(shape=shape,width_mm=w,height_mm=h)


class HitCloud:
    """Float32 local XY, append-only. Spill large clouds to a private temp file.

    Each unchanged bin setting visits only newly committed chunks. Rebinning is
    exact for the stored coordinates; no interpolation of a coarse master grid.
    """
    def __init__(self, geometry, memory_limit=64*1024*1024):
        self.geometry=geometry;self.memory_limit=memory_limit
        self.chunks=[];self.bytes=0;self.count=0;self.file=None
        self.lock=threading.RLock();self.query_lock=threading.Lock()
        self.cache=None;self.seen=0;self.bins=None

    def validate(self, points):
        a=np.asarray(points,dtype='<f4').reshape(-1,2)
        w,h=self.geometry['width_mm'],self.geometry['height_mm'];eps=max(w,h)*2e-6
        if not np.isfinite(a).all() or np.any(np.abs(a)>np.array([w/2+eps,h/2+eps])):
            raise ValueError('Photocathode hit lies outside the recorded active surface.')
        if self.geometry['shape']=='circle' and np.any(np.sum(a.astype(float)**2,axis=1)>(w/2+eps)**2):
            raise ValueError('Photocathode hit lies outside the circular active surface.')
        return a

    def append(self, points):
        a=np.ascontiguousarray(self.validate(points))
        if not len(a):return
        with self.lock:
            if self.file is None and self.bytes+a.nbytes>self.memory_limit:
                self.file=tempfile.TemporaryFile(prefix='twinpals-hits-')
                old=self.chunks;self.chunks=[]
                for previous in old:
                    offset=self.file.tell();self.file.write(previous.tobytes());self.chunks.append((offset,len(previous)))
            if self.file is None:self.chunks.append(a.copy())
            else:
                self.file.seek(0,2);offset=self.file.tell();self.file.write(a.tobytes());self.chunks.append((offset,len(a)))
            self.bytes+=a.nbytes;self.count+=len(a)

    def histogram(self, bins, cancel=None):
        if type(bins) is not int or not 10<=bins<=1000:raise ValueError('Choose 10 to 1000 bins per cathode axis.')
        with self.query_lock:
            if self.bins!=bins:self.cache=np.zeros((bins,bins),dtype=np.uint64);self.bins=bins;self.seen=0
            with self.lock:stop=len(self.chunks);count=self.count
            w,h=self.geometry['width_mm'],self.geometry['height_mm']
            while self.seen<stop:
                if cancel and cancel.is_set():raise ValueError('Hit-map query cancelled.')
                with self.lock:
                    chunk=self.chunks[self.seen]
                    if isinstance(chunk,tuple):
                        self.file.seek(chunk[0]);points=np.frombuffer(self.file.read(chunk[1]*8),dtype='<f4').reshape(-1,2)
                    else:points=chunk
                # x is column, y is row. Inclusive positive edge goes to the last bin.
                indices=np.floor((points.astype(float)/[w,h]+.5)*bins).astype(np.int64)
                np.clip(indices,0,bins-1,out=indices)
                self.cache+=np.bincount(indices[:,1]*bins+indices[:,0],minlength=bins*bins).reshape(bins,bins).astype(np.uint64)
                self.seen+=1
            return self.cache.copy(),count

    def close(self):
        with self.query_lock,self.lock:
            if self.file:self.file.close();self.file=None
            self.chunks.clear()
