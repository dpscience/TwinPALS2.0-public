// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';
import {processingProgress,outcomeProgress} from './processingProgress';
import type {Analysis} from './m1types';
import {SharedLegend,useSharedLegend} from './SharedLegend';
import {AnalysisBasis} from './AnalysisBasis';
import {matchesAnodePreview} from './previewSelection';
import {OriginSelect,OriginSplit} from './LightOrigin';
import {SessionEmpty} from './SessionEmpty';
import {DetectorInset} from './DetectorInset';
import {useConfirm} from './Confirm';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {OutcomeOverlay} from './OutcomeSummary';
import {ChevronRight,Download,Square} from 'lucide-react';
import type {AnalysisSelection,ImportedSession,ImportProgress,M1Run,Profile,State} from './m1types';
import type {Entry} from './types';
import type {PlotData} from './Plot';
import {Plot} from './Plot';
import Scene from './Scene';
import Setup from './Setup';
import {Field} from './Fields';
import {usePreference} from './Preferences';
import {api,downloadJson,duration,number} from './api';

export const roleNames:Record<string,string>={na22_prompt:'Na-22 · 1275 keV',na22_annihilation:'Na-22 · 511 keV (pair)',co60_1173:'Co-60 · 1173 keV',co60_1332:'Co-60 · 1332 keV'};
export const roleColors:Record<string,string>={na22_prompt:'#198f8c',na22_annihilation:'#9870ca',co60_1173:'#227bb0',co60_1332:'#c58a32'};
export const sections=[['source','Source'],['A','A'],['B','B'],['shield','Shield'],['physics','Physics'],['run','Run']];
export const active=(run:M1Run|null)=>run?.status==='running'||run?.status==='queued'||run?.status==='stopping';

type Props={state:State;run:M1Run|null;imported:ImportedSession|null;progress:ImportProgress|null;isImport:boolean;plots:PlotData[];analyses:Analysis[];loading:boolean;error:string;selection:AnalysisSelection;setSelection:(fn:(s:AnalysisSelection)=>AnalysisSelection)=>void;stop:()=>void;stopImport:()=>void;apply:(profile:Profile)=>void;analysis:()=>void;busy:boolean};
export default function Simulation({state,run,imported,progress,isImport,plots,analyses,loading,error,selection,setSelection,stop,stopImport,apply,analysis,busy}:Props){
 const confirm=useConfirm();
 const [panel,setPanel]=usePreference('simulation_panel'),[section,setSection]=usePreference('simulation_section');
 const [filter,setFilter]=usePreference('preview_filter'),[detector,setDetector]=usePreference('preview_detector');
 const profile=isImport?imported?.profile:run?.profile,roles=isImport?imported?.roles??[]:run?.streams.map(s=>s.role)??[];
 const progressStreams=isImport?progress?.streams??[]:run?.streams??[];
 const processing=processingProgress(progressStreams,selection.primary);
 const accumulating=isImport?!!progress?.loading:active(run);
 const outcomePercent=run?outcomeProgress(run.streams,run.total):0;
 const outcomeActivity=!isImport&&run&&(active(run)||(run.status==='completed'&&outcomePercent<100))?{
  percent:outcomePercent,
  details:run.streams.map(s=>(roleNames[s.role]??s.role)+' · '+number(s.outcomes?.total??0)+' / '+number(s.total)+' events processed').join('\n')
 }:undefined;
 const legend=useSharedLegend(plots,selection.basis??"anode",!!selection.split_origin,roles);
 useEffect(()=>{if(profile&&!profile.physics.include_cherenkov&&['cherenkov','mixed'].includes(selection.origin??''))setSelection(s=>({...s,origin:'all'}));},[profile?.physics.include_cherenkov,selection.origin]);
 const names=(isImport?imported?.streams[0]?.header.material_names:run?.material_names) as Record<string,string>|undefined;
 const pmtSnapshot=(isImport?imported?.streams[0]?.header.pmt_snapshot:run?.pmt_snapshot) as Entry[]|undefined;
 const displayEntries=useMemo(()=>Object.entries(names??Object.fromEntries(state.entries.map(e=>[e.id,e.name]))).map(([id,name])=>({id,name,properties:pmtSnapshot?.find(e=>e.id===id)?.properties})),[names,pmtSnapshot,state.entries]);
 // The live history belongs only to the running/completed native session.
 // Imports use the retained event tracks from the same stream as the pulse data.
 return <main className="simulation-layout"><div className="simulation-left">
  {profile?<SimulationScene processingStreams={progressStreams} accumulating={accumulating} key={isImport?imported?.streams.map(s=>s.path).join('|'):run?.id} profile={profile} names={displayEntries} run={isImport?null:run} paths={isImport?imported?.streams.map(s=>s.path):undefined} bins={selection.bins} roles={roles} revision={isImport?progress?.total_events??0:run?.completed??0} isImport={isImport} filter={filter} setFilter={setFilter} detector={detector} setDetector={setDetector} overlay={()=><OutcomeOverlay activity={outcomeActivity} streams={(isImport?progress?.streams??[]:run?.streams??[]).map(s=>({role:s.role,label:roleNames[s.role]??s.role,color:roleColors[s.role],outcomes:s.outcomes}))}/>}/>:<SessionEmpty kind="simulation"/>}
  {(isImport||run)&&<div className="stream-progress">{isImport?(progress?.streams.map(s=><div key={s.role}>
   <div><strong>{roleNames[s.role]??s.role}</strong><span>{number(s.completed)} events</span></div>
   <code className="stream-destination" title={s.path}>{s.path.split(/[\\/]/).at(-1)}</code>
   {s.status!=='failed'&&<progress aria-label={`${roleNames[s.role]} import`} max={Math.max(1,s.total_bytes)} value={s.loaded_bytes}/>}
   <small>{s.error?'Import failed':s.loading?`Reading · ${percent(100*s.loaded_bytes/Math.max(1,s.total_bytes))}`:s.status==='completed'?'Loaded · complete':s.status==='cancelled'?'Loaded · cancelled run':'Loaded · partial stream'}{s.error&&<button className="text-button" title={s.error} onClick={()=>void confirm(s.error!,{title:'Stream import failed',acceptLabel:'Close',cancelLabel:false})}>Details</button>}</small>
  </div>)??<div className="empty">Opening streams…</div>):run?run.streams.map(s=><div key={s.role}>
   <div><strong>{roleNames[s.role]??s.role}</strong><span>{number(s.completed)} / {number(s.total)}</span></div>
   <code className="stream-destination" title={s.path}>{s.path.split(/[\\/]/).at(-1)}</code>
   {s.status!=='failed'&&<progress aria-label={`${roleNames[s.role]} simulation`} max={Math.max(1,s.total)} value={s.completed}/>}
   <small>{s.status}{s.eta_s!=null?` · ${duration(s.eta_s)} remaining`:''}</small>
  </div>):<div className="empty">No stream selected.</div>}</div>}
  {(isImport||run)&&<div className="simulation-status">{isImport?<><strong>Imported streams</strong><span>{progress?.loading?'Reading files…':progress?.error?'Import failed':progress?.streams.some(s=>s.status==='stopped')?'Reading stopped':'Files loaded'}</span>{(progress?.loading||progress?.streams.some(s=>s.status==='incomplete'))&&<button className="danger" title="Stop reading these files; keep loaded events for analysis" disabled={busy} onClick={stopImport}>{busy?<span className="spinner"/>:<Square size={12}/>}Stop reading</button>}</>:run&&<><strong>Simulation · {run.status}</strong><span>{duration(run.elapsed_s)} elapsed</span>{active(run)&&<><span>{run.eta_s!=null?`${duration(run.eta_s)} remaining`:'Estimating…'}</span><span>Finish {run.estimated_finish?new Date(run.estimated_finish).toLocaleString(undefined,{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'}</span></>}<span>{run.threads} CPUs</span>{active(run)&&<button title="Stop this simulation; completed events remain available" className="danger" disabled={busy||run.status==='stopping'} onClick={stop}>{run.status==='stopping'?<><span className="spinner"/>Stopping…</>:<><Square size={12}/>Stop simulation</>}</button>}{run.status==='failed'&&<span title={run.message}>{run.message}</span>}</>}</div>}
 </div><aside className="monitor-panel">
  <nav className="session-tabs" aria-label="Simulation panels">{(['monitoring','settings'] as const).map(key=><button key={key} className={panel===key?'active':''} onClick={()=>setPanel(key)}>{key==='monitoring'?'Monitoring':'Settings'}</button>)}<button title="Open the full analysis plots for these streams" className="to-analysis" onClick={analysis}>Analysis<ChevronRight size={13}/></button></nav>
  {panel==='settings'?profile?<>
   <div className="session-settings-actions"><span className="readonly-badge">Module 1 · read-only</span><button title="Export the Module 1 settings recorded in these streams" disabled={busy} onClick={()=>downloadJson(profile,'Module1.tpm1')}><Download size={13}/>Export</button><button title="Replace the editable Setup with these stream settings after confirmation" disabled={busy} onClick={()=>apply(profile)}>Apply to setup</button></div>
   <nav className="inspector-tabs" aria-label="Simulation settings sections">{sections.map(([key,label])=><button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>{label}</button>)}</nav>
   <div className="inspector-scroll snapshot-settings"><fieldset className="setup-fields" disabled><Setup readOnly profile={profile} state={state} section={section} entries={[...(pmtSnapshot??[]),...state.entries.filter(e=>!pmtSnapshot?.some(p=>p.id===e.id))]} patch={()=>{}} browse={async()=>null} entrySelector={(label,id)=><Field label={label} help="Material recorded in this stream's Module 1 settings."><input readOnly value={displayEntries.find(e=>e.id===id)?.name??id}/></Field>}/></fieldset></div>
  </>:<div className="empty">No stream settings available.</div>:<>
   <AnalysisBasis selection={selection} onChange={setSelection} disabled={!profile||!run?.completed&&!progress?.total_events}/><div className="monitor-filters"><select title="Choose detector A, B or both for the monitoring plots" disabled={!profile||!run?.completed&&!progress?.total_events} aria-label="Monitoring detector" value={selection.detector} onChange={e=>setSelection(s=>({...s,detector:e.target.value as AnalysisSelection['detector']}))}><option value="all">A + B</option><option>A</option><option>B</option></select><select title="Choose which gamma energy is plotted" disabled={!profile||!run?.completed&&!progress?.total_events} aria-label="Monitoring primary" value={selection.primary} onChange={e=>setSelection(s=>({...s,primary:e.target.value}))}><option value="all">All primaries</option>{roles.map(r=><option key={r} value={r}>{roleNames[r]??r}</option>)}</select></div>
   <div className="monitor-filters monitor-outcome"><select aria-label="Monitoring crystal outcome" title="Select the crystal response in the same detector as each trace. In Anode view, a pulse is additionally required." disabled={!profile||!run?.completed&&!progress?.total_events} value={selection.category} onChange={e=>setSelection(s=>({...s,category:e.target.value as AnalysisSelection['category']}))}><option value="all">All crystal outcomes</option><option value="interaction">Interaction</option><option value="transmission">Pass through</option><option value="miss">Miss</option></select><OriginSelect basis={selection.basis??'anode'} disabled={selection.split_origin||!profile||!run?.completed&&!progress?.total_events} value={selection.origin??'all'} cherenkov={profile?.physics.include_cherenkov??false} onChange={origin=>setSelection(s=>({...s,origin}))}/></div><div className="monitor-origin"><OriginSplit basis={selection.basis??'anode'} value={selection.split_origin??false} disabled={!profile||!run?.completed&&!progress?.total_events} onChange={split_origin=>setSelection(s=>({...s,split_origin,origin:split_origin?'all':s.origin}))}/></div>
   <div className="monitor-plots">{plots.length?plots.filter(p=>['Deposited energy','Photocathode counts','Anode pulse height'].includes(p.title)).map(p=><Plot sharedHidden={legend.hidden} hideLegend key={p.title} preferenceKey={`monitor.${selection.basis??'anode'}.${p.title}`} data={p} compact busy={loading} activity={{active:accumulating||loading||(analyses[0]?.total_events??0)<processing.processed,processed:analyses[0]?.total_events??0,total:processing.total}}/>):<div className="empty">{profile?'Waiting for events…':'No streams open.'}</div>}</div><SharedLegend legend={legend}/>
   {error&&<div className="inline-error">{error}</div>}
  </>}
 </aside></main>;
}

type SceneProps={processingStreams:import("./processingProgress").StreamProgress[];accumulating:boolean;paths?:string[];bins:number;roles:string[];revision:number;overlay:(preview:M1Run['trajectories'][number]|undefined)=>ReactNode;profile:Profile;names:(Pick<Entry,'id'|'name'>&Partial<Pick<Entry,'properties'>>)[];run:M1Run|null;isImport:boolean;filter:Record<'interaction'|'transmission'|'miss',boolean>;setFilter:(fn:(v:SceneProps['filter'])=>SceneProps['filter'])=>void;detector:'all'|'A'|'B';setDetector:(v:SceneProps['detector'])=>void};
function SimulationScene({processingStreams,accumulating,overlay,profile,names,run,isImport,filter,setFilter,detector,setDetector,paths,bins,roles,revision}:SceneProps){
 const [pulseOrigin,setPulseOrigin]=usePreference('preview_origin'),[previewLevel,setPreviewLevel]=usePreference('preview_level');
 useEffect(()=>{if(!profile.physics.include_cherenkov&&['cherenkov','mixed'].includes(pulseOrigin))setPulseOrigin('all');},[profile.physics.include_cherenkov,pulseOrigin,setPulseOrigin]);
 const [paused,setPaused]=useState(false),[frozen,setFrozen]=useState<M1Run['trajectories']>([]),[index,setIndex]=useState(-1);
 const [importPreviews,setImportPreviews]=useState<M1Run['trajectories']>([]);
 const [tick,setTick]=useState(0);
 const source=paths?{paths}:{run_id:run?.id};
 const pathsKey=JSON.stringify(paths),counts=useRef(processingStreams);
 counts.current=processingStreams;
 useEffect(()=>{
  if(!paths)return;
  const controller=new AbortController();
  let cursors:Record<string,number>={},timer:ReturnType<typeof setTimeout>;
  const pending=()=>counts.current.some(s=>(s.preview_count??0)>(cursors[s.role]??0));
  const fetchNext=async()=>{
   let delay=250;
   try{
    if(pending()){
     const batch=await api<{previews:M1Run['trajectories'];cursors:Record<string,number>}>('/m1/pulse/previews',{method:'POST',signal:controller.signal,body:JSON.stringify({paths,after:cursors})});
     if(controller.signal.aborted)return;
     cursors=batch.cursors;
     if(batch.previews.length)setImportPreviews(previous=>previous.concat(batch.previews));
     if(pending())delay=0;
    }
   }catch{delay=1000;}
   if(!controller.signal.aborted)timer=setTimeout(fetchNext,delay);
  };
  void fetchNext();
  return()=>{controller.abort();clearTimeout(timer);};
 },[pathsKey]);
 const limit=profile.run.trajectory_sample_limit;
 const available=useMemo(()=>{
  const matches=(isImport?importPreviews:run?.trajectories??[]).filter(t=>previewLevel==='crystal'?filter[detector==='all'?t.category??'miss':t.detectors?.[detector]??'miss']:matchesAnodePreview([0,1].map(d=>t.pulse_origins?.[d]??(t.light_origins?.[d]??[]).reduce((m,v)=>m|v[0],0)),detector,pulseOrigin));
  if(!isImport||!limit)return limit?matches.slice(-limit):[];
  const groups=new Map<string,M1Run['trajectories']>();
  for(const preview of matches){
   if(!groups.has(preview.role))groups.set(preview.role,[]);
   groups.get(preview.role)!.push(preview);
  }
  // Take recent matching events from both archives, including the shorter one.
  const result:M1Run['trajectories']=[];
  const sampleSize=Math.max(limit,groups.size);
  for(let i=1;result.length<sampleSize;i++){
   const size=result.length;
   for(const group of groups.values()){
    const event=group.at(-i);
    if(event&&result.length<sampleSize)result.push(event);
   }
   if(result.length===size)break;
  }
  return result.reverse();
 },[isImport,importPreviews,run?.trajectories,previewLevel,filter,detector,pulseOrigin,limit]);
 useEffect(()=>{
  if(!isImport||!accumulating||paused)return;
  const timer=setInterval(()=>setTick(value=>value+1),650);
  return()=>clearInterval(timer);
 },[isImport,accumulating,paused]);
 const playingIndex=available.length-1-(isImport&&accumulating&&available.length?tick%available.length:0);
 const history=limit===1&&available.length?[available[playingIndex]]:available;
 const trajectories=paused?frozen:history;
 const shownIndex=paused?Math.max(0,Math.min(index,trajectories.length-1)):limit===1?0:playingIndex;
 const preview=trajectories[shownIndex];
 return <><Scene overlay={<>{overlay(preview)}<DetectorInset processingStreams={processingStreams} accumulating={accumulating} scope={JSON.stringify([previewLevel,detector,pulseOrigin,filter])} source={source} preview={preview} bins={bins} roles={roles} revision={revision}/></>} live profile={profile} entries={names} trajectories={preview?[preview]:[]}/>
 <fieldset className="preview-options">
  <div className="preview-filters"><label className="preview-basis">Preview by<select aria-label="Preview event basis" value={previewLevel} title="Choose one basis. Crystal response uses interaction / pass through / miss. Anode response uses the origin of accepted light; crystal outcome is then ignored." onChange={e=>{setPreviewLevel(e.target.value as 'crystal'|'anode');setPaused(false);}}><option value="crystal">Crystal response</option><option value="anode">Anode response</option></select></label><select aria-label="Preview detector" value={detector} onChange={e=>{setDetector(e.target.value as SceneProps['detector']);setPaused(false);}}><option value="all">{previewLevel==='anode'&&pulseOrigin==='none'?'Neither detector':'Either detector'}</option><option value="A">Detector A</option><option value="B">Detector B</option></select>{previewLevel==='crystal'?(['interaction','transmission','miss'] as const).map(key=><label key={key} title={key==='interaction'?'Show events that interact in the selected crystal(s)':key==='transmission'?'Show events entering a crystal without interaction':'Show events missing the selected crystal(s)'}><input type="checkbox" checked={filter[key]} onChange={e=>{setFilter(f=>({...f,[key]:e.target.checked}));setPaused(false);}}/>{key==='interaction'?'Interaction':key==='transmission'?'Pass through':'Miss'}</label>):<OriginSelect value={pulseOrigin} cherenkov={profile.physics.include_cherenkov} onChange={v=>{setPulseOrigin(v);setPaused(false);}}/>}</div>
  <div className="preview-controls"><button title="Pause or resume the displayed event history; simulation continues" onClick={()=>{setFrozen(history);setPaused(!paused);setIndex(shownIndex);}}>{paused?'Resume':'Pause'} preview</button><button title="Show the previous saved preview event" disabled={!paused||index<=0} onClick={()=>setIndex(Math.max(0,index-1))}>Previous</button><button title="Show the next saved preview event" disabled={!paused||index>=trajectories.length-1} onClick={()=>setIndex(Math.min(trajectories.length-1,index+1))}>Next</button><output className="preview-position" aria-label="Preview position" title="Position in the retained preview events matching these filters; not the simulation event number.">{`${preview?shownIndex+1:0} / ${trajectories.length}`}</output><span title={isImport?'One recorded event at a time. Matching trajectories from the open streams alternate while reading.':undefined}>{preview?`${roleNames[preview.role]??preview.role} · event ${preview.event_id}`:active(run)?'Waiting for a matching event…':'No sampled event'}</span></div>
 </fieldset></>;
}
