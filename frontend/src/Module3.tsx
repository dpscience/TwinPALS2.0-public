// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useMemo,useRef,useState} from 'react';
import {Download,FileUp,FolderOpen,Play,RotateCcw,Save,Square} from 'lucide-react';
import {api,percent,duration} from './api';
import {PhaseBadge} from './SessionBadges';
import {Field,Help} from './Fields';
import {SpectrumHoverProvider} from './SpectrumLegend';
import {ContributionShares} from './ContributionShares';
import {Modal} from './Modal';
import {useConfirm} from './Confirm';
import {usePreference} from './Preferences';
import {defaultAreaFit,defaultShapeFit,defaultMonitor,plotDelayMs,lifetimeActive,type ShapeFitCount,type Adc,type SourceStream,type InputInspection,type LifetimeChannel,type LifetimeData,type LifetimeJob,type LifetimeProfile,type LifetimeViews,type MeasurementGrid,type MonitorView} from './m3types';
import {saveLifetimeReport} from './lifetimeReport';
import {InputDiagram,StreamInputs} from './LifetimeInputs';
import {FilterSettings,MeasurementPlots,TimingSettings,WindowSettings,measurementSpecs,plotKey} from './LifetimeTuning';
import {SpectraPlots,SpectrumSettings} from './LifetimeSpectra';
import {LifetimePair} from './LifetimePair';
import {LifetimePlotActivity} from './LifetimePlot';
import type {Activity} from './ProcessingActivity';
import {displaySettings,gateError,type WindowRole} from './lifetimeEditing';
import {spectrumDisplay,spectrumNames,spectrumQuery} from './spectrumAnalysis';
import type {AnalysisData,SpectrumAnalysis,SpectrumDirection,SpectrumDisplay} from './m3types';
import './module3.css';

type Props={visible:boolean;cpuCount:number;autoWorkers:number;profile:LifetimeProfile;setProfile:(p:LifetimeProfile)=>void;job:LifetimeJob|null;setJob:(j:LifetimeJob|null)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>;onBusy:(b:boolean)=>void};
type Rule='first'|'highest';
type PlotSnapshots={id:string;groups:Record<string,{key:string;grids:MeasurementGrid[]}>};
const post=<T,>(path:string,value:unknown={},signal?:AbortSignal)=>api<T>(path,{method:'POST',body:JSON.stringify(value),signal});
const basename=(p:string)=>p.split(/[\\/]/).at(-1);
const initialInputs:InputInspection={streams:[],errors:[],conflict:''};
const fallbackAdc:Adc={low:-500,high:500,height:500,baseline:0,polarity:'negative'};
const elapsed=(sec:number)=>sec>=60?Math.floor(sec/60)+'m '+Math.floor(sec%60)+'s':sec.toFixed(sec<10?2:0)+' s';
const panels=['Input','Pulse','PHS','Filters'];
function Progress({job}:{job:LifetimeJob|null}){
 const name=job?({running:'Reading',pausing:'Stopping',paused:'Stopped',completed:'Completed',failed:'Failed',stopping:'Stopping',stopped:'Stopped'}[job.status]??job.status):'Ready';
 const reading=job?.status==='running',path=job?.profile.input_paths[0]??'';
 return <footer className="m3-progress">{job&&<div className="stream-progress m2-stream-progress"><div><div><strong>Waveform pairs read</strong><span>{job.total_processed.toLocaleString()} pairs</span></div><code className="stream-destination" title={path}>{basename(path)}</code><progress aria-label="Module 3 stream progress" max={1} value={job.progress}/><small>{name} · {percent(job.progress*100)}</small></div></div>}
 <div className="simulation-status"><strong>Acquisition · {name}</strong>{job&&<><span>{duration(job.elapsed)} elapsed</span>{reading&&<><span>{job.eta_s!=null?duration(job.eta_s)+' remaining':'Estimating…'}</span><span>Finish {job.estimated_finish?new Date(job.estimated_finish).toLocaleString(undefined,{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'}</span></>}<span>{job.accepted.toLocaleString()} accepted pairs</span><span className="m3-measurement-readout"><span>Measurement time · {elapsed(job.measurement_ns/1e9)}</span><Help text="Simulated Module 2 source clock at the start of the latest readout window processed by Module 3. Module 2 monitoring can extend through the final digitizer dead time."/></span></>}{job?.error&&<span role="alert">{job.error}</span>}</div></footer>;
}
export default function Module3(p:Props){
 const [view,setView]=usePreference('module3'),[channels,setChannels]=useState(p.profile.channels);
 const [inputEpoch,setInputEpoch]=useState(0);
 const [inputRead,setInputRead]=useState({paths:'',epoch:-1,info:initialInputs});
 const pathsKey=JSON.stringify(p.profile.input_paths);
 const inspected=inputRead.paths===pathsKey?inputRead.info:initialInputs;
 const inspecting=inputRead.paths!==pathsKey||inputRead.epoch!==inputEpoch;
 const source=inspected.streams[0]??undefined;
 const [data,setData]=useState<(AnalysisData&{display:SpectrumDisplay})|null>(null),[maps,setMaps]=useState<PlotSnapshots|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [place,setPlace]=useState(''),[dialog,setDialog]=useState<'save'|'load'|null>(null),[file,setFile]=useState(''),[tick,setTick]=useState(0);
 const [,setPlotViews]=usePreference('plots');
 const [runReads,setRunReads]=useState(()=>new AbortController());
 const [fitCounts,setFitCounts]=useState<{job?:string;plots:Record<string,ShapeFitCount>}>({plots:{}});
 const [fitting,setFitting]=useState('');
 const activeReader=p.job&&['running','pausing','stopping'].includes(p.job.status);
 const sameFile=p.job?.profile.input_paths[0]===p.profile.input_paths[0]&&(!source||
  (p.job?.stream_id===source.stream_id&&p.job.file_sizes[0]===source.bytes));
 const job=activeReader||sameFile?p.job:null;
 const confirm=useConfirm(),setup=view.tab==='setup',section=view.section,m={...defaultMonitor,...view.monitor},rule=p.profile.pulse_selection??'highest',session=!!job&&['running','pausing','paused'].includes(job.status);
 const update=(v:Partial<LifetimeViews>)=>setView(old=>({...old,...v})),patch=(monitor:MonitorView)=>update({monitor}),invalid=gateError(channels);
 const direction=view.analysis?.direction??'merged',display=spectrumDisplay(view,direction);
 const chooseDirection=(d:SpectrumDirection)=>setView(old=>({...old,analysis:{direction:d,displays:old.analysis?.displays??{}}}));
 const specs=measurementSpecs(section,invalid?p.profile.channels:channels,m),queryKey=JSON.stringify(setup?{plots:specs,share_cells:true}:{[direction]:spectrumQuery(display)}),pathOK=!inspecting&&!inspected.conflict&&!inspected.errors.length&&!!source;
 const group=setup?(section==='Filters'?m.filter_kind:section):'analysis';
 const selectionKey=JSON.stringify([direction,display.origin,display.scatter]);
 const plotKeys=useMemo<Record<string,string>>(()=>{
  if(setup)return Object.fromEntries(specs.map(s=>[plotKey(s.kind,s.channel,'role' in s?s.role:'start'),JSON.stringify(s)]));
  return {lifetime:JSON.stringify([selectionKey,display.low_ns,display.high_ns,display.bin_ps,display.zero_ps]),
   'phs-A':JSON.stringify([selectionKey,display.phs_bins[0]]),'phs-B':JSON.stringify([selectionKey,display.phs_bins[1]])};
 },[queryKey]);
 const draft={...p.profile,channels,pulse_selection:rule,input_paths:p.profile.input_paths.filter(Boolean)};
 const newInputs=!job||JSON.stringify(draft.input_paths)!==JSON.stringify(job.profile.input_paths);
 const reading=job?.status==='running',transition=job?.status==='pausing'||job?.status==='stopping';
 const inputLocked=!!reading||!!transition||busy;
 const canStart=!!pathOK&&!invalid&&!transition&&!reading;
 const current=useRef({job,profile:p.profile,channels});current.current={job,profile:p.profile,channels};
 const editQueue=useRef<Promise<unknown>>(Promise.resolve()),lastEdit=useRef(0);
 const rendered=useRef<Record<string,{id:string;key:string;plots:Record<string,string>;pairs:number;bytes:number;epoch:number;revision:number}>>({});
 const [late,setLate]=useState<{id:string;group:string;key:string}|null>(null);
 const act=async(fn:()=>Promise<void>)=>{if(busy)return;setBusy(true);p.onBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);p.onBusy(false);}};
 function queueSettings(next:LifetimeChannel[],selection:Rule,retained=current.current.profile.preview_count){
  const id=current.current.job?.id,order=++lastEdit.current;
  if(!session||!id||newInputs)return;
  editQueue.current=editQueue.current.catch(()=>{}).then(async()=>{
   if(order!==lastEdit.current||current.current.job?.id!==id)return;
   try{await post('/m3/configure',{id,channels:next,pulse_selection:selection,preview_count:retained});if(order===lastEdit.current)setTick(t=>t+1);}
   catch(e){if(order===lastEdit.current&&current.current.job?.id===id)setError((e as Error).message);}
  });
 }
 function setWorkers(workers:number){
  const next={...current.current.profile,workers};current.current.profile=next;p.setProfile(next);
  const id=current.current.job?.id;
  if(id&&session&&!newInputs){
   editQueue.current=editQueue.current.catch(()=>{}).then(async()=>{
    if(current.current.job?.id===id&&current.current.profile.workers===workers)
     await post('/m3/workers',{id,workers});
   }).catch(e=>{if(current.current.job?.id===id&&current.current.job.status!=='completed')setError((e as Error).message);});
  }
 }
 function edit(ch:number,c:LifetimeChannel,preview=false){const next=current.current.channels.map((old,i)=>ch===i?c:old);current.current.channels=next;setChannels(next);setError('');
  if(!preview&&!gateError(next)){const profile={...current.current.profile,channels:next};current.current.profile=profile;p.setProfile(profile);queueSettings(next,profile.pulse_selection??'highest');}
 }
 const selectRule=(next:Rule)=>{const profile={...current.current.profile,pulse_selection:next};current.current.profile=profile;p.setProfile(profile);if(!invalid)queueSettings(current.current.channels,next);};
 useEffect(()=>{const controller=new AbortController();api<{job:LifetimeJob|null}>('/m3/state',{signal:controller.signal}).then(v=>{if(!controller.signal.aborted)p.setJob(v.job);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[]);
 useEffect(()=>{
  const controller=new AbortController();
  const save=(info:InputInspection)=>{if(!controller.signal.aborted)setInputRead({paths:pathsKey,epoch:inputEpoch,info});};
  const timer=setTimeout(()=>{
   post<InputInspection>('/m3/inputs',{paths:JSON.parse(pathsKey)},controller.signal).then(save)
    .catch(e=>save({...initialInputs,errors:[{index:0,message:e.message}]}));
  },220);
  return ()=>{clearTimeout(timer);controller.abort();};
 },[pathsKey,inputEpoch]);
 useEffect(()=>{
  if(!job||runReads.signal.aborted)return;
  const id=job.id,abort=new AbortController(),signal=AbortSignal.any([abort.signal,runReads.signal]);
  const watch=p.visible&&(!setup||section==='PHS'||section==='Filters');
  let timer:ReturnType<typeof setTimeout>,probe:ReturnType<typeof setTimeout>;
  const valid=()=>!signal.aborted&&current.current.job?.id===id;
  function publish(head:LifetimeJob){
   const last=current.current.job;
   if(!valid()||head.id!==id||!last||head.elapsed<last.elapsed||head.total_processed<last.total_processed||head.epoch<last.epoch||head.revision<last.revision)return;
   current.current.job=head;p.setJob(head);
  }
  async function refresh(){
   if(!valid())return;
   let pending=true;
   // Only a slow view asks how far the reader has advanced.
   async function inspectDelay(){
    if(!valid()||!pending)return;
    const shown=rendered.current[group];
    const missing=!shown||shown.id!==id||shown.key!==queryKey;
    if(missing&&(current.current.job?.total_processed??0)>0)setLate({id,group,key:queryKey});
    try{
     const {job:head}=await api<{job:LifetimeJob|null}>('/m3/state',{signal});
     if(!valid()||!pending||head?.id!==id)return;
     publish(head);
     const behind=shown&&shown.id===id&&(head.total_processed>shown.pairs||head.epoch>shown.epoch);
     if((missing&&head.total_processed>0)||behind)setLate({id,group,key:queryKey});
    }catch{/* The view request reports connection errors. */}
    if(valid()&&pending)probe=setTimeout(inspectDelay,plotDelayMs);
   }
   if(watch)probe=setTimeout(inspectDelay,plotDelayMs);
   try{
    let snapshot:LifetimeJob;
    if(!p.visible){const s=await api<{job:LifetimeJob|null}>('/m3/state',{signal});if(!s.job)return;snapshot=s.job;}
    else if(setup){const s=await post<LifetimeJob&{plots:MeasurementGrid[]}>('/m3/monitor',JSON.parse(queryKey),signal);snapshot=s;
     if(valid()&&s.id===id)setMaps(old=>({id,groups:{...(old?.id===id?old.groups:{}),[group]:{key:queryKey,grids:s.plots.map(g=>g.cells_from===undefined?g:{...g,cells:s.plots[g.cells_from].cells})}}}));
    }else{const s=await post<AnalysisData>('/m3/analysis',JSON.parse(queryKey),signal);snapshot=s;
     if(valid()&&s.id===id)setData({...s,display});
    }
    if(!valid()||snapshot.id!==id)return;
    if(watch)rendered.current[group]={id,key:queryKey,plots:plotKeys,pairs:snapshot.total_processed,bytes:snapshot.bytes_read,epoch:snapshot.epoch,revision:snapshot.revision};
    publish(snapshot);
    const head=current.current.job!;
    if(head.total_processed>snapshot.total_processed||head.epoch>snapshot.epoch||head.revision>snapshot.revision)timer=setTimeout(refresh,0);
    else{setLate(null);if(lifetimeActive(head))timer=setTimeout(refresh,p.visible?850:1700);}
   }catch(e){if(valid()){setLate(null);setError((e as Error).message);timer=setTimeout(refresh,1500);}}
   finally{pending=false;clearTimeout(probe);}
  }
  setLate(null);void refresh();
  return ()=>{abort.abort();clearTimeout(timer);clearTimeout(probe);};
 },[job?.id,setup,p.visible,queryKey,group,tick,runReads]);
 const headrooms=useMemo(()=>[0,1].map(i=>{const vals=inspected.streams.flatMap(s=>s?.adc[i]?[s.adc[i].height]:[]);return vals.length?Math.max(...vals):500;}),[inspected]);
 const shown=rendered.current[group];
 const stalePlots=new Set(job?Object.keys(plotKeys).filter(key=>!!invalid||shown?.id!==job.id||shown.plots[key]!==plotKeys[key]):[]);
 const live=job&&data?.id===job.id&&data.comparisons[direction]&&data.display.origin===display.origin&&data.display.scatter===display.scatter?data:null;
 const previous=maps&&maps.id===job?.id?maps.groups[group]:undefined;
 const grids=previous?.grids??[];
 const delayed=!!job&&!error&&!invalid&&late?.id===job.id&&late.group===group&&late.key===queryKey;
 const activities:Record<string,Activity>={};
 if(delayed){
  for(const key of Object.keys(plotKeys)){
   if(stalePlots.has(key)||job.epoch!==shown?.epoch){
    activities[key]={active:true,description:'Preparing the plot for the current settings.'};
   }else if(job.total_processed>shown.pairs){
    activities[key]={active:true,processed:shown.bytes,total:job.file_sizes.reduce((a,b)=>a+b,0),
     description:`This plot includes ${shown.pairs.toLocaleString()} waveform pairs. The reader has processed ${job.total_processed.toLocaleString()}. The percentage is the displayed position in the stream.`};
   }
  }
 }
 const start=(restart:boolean)=>act(async()=>{
  await editQueue.current;
  if(!restart&&!newInputs&&job?.status==='paused'){p.setJob(await post('/m3/resume',{id:job.id}));}
  else{if(invalid||!pathOK)return;
   const reread=!!job&&!newInputs;
   if(restart||reread){
    const confirmed=await confirm('Read '+basename(draft.input_paths[0])+' from the first pair? This clears all spectra, PHS and filter maps, counters, plot zooms and retained pulses. The new acquisition uses your current measurement settings.',{title:'Restart stream?',acceptLabel:'Restart stream',destructive:true});
    if(!confirmed)return;
   }
   // Finish showing the current pass until confirmation, then cancel its pending reads.
   runReads.abort();
   try{
    const next=await post<LifetimeJob>(reread?'/m3/restart':'/m3/start',reread?{id:job.id,profile:draft}:draft);
    current.current.job=next;
    setData(null);setMaps(null);setFitCounts({plots:{}});setPlace('');
    if(reread){
     setView(old=>{
      const monitor=old.monitor;
      const plots=Object.fromEntries(Object.entries(monitor?.plots??{}).map(([key,plot])=>[key,{...plot,axes:null}]));
      const analysis=old.analysis&&{...old.analysis,displays:Object.fromEntries(
       Object.entries(old.analysis.displays).map(([dir,settings])=>[dir,{...settings,time_view:null}]))};
      return {...old,analysis,monitor:monitor&&{...monitor,plots}};
     });
     setPlotViews(old=>{
      const next={...old};
      for(const key of ['module3.timing.0','module3.timing.1'])if(next[key])next[key]={...next[key],x:null,y:null};
      return next;
     });
    }
    p.setJob(next);
   }finally{setRunReads(new AbortController());}
  }
  setTick(v=>v+1);
 });
 const reset=(kind:string,target:string)=>act(async()=>{if(!job)return;
  if(kind==='spectrum'&&target==='all'&&!await confirm('Clear all lifetime spectra and their paired pulse-height spectra in Merged, A → B, B → A and Stop–Stop? Reading continues from the current stream position.',{title:'Reset all spectra?',acceptLabel:'Reset all spectra',destructive:true}))return;
  await post('/m3/plot/reset',{id:job.id,kind,target});
  if(kind==='spectrum'){delete rendered.current.analysis;setData(null);}
  else{
   const slot=kind==='phs'?'PHS':kind,previous=rendered.current[slot];
   if(previous)rendered.current[slot]={...previous,key:'',plots:Object.fromEntries(Object.entries(previous.plots).filter(([key])=>!key.startsWith(kind+'-'+target+'-')))};
  }
  if(kind!=='spectrum')setMaps(old=>{const slot=kind==='phs'?'PHS':kind;if(!old||old.id!==job.id||!old.groups[slot])return old;
   const group=old.groups[slot];return {...old,groups:{...old.groups,[slot]:{...group,grids:group.grids.filter(g=>'AB'[g.channel]!==target)}}};});
  setTick(v=>v+1);});
 const fit=(kind:'area'|'shape',ch:number,r:WindowRole)=>act(async()=>{
  const selected=channels[ch][r].phs,id=job?.id;
  const key='AB'[ch]+'-'+r,options=kind==='area'?(m.area_fit?.[key]??defaultAreaFit):(m.shape_fit?.[key]??defaultShapeFit);
  const originalGate=channels[ch][r][kind];setFitting([kind,'AB'[ch],r].join('-'));
  try{
   type Gate=LifetimeChannel['start'];
   const reply=await post<Gate['area']|{gate:Gate['shape'];inside:number;total:number;first:number}>('/m3/autofit',{id,channel:ch,kind,window:r,phs:selected,options,include_counts:kind==='shape'});
   const c=current.current.channels[ch];
   if(current.current.job?.id!==id||JSON.stringify(c[r].phs)!==JSON.stringify(selected)||JSON.stringify(c[r][kind])!==JSON.stringify(originalGate))return;
   const gate='gate' in reply?reply.gate:reply;
   edit(ch,{...c,[r]:{...c[r],[kind]:gate}});
   if('gate' in reply){const count={inside:reply.inside,total:reply.total,first:reply.first,signature:JSON.stringify([selected,gate])};
    setFitCounts(old=>({job:id,plots:{...(old.job===id?old.plots:{}),[key]:count}}));}

  }finally{setFitting('');}
 });
 const settings=()=>act(async()=>{if(dialog==='load'){
  const q=await post<{processing:LifetimeProfile;display:Partial<LifetimeViews>;monitor?:MonitorView;analysis?:SpectrumAnalysis}>('/m3/settings/open',{path:file});
  const loaded={...q.processing,input_paths:inputLocked?p.profile.input_paths:q.processing.input_paths};
  if(session&&!newInputs&&JSON.stringify(loaded.input_paths)===JSON.stringify(job?.profile.input_paths))setWorkers(loaded.workers);
  setChannels(loaded.channels);p.setProfile(loaded);update({...q.display,monitor:q.monitor??defaultMonitor,analysis:q.analysis??{direction:'merged',displays:{}}});
  if(job&&JSON.stringify(loaded.input_paths)===JSON.stringify(job.profile.input_paths))queueSettings(loaded.channels,loaded.pulse_selection??'highest',loaded.preview_count);
 }else{
  if(invalid)throw Error(invalid);
  const value={processing:draft,display:displaySettings(view),analysis:view.analysis,monitor:m};
  try{await post('/m3/settings/save',{path:file,settings:value});}catch(e){if(!(e as Error).message.includes('exists'))throw e;
   if(!await confirm('Replace the existing Module 3 settings file?',{acceptLabel:'Replace'}))return;await post('/m3/settings/save',{path:file,settings:value,overwrite:true});}
 }setDialog(null);});
 const report=()=>act(async()=>{
  const allPlots=[...measurementSpecs('PHS',channels,m),...measurementSpecs('Filters',channels,{...m,filter_kind:'area'}),...measurementSpecs('Filters',channels,{...m,filter_kind:'shape'})];
  const directions=Object.keys(spectrumNames) as SpectrumDirection[];
  const comparison_displays=Object.fromEntries(directions.map(dir=>[dir,{...spectrumDisplay(view,dir),category:'all',categories:null,individual:true}]));
  const snapshot=await post<LifetimeData>('/m3/query',{...displaySettings(view),category:'all',categories:null,individual:true,compact:true,comparison_displays,report_all_paths:true,plots:allPlots,area_views:true,share_cells:true});
  const context=await api<{streams:SourceStream[]}>('/m3/context');
  if(snapshot.stream_id&&context.streams[0]?.stream_id!==snapshot.stream_id)throw Error('The input stream changed during export. Export the current analysis again.');
  saveLifetimeReport(snapshot,view,context);
 });
 const displayPatch=(v:Partial<SpectrumDisplay>)=>{
  const next={...display,...v},bins=(next.high_ns-next.low_ns)*1000/next.bin_ps;
  if(!Number.isFinite(bins)||bins<1||bins>100000||Math.abs(next.zero_ps)>1e9){setError('Choose increasing time limits with 1 to 100,000 bins and a zero shift within ±1,000,000,000 ps.');return;}
  setError('');
  const change=v.low_ns!==undefined||v.high_ns!==undefined?{...v,time_view:null}:v;
  setView(old=>({...old,analysis:{direction,displays:{...old.analysis?.displays,[direction]:{...spectrumDisplay(old,direction),...change}}}}));
 };
 if(!p.visible)return null;
 return <div className="lifetime-module m2-workbench"><div className="workspace-bar"><nav className="tabs" aria-label="Module 3 views">{(['setup','analysis'] as const).map(t=><button key={t} className={view.tab===t?'active':''} onClick={()=>update({tab:t})}>{t==='setup'?'Setup & Acquisition':'Analysis'}</button>)}</nav>
 {draft.input_paths[0]&&<span className="lifetime-stream" title={draft.input_paths[0]}>{basename(draft.input_paths[0])}</span>}
 <div className="workspace-actions m3-stream-actions">{(reading||transition)&&<PhaseBadge label={reading?'Live':'Stopping'} progress={job!.progress*100}/>}
 <label className="m3-workers">CPU workers<select aria-label="CPU workers" title="Auto uses the recommended CPU count. Changes take effect at the next processing block." disabled={!!transition||busy} value={p.profile.workers} onChange={e=>setWorkers(+e.target.value)}><option value={0}>Auto · {p.autoWorkers}</option>{p.profile.workers>p.cpuCount&&<option value={p.profile.workers}>{p.profile.workers} · {p.cpuCount} available</option>}{Array.from({length:Math.min(32,p.cpuCount)},(_,i)=><option key={i} value={i+1}>{i+1}</option>)}</select></label>
 {reading||transition?<button className="danger m3-stream-toggle" disabled={busy||transition} onClick={()=>act(async()=>{p.setJob(await post('/m3/hold',{id:job!.id}));setTick(v=>v+1);})} title="Stop after the current batch and keep the stream position"><Square size={12}/>{transition?'Stopping…':'Stop stream'}</button>:<button className="primary m3-stream-toggle" disabled={busy||!canStart} onClick={()=>start(false)} title={!newInputs&&job?.status==='paused'?'Continue from the next unread pair':'Read the selected pulse stream'}><Play size={13}/>Start stream</button>}
 <button disabled={busy||transition||newInputs||!job||!!invalid||!pathOK} onClick={()=>start(true)} title="Clear this acquisition and read the selected file from the beginning"><RotateCcw size={13}/>Restart stream</button>
 {!setup&&<button disabled={!job||busy||!!invalid} onClick={report}><Download size={14}/>HTML report</button>}</div></div>
 <SpectrumHoverProvider scope={setup?'':[job?.id,direction].join('|')}><div className="m2-setup-layout m3-layout"><main key={job?.id??'ready'} className={'m3-main'+(setup?'':' m3-analysis-main')}><LifetimePlotActivity.Provider value={activities}>
 <div className="m3-pulse-pane" hidden={!setup||section!=='Pulse'}><LifetimePair runSignal={runReads.signal} visible={setup&&section==='Pulse'} job={job} channels={invalid?p.profile.channels:channels} rule={rule} adc={source?.adc??[fallbackAdc,fallbackAdc]} m={m} patch={patch} retained={p.profile.preview_count} setRetained={preview_count=>{const profile={...current.current.profile,preview_count};current.current.profile=profile;p.setProfile(profile);queueSettings(current.current.channels,rule,preview_count);}}/></div>
 {!setup?<SpectraPlots key={job?.id} data={live} direction={direction} selectDirection={chooseDirection} view={display} patch={displayPatch} channels={live?.profile.channels??(invalid?p.profile.channels:channels)} headrooms={headrooms} isotope={source?.source} onReset={()=>reset('spectrum',direction)} onResetAll={()=>reset('spectrum','all')} stalePlots={stalePlots}/>:section==='Input'?<InputDiagram key={source?.stream_id} source={source} loading={!!draft.input_paths.length&&inspecting}/>:section!=='Pulse'?<MeasurementPlots fitCounts={fitCounts.job===job?.id?fitCounts.plots:{}} section={section} grids={grids} headrooms={headrooms} channels={channels} edit={edit} m={m} patch={patch} ready={!!job} reset={reset} place={place} setPlace={setPlace} stalePlots={stalePlots}/>:null}
 </LifetimePlotActivity.Provider></main>
 <aside className="inspector"><div className="module-settings"><span>Module 3 settings</span><button onClick={()=>{setFile('');setError('');setDialog('load');}}><FileUp size={13}/>Load</button><button onClick={()=>{setFile('module3.tpm3');setError('');setDialog('save');}}><Save size={13}/>Save as</button></div>
 {setup&&<nav className="inspector-tabs" aria-label="Module 3 sections">{panels.map(s=><button key={s} className={section===s?'active':''} onClick={()=>{setPlace('');update({section:s});}}>{s}</button>)}</nav>}
 <div key={setup?section:direction} className={'inspector-scroll'+(!setup||section!=='Filters'?' m3-setup-inspector':'')}><div className="setup-fields m3-rail">{(invalid||error)&&!dialog&&<div className="lifetime-inline-error" role="alert">{invalid||error}{!invalid&&<button onClick={()=>setError('')} aria-label="Dismiss message">×</button>}</div>}
 {setup?(section==='Input'?<StreamInputs path={p.profile.input_paths[0]??''} inspection={inspected} locked={inputLocked} inspecting={inspecting} reload={()=>setInputEpoch(n=>n+1)} change={path=>{if(!inputLocked)p.setProfile({...p.profile,input_paths:path?[path]:[]});}} browse={path=>p.browse('open_pulses',path)}/>:section==='Pulse'?<TimingSettings channels={channels} edit={edit} m={m} patch={patch} rule={rule} selectRule={selectRule}/>:section==='PHS'?<WindowSettings channels={channels} edit={edit} m={m} patch={patch}/>:<FilterSettings channels={channels} edit={edit} m={m} patch={patch} place={place} setPlace={setPlace} fit={fit} fitting={fitting} ready={!!job}/>):<><SpectrumSettings direction={direction} view={display} patch={displayPatch} delays={live?.cable_delays_ns??[0,1].map(i=>source?.channels[i]?.cable_delay_ns)} comparison={live?.comparisons[direction]}/><ContributionShares isotope={source?.source} comparison={live?.comparisons[direction]} categories={live?.categories}/></>}</div></div></aside></div></SpectrumHoverProvider>
 <Progress job={job}/>
 {dialog&&<Modal title={dialog==='save'?'Save Module 3 settings':'Load Module 3 settings'} close={()=>setDialog(null)} busy={busy} error={error}><Field label="Settings file" help="A .tpm3 file stores the selected pulse stream, pulse selection, timing, filter windows, PHS and density bins, axes and spectrum display."><div className="lifetime-input"><input value={file} onChange={e=>setFile(e.target.value)}/><button title="Choose settings file" onClick={()=>act(async()=>{const f=await p.browse(dialog==='save'?'save_m3':'open_m3',file);if(f)setFile(f);})}><FolderOpen size={14}/></button></div></Field><button disabled={!file||busy} onClick={settings}>{dialog==='save'?'Save':'Load'}</button></Modal>}</div>;
}

