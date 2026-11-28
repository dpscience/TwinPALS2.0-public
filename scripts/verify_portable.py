# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Run the shipped CMD from a displaced copy with development paths removed."""
from __future__ import annotations
import hashlib
import argparse
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CLIENT_TOKEN=""


def request(base,path,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(base+path,data=data,headers={"X-TwinPALS-Client":CLIENT_TOKEN,**({"Content-Type":"application/json"} if data else {})})
    with urllib.request.urlopen(req,timeout=30) as response:
        return json.loads(response.read())


def port_open(port):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as connection:
        connection.settimeout(.25)
        return connection.connect_ex(("127.0.0.1",port))==0


def require_closed_port(port,timeout=15):
    deadline=time.monotonic()+timeout
    while port_open(port):
        if time.monotonic()>=deadline:
            raise RuntimeError(f"Portable-test server port {port} remains open after stopping its owned process tree")
        time.sleep(.1)


def verify_used_folder(target,command,env,base,port,initial_entries,initial_components):
    """Exercise the shipped EXE after a real run, not just an empty data folder."""
    global CLIENT_TOKEN
    state_path=target/'data/app-state.json'
    valid=json.loads(state_path.read_text(encoding='utf-8'))
    legacy=json.loads(json.dumps(valid));legacy['version']=1;legacy['modules']['module1']['version']=4
    legacy['ui']['selection']['bins']=80
    old_bytes=json.dumps(legacy,indent=2).encode('utf-8')+b'\r\n'
    stream_hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file() and p.suffix in ('.tpstream','.tppulses')}
    results=[];keep_state=None;archives={}
    for name,payload,recovered in [('old_format',old_bytes,True),('current_format',None,False),('damaged_json',b'{"format":',True)]:
        require_closed_port(port)
        if payload is not None:state_path.write_bytes(payload)
        original=state_path.read_bytes()
        with (target/f'portable-restart-{name}.log').open('wb') as log:
            process=subprocess.Popen(command,cwd=ROOT/'tmp',env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            connection=None
            try:
                deadline=time.monotonic()+45
                while True:
                    try:health=request(base,'/api/health');break
                    except (urllib.error.URLError,TimeoutError):
                        if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError(f'Packaged restart failed: {name}')
                        time.sleep(.15)
                connection=urllib.request.urlopen(base+'/api/client/connect',timeout=30)
                while True:
                    line=connection.readline()
                    if line.startswith(b'data: '):
                        lease=json.loads(line[6:]);assert lease['type']=='ready';CLIENT_TOKEN=lease['token'];break
                state=request(base,'/api/m1/state')
                assert state['entries']==initial_entries
                assert request(base,'/api/m2/components')['entries']==initial_components
                assert {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in stream_hashes}==stream_hashes
                for path,content in archives.items():assert path.read_bytes()==content
                notice=state['startup_notice']
                if recovered:
                    assert notice and state['ui']['tab']=='setup' and state['ui']['selection']['bins']==120
                    assert state['profile']['source']=='na22' and state['profile']['version']==8
                    backup=Path(notice['backup_path']);assert backup.parent==state_path.parent and backup.read_bytes()==original
                    archives[backup]=original
                    assert json.loads(state_path.read_bytes())['version']==4
                else:
                    assert notice is None and state_path.read_bytes()==original
                    assert (state['profile'],state['module2'],state['module3'],state['ui'])==keep_state
                if name=='old_format':
                    state['profile']['detectors'][0]['distance_mm']=45
                    state['ui']['selection']['bins']=173
                    state['ui']['dialog_paths']={'open_profile':'C:/retained-path/Example.tpm1'}
                    state['module3']['preview_count']=17
                    request(base,'/api/session',dict(profile=state['profile'],module2=state['module2'],module3=state['module3'],ui=state['ui'],client_id='portable-restart',sequence=1))
                    keep_state=(state['profile'],state['module2'],state['module3'],state['ui'])
                assert len(list(state_path.parent.glob('app-state.backup-*.json')))==len(archives)
                results.append({'case':name,'status':'passed','backup_created':recovered,'original_sha256':hashlib.sha256(original).hexdigest(),'materials_and_streams_retained':True})
                request(base,'/api/client/close',{'token':CLIENT_TOKEN})
            finally:
                if connection is not None:connection.close()
                subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/taskkill.exe'),'/PID',str(process.pid),'/T','/F'],capture_output=True,check=False)
                process.wait(timeout=15);require_closed_port(port)
    return results


def main():
    global CLIENT_TOKEN
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=ROOT/"release")
    parser.add_argument("--report",type=Path,default=ROOT/"tmp/portable-validation.json")
    args=parser.parse_args()
    source=args.source.resolve()
    report_path=args.report.resolve()
    if not report_path.is_relative_to(ROOT.resolve()):
        raise ValueError("Portable evidence must be written inside the project directory")
    report_path.parent.mkdir(parents=True,exist_ok=True)
    source_manifest_sha256=hashlib.sha256((source/"release-manifest.json").read_bytes()).hexdigest()
    target=ROOT/"tmp"/("portable isolated copy "+uuid.uuid4().hex[:8])
    print("Copying complete portable folder:",target,flush=True)
    # Copy the complete owned application, not the user's mutable settings,
    # databases, streams or backups. The displaced EXE must seed its own data.
    from package_release import verify_folder, contained, MANIFEST
    manifest=verify_folder(source)
    target.mkdir(parents=True)
    for relative in [*manifest['files'],MANIFEST]:
        destination=contained(target,relative);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(contained(source,relative),destination)
    env={k:v for k,v in os.environ.items() if not (k.upper().startswith(("PYTHON","G4","GEANT4","TWINPALS")) or k.upper() in ("VIRTUAL_ENV","NODE_PATH"))}
    env["PATH"]=str(Path(os.environ["SystemRoot"])/"System32")
    port=18623
    base=f"http://127.0.0.1:{port}"
    if port_open(port):
        raise RuntimeError("Portable test port is already occupied; no process stopped")
    report_path.write_text(json.dumps({"status":"running","source_release_manifest_sha256":source_manifest_sha256},indent=2),encoding="utf-8")
    log_path=target/"portable-launch.log"
    command=f'"{Path(os.environ["SystemRoot"])/"System32/cmd.exe"}" /d /s /c ""{target / "Start-TwinPALS.cmd"}" --port {port} --no-browser"'
    with log_path.open("wb") as log:
        process=subprocess.Popen(command,cwd=ROOT/"tmp",env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            health=None
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                try:
                    health=request(base,"/api/health")
                    break
                except (urllib.error.URLError,TimeoutError):
                    if process.poll() is not None:
                        raise RuntimeError(log_path.read_text(errors="replace"))
                    time.sleep(.25)
            assert health and health["engine"]["available"],(health,log_path.read_text(errors="replace"))
            assert Path(health["engine"]["path"]).resolve().is_relative_to(target.resolve()),health
            page=urllib.request.urlopen(base,timeout=20).read()
            assert b"<title>TwinPALS" in page,page[:300]
            assert health["engine"]["multithreaded"] is True
            assert health["engine"]["worker_version"] == health["version"]
            worker_metadata=json.loads(subprocess.check_output([health["engine"]["path"],"--version"],env=env,timeout=10))
            assert worker_metadata['stream_version']==7,worker_metadata
            connection=urllib.request.urlopen(base+'/api/client/connect',timeout=30)
            while True:
                line=connection.readline()
                if line.startswith(b'data: '):
                    lease=json.loads(line[6:]);assert lease['type']=='ready';CLIENT_TOKEN=lease['token'];break
            try:
                urllib.request.urlopen(base+'/api/m1/state',timeout=10)
                raise AssertionError('Unauthenticated client was accepted')
            except urllib.error.HTTPError as exc:assert exc.code==423
            state=request(base,"/api/m1/state")
            assert Path(state['database_path']).resolve()==target/'data/catalogue.tpdb'
            assert len(state['entries'])==len(json.loads((target/'seed/factory_catalogue.json').read_text(encoding='utf-8'))['items']) and 'entries' not in state['profile']
            catalogue={entry['id']:entry for entry in state['entries']}
            assert 'labr3-ce' not in catalogue
            assert catalogue['cebr3']['properties']['absorption_length_mm']==1000000
            assert not any(c['name']=='absorption_length' for c in catalogue['cebr3']['curves'])
            assert any('assumed' in ref.get('comment','').lower() and 'absorption_length' in ref.get('properties',[])
                       for ref in catalogue['cebr3']['provenance']['references'])
            assert len(request(base,'/api/materials/standards')['items'])==309
            if catalogue['bc422q-05']['builtin']:
                assert catalogue['bc422q-05']['properties']['light_yield_per_MeV']==2900
                assert 'O' in catalogue['bc422q-05']['properties']['composition']
            if catalogue['ej232q-05']['builtin']:
                loss=next(c for c in catalogue['ej232q-05']['curves'] if c['name']=='absorption_length')
                assert all(y==100 for x,y in loss['points'])
            assert Path(state["folder"]).resolve().is_relative_to(target.resolve())
            import copy
            import sys
            sys.path.insert(0,str(ROOT))
            from backend.streams import analyze, validate_complete, inspect_stream
            initial_components=request(base,'/api/m2/components')['entries']
            runs=[];pulse_runs=[];lifetime_runs=[]
            native_threads=min(4,health["engine"]["cpu_count"])
            for isotope in ("na22","co60"):
                profile=copy.deepcopy(state["profile"])
                profile.update(name="Portable release validation "+isotope,source=isotope)
                names=["1275","511"] if isotope=="na22" else ["1173","1332"]
                # A deterministic, close-detector transport fixture supplies real
                # photoelectron pulses; 100 distant, auto-seeded events can all
                # stay below the smoke test's trigger threshold.
                for detector in profile['detectors']:detector['distance_mm']=2
                profile["run"].update(events=1000,secondary_events=1000,threads=4,seed=73125,auto_seed=False,
                    output_paths=["runs/portable_"+isotope+"_"+name+".tpstream" for name in names],trajectory_sample_limit=2)
                validation=request(base,"/api/m1/validate",{"profile":profile})
                assert validation["valid"],validation
                run=request(base,"/api/m1/runs",{"profile":profile})
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    run=request(base,"/api/m1/runs/current")
                    if run["status"] not in ("running","queued"): break
                    time.sleep(.2)
                assert run["status"]=="completed",run["message"]
                assert run["completed"]==run["total"]==2000
                assert run["threads"]==native_threads
                paths=[stream["path"] for stream in run["streams"]]
                for path in paths:
                    assert Path(path).resolve().is_relative_to(target.resolve())
                    completion=validate_complete(path)
                    assert completion["events"]==1000 and completion["status"]=="completed"
                    header=inspect_stream(path)["header"]
                    assert header["native"]["threads"]==native_threads
                    assert header["native"]["worker_version"]==health["version"]
                    assert header["profile"]["source"]==isotope
                    assert "entries" not in header["profile"]
                query={"paths":paths,"metric":"energy","detector":"all","primary":"all","bins":80}
                analysis=request(base,"/api/m1/analysis",query)
                until=time.monotonic()+20
                while analysis["loading"] and time.monotonic()<until:
                    time.sleep(.05);analysis=request(base,"/api/m1/analysis",query)
                independent=analyze(paths,query)
                assert analysis["complete"] and analysis["total_events"]==2000
                assert analysis["series"]==independent["series"]
                assert len(analysis["series"])==4
                assert all(series["events"]==sum(series["counts"])==1000 for series in analysis["series"])
                numeric={**query,"format":"csv"}
                req=urllib.request.Request(base+"/api/m1/analysis/export",data=json.dumps(numeric).encode(),headers={"Content-Type":"application/json","X-TwinPALS-Client":CLIENT_TOKEN})
                with urllib.request.urlopen(req,timeout=30) as response: csv_data=response.read()
                assert b"bin_left,bin_right,count" in csv_data
                csv_path=target/("portable-"+isotope+"-energy.csv");csv_path.write_bytes(csv_data)
                saved=request(base,"/api/m1/profiles/save",{"profile":profile,"path":"profiles/portable-"+isotope+".tpm1"})
                inspected=request(base,"/api/m1/profiles/inspect",{"path":saved["path"]})
                assert inspected["profile"]==saved["profile"]
                assert Path(saved["path"]).resolve().is_relative_to(target.resolve())
                logs=Path(state["folder"])/".twinpals-runs"/run["id"]
                observed=[]
                for joblog in sorted(logs.glob("job-*.log")):
                    messages=[json.loads(line) for line in joblog.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
                    final=next(m for m in reversed(messages) if m.get("type")=="finished")
                    assert final["status"]=="completed" and final["threads_observed"]==native_threads
                    observed.append(final["worker_event_counts"])
                runs.append({"source":isotope,"events_per_stream":1000,"stream_event_records":2000,
                    "stream_sha256":[hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths],
                    "profile_sha256":hashlib.sha256(Path(saved["path"]).read_bytes()).hexdigest(),
                    "csv_sha256":hashlib.sha256(csv_data).hexdigest(),"worker_event_counts":observed,
                    "independent_stream_validation":"passed","analysis_matches_independent_reader":True})
                m2=copy.deepcopy(state['module2'])
                # A lower source activity leaves enough separated triggers after
                # device readout dead time within the finite Co-60 fixture.
                m2.update(input_paths=paths,activity_Bq=10000,waveform_pairs=20 if isotope=='na22' else 2,auto_seed=False,
                          output_path=f'runs/portable-{isotope}.tppulses')
                m2['acquisition']['trigger']='either'
                for channel in m2['channels']:channel['threshold_mV']=1
                check=request(base,'/api/m2/validate',{'profile':m2});assert check['valid'],check
                pulse=request(base,'/api/m2/runs',{'profile':m2})
                deadline=time.monotonic()+120
                while pulse['status'] in ('queued','loading','running') and time.monotonic()<deadline:
                    time.sleep(.1);pulse=request(base,'/api/m2/runs/current')
                assert pulse['status']=='completed' and pulse['waveforms']==m2['waveform_pairs'],pulse
                assert pulse['header']['isotope']==isotope
                assert sum(pulse['counts'].values())==pulse['waveforms']
                features=request(base,'/api/m2/analysis',{})
                imported=request(base,'/api/m2/analysis/open',{'paths':pulse['paths']})
                deadline=time.monotonic()+30
                while imported['status'] in ('queued','loading','running') and time.monotonic()<deadline:
                    time.sleep(.1);imported=request(base,'/api/m2/runs/current')
                assert imported['status']=='completed'
                assert request(base,'/api/m2/analysis',{})==features
                saved_m2=request(base,'/api/m2/profiles/save',{'profile':m2,'path':f'profiles/portable-{isotope}.tpm2'})
                assert request(base,'/api/m2/profiles/inspect',{'path':saved_m2['path']})['profile']==m2
                pulse_runs.append({'isotope':isotope,'target_pairs':m2['waveform_pairs'],'waveforms':pulse['waveforms'],
                                   'counts':pulse['counts'],'stream_sha256':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in pulse['paths']],
                                   'reimport_analysis':'identical','settings_roundtrip':'passed'})
                m3=copy.deepcopy(state['module3'])
                m3.update(input_paths=pulse['paths'],workers=2,preview_count=7)
                for channel in m3['channels']:
                    channel.update(minimum_height_mV=1,reject_clipped=False)
                    channel['start']['phs']={'low':400,'high':500}
                    channel['stop']['phs']={'low':1,'high':400}
                assert request(base,'/api/m3/check',m3)['valid']
                lifetime=request(base,'/api/m3/start',m3)
                deadline=time.monotonic()+60
                while lifetime['status'] in ('running','loading','queued') and time.monotonic()<deadline:
                    time.sleep(.1);lifetime=request(base,'/api/m3/state')['job']
                assert lifetime['status']=='completed',lifetime
                assert lifetime['processed']==pulse['waveforms'] and len(lifetime['preview'])<=7,lifetime
                view={'bin_ps':5,'zero_ps':0,'low_ns':-100,'high_ns':100,'category':'all','origin':'all','scatter':'all'}
                spectra=request(base,'/api/m3/query',view)
                assert spectra['processed']==pulse['waveforms']
                changed=request(base,'/api/m3/query',{**view,'bin_ps':20,'zero_ps':25})
                assert changed['accepted']==spectra['accepted']
                settings={'format':'twinpals-lifetime-settings','version':1,'processing':m3,'display':view}
                saved_m3=request(base,'/api/m3/settings/save',{'path':f'profiles/portable-{isotope}.tpm3','settings':settings})
                from backend.m3_models import Settings
                assert request(base,'/api/m3/settings/open',{'path':saved_m3['path']})==Settings.model_validate(settings).model_dump(mode='json')
                request(base,'/api/m3/reset',{})
                assert request(base,'/api/m3/query',view)['processed']==0
                lifetime_runs.append({'isotope':isotope,'processed_pairs':lifetime['processed'],'accepted_pairs':spectra['accepted'],
                    'parallel_workers':2,'bounded_preview':len(lifetime['preview']),'settings_roundtrip':'passed','live_rebin_and_zero':'passed','reset':'passed'})
            request(base,'/api/session',{'module2':m2,'module3':m3,'profile':profile,'ui':state['ui'],'client_id':'portable','sequence':1})
            assert json.loads((target/'data/app-state.json').read_text(encoding='utf-8'))['modules']['module1']['source']=='co60'
            app_export=request(base,'/api/profile/export',{'path':'profiles/portable.tpprofile'})
            app_data=json.loads(Path(app_export['path']).read_text(encoding='utf-8'))
            preview=request(base,'/api/profile/preview',{'path':app_export['path']})
            loaded=request(base,'/api/profile/import',{'path':app_export['path'],'sha256':preview['sha256'],'confirmed':True})
            assert loaded['profile']==app_data['modules']['module1'] and loaded['ui']==app_data['ui'] and loaded['module2']==app_data['modules']['module2']
            assert loaded['module3']==app_data['modules']['module3']
            material_export=request(base,'/api/materials/export',{'path':'profiles/portable.tpcatalogue'})
            material_data=json.loads(Path(material_export['path']).read_text(encoding='utf-8'))
            material_preview=request(base,'/api/materials/import/preview',{'path':material_export['path']})
            assert len(material_preview['unchanged'])==len(material_data['entries'])==len(state['entries'])
            assert not material_preview['added'] and not material_preview['conflicts']
            request(base,'/api/client/close',{'token':CLIENT_TOKEN});connection.close()
            body=log_path.read_text(errors="replace")
            assert base in body,"Launcher did not print its actual address"
            result={"status":"passed","application_version":health["version"],"engine":health["engine"],
                "copied_folder":str(target),"launcher":"Start-TwinPALS.cmd","port":port,"sanitized_path":env["PATH"],
                "python_node_geant4_env_removed":True,"runs":runs,"pulse_runs":pulse_runs,"lifetime_runs":lifetime_runs,"events":4000,"sources":["na22","co60"],
                "profile_exchange":"passed","material_exchange_preview":"passed","factory_entries":len(state['entries']),"standard_materials":309,"event_schema_version":7,"printed_url":base,"independent_stream_validation":"passed",
                "execution":"real Geant4; Na independent pools, Co correlated projections; selected gamma transport",
                "native_threads":native_threads,"source_release_manifest_sha256":source_manifest_sha256,"worker_stream_version":worker_metadata['stream_version'],
                "packaged_server_sha256":hashlib.sha256((target/"TwinPALS.exe").read_bytes()).hexdigest(),
                "packaged_worker_sha256":hashlib.sha256(Path(health["engine"]["path"]).read_bytes()).hexdigest()}
        finally:
            # Stop only the process tree created by this test; never a pre-existing listener.
            subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/taskkill.exe"),"/PID",str(process.pid),"/T","/F"],capture_output=True,check=False)
            process.wait(timeout=15)
            require_closed_port(port)
    result['private_state_restarts']=verify_used_folder(target,command,env,base,port,state['entries'],initial_components)
    result["server_stopped"]=True
    result["port_closed_after_stop"]=True
    report_path.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":
    main()
