# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded online persistence of acquired waveform pairs (not preview samples)."""
import numpy as np
import ctypes
from .analog_pmt import native_library


class AcquiredPersistence:
    def __init__(self, profile, bins=120):
        d = profile['digitization']
        self.window = d['samples'] / d['rate_GSps']
        self.bins = bins
        self.x = (np.arange(bins) + .5) * self.window / bins
        self.grids = np.zeros((2, bins, bins), dtype=np.uint64)
        self.count = [0, 0]
        self.skipped = [0, 0]
        self.ymax = [1/64, 1/64]
        self.ranges = [[0., self.window], [0., self.window]]
        self.warmup = [[], []]
        self.warmup_supports = [[], []]
        self.range_frozen = [False, False]
        library=native_library()
        self._native=(ctypes.PYFUNCTYPE(ctypes.c_double,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_double)(('tp_acquired_density',library))
                      if bins%2==0 and library is not None and hasattr(library,'tp_acquired_density') else None)
        self._batch=getattr(library,'tp_acquired_density_batch',None)
        if self._batch is not None:
            ptr=ctypes.c_void_p
            self._batch.argtypes=[ptr,ptr,ctypes.c_int,ptr,ctypes.c_int,ptr];self._batch.restype=ctypes.c_int

    def prepared_batch(self,rows,features):
        if self._native is None or self._batch is None or not all(self.range_frozen):return False
        expected=[(*r,self.bins) for r in self.ranges]
        for _,data,_,_ in rows:
            if data.monitor_density[0]!=expected:return False
        n=len(rows);valid=np.zeros((n,2),dtype=np.uint8)
        values=np.empty((n,2,self.bins),dtype=float)
        for i,(_,data,_,_) in enumerate(rows):
            for _,_,ch in data.transport_keys:valid[i,ch]=1
            for ch,samples in enumerate(data.monitor_density[1]):
                if samples is not None:values[i,ch]=samples
                else:valid[i,ch]=0
        areas=features[:,2:4];valid&=np.isfinite(areas)&(areas>0)
        maxima=np.array(self.ymax)
        if self._batch(values.ctypes.data,valid.ctypes.data,n,self.grids.ctypes.data,self.bins,maxima.ctypes.data):
            raise ValueError('Invalid acquired-persistence coordinates.')
        self.ymax=maxima.tolist()
        for ch,total in enumerate(valid.sum(axis=0).tolist()):
            self.count[ch]+=total;self.skipped[ch]+=n-total
        return True

    def prepared_sweeps(self,batch):
        expected=[(*r,self.bins) for r in self.ranges]
        batched=self._native is not None and self._batch is not None and batch.ranges==expected
        if batched:
            channels=batch.rows['channels']
            batched=all(frozen or not np.any(channels & (1<<ch)) for ch,frozen in enumerate(self.range_frozen))
        if not batched:
            for i in range(len(batch.rows)):
                meta,data=batch.record(i)
                self.append(meta,data,None,batch.features[i,2:4])
            return
        valid=np.column_stack((channels&1,(channels>>1)&1)).astype(np.uint8)
        areas=batch.features[:,2:4]
        valid&=np.isfinite(areas)&(areas>0)
        maxima=np.array(self.ymax)
        if self._batch(batch.densities.ctypes.data,valid.ctypes.data,len(valid),self.grids.ctypes.data,
                       self.bins,maxima.ctypes.data):
            raise ValueError('Invalid acquired-persistence coordinates.')
        self.ymax=maxima.tolist()
        for ch,n in enumerate(valid.sum(axis=0).tolist()):
            self.count[ch]+=n;self.skipped[ch]+=len(valid)-n

    def append(self, meta, data, magnitudes, areas):
        keys=getattr(data,'transport_keys',None)
        channels = ({p['channel'] for p in meta.get('pulses', []) if abs(p.get('height_mV', 0)) > 0}
                    if keys is None else {ch for role,record,ch in keys})
        for ch in range(2):
            area = areas[ch]
            if ch not in channels or not np.isfinite(area) or area <= 0:
                self.skipped[ch] += 1
                continue
            prepared=getattr(data,'monitor_density',None)
            if prepared is not None and self.range_frozen[ch]:
                ranges,densities=prepared
                # Worker used this record's actual stored trigger/start doubles.
                if ranges[ch] is not None and ranges[ch]==(*self.ranges[ch],self.bins) and densities[ch] is not None:
                    self.count[ch]+=1;self._accumulate_values(ch,densities[ch]);continue
            t = data[ch * 2].astype(float) - (meta.get('trigger_ns', meta.get('start_ns', 0.)) - meta.get('start_ns', 0.))
            magnitude=magnitudes[ch] if magnitudes is not None else np.abs(data[ch*2+1].astype(float)-meta['baseline_mV'][ch])
            values = magnitude / area
            self.count[ch] += 1
            if not self.range_frozen[ch]:
                self.warmup[ch].append((t.copy(), values.copy()))
                # Choose the connected pulse at the accepted channel crossing.
                # A larger, later pile-up must not set the trigger-pulse focus.
                # Only these first 20 traces perform the range-learning work.
                threshold=max(float(np.max(values))*.02,6*float(np.median(values)))
                significant=np.flatnonzero(values>=threshold)
                crossing=(meta.get('accepted_crossings_ns') or [None,None])[ch]
                centre=(crossing-meta.get('trigger_ns',0.)) if crossing is not None else 0.
                if len(significant):
                    nearest=int(significant[np.argmin(np.abs(t[significant]-centre))])
                    lo_index=hi_index=nearest
                    while lo_index>0 and values[lo_index-1]>=threshold:lo_index-=1
                    while hi_index+1<len(values) and values[hi_index+1]>=threshold:hi_index+=1
                    self.warmup_supports[ch].extend([float(t[lo_index]),float(t[hi_index])])
                supports=self.warmup_supports[ch]
                lo, hi = min([0., *supports]), max([0., *supports])
                padding = max(5., (hi-lo)*.3)
                self.ranges[ch] = [lo-padding, hi+padding]
                self.grids[ch].fill(0)
                for tx, vy in self.warmup[ch]:
                    self._accumulate(ch, tx, vy)
                if len(self.warmup[ch]) == 20:
                    self.range_frozen[ch] = True
                    self.warmup[ch].clear()
                    self.warmup_supports[ch].clear()
            else:
                self._accumulate(ch, t, values)

    def _accumulate(self, ch, t, values):
            lo, hi = self.ranges[ch]
            x = lo + (np.arange(self.bins)+.5)*(hi-lo)/self.bins
            y = np.interp(x, t, values, left=np.nan, right=np.nan)
            self._accumulate_values(ch,y)

    def _accumulate_values(self,ch,y):
            if self._native is not None:
                maximum=self._native(y.ctypes.data,self.grids[ch].ctypes.data,self.bins,self.ymax[ch])
                if maximum<=0:raise ValueError('Invalid acquired-persistence coordinates.')
                self.ymax[ch]=maximum
                return
            valid = np.isfinite(y) & (y > 0)
            peak = float(np.max(y[valid])) if np.any(valid) else 0.
            # Doubling coarsens existing bins exactly; storage never grows with events.
            while peak >= self.ymax[ch]:
                grid = self.grids[ch]
                half=self.bins//2
                last=grid[-1].copy() if self.bins%2 else None
                grid[:half] = grid[:2*half].reshape(half, 2, self.bins).sum(axis=1)
                grid[half:] = 0
                if last is not None:grid[half]=last
                self.ymax[ch] *= 2
            xs = np.flatnonzero(valid)
            ys = (y[valid] * self.bins / self.ymax[ch]).astype(int)
            self.grids[ch, ys, xs] += 1

    def snapshot(self):
        return [dict(detector='AB'[ch], primary='all', bins=self.bins,
                     count=self.count[ch], skipped=self.skipped[ch],
                     counts=self.grids[ch].tolist(), x_range=self.ranges[ch],
                     alignment='common_trigger', range_frozen=self.range_frozen[ch],
                     y_range=[0., self.ymax[ch]]) for ch in range(2)]
