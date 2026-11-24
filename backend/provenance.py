# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Shared, ordered transport ancestry. Node IDs are one-based; zero is the root.

One non-optical track birth/step per node, plus optical steps that produce descendants. Optical photons refer to the parent's
head at their birth, never its eventual final path. This is simulation truth;
waveform pulse finding and CF must not inspect it.
"""
import json
import struct
from functools import lru_cache
import numpy as np

PREFIX=struct.Struct('<QIIII')
NODE=np.dtype([(key,'<u4') for key in ('parent','track','parent_track','primary','component','next_component')]
              +[('pdg','<i4'),('process','<u4'),('time_ns','<f8'),('position_mm','<f8',(3,)),
                ('energy_before_keV','<f8'),('energy_after_keV','<f8'),
                ('direction_before','<f8',(3,)),('direction_after','<f8',(3,))])
assert NODE.itemsize==128

def _parse_dictionary(encoded):
    from .streams import StreamError
    try:processes=json.loads(encoded)
    except (ValueError,UnicodeError) as e:raise StreamError('Invalid transport process dictionary') from e
    if not isinstance(processes,list) or not all(isinstance(x,str) and x for x in processes):raise StreamError('Invalid transport processes')
    return tuple(processes)

_cached_dictionary=lru_cache(maxsize=256)(_parse_dictionary)

def _process_dictionary(encoded):
    return _cached_dictionary(encoded) if len(encoded)<=4096 else _parse_dictionary(encoded)

def decode(payload,event_id=None,counts=None,components=None):
    from .streams import StreamError
    if len(payload)<PREFIX.size:raise StreamError('Truncated transport ancestry')
    event,n,a,b,j=PREFIX.unpack_from(payload)
    if len(payload)!=PREFIX.size+j+n*NODE.itemsize+(a+b)*4:raise StreamError('Invalid transport ancestry length')
    if event_id is not None and event!=event_id:raise StreamError('Transport ancestry event ID does not match')
    if counts is not None and [a,b]!=list(counts):raise StreamError('Transport ancestry photoelectron counts do not match')
    processes=list(_process_dictionary(bytes(payload[PREFIX.size:PREFIX.size+j])))
    nodes=np.frombuffer(payload,dtype=NODE,count=n,offset=PREFIX.size+j)
    refs=np.frombuffer(payload,dtype='<u4',count=a+b,offset=PREFIX.size+j+n*NODE.itemsize)
    from .analog_pmt import native_library
    library=native_library()
    fast=getattr(library,'tp_transport_validate',None)
    if fast is not None:
        raw=np.frombuffer(payload,dtype=np.uint8,offset=PREFIX.size+j)
        code=fast(raw[:n*128],n,raw[n*128:],a+b,len(processes),-1 if components is None else components)
        if code:raise StreamError({1:'Invalid transport tree node',2:'Transport tree references an unknown component',3:'Photoelectron references an unknown transport node'}[code])
    elif n:
        floats=np.ndarray((n,12),dtype='<f8',buffer=payload,offset=PREFIX.size+j+32,strides=(128,8))
        if (not np.all(np.isfinite(floats)) or np.any(nodes['parent']>=np.arange(1,n+1))
            or np.any(nodes['track']==0) or np.any(nodes['primary']>2) or np.any(nodes['process']>=len(processes))
            or np.any(nodes['energy_before_keV']<0) or np.any(nodes['energy_after_keV']<0)):
            raise StreamError('Invalid transport tree node')
        if components is not None and (np.any(nodes['component']>=components) or np.any(nodes['next_component']>=components)):
            raise StreamError('Transport tree references an unknown component')
    if fast is None and (np.any(refs==0) or np.any(refs>n)):raise StreamError('Photoelectron references an unknown transport node')
    return dict(event_id=event,processes=processes,nodes=nodes,photoelectron_nodes=[refs[:a],refs[a:]])

def path(tree,node):
    """Ordered immutable ancestry, including repeat visits and secondary branches."""
    result=[]
    while node:
        value=tree['nodes'][node-1]
        item={name:value[name].tolist() for name in NODE.names}
        item['id']=int(node);item['process']=tree['processes'][item['process']]
        result.append(item);node=int(value['parent'])
    return list(reversed(result))


def preview_summary(tree,components,role):
    """Small view of one retained event, never the all-event statistical sample.

    Group consecutive component visits on each immutable branch. Intervening air
    is hidden after collapsing, so A -> air -> A still displays a repeated visit.
    Anode routes terminate at the light's parent at birth, not later gamma steps.
    """
    from collections import Counter
    labels={c['id']:c['label'] for c in components}
    crystals={c['id']:('A' if c['volume']=='ScintA' else 'B') for c in components if c['volume'] in ('ScintA','ScintB')}
    allowed={1,2} if role=='na22_annihilation' else {1} if role=='co60_1332' else {0}
    nodes=tree['nodes'];cache={0:()}
    def route(head):
        pending=[];n=head
        while n not in cache:pending.append(n);n=int(nodes[n-1]['parent'])
        for n in reversed(pending):
            item=nodes[n-1];prefix=cache[int(item['parent'])];component=int(item['component'])
            cache[n]=prefix if prefix and prefix[-1]==component else (*prefix,component)
        return tuple(labels[c] for c in cache[head] if c)
    def summarize(counts):
        routes=[];primary_by_detector={'A':set(),'B':set()}
        for (detector,head),count in counts.items():
            primary=int(nodes[head-1]['primary'])
            if primary not in allowed:continue
            primary_by_detector[detector].add(primary)
            routes.append((detector,primary,route(head),count))
        grouped=Counter()
        for detector,primary,visits,count in routes:grouped[(detector,primary,visits)]+=count
        a,b=primary_by_detector.values()
        return dict(shared_primary=bool(a&b),distinct_primaries=any(x!=y for x in a for y in b),
                    routes=[dict(detector=d,primary=p,visits=list(v),count=n) for (d,p,v),n in sorted(grouped.items())])
    anode=Counter()
    for d,refs in zip('AB',tree['photoelectron_nodes']):
        anode.update({(d,int(head)):int(count) for head,count in zip(*np.unique(refs,return_counts=True))})
    crystal=Counter()
    for i,n in enumerate(nodes):
        if not n['parent'] or n['track']!=nodes[int(n['parent'])-1]['track']:continue
        component=int(n['component']);process=tree['processes'][int(n['process'])]
        if component not in crystals or not n['pdg'] or process in ('Birth','Transportation','CoupledTransportation'):continue
        # Actual non-optical interaction nodes, not geometrical crossings.
        if n['pdg']==22 or n['energy_before_keV']>n['energy_after_keV']:
            crystal[(crystals[component],i+1)]+=1
    return dict(crystal=summarize(crystal),anode=summarize(anode))

def pulse_routes(tree, components, photoelectrons, cf_cutoffs):
    """Trace the PE contributors of a displayed record to their immutable birth ancestry."""
    from collections import Counter
    labels={c['id']:c['label'] for c in components}
    volumes={c['id']:c.get('volume','') for c in components}
    nodes=tree['nodes']
    cache={0:(None,())}
    processes={'compt':'Compton','compton':'Compton','rayl':'Rayleigh','rayleigh':'Rayleigh'}

    def branch(head):
        pending=[]
        while head not in cache:
            pending.append(head)
            head=int(nodes[head-1]['parent'])
        previous,steps=cache[head]
        for index in reversed(pending):
            node=nodes[index-1]
            component=int(node['component'])
            label=labels.get(component,'Surroundings') if component else 'Surroundings'
            process=processes.get(tree['processes'][int(node['process'])].lower()) if node['pdg']==22 else None
            if component and component!=previous:
                steps+=((label,'',None,False),)
            if process:
                before,after=node['direction_before'],node['direction_after']
                norm=float(np.linalg.norm(before)*np.linalg.norm(after))
                angle=None
                if norm>0 and node['energy_after_keV']>0:
                    angle=float(np.degrees(np.arccos(np.clip(np.dot(before,after)/norm,-1,1))))
                steps+=((label,process,round(angle,2) if angle is not None else None,angle is not None and angle>90),)
            previous=component
            cache[index]=previous,steps
        return steps

    paths=[]
    for detector,refs,pe,cutoffs in zip('AB',tree['photoelectron_nodes'],photoelectrons,cf_cutoffs):
        if not len(refs):continue
        groups,inverse,counts=np.unique(np.column_stack((refs,pe[:,4:6])).astype(np.int64),
                                        axis=0,return_inverse=True,return_counts=True)
        # A record may be reused by independent decays in the same sweep.
        early={decay:np.bincount(inverse[pe[:,1]<=cut],minlength=len(groups)) for decay,cut in cutoffs.items()}
        first_arrival=np.full(len(groups),np.inf)
        last_arrival=np.full(len(groups),-np.inf)
        np.minimum.at(first_arrival,inverse,pe[:,0])
        np.maximum.at(last_arrival,inverse,pe[:,0])
        arrivals={}
        routes=Counter()
        by_cf={decay:Counter() for decay in cutoffs}
        for group,((head,mechanism,birth),count) in enumerate(zip(groups,counts)):
            key=(int(nodes[head-1]['primary']),branch(int(head)),int(mechanism),int(birth))
            routes[key]+=int(count)
            lo,hi=arrivals.get(key,(np.inf,-np.inf))
            arrivals[key]=(min(lo,first_arrival[group]),max(hi,last_arrival[group]))
            for decay,values in early.items():by_cf[decay][key]+=int(values[group])
        for key,count in routes.most_common():
            primary,steps,mechanism,birth=key
            paths.append(dict(detector=detector,primary=primary,count=count,
                              cathode_arrival_ns=[float(v) for v in arrivals[key]],by_cf={d:c[key] for d,c in by_cf.items()},
                              steps=[dict(component=c,process=p,angle_deg=a,backscatter=b) for c,p,a,b in steps],
                              origin='Cherenkov' if mechanism==2 else 'Scintillation',
                              birth_volume=volumes.get(birth,''),birth=labels.get(birth,'Surroundings' if birth==0 else 'Unknown component')))
    return paths


def fixture(event_id,counts,primary=0):
    """Explicit synthetic birth node, for unit fixtures only; never runtime fallback."""
    nodes=np.zeros(1,dtype=NODE);nodes['track']=1;nodes['primary']=primary;nodes['pdg']=11
    names=b'["Synthetic test birth"]'
    return PREFIX.pack(event_id,1,*counts,len(names))+names+nodes.tobytes()+np.ones(sum(counts),dtype='<u4').tobytes()
