// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import LegalNotices from './LegalNotices';
import ReleaseUpdates from './ReleaseUpdates';
import {outcomeProgress} from './processingProgress';
import {percent} from './api';
import {ImportWorkers} from './ImportWorkers';
import {analysisMetricsFor} from './analysisModel';
import {mergeRunUpdate} from './runUpdates';
import type {RunUpdate} from './runUpdates';
import {lockBackground} from './modalInert';
import {restoreSessionViews} from './sessionRestore';
import {SessionBadges} from './SessionBadges';
import Module2 from './Module2';
import Module3 from './Module3';
import {lifetimeActive} from './m3types';
import type {LifetimeProfile,LifetimeJob} from './m3types';
import {pulseActive} from './m2types';
import type {PulseProfile,PulseJob} from './m2types';
import {useConfirm} from './Confirm';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {AlertTriangle,Check,CircleHelp,Database,FileDown,FileUp,FolderOpen,Play,Save,X} from 'lucide-react';
import {api,connectClient,number} from './api';
import type {Entry} from './types';
import type {Analysis,AnalysisSelection,ImportedSession,ImportProgress,M1Run,Profile,State} from './m1types';
import {Field,Help} from './Fields';
import Setup,{EntrySelector} from './Setup';
import Scene,{assemblySnapshot} from './Scene';
import Simulation,{active,roleNames,roleColors,sections} from './Simulation';
import AnalysisView from './AnalysisView';
import MaterialDatabase from './MaterialDatabase';
import {ProfileExchange} from './ProfileExchange';
import {Modal} from './Modal';
import {makePlot,metricNames} from './analysisModel';
import {cathodeLayer,persistenceLayer} from './reportDensity';
import type {ReportPlot,DensityLayer} from './reportDensity';
import type {CathodeData} from './CathodeMap';
import type {PersistenceData} from './PersistencePlot';
import {exportReport} from './report';
import {usePreferences,usePreference} from './Preferences';
import {useAutosave} from './useAutosave';
export {metricNames,metricHelp,makePlot} from './analysisModel';
const err=(e:unknown)=>e instanceof Error?e.message:String(e);

type Validation={key:string;valid:boolean;errors:string[];warnings?:string[]};
export default function App(){
 const [connection,setConnection]=useState<'connecting'|'ready'|'busy'|'disconnected'>('connecting'),[attempt,setAttempt]=useState(0);
 useEffect(()=>{setConnection('connecting');return connectClient(setConnection);},[attempt]);
 if(connection==='ready')return <Workbench key={attempt}/>;
 return <div className="loading-screen"><strong>TwinPALS 2.0</strong>{connection==='connecting'?<p>Connecting…</p>:<><h2>{connection==='busy'?'TwinPALS is already open':'Connection closed'}</h2><p>{connection==='busy'?'Only one window can use this application. Close the active TwinPALS window, then reconnect here.':'Check that the TwinPALS server is running, then reconnect.'}</p><button onClick={()=>setAttempt(v=>v+1)}>Reconnect</button></>}</div>;
}
function validationText(errors:string[],warnings:string[]){
 return [...errors,...warnings].map(message=>{const match=message.match(/^(Detector [AB]) → (.*)$/);const title=match?match[1]:errors.includes(message)?'Correction needed':'Setup note';const body=match?match[2]:message;return title+'\n'+body.split(/(?<=\.) (?=[A-Z])/).map(s=>'- '+s).join('\n');}).join('\n\n');
}
function Workbench(){
 const confirm=useConfirm();
 useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 const prefs=usePreferences();
 const [state,setState]=useState<State|null>(null),[profile,setProfile]=useState<Profile|null>(null),[run,setRun]=useState<M1Run|null>(null);
 const [module,setModule]=usePreference('module'),[tab,setTab]=usePreference('tab'),[section,setSection]=usePreference('section');
 const [selection,setSelection]=usePreference('selection'),[analysisPaths,setAnalysisPaths]=usePreference('analysis_paths');
 const [paths,setPaths]=usePreference('dialog_paths');
 const [materialDirty,setMaterialDirty]=useState(false);
 const [lifetimeProfile,setLifetimeProfile]=useState<LifetimeProfile|null>(null),[lifetimeJob,setLifetimeJob]=useState<LifetimeJob|null>(null),[lifetimeBusy,setLifetimeBusy]=useState(false);
 const [pulseProfile,setPulseProfile]=useState<PulseProfile|null>(null),[pulseJob,setPulseJob]=useState<PulseJob|null>(null),[pulseBusy,setPulseBusy]=useState(false);
 const [profileDialog,setProfileDialog]=useState<'load'|'save'|null>(null);
 const [profileEpoch,setProfileEpoch]=useState(0);
 const [startupNotice,setStartupNotice]=useState<State['startup_notice']>(null);
 const leaveMaterial=async()=>!(materialDirty)||await confirm('Discard unsaved database changes?');
 const navigateTab=async(value:string)=>{if(value===tab||await leaveMaterial())setTab(value);};
 const navigateModule=async(value:number)=>{if(value===module||await leaveMaterial())setModule(value);};
 const [busy,setBusy]=useState(false),[checking,setChecking]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [dialog,setDialog]=useState<'load'|'save'|'streams'|null>(null),[dialogError,setDialogError]=useState(''),[profilePath,setProfilePath]=useState(''),[streamPaths,setStreamPaths]=useState(['','']);
 const actionPending=useRef(false);
 const showDialog=(value:typeof dialog)=>{setDialogError('');setDialog(value);};
 const closeDialog=()=>{if(!actionPending.current)showDialog(null);};
 const [importWorkers,setImportWorkers]=useState(0);
 const [imported,setImported]=useState<ImportedSession|null>(null),[importProgress,setImportProgress]=useState<ImportProgress|null>(null),[importActive,setImportActive]=useState(false);
 const [analyses,setAnalyses]=useState<Analysis[]>([]),[analysisLoading,setAnalysisLoading]=useState(false),[analysisError,setAnalysisError]=useState('');
 const [plottedSelection,setPlottedSelection]=useState(selection),[validation,setValidation]=useState<Validation|null>(null);
 const analysisCache=useRef(new Map<string,Analysis[]>());
 const analysisAbort=useRef<AbortController|null>(null),lastRun=useRef<{id:string;status:string}|null>(null);
 const autosave=useAutosave(profile,prefs.values,pulseProfile,lifetimeProfile);
 const fileLocked=busy||active(run)||importActive;
 const sharedLocked=fileLocked||pulseActive(pulseJob)||pulseBusy||lifetimeActive(lifetimeJob)||lifetimeBusy;
 const entries=state?.entries??[];
 const draftKey=JSON.stringify([profile,state?.database_revision]);
 const checked=validation?.key===draftKey?validation:null;
 const act=async(fn:()=>Promise<void>)=>{if(actionPending.current)return;actionPending.current=true;const scope=dialog;setBusy(true);if(scope)setDialogError('');else setError('');try{await fn();}catch(e){if(scope)setDialogError(err(e));else setError(err(e));}finally{actionPending.current=false;setBusy(false);}};
 const patch=(change:Partial<Profile>)=>{setProfile(p=>p?{...p,...change}:p);setValidation(null);};
 const browseFile=async(kind:string,initial?:string)=>{const result=await api<{path:string|null}>('/m1/browse',{method:'POST',body:JSON.stringify({kind,initial:initial||paths[kind]})});if(result.path){setPaths(p=>({...p,[kind]:result.path!}));setDialogError('');}return result.path;};
 const browse=async(kind:string,initial?:string)=>{try{return await browseFile(kind,initial);}catch(e){if(dialog)setDialogError(err(e));else setError(err(e));return null;}};
 useEffect(()=>{api<State>('/m1/state').then(s=>{prefs.restore(restoreSessionViews(s.ui,s.imported?.streams.map(v=>v.path)));setImported(s.imported??null);setImportProgress(s.imported?.progress??null);setImportActive(s.imported?.progress.loading??false);setState(s);setProfile(s.profile);setPulseProfile(s.module2);setLifetimeProfile(s.module3);setRun(s.run);setStartupNotice(s.startup_notice);}).catch(e=>setError(err(e)));},[]);
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),4500);return()=>clearTimeout(timer);},[notice]);
 useEffect(()=>{
  if(!active(run))return;let stopped=false,timer:ReturnType<typeof setTimeout>;
  let snapshot:RunUpdate|null=run;
  const poll=async()=>{try{
   const query=snapshot?.trajectory_revision!==undefined?`?preview_after=${snapshot.trajectory_revision}&preview_run=${encodeURIComponent(snapshot.id)}`:'';
   const next=await api<RunUpdate|null>('/m1/runs/current'+query);
   if(!stopped){try{snapshot=mergeRunUpdate(snapshot,next);}catch{snapshot=await api<RunUpdate|null>('/m1/runs/current');}if(!stopped)setRun(snapshot);}
  }catch(e){if(!stopped)setError(err(e));}finally{if(!stopped)timer=setTimeout(poll,350);}};
  timer=setTimeout(poll,350);return()=>{stopped=true;clearTimeout(timer);};
 },[run?.id,run?.status]);
 useEffect(()=>{const old=lastRun.current;if(run&&old?.id===run.id&&old.status!==run.status){if(run.status==='failed')setError(`Module 1 simulation failed.\n\n${run.message}`);else if(run.status==='completed')setNotice(`Module 1 completed · ${number(run.completed)} records`);else if(run.status==='cancelled')setNotice('Module 1 stopped.');}lastRun.current=run?{id:run.id,status:run.status}:null;},[run?.id,run?.status]);
 useEffect(()=>{if(run)prefs.set('last_session_paths',run.streams.map(s=>s.path));},[JSON.stringify(run?.streams.map(s=>s.path))]);
 useEffect(()=>{if(!pulseActive(pulseJob))return;let stopped=false,timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const next=await api<PulseJob|null>('/m2/runs/current');if(!stopped){setPulseJob(next);if(next&&!pulseActive(next))setNotice(next.status==='failed'?'Module 2 failed · '+next.message:`Module 2 ${next.status} · ${number(next.waveforms)} waveform pairs`);}}catch(e){if(!stopped)setNotice('Module 2 monitoring: '+err(e));}finally{if(!stopped)timer=setTimeout(poll,400);}};timer=setTimeout(poll,400);return()=>{stopped=true;clearTimeout(timer);};},[pulseJob?.id,pulseJob?.status]);
 const importKey=JSON.stringify(analysisPaths);
 useEffect(()=>{
  if(!state||!analysisPaths.length||active(run)||JSON.stringify(imported?.streams.map(s=>s.path))===importKey)return;
  let disposed=false;setImportActive(true);setAnalysisError('');
  api<ImportedSession>('/m1/analysis/info',{method:'POST',body:JSON.stringify({paths:analysisPaths})}).then(info=>{if(!disposed){setImported(info);setImportProgress(info.progress);setImportActive(info.progress.loading);setAnalyses([]);analysisCache.current.clear();setAnalysisPaths(info.streams.map(s=>s.path));}}).catch(e=>{if(!disposed){setImportActive(false);setAnalysisError(err(e));setError(`Could not open streams.\n\n${err(e)}`);}});
  return()=>{disposed=true;};
 },[importKey,!!state,active(run),profileEpoch]);
 useEffect(()=>{
  if(!imported||!analysisPaths.length)return;let disposed=false,timer:ReturnType<typeof setTimeout>;
  const poll=async()=>{try{const next=await api<ImportProgress>('/m1/import/status');if(disposed||JSON.stringify(next.streams.map(s=>s.path))!==importKey)return;
   setImportProgress(next);setImportActive(next.loading);if(next.error){setAnalysisError(next.error);setError(`Stream import failed.\n\n${next.error}`);return;}
   if(next.loading||next.streams.some(s=>s.status==='incomplete'))timer=setTimeout(poll,400);
  }catch(e){if(!disposed){setImportActive(false);setAnalysisError(err(e));}}};
  void poll();return()=>{disposed=true;clearTimeout(timer);};
 },[imported,importKey]);
 const queryKey=JSON.stringify({analysisPaths,importReady:!!imported,run_id:run?.id,run_status:run?.status,records:(run?.completed??0)>0,selection,viewActive:tab==='analysis'||tab==='simulation'});
 const refreshAnalysis=useCallback(async(force=true)=>{
  if(tab!=='analysis'&&tab!=='simulation')return;
  if(analysisPaths.length&&!imported)return;
  if(!analysisPaths.length&&(!run||active(run)&&run.completed===0))return;
  if(!force&&analysisAbort.current&&!analysisAbort.current.signal.aborted)return;
  analysisAbort.current?.abort();const controller=new AbortController();analysisAbort.current=controller;const cacheKey=JSON.stringify([analysisPaths,run?.id,selection]);const cached=analysisCache.current.get(cacheKey);if(force){if(cached){setAnalyses(cached);setPlottedSelection(selection);}setAnalysisLoading(!cached);}setAnalysisError('');
  try{const data=await api<Analysis[]>('/m1/analysis/batch',{method:'POST',signal:controller.signal,body:JSON.stringify({...selection,basis:selection.basis??'anode',include_positions:false,metrics:analysisMetricsFor(selection),...(analysisPaths.length?{paths:analysisPaths}:{run_id:run!.id})})});if(!controller.signal.aborted&&analysisAbort.current===controller){setAnalyses(data);setPlottedSelection(selection);analysisCache.current.delete(cacheKey);analysisCache.current.set(cacheKey,data);while(analysisCache.current.size>24)analysisCache.current.delete(analysisCache.current.keys().next().value!);
   const alternate:AnalysisSelection={...selection,basis:selection.basis==='crystal'?'anode':'crystal',origin:'all'};
   const alternateKey=JSON.stringify([analysisPaths,run?.id,alternate]);
   setAnalysisLoading(false);
   try{const prepared=await api<Analysis[]>('/m1/analysis/batch',{method:'POST',signal:controller.signal,body:JSON.stringify({...alternate,include_positions:false,metrics:analysisMetricsFor(alternate),...(analysisPaths.length?{paths:analysisPaths}:{run_id:run!.id})})});
    if(!controller.signal.aborted)analysisCache.current.set(alternateKey,prepared);
   }catch{/* Background preparation never invalidates the visible result. */}
  }}
  catch(e){if(!controller.signal.aborted)setAnalysisError(err(e));}
  finally{if(analysisAbort.current===controller){analysisAbort.current=null;setAnalysisLoading(false);}}
 },[queryKey]);
 useEffect(()=>{const timer=setTimeout(()=>void refreshAnalysis(),25);return()=>{clearTimeout(timer);analysisAbort.current?.abort();};},[refreshAnalysis]);
 const following=analysisPaths.length>0&&!importProgress?.error&&(!importProgress||importProgress.loading||importProgress.streams.some(s=>s.status==='incomplete')||analyses.some(a=>a.loading));
 useEffect(()=>{if((tab!=='simulation'&&tab!=='analysis')||(!active(run)&&!following))return;const timer=setInterval(()=>void refreshAnalysis(false),800);return()=>clearInterval(timer);},[tab,run?.status,following,refreshAnalysis]);
 const validate=()=>act(async()=>{if(!profile)return;setChecking(true);try{const result=await api<{valid:boolean;errors:string[];warnings:string[]}>('/m1/validate',{method:'POST',body:JSON.stringify({profile})});setValidation({...result,key:draftKey});}finally{setChecking(false);}});
 const start=()=>act(async()=>{
  if(!profile)return;const validated=await api<{valid:boolean;errors:string[];warnings:string[]}>('/m1/validate',{method:'POST',body:JSON.stringify({profile})});setValidation({...validated,key:draftKey});if(!validated.valid)throw new Error(validated.errors.join('\n'));
  let started:M1Run;try{started=await api<M1Run>('/m1/runs',{method:'POST',body:JSON.stringify({profile,overwrite:false})});}catch(e){if(!/Output exists/i.test(err(e)))throw e;if(!await confirm(`Replace these output files and partial files?\n\n${profile.run.output_paths.join('\n')}`))return;started=await api<M1Run>('/m1/runs',{method:'POST',body:JSON.stringify({profile,overwrite:true})});}
  analysisAbort.current?.abort();prefs.set('scene_simulation',v=>({...v,camera:null}));setRun(started);setValidation({...validated,key:draftKey});setImported(null);setImportProgress(null);setImportActive(false);setAnalyses([]);analysisCache.current.clear();setAnalysisPaths([]);setAnalysisError('');setSelection(s=>({...s,primary:'all'}));setTab('simulation');
 });
 const stopImport=()=>void act(async()=>{const progress=await api<ImportProgress>('/m1/import/stop',{method:'POST'});setImportProgress(progress);setImportActive(progress.loading);setNotice('Stream reading stopped. Loaded events remain available.');});
 const stop=async()=>{if(run&&await confirm('Stop the simulation? Completed records remain available.'))void act(async()=>setRun(await api<M1Run>(`/m1/runs/${run.id}/stop`,{method:'POST'})));};
 const apply=async(value:Profile)=>{if(!await confirm('Apply these stream settings to Setup? The current Module 1 draft will be replaced.'))return;await act(async()=>{const result=await api<{profile:Profile}>('/m1/profiles/inspect',{method:'POST',body:JSON.stringify({profile:value})});setProfile(result.profile);setValidation(null);setTab('setup');setNotice('Module 1 settings applied.');});};
 const openStreams=()=>act(async()=>{
  if(fileLocked)return;const values=streamPaths.map(s=>s.trim()).filter(Boolean);if(!values.length)throw new Error('Choose at least one stream.');
  const info=await api<ImportedSession>('/m1/analysis/info',{method:'POST',body:JSON.stringify({paths:values,workers:importWorkers})});
  analysisAbort.current?.abort();prefs.set('scene_simulation',v=>({...v,camera:null}));setImported(info);setImportProgress(info.progress);setImportActive(info.progress.loading);setAnalysisPaths(info.streams.map(s=>s.path));prefs.set('last_session_paths',info.streams.map(s=>s.path));setSelection(s=>({...s,primary:'all'}));setAnalyses([]);analysisCache.current.clear();setAnalysisError('');setPaths(p=>({...p,open_stream:values[0],second_stream:values[1]??''}));setDialog(null);setTab('analysis');
 });
 const exportHTML=()=>act(async()=>{if(!analyses.length)return;
  const source=analysisPaths.length?{paths:analysisPaths}:{run_id:run!.id};
  const wanted=Object.keys(metricNames).filter(m=>!['cathode_map','persistence'].includes(m));const all:Analysis[]=[];
  for(const basis of ['crystal','anode'])for(let i=0;i<wanted.length;i+=8)all.push(...await api<Analysis[]>('/m1/analysis/batch',{method:'POST',body:JSON.stringify({...selection,basis,origin:selection.origin==='none'&&basis==='anode'?'all':selection.origin,...source,include_positions:false,metrics:wanted.slice(i,i+8)})}));
  const maps:DensityLayer[]=[],persistence:DensityLayer[]=[];
  for(const detector of ['A','B'])for(const primary of ['all',...roles]){
   const request={method:'POST',body:JSON.stringify({...source,bins:selection.bins,detector,primary})};
   const label=`Detector ${detector} · ${primary==='all'?'All primaries':roleNames[primary]}`;
   maps.push(cathodeLayer(await api<CathodeData>('/m1/cathode-map',request),label));
   for(const origin of ['all','scintillation','cherenkov','mixed'])persistence.push(persistenceLayer(await api<PersistenceData>('/m1/persistence',{...request,body:JSON.stringify({...source,bins:selection.bins,detector,primary,origin})}),`${label} · ${origin==='all'?'All origins':origin[0].toUpperCase()+origin.slice(1)}`));
  }
  const reportPlots:ReportPlot[]=[...all.filter(a=>a.available!==false).map(a=>({...makePlot(a,{...selection,basis:a.basis}),title:`${a.basis==='crystal'?'Crystal':'Anode'} · ${metricNames[a.metric]}`})),{title:'Cathode map',xLabel:'Local X (mm)',yLabel:'Local Y (mm)',series:[],density:maps,note:'QE-accepted hits from all events. Response cuts do not apply to spatial maps.'},{title:'Pulse persistence',xLabel:'Time after gamma emission (ns)',yLabel:'|I| / charge (1/ns)',series:[],density:persistence,note:'Each nonempty analog pulse has unit area. No time alignment; zero baseline omitted. Response cuts do not apply.'}];
  const recorded=all[0],header=recorded.streams[0]?.header;
  const image=assemblySnapshot(recorded.profile,(header?.pmt_snapshot as Entry[]|undefined)??[]);
  exportReport(all[0].profile,reportPlots,{created_at:new Date().toISOString(),selection,streams:all[0].streams,complete:all.every(a=>a.complete),total_events:all[0].total_events},image?{title:'Detector assembly',alt:'Isometric view of the recorded detector assembly with channels A and B',src:image}:undefined);
 });
 const entrySelector=(label:string,id:string,category:Entry['category'],onChange:(id:string)=>void)=><EntrySelector label={label} id={id} category={category} entries={entries} onChange={onChange}/>;
 const roles=analysisPaths.length?imported?.roles??[]:run?.streams.map(s=>s.role)??[];
 const badges=analysisPaths.length?(imported?.streams.map(s=>({path:s.path,role:String(s.header.role)}))??[]):run?.streams??[];
 const plots=useMemo(()=>analyses.map(a=>makePlot(a,plottedSelection)),[analyses,plottedSelection]);
 const streamsDialog=()=>{setStreamPaths([paths.open_stream??'',paths.second_stream??'']);showDialog('streams');};
 const databaseChanged=(result:{entries:Entry[];revision:number})=>{setState(s=>s?{...s,entries:result.entries,database_revision:result.revision}:s);setValidation(null);};
 if(!state||!profile||!pulseProfile||!lifetimeProfile)return <div className="loading-screen"><strong>TwinPALS</strong>{error?<><p role="alert">{error}</p><button onClick={()=>location.reload()}>Retry</button></>:<p>Opening application…</p>}</div>;
 const progress=run&&run.total?run.completed/run.total:0;
 const summaryStreams=analysisPaths.length?(importProgress?.streams.map(s=>({role:s.role,path:s.path,completed:s.completed,expected_events:s.expected_events,status:s.status,outcomes:s.outcomes}))??[]):run?.streams??[];
 const phase=active(run)&&!analysisPaths.length?'Live':importActive?'Reading':analysisPaths.length?importProgress?.streams.some(s=>s.status==='incomplete')?'Partial':importProgress?.error?'Failed':'':run?.status==='cancelled'?'Stopped':run?.status==='failed'?'Failed':'';
 const phaseProgress=phase==='Live'?outcomeProgress(summaryStreams,run?.total??0):phase==='Reading'?100*(importProgress?.loaded_bytes??0)/Math.max(1,importProgress?.total_bytes??0):undefined;
 return <div className="application">
  <header className="app-header"><span className="brand"><img className="product-icon" src="/favicon.svg" width="24" height="24" alt=""/>TwinPALS <b>2.0</b></span><nav className="modules" aria-label="Modules">{[1,2,3].map(n=><button key={n} className={module===n?'active':''} onClick={()=>navigateModule(n)} title={["Photon transport and material setup","Generate sampled detector pulses from Module 1 streams","Extract CF times, apply waveform filters and build lifetime spectra"][n-1]}>Module {n} | {["Detector response","Digitizer acquisition","Lifetime spectrum"][n-1]}</button>)}<button className={module===4?'active database-top':'database-top'} title="Materials, complete photomultipliers and digitizers for all modules" onClick={()=>navigateModule(4)}><Database size={14}/>Database</button></nav>{(active(run)||importActive)&&<button title={importActive?"Open monitoring for the Module 1 stream import":"Open monitoring for the active Module 1 simulation"} className="module-run-badge" onClick={async()=>{if(await leaveMaterial()){setModule(1);setTab('simulation');}}}><span className="spinner"/>M1 · {importActive?`Reading ${percent(100*(importProgress?.loaded_bytes??0)/Math.max(1,importProgress?.total_bytes??0))}`:percent(100*progress)}</button>}{pulseActive(pulseJob)&&<button title="Open monitoring for the active Module 2 job" className="module-run-badge" onClick={async()=>{if(await leaveMaterial()){setModule(2);prefs.set('module2',v=>({...v,tab:'simulation'}));}}}><span className="spinner"/>M2 · {pulseJob?.status==='loading'?`Reading ${percent(100*(pulseJob.kind==='import'?pulseJob.progress:pulseJob.input_progress??0))}`:percent(100*(pulseJob?.progress??0))}</button>}{lifetimeActive(lifetimeJob)&&<button className="module-run-badge" title="Show Module 3 acquisition" onClick={()=>{setModule(3);prefs.set('module3',v=>({...v,tab:'analysis'}));}}><span className="spinner"/>M3 · {percent(100*(lifetimeJob?.progress??0))}</button>}<div className="global-profile"><button disabled={sharedLocked} title="Load a saved application profile, including setup and view preferences" onClick={async()=>{if(await leaveMaterial())setProfileDialog('load');}}><FileUp size={13}/>Load profile</button><button disabled={sharedLocked} title="Save all module setups, view preferences and dialog paths to a profile file" onClick={()=>setProfileDialog('save')}><Save size={13}/>Save profile</button></div></header>
  <Module2 key={profileEpoch} autoWorkers={state.health.recommended_threads??1} cpuCount={state.health.cpu_count??1} visible={module===2} catalogueRevision={state.database_revision} profile={pulseProfile} setProfile={setPulseProfile} job={pulseJob} setJob={setPulseJob} browse={browseFile} onBusy={setPulseBusy}/>
  <Module3 key={profileEpoch} visible={module===3} cpuCount={state.health.cpu_count??1} autoWorkers={state.health.recommended_threads??1} profile={lifetimeProfile} setProfile={setLifetimeProfile} job={lifetimeJob} setJob={setLifetimeJob} browse={browseFile} onBusy={setLifetimeBusy}/>
  {module===1?<>
   <div className="workspace-bar">
    <nav className="tabs" aria-label="Module 1 views">{['setup','simulation','analysis'].map(t=><button key={t} className={`${t==='materials'?'materials-tab ':''}${tab===t?'active':''}`} onClick={()=>navigateTab(t)}>{t==='materials'?<><Database size={13}/>Material database</>:t[0].toUpperCase()+t.slice(1)}</button>)}</nav>
    {tab!=='materials'&&<SessionBadges origin={analysisPaths.length?'Imported':'Simulation'} streams={badges.map(s=>({key:s.role,label:roleNames[s.role],path:s.path,color:roleColors[s.role]}))}/>}
    <div className="workspace-actions">{importActive&&tab!=='simulation'&&<button className="danger" title="Stop reading streams; keep already loaded events" disabled={busy} onClick={stopImport}>{busy&&<span className="spinner"/>}Stop reading</button>}{tab==='setup'?<>
     <div className="geometry-check"><button data-state={checking?'checking':checked?checked.valid?'valid':'invalid':'unchecked'} disabled={busy||!state.health.engine.available} onClick={()=>void validate()} title={checked?'Check the current geometry again':'Check geometry and review any corrections or optical advice'}>{checking?<span className="spinner"/>:checked?checked.valid?<Check size={14}/>:<AlertTriangle size={14}/>:<CircleHelp size={14}/>}<span>{checking?'Checking…':checked?checked.valid?'Geometry valid':'Geometry error':'Check geometry'}</span></button>{checked&&(!checked.valid||!!checked.warnings?.length)&&<Help label={!checked.valid?`${checked.errors.length} issue${checked.errors.length===1?'':'s'}`:`${checked.warnings?.length} note${checked.warnings?.length===1?'':'s'}`} text={validationText(checked.errors,checked.warnings??[])}/>}</div>
     <button title="Start a run with a snapshot of the current Module 1 setup" className="primary" disabled={fileLocked||!state.health.engine.available} onClick={()=>void start()}>{active(run)?<><span className="spinner"/>{run?.status==='stopping'?'Stopping…':'Running'} · {percent(100*progress)}</>:<><Play size={14}/>Run simulation</>}</button>
    </>:tab==='analysis'?<><button title="Open binary event streams for simulation review and analysis" disabled={fileLocked} onClick={streamsDialog}><FolderOpen size={14}/>Open streams</button><button title="Save the recorded detector assembly, histograms, cathode maps, pulse persistence and Module 1 settings" disabled={fileLocked||analysisLoading||!analyses.length||!!analysisError} onClick={exportHTML}>{busy?<span className="spinner"/>:<FileDown size={14}/>}HTML report</button></>:null}</div>
   </div>
   {tab==='setup'?<main className="setup-layout">
    <div className="scene-column"><Scene profile={profile} entries={entries}/><div className="setup-summary"><span className="summary-source">{profile.source==='na22'?'²²Na':'⁶⁰Co'}</span>{profile.detectors.map(d=><span className="summary-detector" key={d.id}><i className={`detector-dot ${d.id}`}/><strong>{d.id}</strong><span>{entries.find(e=>e.id===d.scintillator_id)?.name??d.scintillator_id}</span><span>{d.shape}</span></span>)}</div></div>
    <aside className="inspector"><div className="module-settings"><span>Module 1 settings</span><button title="Load a Module 1 setup file; confirmation is required before replacement" disabled={busy} onClick={()=>{setProfilePath(paths.open_profile??'');showDialog('load');}}><FileUp size={13}/>Load</button><button title="Save the current Module 1 setup as a separate file" disabled={busy} onClick={()=>{setProfilePath(paths.save_profile??'Module1.tpm1');showDialog('save');}}><Save size={13}/>Save as</button></div><nav className="inspector-tabs" aria-label="Setup sections">{sections.map(([key,label])=><button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>{label}</button>)}</nav><div className="inspector-scroll"><fieldset className="setup-fields" disabled={busy}><Setup profile={profile} state={state} section={section} entries={entries} patch={patch} entrySelector={entrySelector} browse={browse}/></fieldset></div></aside>
   </main>:tab==='simulation'?<Simulation state={state} run={run} imported={imported} progress={importProgress} isImport={analysisPaths.length>0} plots={plots} analyses={analyses} loading={analysisLoading} error={analysisError} selection={selection} setSelection={setSelection} stop={stop} stopImport={stopImport} apply={p=>void apply(p)} analysis={()=>setTab('analysis')} busy={busy}/>:<AnalysisView source={analysisPaths.length?{paths:analysisPaths}:{run_id:run?.id}} revision={analysisPaths.length?importProgress?.total_events??0:run?.completed??0} analyses={analyses} selection={selection} plottedSelection={plottedSelection} setSelection={setSelection}  roles={roles} summaryStreams={summaryStreams} sessionPhase={phase} progress={phaseProgress} loading={analysisLoading} error={analysisError} hasSession={!!run||analysisPaths.length>0} open={streamsDialog} locked={fileLocked}/>}
  </>:null}
  {module===4?<MaterialDatabase key={profileEpoch} entries={entries} path={state.database_path} changed={databaseChanged} browse={browseFile} flush={autosave.flush} onDirty={setMaterialDirty} locked={sharedLocked}/>:null}
  <footer className="app-footer"><span className={`autosave-state ${autosave.status}`} title={autosave.error||'Your setup and view preferences are saved automatically on this computer.'}>{autosave.status==='saving'?<><span className="spinner"/>Saving…</>:autosave.status==='error'?<><AlertTriangle size={12}/>Could not save <button onClick={()=>void autosave.flush().catch(e=>setError(err(e)))}>Retry</button></>:null}</span><span className="footer-grow"/><LegalNotices/><ReleaseUpdates version={state.health.version}/></footer>
  {profileDialog&&<ProfileExchange mode={profileDialog} close={()=>setProfileDialog(null)} browse={browseFile} flush={autosave.flush} loaded={value=>{setProfileEpoch(v=>v+1);analysisAbort.current?.abort();setState(value);setProfile(value.profile);setPulseProfile(value.module2);setLifetimeProfile(value.module3);setLifetimeJob(null);setPulseJob(null);setRun(null);setImported(null);setImportProgress(null);setImportActive(false);setAnalyses([]);analysisCache.current.clear();setAnalysisError('');setValidation(null);setMaterialDirty(false);prefs.restore(restoreSessionViews(value.ui));setNotice('Profile loaded.');}}/>}
  {startupNotice&&<Modal title="Previous settings saved" close={()=>setStartupNotice(null)}><p>{startupNotice.message}</p><Field label="Backup file" help="An unchanged copy of the previous private settings. Keep it if you need to inspect or recover values later."><input readOnly value={startupNotice.backup_path}/></Field><div className="dialog-actions"><button className="primary" onClick={()=>setStartupNotice(null)}>Continue</button></div></Modal>}
  {notice&&<div className="toast" role="status"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="Dismiss"><X size={15}/></button></div>}
  {error&&<Dialog title="TwinPALS · Module 1" elevated close={()=>setError('')}><div className="error-box" role="alert">{error}</div><div className="dialog-actions"><button onClick={()=>setError('')}>Close</button></div></Dialog>}
  {(dialog==='load'||dialog==='save')&&<Dialog title={dialog==='load'?'Load Module 1 settings':'Save Module 1 settings as'} close={closeDialog} busy={busy} error={dialogError}><Field label="M1 file" help="A .tpm1 file contains geometry, material references and run settings. Referenced materials must exist in the material database."><div className="path-control"><input value={profilePath} disabled={busy} onChange={e=>{setProfilePath(e.target.value);setDialogError('');}}/><button title="Choose a file" disabled={busy} onClick={async()=>{const value=await browse(dialog==='load'?'open_profile':'save_profile',profilePath);if(value)setProfilePath(value);}}><FolderOpen size={15}/></button></div></Field><div className="dialog-actions"><button disabled={busy} onClick={closeDialog}>Cancel</button><button className="primary" disabled={busy} onClick={()=>void act(async()=>{
   if(dialog==='load'){
    const result=await api<{profile:Profile}>('/m1/profiles/inspect',{method:'POST',body:JSON.stringify({path:profilePath})});
    if(!await confirm('Replace the current Module 1 setup with this file?'))return;
    setProfile(result.profile);setValidation(null);setPaths(p=>({...p,open_profile:profilePath}));setNotice('Module 1 settings loaded.');
   }else{
    const body={profile,path:profilePath,overwrite:false};try{await api('/m1/profiles/save',{method:'POST',body:JSON.stringify(body)});}catch(e){if(!/File already exists/i.test(err(e)))throw e;if(!await confirm(`Overwrite ${profilePath}?`))return;await api('/m1/profiles/save',{method:'POST',body:JSON.stringify({...body,overwrite:true})});}
    setPaths(p=>({...p,save_profile:profilePath}));setNotice('Module 1 settings saved.');
   }setDialog(null);
  })}>{dialog==='load'?'Load':'Save Module 1'}</button></div></Dialog>}
  {dialog==='streams'&&<Dialog title="Open streams" close={closeDialog} busy={busy} error={dialogError}>{streamPaths.map((path,i)=><Field key={i} label={i?'Second stream · optional':'Stream'} help="Read event records progressively into memory. The embedded M1 settings refer to the current material database."><div className="path-control"><input value={path} disabled={busy} onChange={e=>{setStreamPaths(p=>p.map((s,j)=>i===j?e.target.value:s));setDialogError('');}}/><button title="Choose a file" disabled={busy} onClick={async()=>{const value=await browse('open_stream',path);if(value)setStreamPaths(p=>p.map((s,j)=>i===j?value:s));}}><FolderOpen size={15}/></button></div></Field>)}<ImportWorkers value={importWorkers} onChange={setImportWorkers} cpus={state.health.cpu_count??1} automatic={state.health.recommended_threads??1} disabled={busy}/><div className="dialog-actions"><button disabled={busy} onClick={closeDialog}>Cancel</button><button className="primary" disabled={busy} onClick={()=>void openStreams()}>Open</button></div></Dialog>}
 </div>;
}
function Dialog({title,close,children,error='',busy=false,elevated=false}:{title:string;close:()=>void;children:ReactNode;error?:string;busy?:boolean;elevated?:boolean}){
 const layer=useRef<HTMLDivElement>(null),latest=useRef({close,busy});latest.current={close,busy};
 useEffect(()=>{
  const element=layer.current!,previous=document.activeElement as HTMLElement|null;
  const siblings=[...element.parentElement!.children].filter(e=>e!==element) as HTMLElement[];
  const releases=siblings.map(lockBackground);
  (element.querySelector<HTMLElement>('input,select,textarea')??element.querySelector<HTMLElement>('button'))?.focus();
  const key=(event:KeyboardEvent)=>{
   if(element.closest('[inert]'))return;
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!latest.current.busy)latest.current.close();}
   if(event.key==='Tab'){
    const controls=[...element.querySelectorAll<HTMLElement>('button,input,select,textarea,[tabindex="0"]')].filter(e=>!e.matches(':disabled'));
    const first=controls[0],last=controls.at(-1);
    if(!element.contains(document.activeElement)){event.preventDefault();first?.focus();}
    else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
   }
  };
  document.addEventListener('keydown',key,true);
  return()=>{document.removeEventListener('keydown',key,true);releases.forEach(release=>release());if(previous?.isConnected&&!previous.closest('[inert]'))previous.focus();};
 },[]);
 return <div ref={layer} className={`modal-backdrop ${elevated?'error-backdrop':''}`}><section className="dialog" role="dialog" aria-modal="true" aria-label={title} aria-busy={busy}><header><h2>{title}</h2><button disabled={busy} onClick={close} aria-label="Close"><X size={18}/></button></header>{error&&<div className="error-box dialog-error" role="alert">{error}</div>}{children}</section></div>;
}
