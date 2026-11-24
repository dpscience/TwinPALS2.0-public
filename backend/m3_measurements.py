# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Compact ordered lifetime measurements and live pulse statistics."""
from collections import deque
import math
import numpy as np
from .m3_blocks import REASONS, FEATURES, RESULT

# Only the seek address and processing revision are needed to reopen a waveform.
POSITION=np.dtype([('file','<u4'),('revision','<u4'),('offset','<u8')])
TIMING=np.dtype([('dt','<f8'),('d','u1'),('c','u1'),('o','u1'),('s','u1')])
SCATTERS={'all':0,'none':-1,'any':1,'shield':2,'sample':4,'other_detector':8}


def empty_bank(view,categories,origins):
    bins=math.ceil((view['high_ns']-view['low_ns'])*1000/view['bin_ps'])
    return np.zeros((3,categories,origins,bins),dtype=np.uint64)


def accumulate(hist,view,rows):
    if not len(rows):return
    scatter=SCATTERS[view.get('scatter','all')]
    if scatter:rows=rows[rows['s']==0 if scatter==-1 else (rows['s']&scatter)!=0]
    elapsed=rows['dt']-view['zero_ps']/1000
    bins=np.floor((elapsed-view['low_ns'])*1000/view['bin_ps']).astype(np.int64)
    inside=(bins>=0)&(bins<hist.shape[-1])&(elapsed<view['high_ns'])
    selected=rows[inside]
    np.add.at(hist,(selected['d'],selected['c'],selected['o'],bins[inside]),1)


def classify(rows,channels):
    reasons=rows['reason'].copy()
    windows=np.full((len(rows),2),-1,dtype='i1')
    for ch,settings in enumerate(channels):
        height,area,rise,fall,_=rows['values'][:,ch].T
        why=reasons[:,ch]
        if settings['reject_clipped']:why[(why==0)&(rows['clipped'][:,ch]!=0)]=4
        valid=why==0
        why[valid]=5
        for code,key in enumerate(('start','stop')):
            gate=settings[key];limits=gate['phs'];band=gate['area'];ellipse=gate['shape']
            inside=valid&(height>=limits['low'])&(height<limits['high'])
            if band['enabled']:
                error=area-(band['slope']*height+band['intercept'])
                failed=inside&((error < -band['below'])|(error>band['above']))
                why[failed]=6;inside&=~failed
            if ellipse['enabled']:
                a=math.radians(ellipse['angle_deg']);x=rise-ellipse['rise'];y=fall-ellipse['fall']
                u=(x*math.cos(a)+y*math.sin(a))/ellipse['radius_rise']
                v=(-x*math.sin(a)+y*math.cos(a))/ellipse['radius_fall']
                failed=inside&(~np.isfinite(u)|~np.isfinite(v)|(u*u+v*v>1));why[failed]=7;inside&=~failed
            why[inside]=0;windows[inside,ch]=code
    a,b=windows.T
    direction=np.full(len(rows),-1,dtype='i1')
    direction[(a==0)&(b==1)]=0;direction[(a==1)&(b==0)]=1;direction[(a==1)&(b==1)]=2
    return direction,reasons


def rejection_counts(reasons,rejected):
    packed=reasons[rejected,0].astype(int)*len(REASONS)+reasons[rejected,1]
    counts={}
    for i,n in enumerate(np.bincount(packed)):
        if n:
            label=' / '.join(v for v in (REASONS[i//len(REASONS)],REASONS[i%len(REASONS)]) if v) or 'Both channels in Start windows'
            counts[label]=counts.get(label,0)+int(n)
    return counts


class Diagnostics:
    """A bounded population of consecutive pairs; keep both channels paired."""
    def __init__(self):
        self.parts=deque();self.size=0
    def __len__(self):return self.size
    def clear(self):self.parts.clear();self.size=0
    def append(self,rows):
        # Each chunk owns just its measurements, independent of the input block.
        data=rows['values'][:,:,[0,1,2,3]].copy()
        data[rows['reason']!=0]=np.nan
        self.parts.append(data);self.size+=len(data)
        while self.size>6000:
            excess=self.size-6000;old=self.parts.popleft()
            if len(old)>excess:self.parts.appendleft(old[excess:]);self.size=6000
            else:self.size-=len(old)
    def channel(self,ch):
        if not self.parts:return np.empty((0,4))
        data=np.concatenate([part[:,ch] for part in self.parts]);return data[np.isfinite(data[:,0])]


class PulseHeights:
    def __init__(self,headers):
        span=max((h['profile']['digitization']['full_range_mV'] for h in headers),default=1000)
        self.step=span/1024
        self.counts=np.zeros((2,2,1025),dtype='uint64')
        self.overflow=np.zeros((2,2),dtype='uint64')
    def add(self,rows,accepted):
        for ch in (0,1):
            mask=rows['reason'][:,ch]==0
            for index,select in enumerate((mask,mask&accepted)):
                heights=rows['values'][select,ch,0]
                if not len(heights):continue
                inside=heights<len(self.counts[ch,index])*self.step
                self.overflow[ch,index]+=np.uint64(np.count_nonzero(~inside))
                heights=heights[inside]
                if not len(heights):continue
                bins=np.floor(heights/self.step).astype(np.int64)
                hist=np.bincount(bins)
                self.counts[ch,index,:len(hist)]+=hist.astype(np.uint64)
    def snapshot(self):
        result=[]
        for ch,(before,after) in enumerate(self.counts):
            used=np.flatnonzero(before);n=int(used[-1])+1 if len(used) else 0
            result.append(dict(channel='AB'[ch],step_mV=self.step,before=before[:n].tolist(),
                               accepted=after[:n].tolist(),overflow=self.overflow[ch].tolist(),
                               measured=int(before.sum()+self.overflow[ch,0]),selected=int(after.sum()+self.overflow[ch,1])))
        return result


def scalar_rows(items,categories,origins):
    rows=np.zeros(len(items),dtype=RESULT)
    for i,r in enumerate(items):
        truth=r['truth'];row=rows[i]
        row['id']=r['id'];row['start']=r['start_ns'];row['category']=categories.index(truth['category'])
        row['origin']=origins.index(truth['origin']);row['scatter']=truth['scatter_mask']
        row['contributions']=truth['contributions']
        for ch,f in enumerate(r['features']):
            row['values'][ch]=[f.get(k,0) for k in FEATURES]
            row['reason'][ch]=0 if f['valid'] else REASONS.index(f['reason'])
    return rows

