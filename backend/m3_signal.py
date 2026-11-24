# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Independent CF implementation; provenance is never used for waveform selection."""
import math
from functools import lru_cache
import numpy as np
from .m3_interpolation import slopes, refined_crossing
from .m3_subtypes import subtype_key

CATEGORIES = ['correlated', 'annihilation_pair', 'same_primary', 'accidental', 'pileup_same_decay', 'pileup_multiple_decays', 'unresolved']


@lru_cache(maxsize=128)
def _response_span(order,tau,bandwidth):
    from .analog_pmt import tail_span
    return tail_span(order,tau)+(30*1000/(2*np.pi*bandwidth) if bandwidth else 0)


def transport_support(tr, channel, response, bandwidth, components):
    """Compact truth for one reused transport record; no waveform decisions here."""
    q=tr['photoelectrons'][channel];tree=tr['provenance'];nodes=tree['nodes']
    refs=tree['photoelectron_nodes'][channel]
    volumes={c['id']:c['volume'] for c in components}
    heads=np.unique(refs)
    primaries=np.unique(nodes['primary'][heads-1]).tolist() if len(heads) else []
    mask=0;visited=set();local=set();backscattered=set();external=False
    interactions={}
    for head in heads:
        head=int(head)
        while head and head not in visited:
            visited.add(head);node=nodes[head-1]
            process=tree['processes'][int(node['process'])].lower()
            volume=volumes.get(int(node['component']),'')
            scatter=node['pdg']==22 and process in ('compt','compton','rayl','rayleigh')
            if node['pdg']==22 and node['parent_track']==0:
                if scatter or node['energy_before_keV']>node['energy_after_keV']:interactions[head]=volume
                external |= scatter and volume not in ('ScintA','ScintB')
                if volume=='Scint'+'AB'[channel] and (scatter or node['energy_before_keV']>node['energy_after_keV']):
                    local.add(int(node['primary']))
                if (scatter and volume=='Scint'+'BA'[channel] and node['energy_after_keV']>0
                        and np.dot(node['direction_before'],node['direction_after'])<0):
                    backscattered.add(int(node['primary']))
            if scatter:
                mask |= 1
                if volume.startswith('Shield'):mask |= 2
                if volume.startswith(('Sample','Foil','Source')):mask |= 4
                if volume=='Scint'+('B' if channel==0 else 'A'):mask |= 8
            head=int(node['parent'])
    span=(float(np.ptp(q[:,1])) if len(q) else 0)+_response_span(response['order'],response['tau_ns'],bandwidth)
    first={0:None}
    for node_id in sorted(visited):
        previous=first[int(nodes[node_id-1]['parent'])]
        first[node_id]=interactions.get(node_id) if previous is None else previous
    direct={int(nodes[h-1]['primary']) for h in heads if first[h]=='Scint'+'AB'[channel]}
    return dict(span=span,primaries=primaries,scatter_mask=mask,local_primaries=sorted(local),direct_primaries=sorted(direct),
                backscatter_primaries=sorted(backscattered),external_scatter=bool(external))


def crossing(t, y, level, begin, end, rising=True, derivatives=None, steps=1, last=False):
    for i in (range(end-1,begin-1,-1) if last else range(begin,end)):
        if (y[i] <= level < y[i+1]) if rising else (y[i] >= level > y[i+1]):
            if derivatives is not None:return refined_crossing(t,y,derivatives,level,i,steps,rising,last)
            return float(t[i]+(level-y[i])*(t[i+1]-t[i])/(y[i+1]-y[i]))
    return None


def selected_peak(y, baseline, threshold, noise, rule):
    if rule=='highest':return int(np.argmax(y))
    peak=None
    for i in range(baseline+1,len(y)):
        if peak is None:
            if y[i]>=threshold and y[i-1]<threshold:peak=i
        elif y[i]>y[peak]:peak=i
        elif y[peak]-y[i]>=max(5*noise,.1*y[peak]):break
    return peak


def lobe_edge(y,peak,step,floor,prominence):
    valley=peak
    for i in range(peak+step,len(y) if step>0 else -1,step):
        if y[i]<=y[valley]:valley=i
        if y[i]<=floor or y[i]-y[valley]>=prominence:break
    return valley


def extract(t, v, settings, rule='highest'):
    n=len(t); b=settings['baseline_samples']; k=settings['median_samples']
    if n<=b+4 or not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)) or np.any(np.diff(t)<=0): return {'valid':False,'reason':'Invalid samples or baseline region'}
    dynamic=settings.get('baseline_mode')=='pre_pulse'
    seed=min(8,b) if dynamic else b
    baseline=float(np.median(v[:seed])); noise=float(1.4826*np.median(np.abs(v[:seed]-baseline)))
    sign=1 if settings['polarity']=='positive' else -1
    y=sign*(v.astype(float)-baseline)
    if k>1:
        y=np.median(np.lib.stride_tricks.sliding_window_view(np.pad(y,(k//2,k//2),mode='edge'),k),axis=1)
    peak=selected_peak(y,seed,max(settings['minimum_height_mV'],5*noise),noise,rule)
    region={} if dynamic else dict(baseline_start=0,baseline=baseline,noise=noise)
    if peak is None:return dict(valid=False,reason='No usable pulse',**region)
    if dynamic:
        if y[peak]<max(settings['minimum_height_mV'],5*noise) or peak>=n-2:
            return dict(valid=False,reason='No usable pulse')
        # Anchor on the selected lobe's steepest rising step, then seek the
        # nearest three quiet samples preceding it. Only ADC data enter here.
        tolerance=max(3*noise,.005*y[peak])
        left=lobe_edge(y,peak,-1,tolerance,max(5*noise,.1*y[peak]))
        edge=left+int(np.argmax(np.diff(y[left:peak+1]))) if left<peak else peak
        onset=next((j+1 for j in range(edge,1,-1) if np.ptp(y[j-2:j+1])<=tolerance),0)
        end=onset-settings.get('baseline_gap',4)
        if end<b:return dict(valid=False,reason='Insufficient pre-pulse baseline')
        samples=v[end-b:end]
        local=float(np.median(samples));noise=float(1.4826*np.median(np.abs(samples-local)))
        y+=sign*(baseline-local);baseline=local
        region=dict(baseline_start=end-b,baseline=baseline,noise=noise,onset_ns=float(t[onset]))
    height=float(y[peak])
    result=dict(valid=False,reason='No usable pulse',height=height,peak_ns=float(t[peak]),**region)
    if height<max(settings['minimum_height_mV'],5*noise) or peak<=seed or peak>=n-2:return result
    floor=max(3*noise,height*.005)
    edge_level=min(floor,height*.1,height*settings['cfd_percent']*.01)
    prominence=max(5*noise,height*.1)
    lo=lobe_edge(y,peak,-1,edge_level,prominence)
    # Three consecutive samples inside the baseline band separate connected pulses.
    quiet=0;hi=n-1;settled=False
    for i in range(peak+1,n):
        quiet=quiet+1 if abs(y[i])<=floor else 0
        if quiet==3:
            hi=i;settled=True;break
    method=settings.get('interpolation','linear');steps=settings.get('intra_steps',8)
    d=slopes(t,y,method) if method!='linear' else None
    t10=crossing(t,y,.1*height,lo,peak,True,d,steps)
    t90=crossing(t,y,.9*height,lo,peak,True,d,steps)
    cfd=crossing(t,y,settings['cfd_percent']*.01*height,lo,peak,True,d,steps)
    f10=crossing(t,y,.1*height,peak,hi,False,d,steps,True) if settled else None
    f90=crossing(t,y,.9*height,peak,min(hi,int(np.searchsorted(t,f10,side='right'))),False,d,steps,True) if f10 is not None else None
    if cfd is None:
        result['reason']='Missing leading CF crossing';return result
    a=peak
    while a>lo and y[a]>floor:a-=1
    # Absolute trapezoids across the full calibrated readout, in mV ns.
    area=float(np.sum(np.abs((y[:-1]+y[1:])*.5*np.diff(t))))
    result.update(valid=True,reason='',cfd_ns=cfd,rise_ns=t90-t10 if t10 is not None and t90 is not None else None,
                  fall_ns=f10-f90 if f90 is not None and f10>=f90 else None,area=area,
                  settled=settled,baseline_band_mV=floor,support=[float(t[a]),float(t[hi-2 if settled else hi])],t10=t10,t90=t90,f90=f90,f10=f10)
    return result


def gate(feature, settings, clipped):
    if not feature['valid']:return None,feature['reason']
    if settings['reject_clipped'] and clipped:return None,'ADC clipping'
    for name in ('start','stop'):
        g=settings[name];p=g['phs'];h=feature['height']
        if not p['low']<=h<p['high']:continue
        band=g['area'];shape=g['shape']
        residual=feature['area']-(band['slope']*h+band['intercept'])
        if band['enabled'] and not -band['below']<=residual<=band['above']:return None,'Area filter'
        if not shape['enabled']:return name,''
        if feature['rise_ns'] is None or feature['fall_ns'] is None:return None,'Rise/fall filter'
        angle=math.radians(shape['angle_deg']);x=feature['rise_ns']-shape['rise'];y=feature['fall_ns']-shape['fall']
        u=x*math.cos(angle)+y*math.sin(angle);v=-x*math.sin(angle)+y*math.cos(angle)
        if shape['enabled'] and (u/shape['radius_rise'])**2+(v/shape['radius_fall'])**2>1:return None,'Rise/fall filter'
        return name,''
    return None,'Outside PHS windows'


def provenance(meta, features, isotope):
    # Full acquisition-window contributions remain available. Restrict attribution
    # only where a stored support end exists; otherwise conservatively retain it.
    selected=[]
    for ch,f in enumerate(features):
        if not f['valid']:selected.append([]);continue
        lo,hi=f['support']
        selected.append([p for p in meta['pulses'] if p['channel']==ch and p['onset_ns']<=hi
                         and p.get('end_ns',float('inf'))>=lo])
    pa,pb=selected;allp=pa+pb;decays={p['decay'] for p in allp}
    if not pa or not pb:category='unresolved'
    elif len(pa)>1 or len(pb)>1:category='pileup_same_decay' if len(decays)==1 else 'pileup_multiple_decays'
    elif pa[0]['decay']!=pb[0]['decay']:category='accidental'
    elif pa[0]['role']!=pb[0]['role']:category='correlated'
    else:
        a=set(pa[0].get('primary_ids',[]));b=set(pb[0].get('primary_ids',[]))
        if len(a)!=1 or len(b)!=1 or pa[0].get('record') is None or pa[0].get('record')!=pb[0].get('record'):category='unresolved'
        elif a==b:category='same_primary'
        elif isotope=='na22' and pa[0]['role']==1:category='annihilation_pair'
        else:category='unresolved'
    counts=[[0,0],[0,0]]
    for ch,pulses in enumerate(selected):
        for p in pulses:
            counts[ch][p['role']]+=1
    kinds={p['light_origin'] for p in allp}
    origin='unknown' if not kinds else next(iter(kinds)) if len(kinds)==1 else 'mixed'
    scatter_mask=0
    for p in allp:scatter_mask |= p.get('scatter_mask',0)
    return dict(category=category,subtype=subtype_key(isotope,CATEGORIES.index(category),counts[0]+counts[1]),contributions=counts,origin=origin,scatter_mask=scatter_mask,selected=selected,all_contributions=meta['pulses'],
                attribution='Conservative temporal overlap; no unique CF cause assigned for superposition.')


def process(item):
    offset,meta,data,profile,isotope=item
    features=[extract(data[2*c],data[2*c+1],s,profile.get('pulse_selection','highest')) for c,s in enumerate(profile['channels'])]
    gates=[gate(f,s,meta['clipped'][c]) for c,(f,s) in enumerate(zip(features,profile['channels']))]
    a,b=(v[0] for v in gates);direction=None;dt=None
    if a=='start' and b=='stop':direction='AB';dt=features[1]['cfd_ns']-features[0]['cfd_ns']
    elif a=='stop' and b=='start':direction='BA';dt=features[0]['cfd_ns']-features[1]['cfd_ns']
    elif a=='stop' and b=='stop':direction='SS';dt=features[1]['cfd_ns']-features[0]['cfd_ns']
    truth=provenance(meta,features,isotope)
    return dict(offset=offset,id=meta['id'],features=features,gates=gates,direction=direction,dt_ns=dt,
                truth=truth,start_ns=meta['start_ns'])
