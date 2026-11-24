# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exact incremental sufficient data for arbitrary M1 histogram selections.

Values are partitioned once by crystal response, joint detector response and
accepted-light origin and independent crystal light production. Sorted runs answer new binning/filter queries by binary
search. Zero counts are compressed; no precomputed cross-product of UI options.
"""
import math
import numpy as np
from .streams import METRICS, ROLES, _pose, _check_cancel

ORIGINS=('none','scintillation','cherenkov','mixed')


class SortedValues:
    def __init__(self):
        self.runs=[]
        self.zeros=0
        self.count=0
        self.missing=0

    def append(self, values, missing):
        self.missing+=missing
        self.count+=len(values)
        nonzero=values[values!=0]
        self.zeros+=len(values)-len(nonzero)
        if not len(nonzero):return
        run=np.sort(nonzero.astype(np.float64),kind='stable')
        # Binary compaction bounds the number of searches, even after long runs.
        level=0
        while level<len(self.runs) and self.runs[level] is not None:
            run=np.sort(np.concatenate((self.runs[level],run)),kind='stable')
            self.runs[level]=None
            level+=1
        if level==len(self.runs):self.runs.append(run)
        else:self.runs[level]=run

    def bounds(self, suppress):
        low,high=math.inf,-math.inf
        if self.zeros and not suppress:low=high=0.
        for r in self.runs:
            if r is not None:low=min(low,float(r[0]));high=max(high,float(r[-1]))
        return low,high

    def histogram(self, edges, low, high, suppress):
        counts=np.zeros(len(edges)-1,dtype=np.int64);under=over=0
        for r in self.runs:
            if r is None:continue
            first=int(np.searchsorted(r,low,side='left'))
            last=int(np.searchsorted(r,high,side='right'))
            cuts=np.concatenate(([first],np.clip(np.searchsorted(r,edges[1:-1],side='left'),first,last),[last]))
            counts+=np.diff(cuts);under+=first;over+=len(r)-last
        if not suppress and self.zeros:
            if 0<low:under+=self.zeros
            elif 0>high:over+=self.zeros
            else:counts[np.clip(np.searchsorted(edges,0.,side='right')-1,0,len(counts)-1)]+=self.zeros
        return counts,under,over


class HistogramIndex:
    def __init__(self):
        self.streams={}

    def prepare(self, snapshots, cancel=None):
        from .live_analysis import values
        for s in snapshots:
            state=self.streams.setdefault(s.path,dict(count=0,detectors=[{},{}]))
            if s.count<state['count']:raise ValueError('Histogram source was replaced without a new analysis session')
            offset=0
            for chunk in s.chunks:
                end=offset+len(chunk)
                if end<=state['count']:offset=end;continue
                rows=chunk[max(0,state['count']-offset):]
                _check_cancel(cancel)
                flags=rows['detectors']['flags'];energy=rows['detectors']['energy']
                pulse=(flags&5)==5
                joint=pulse[:,0].astype(int)+2*pulse[:,1].astype(int)
                for d in range(2):
                    interaction=((flags[:,d]&2)!=0)|(energy[:,d]>0)
                    crystal=np.where(interaction,0,np.where((flags[:,d]&8)!=0,1,2))
                    origin=((flags[:,d]>>4)&3).astype(int)
                    production=((flags[:,d]>>6)&3).astype(int)
                    codes=crystal*64+joint*16+origin*4+production
                    pose=_pose(s.header,d)
                    for code in np.unique(codes):
                        part=rows[codes==code]
                        group=state['detectors'][d].setdefault(int(code),dict(rows=0,eligible=0,metrics={m:SortedValues() for m in METRICS}))
                        group['rows']+=len(part)
                        group['eligible']+=int(np.count_nonzero(part['detectors']['flags'][:,d]&4))
                        for metric in METRICS:
                            v,missing=values(part,metric,d,s.header['role'],pose)
                            group['metrics'][metric].append(v,missing)
                state['count']=end;offset=end

    def groups(self,path,detector,category,origin='all',basis=None):
        for code,g in self.streams[path]['detectors'][detector].items():
            crystal,joint=code//64,(code//16)%4
            light=code%4 if basis=='crystal' else (code//4)%4
            if basis=='anode' and not joint&(1<<detector):continue
            if category in ('interaction','transmission','miss') and crystal!=('interaction','transmission','miss').index(category):continue
            if category in ('none','A','B','both') and joint!=('none','A','B','both').index(category):continue
            if origin!='all' and light!=ORIGINS.index(origin):continue
            yield g

    def query_series(self,active,request,cancel=None):
        metric=request.get('metric','energy');category=request.get('category','all');basis=request.get('basis')
        detector=request.get('detector','all');origin=request.get('origin','all');split=request.get('split_origin',False)
        suppress=metric in request.get('suppress_zero',[]);bins=request.get('bins',120)
        detectors=(0,1) if detector=='all' else ('AB'.index(detector),)
        origins=(ORIGINS[1:] if basis=='anode' else ORIGINS) if split and origin=='all' else (origin,)
        series=[];work=[];low,high=math.inf,-math.inf
        for s in active:
            role=s.header['role']
            for d in detectors:
                total=sum(g['rows'] for g in self.groups(s.path,d,category))
                for kind in origins:
                    groups=list(self.groups(s.path,d,category,kind,basis))
                    parts=[g['metrics'][metric] for g in groups]
                    row=dict(key=f'{role}:{"AB"[d]}'+(f':{kind}' if split else ''),label=f'{ROLES[role]} · Detector {"AB"[d]}',detector='AB'[d],primary=role,
                        events=total,valid=sum(v.count-(v.zeros if suppress else 0) for v in parts),
                        missing=total-sum(g['eligible'] for g in groups)+sum(v.missing for v in parts),underflow=0,overflow=0)
                    if split:row['origin']=kind
                    if suppress:row['suppressed_zero']=sum(v.zeros for v in parts)
                    for v in parts:
                        a,b=v.bounds(suppress);low=min(low,a);high=max(high,b)
                    series.append(row);work.append(parts)
        low,high=request.get('range') or (low,high)
        if not math.isfinite(low):low,high=0.,1.
        elif low==high:
            half=.5 if metric in ('photon_count','reflections') else max(abs(low)*.01,.0005)
            low,high=low-half,high+half
        edges=np.array([float(low+(high-low)*i/bins) for i in range(bins+1)])
        for row,parts in zip(series,work):
            _check_cancel(cancel)
            counts=np.zeros(bins,dtype=np.int64)
            for v in parts:
                c,u,o=v.histogram(edges,low,high,suppress)
                counts+=c;row['underflow']+=u;row['overflow']+=o
            row['counts']=counts.tolist();row['edges']=edges.tolist()
        return series

    @property
    def bytes(self):
        return sum(r.nbytes for s in self.streams.values() for d in s['detectors'] for g in d.values() for v in g['metrics'].values() for r in v.runs if r is not None)
