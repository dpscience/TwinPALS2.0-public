# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import base64
import json
import struct
import numpy as np
import pytest
from backend.streams import MAGIC,PREFIX,DETECTOR,StreamError,analyze,validate_complete,inspect_stream
from backend.live_analysis import AnalysisStore
from test_streams_v1 import fixture_header,event,frame,record
from test_live_analysis import loaded

def sample(index,origins,mask=1,threshold=0):
    row=event(index,(10,len(origins[0]),1 if origins[0] else 0),(0,len(origins[1]),2 if origins[1] else 0),mask,threshold)
    raw=bytearray(row[12:]);packed=record(row);n=struct.unpack_from('<I',packed,4)[0];analog=bytearray(packed[12:12+n])
    offset=16+32*sum(map(len,origins))
    for d,tags in enumerate(origins):
        flags=struct.unpack_from('<I',raw,PREFIX.size+d*DETECTOR.size)[0]&~48
        for mechanism,component in tags:flags|=mechanism<<4
        struct.pack_into('<I',raw,PREFIX.size+d*DETECTOR.size,flags)
        for mechanism,component in tags:analog[offset:offset+2]=bytes([mechanism,component]);offset+=2
    return bytes(raw),bytes(analog)

@pytest.mark.parametrize('role,mask',[('na22_prompt',1),('na22_annihilation',6),('co60_1173',3),('co60_1332',3)])
@pytest.mark.parametrize('threshold',[0,5])
def test_origin_filters_raw_crystal_counts_live_reload(tmp_path,role,mask,threshold):
    header=fixture_header(role);header['physics']['minimum_energy_keV']=threshold
    header['light_components'].append(dict(id=1,volume='WindowB',label='Window B',material='Silica'))
    tags=[([[],[]]),([[(1,0)],[(2,1),(2,1)]]),([[(1,0),(2,0),(2,0),(2,1)],[]]),([[(2,1)],[(1,0)]])]
    records=[sample(i,t,mask,threshold) for i,t in enumerate(tags)]
    data=json.dumps(header).encode();path=tmp_path/'light.tpstream'
    from backend.provenance import fixture
    path.write_bytes(MAGIC+struct.pack('<I',len(data))+data+b''.join(frame(b'APLS',a)+frame(b'PROV',fixture(*((struct.unpack_from('<QII',a)[0],list(struct.unpack_from('<QII',a)[1:])))))+frame(b'EVNT',e) for e,a in records)+frame(b'DONE',json.dumps(dict(status='completed',events=4)).encode()))
    done=validate_complete(path)
    assert done['pulse_origin_counts']==[[1,1,1,1],[2,1,1,0]]
    assert done['eligible_response_counts']==[3,2 if threshold==0 else 0]
    live,imported=AnalysisStore(),AnalysisStore()
    try:
        live.register(header,path)
        for i,(raw,a) in enumerate(records):
            live.feed(dict(type='analysis_batch',role=role,first=i,count=1,data=base64.b64encode(raw).decode(),analog=base64.b64encode(a).decode(),**{f'hit_{ch}':base64.b64encode(np.zeros((len(tags[i][d]),2),dtype='<f4').tobytes()).decode() for d,ch in enumerate('ab')}))
        imported.open_files([path]);loaded(imported)
        lhs=live.buffers[role].outcomes();assert lhs==imported.buffers[role].outcomes()
        assert lhs['interaction']['count']==4 # crystal A energy deposit; independent of optical origin
        assert lhs['pulses']['A']['mixed']['count']==1
        assert lhs['pulses']['B']['cherenkov']['count']==1
        assert lhs['pulses']['B']['births'][0]['label']=='Window B'
        # Frequency is per event/component, not one event per accepted photon.
        a_births={b['id']:b for b in lhs['pulses']['A']['births']}
        assert (a_births[0]['events'],a_births[0]['photons'],a_births[0]['percent'])==(1,2,25.)
        assert (a_births[1]['events'],a_births[1]['photons'],a_births[1]['percent'])==(2,2,50.)
        b_birth=lhs['pulses']['B']['births'][0]
        assert (b_birth['events'],b_birth['photons'],b_birth['percent'])==(1,2,25.)
        for origin in ('all','none','scintillation','cherenkov','mixed'):
            for metric in ('energy','photon_count','pulse_height','mean_arrival','depth','polar_angle','azimuth','track_length','reflections'):
                req=dict(metric=metric,origin=origin,bins=7)
                expected=analyze([path],req)
                for store in (live,imported):assert store.query(req)[0]['series']==expected['series']
        # Origin partitions share the same bins and sum to the unsplit histogram.
        # Crystal cuts apply to the plotted detector, not the opposite side.
        for category in ('all','interaction','transmission','miss'):
            for metric in ('energy','photon_count','mean_arrival'):
                req=dict(metric=metric,category=category,bins=7,range=[0,20])
                total=live.query(req)[0]['series']
                parts=live.query(dict(req,split_origin=True))[0]['series']
                assert parts==imported.query(dict(req,split_origin=True))[0]['series']
                for base in total:
                    matching=[s for s in parts if s['detector']==base['detector'] and s['primary']==base['primary']]
                    assert all(s['edges']==base['edges'] for s in matching)
                    assert np.array_equal(np.sum([s['counts'] for s in matching],axis=0),base['counts'])
    finally:live.close();imported.close()

def test_reject_inconsistent_origin_component_and_disabled_process(tmp_path):
    from backend.streams import analog_payload
    from backend.light_origin import validate
    raw,a=sample(0,[[(2,0)],[]]);arrays=analog_payload(a,0);header=fixture_header()
    with pytest.raises(StreamError,match='origin'):validate(arrays[0],17,header)
    arrays[0][0,5]=9
    with pytest.raises(StreamError,match='component'):validate(arrays[0],33,header)
    arrays[0][0,5]=0;header['physics']['include_cherenkov']=False
    with pytest.raises(StreamError,match='disabled'):validate(arrays[0],33,header)

@pytest.mark.parametrize('isotope',['na22','co60'])
def test_m2_all_origins_class_stream_roundtrip(tmp_path,isotope):
    """Keep per-contribution origin through shuffling, acquisition and reload."""
    import copy
    from test_module2_physics import libraries,ROOT
    from backend.m1_store import ApplicationStore
    from backend.m2_engine import PulseManager
    from backend.streams import FRAME
    paths=libraries(tmp_path,isotope,30)
    for name in paths:
        path=__import__('pathlib').Path(name);data=path.read_bytes()
        size=12+struct.unpack_from('<I',data,8)[0];output=bytearray(data[:size]);offset=size
        while offset<len(data):
            tag,n,crc=FRAME.unpack_from(data,offset);payload=bytearray(data[offset+12:offset+12+n]);offset+=12+n
            if tag==b'APLS':
                event_id,a,b=struct.unpack_from('<QII',payload);code=event_id%3+1
                start=16+32*(a+b)
                for i in range(a+b):payload[start+2*i]=1 if code==1 else 2 if code==2 else 1+i%2
            elif tag==b'EVNT':
                code=struct.unpack_from('<Q',payload)[0]%3+1
                for d in range(2):
                    pos=PREFIX.size+d*DETECTOR.size;flag=struct.unpack_from('<I',payload,pos)[0]
                    struct.pack_into('<I',payload,pos,(flag&~48)|(code<<4))
            output.extend(frame(tag,payload))
        path.write_bytes(output);assert validate_complete(path)['pulse_origin_counts']==[[0,10,10,10]]*2
    store=ApplicationStore(tmp_path/'state',ROOT/'seed/factory_catalogue.json');manager=PulseManager()
    try:
        p=copy.deepcopy(store.module2);p.update(input_paths=paths,auto_seed=False,waveform_pairs=30,output_mode='classes',threads=2)
        p['acquisition']['trigger']='either';p['activity_Bq']=1e7
        manager.create(store,p);manager.thread.join(30);result=manager.current()
        assert result['status']=='completed',result['message'];assert result['waveforms']>0
        before=manager.analysis.query({});wave=manager.analysis.waveform(0)
        manager.import_streams(store,result['paths']);manager.thread.join(30)
        assert manager.current()['status']=='completed';assert manager.analysis.query({})['counts']==before['counts']
        assert manager.analysis.waveform(0)==wave
        seen=set()
        for i in range(result['waveforms']):
            row=manager.analysis.waveform(i)
            for pulse in row['pulses']+row['timeline']['pulses']:
                expected=('scintillation','cherenkov','mixed')[pulse['record']%3]
                assert pulse['light_origin']==expected;seen.add(expected)
        assert seen=={'scintillation','cherenkov','mixed'}
    finally:manager.shutdown();store.close()
