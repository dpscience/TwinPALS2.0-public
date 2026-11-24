# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exact chunk-cached histograms. Completed chunks never need rescanning unless edges change."""
import math
import numpy as np
from .streams import METRICS, ROLES, StreamError, _pose, _check_cancel
from .analysis_basis import selected as population_selected, available


def histogram(snapshots, request, cancel=None, cache=None, index=None):
    from .live_analysis import selected_rows, values
    cache={} if cache is None else cache
    metric=request.get('metric','energy'); detector=request.get('detector','all')
    primary=request.get('primary','all'); category=request.get('category','all'); bins=request.get('bins',120)
    origin=request.get('origin','all'); split=request.get('split_origin',False);basis=request.get('basis')
    if basis not in (None,'crystal','anode'):raise StreamError('Choose Crystal or Anode analysis')
    suppressed=request.get('suppress_zero',[])
    if metric not in METRICS or detector not in ('all','A','B') or category not in ('all','none','A','B','both','interaction','transmission','miss'):
        raise StreamError('Invalid histogram quantity or detector response')
    if origin not in ('all','none','scintillation','cherenkov','mixed') or type(split) is not bool:
        raise StreamError('Choose a valid anode origin')
    if not isinstance(suppressed,list) or any(m not in METRICS for m in suppressed):
        raise StreamError('Hide zeros is unavailable for this quantity')
    if type(bins) is not int or not 1<=bins<=4096:raise StreamError('Bins must be from 1 to 4096')
    chosen=request.get('range')
    if chosen is not None and (not isinstance(chosen,(list,tuple)) or len(chosen)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in chosen) or chosen[1]<=chosen[0]):
        raise StreamError('Invalid histogram range')
    active=[s for s in snapshots if primary in ('all',s.header['role'])]
    if not active:raise StreamError('Selected primary does not exist')
    if not available(metric,basis):
        series=[];positions=[]
    elif index is not None:
        series=index.query_series(active,request,cancel)
        positions=[]
        if metric=='depth' and request.get('include_positions',True):
            detectors=(0,1) if detector=='all' else ('AB'.index(detector),)
            origins=(('scintillation','cherenkov','mixed') if basis=='anode' else ('none','scintillation','cherenkov','mixed')) if split and origin=='all' else (origin,)
            for s in active:
                for d in detectors:
                    pose=_pose(s.header,d)
                    for kind in origins:
                        for chunk in s.chunks:
                            if len(positions)>=5000:break
                            _check_cancel(cancel)
                            rows=selected_rows(chunk,category,d)
                            flags=rows['detectors']['flags'][:,d]
                            valid=rows[((flags&6)==6)&population_selected(flags,kind,basis)][:5000-len(positions)]
                            xyz=valid['detectors'][:,d]['position'];depths=np.sum((xyz-pose[0])*pose[1],axis=1)
                            positions.extend(dict(detector='AB'[d],primary=s.header['role'],event_id=int(r['id']),x=float(p[0]),y=float(p[1]),z=float(p[2]),depth=float(z)) for r,p,z in zip(valid,xyz,depths))
    else:
        signature=(basis,metric,detector,primary,category,bins,origin,split,tuple(suppressed),tuple(chosen) if chosen else None)
        if cache.get('signature')!=signature:cache.clear();cache['signature']=signature;cache['chunks']={}
        chunks=cache['chunks']; active=[s for s in snapshots if primary in ('all',s.header['role'])]
        if not active:raise StreamError('Selected primary does not exist')
        detectors=(0,1) if detector=='all' else ('AB'.index(detector),)
        origins=(('scintillation','cherenkov','mixed') if basis=='anode' else ('none','scintillation','cherenkov','mixed')) if split and origin=='all' else (origin,)
        series=[]; bounds=[math.inf,-math.inf]; positions=[]; work=[]
        for s in active:
            role=s.header['role']
            for d in detectors:
                pose=_pose(s.header,d) if metric in ('depth','polar_angle') else None
                for kind in origins:
                    row=dict(key=f'{role}:{"AB"[d]}:{kind}',label=f'{ROLES[role]} · Detector {"AB"[d]}',detector='AB'[d],primary=role,origin=kind if split else None,edges=[],counts=[],events=0,valid=0,missing=0,underflow=0,overflow=0,suppressed_zero=0)
                    parts=[]
                    for n,chunk in enumerate(s.chunks):
                        _check_cancel(cancel)
                        key=(s.path,d,kind,n)
                        saved=chunks.get(key)
                        if saved is None or saved['size']!=len(chunk):
                            selected=selected_rows(chunk,category,d)
                            v,missing=values(selected,metric,d,role,pose,kind,basis)
                            zeros=int(np.count_nonzero(v==0)) if metric in suppressed else 0
                            if metric in suppressed:v=v[v!=0]
                            keep=((selected['detectors']['flags'][:,d]&4)!=0)&population_selected(selected['detectors']['flags'][:,d],kind,basis)
                            points=[]
                            if metric=='depth' and len(positions)<5000:
                                valid=selected[keep & ((selected['detectors']['flags'][:,d]&6)==6)][:5000-len(positions)]
                                xyz=valid['detectors'][:,d]['position']; depths=np.sum((xyz-pose[0])*pose[1],axis=1)
                                points=[dict(detector='AB'[d],primary=role,event_id=int(r['id']),x=float(p[0]),y=float(p[1]),z=float(p[2]),depth=float(depth)) for r,p,depth in zip(valid,xyz,depths)]
                            saved=dict(size=len(chunk),events=len(selected),valid=len(v),missing=missing+int(np.count_nonzero(~keep)),suppressed_zero=zeros,low=float(v.min()) if len(v) else math.inf,high=float(v.max()) if len(v) else -math.inf,points=points,edges=None)
                            chunks[key]=saved
                            # Only the new tail's values live until this query ends.
                            fresh=v
                        else:fresh=None
                        for field in ('events','valid','missing','suppressed_zero'):row[field]+=saved[field]
                        bounds=[min(bounds[0],saved['low']),max(bounds[1],saved['high'])]
                        if len(positions)<5000:positions.extend(saved['points'][:5000-len(positions)])
                        parts.append((saved,chunk,fresh))
                    series.append(row);work.append((row,parts,d,role,pose,kind))
        low,high=chosen or bounds
        if not math.isfinite(low):low,high=0.,1.
        elif low==high:
            half=.5 if metric in ('photon_count','reflections') else max(abs(low)*.01,.0005)
            low,high=low-half,high+half
        edges=np.array([float(low+(high-low)*i/bins) for i in range(bins+1)])
        edgekey=(low,high,bins)
        for row,parts,d,role,pose,kind in work:
            counts=np.zeros(bins,dtype=np.int64)
            for saved,chunk,fresh in parts:
                _check_cancel(cancel)
                if saved['edges']!=edgekey:
                    v=fresh
                    if v is None:
                        v,_=values(selected_rows(chunk,category,d),metric,d,role,pose,kind,basis)
                        if metric in suppressed:v=v[v!=0]
                    inside=v[(v>=low)&(v<=high)]
                    indices=np.clip(np.searchsorted(edges,inside,side='right')-1,0,bins-1)
                    saved.update(edges=edgekey,counts=np.bincount(indices,minlength=bins),underflow=int(np.count_nonzero(v<low)),overflow=int(np.count_nonzero(v>high)))
                counts+=saved['counts'];row['underflow']+=saved['underflow'];row['overflow']+=saved['overflow']
            row['counts']=counts.tolist();row['edges']=edges.tolist()
            if not split:
                row['key']=f'{role}:{"AB"[d]}'
                row.pop('origin')
            if metric not in suppressed:row.pop('suppressed_zero')
    markers=[]
    if metric=='energy':
        energies=sorted({{'na22_prompt':1274.537,'na22_annihilation':511.,'co60_1173':1173.228,'co60_1332':1332.492}[s.header['role']] for s in active})
        for energy in energies:markers.extend([dict(x=energy,label=f'γ {energy:g} keV'),dict(x=energy*(1-1/(1+2*energy/510.99895)),label=f'Compton edge ({energy:g} keV)')])
    return dict(basis=basis,available=available(metric,basis),metric=metric,unit=METRICS[metric],series=series,streams=[dict(path=s.path,header=s.header,completion=dict(status=s.status,events=s.count,verified=s.verified),snapshot_bytes=s.loaded_bytes,outcomes=s.outcomes) for s in snapshots],profile=active[0].header.get('profile'),total_events=sum(s.count for s in active),complete=all(s.status=='completed' for s in snapshots),warnings=[],markers=markers,positions=positions,loading=any(s.loading for s in snapshots),loaded_bytes=sum(s.loaded_bytes for s in snapshots),total_bytes=sum(s.total_bytes for s in snapshots))
