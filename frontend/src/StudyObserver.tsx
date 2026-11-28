// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect, useRef, useState} from 'react';
import {Activity, ChartColumn, Download, Eye, Layers, Pin, Radio, Settings2} from 'lucide-react';
import Scene from './Scene';
import LegalNotices from './LegalNotices';
import ReleaseUpdates from './ReleaseUpdates';
import {downloadBlob, Plot} from './Plot';
import type {PlotData} from './Plot';
import type {M1Run, Profile} from './m1types';
import type {Entry} from './types';
import './study-observer.css';

type Run={id:string;study:string;name:string;module:number;status:string;progress:number;attempt:number;workers:number;message:string;updated:number};
type Overview={studies:{id:string;name:string}[];runs:Run[];activity:{id:number;at:number;message:string;study:string|null;run:string|null}[];cpu_total:number};
type Stream={role:string;outcomes?:{total:number;interaction:{count:number};joint:{anode:{neither:{count:number};both:{count:number}}}}};
type Metrics={completed?:number;total_events?:number;waveforms?:number;target_pairs?:number;total_processed?:number;accepted?:number;measurement_ns?:number;source_duration_ns?:number;acquisition_rate_Hz?:number;rejected?:Record<string,number>;streams?:Stream[];phase?:string;stop_reason?:string};
type ObserverChart=PlotData&{timingGrid?:(string|number)[]};
type Detail={run:Run;profile:Record<string,unknown>;metrics:Metrics;charts:ObserverChart[];geometry:boolean;trajectories?:M1Run['trajectories'];entries?:Entry[];input_files:string[];saved_queries:string[];context:{objective:string;step:number;steps:number;operation:string;parent:string|null;queries:string[]}};
type Comparison={documents:{id:string;name:string;file:string}[];fields:string[];rows:({id:string;name:string;status:string;source:string;settings:unknown[]}&Metrics)[]};
const modules=['','Detector response','Digitizer acquisition','Lifetime spectrum'];
const phase=(name:string)=>name.slice(0,1).toUpperCase()+name.slice(1);
const percent=(value:number)=>(100*value).toLocaleString(undefined,{maximumFractionDigits:1})+'%';
const format=(v:unknown)=>typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:3}):String(v??'—');
const primaries:Record<string,string>={na22_prompt:'Na-22 · 1275 keV',na22_annihilation:'Na-22 · 511 keV pair',co60_1173:'Co-60 · 1173 keV',co60_1332:'Co-60 · 1332 keV'};
const underway=(r:Run)=>['running','cancelling'].includes(r.status);
const finished=(r:Run)=>['completed','partial'].includes(r.status);
const elapsed=(ns:number)=>ns<1e6?format(ns/1000)+' µs':ns<1e9?format(ns/1e6)+' ms':format(ns/1e9)+' s';
const countShare=(n:number,total:number)=>format(n)+(total?' · '+percent(n/total):'');
function credential(){
  const incoming=location.hash.slice(1);
  if(incoming){
    sessionStorage.setItem('twinpals-observer',incoming);
    history.replaceState(null,'',location.pathname+location.search);
  }
  return sessionStorage.getItem('twinpals-observer')||'';
}
const observerToken=location.pathname==='/observe'?credential():'';

function useObservation<T>(path:string|null,once=false){
  const [reply,setReply]=useState<{path:string;value:T}|null>(null);
  const [failure,setFailure]=useState<{path:string;message:string}|null>(null);
  useEffect(()=>{
    if(!path)return;
    const target=path;
    const abort=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    let loaded=false;
    async function refresh(){
      try{
        const response=await fetch('/observe/api/'+target,{signal:abort.signal,cache:'no-store',headers:{Authorization:'Bearer '+observerToken}});
        if(!response.ok)throw Error(response.status===403?'Open the observer link supplied by the MCP server.':'The study service is reconnecting.');
        const value=await response.json() as T;
        if(!abort.signal.aborted){loaded=true;setReply({path:target,value});setFailure(null);}
      }catch(reason){
        if(!abort.signal.aborted)setFailure({path:target,message:reason instanceof TypeError?'Reconnecting to the local study service…':String((reason as Error).message)});
      }finally{
        if(!abort.signal.aborted&&(!once||!loaded))timer=setTimeout(refresh,1500);
      }
    }
    void refresh();
    return ()=>{abort.abort();clearTimeout(timer);};
  },[path,once]);
  return {value:reply?.path===path?reply?.value:undefined,error:failure?.path===path?failure.message:null};
}

function Settings({value}:{value:Record<string,unknown>}){
  function rows(obj:Record<string,unknown>){
    return Object.entries(obj).map(([name,v])=>{
      const label=name.replaceAll('_',' ');
      if(v!==null && typeof v==='object')return <details key={name}><summary>{label}</summary><div>{rows(v as Record<string,unknown>)}</div></details>;
      return <div className="study-setting" key={name}><span>{label}</span><span>{format(v)}</span></div>;
    });
  }
  return <div className="study-settings">{rows(value)}</div>;
}

function statusText(r:Run,d?:Detail){
  switch(r.status){
    case 'queued':return r.message||'Waiting for inputs or worker capacity';
    case 'cancelled':return r.message||'Cancelled';
    case 'blocked':case 'failed':return r.message||phase(r.status);
    case 'partial':return 'Results cover the readable records in the input stream';
    case 'completed':return d?.metrics.stop_reason==='input_exhausted'?'Source inputs exhausted · results saved':'Results saved';
    case 'cancelling':return 'Cancellation in progress';
    default:return d?.metrics.phase||r.message||'Starting the measurement';
  }
}

function SaveResult({path,name,label}:{path:string;name:string;label:string}){
  const [error,setError]=useState(false);
  async function save(){
    try{
      const response=await fetch('/observe/api/'+path,{headers:{Authorization:'Bearer '+observerToken}});
      if(!response.ok)throw Error();
      downloadBlob(await response.blob(),name);setError(false);
    }catch{setError(true);}
  }
  return <div><button onClick={()=>void save()}><Download size={14}/>{label}</button>{error&&<small role="alert">Download failed. Try again.</small>}</div>;
}

function setupSummary(d:Detail){
  if(d.run.module===1){
    const source=d.profile.source;
    return source==='na22'?'Na-22':source==='co60'?'Co-60':null;
  }
  if(d.run.module===2){
    const digit=d.profile.digitization as {digitizer_id:string;rate_GSps:number}|undefined;
    return digit?digit.digitizer_id+(digit.rate_GSps?' · '+format(digit.rate_GSps)+' GS/s':''):null;
  }
  const channels=d.profile.channels as {cfd_percent:number}[]|undefined;
  return channels?.length===2?'CFD · A '+format(channels[0].cfd_percent)+'% · B '+format(channels[1].cfd_percent)+'%':null;
}

function Measurement({d}:{d:Detail}){
  const [choice,choose]=useState('');
  const [source,setSource]=useState<string|null>(null);
  const query=source??d.saved_queries[0]??'';
  const saved=useObservation<{charts:ObserverChart[]}>(query?'runs/'+d.run.id+'/queries/'+encodeURIComponent(query)+'/charts':null,true);
  const charts=query?saved.value?.charts??[]:d.charts;
  const m=d.metrics,mod=d.run.module;
  const chart=charts.find(c=>c.title===choice)??charts.find(c=>c.series.some(s=>s.points.length))??charts[0];
  const bins=mod===3?chart?.series.flatMap(s=>s.bins??[]):undefined;
  const single=bins?.length&&bins.every(b=>b.low===bins[0].low&&b.high===bins[0].high)?bins[0]:null;
  const stats:[string,string][]=[];
  const add=(label:string,value?:number)=>{if(value!==undefined)stats.push([label,format(value)]);};
  if(mod===1){
    add(d.context.operation==='import'?'Events read':'Events processed',m.total_events??m.completed);
    const outcomes=m.streams?.map(s=>s.outcomes);
    if(outcomes?.length&&outcomes.every(o=>o?.joint?.anode)){
      add('Crystal interactions',outcomes.reduce((n,o)=>n+o!.interaction.count,0));
      add('Events with an anode signal',outcomes.reduce((n,o)=>n+o!.total-o!.joint.anode.neither.count,0));
    }
  }
  if(mod===2){
    add('Waveform pairs',m.waveforms);
    if(d.context.operation!=='import'&&m.target_pairs!=null)add('Acquisition target',m.target_pairs);
    if(m.source_duration_ns){stats.push(['Source exposure',elapsed(m.source_duration_ns)]);}
    if(m.acquisition_rate_Hz&&m.waveforms)stats.push(['Acquisition rate',format(m.acquisition_rate_Hz)+' pairs/s']);
  }
  if(mod===3){
    add('Pairs analyzed',m.total_processed);add('Accepted pairs · all directions',m.accepted);
    if(m.total_processed&&m.accepted!==undefined)stats.push(['Accepted / read',percent(m.accepted/m.total_processed)]);
    if(m.measurement_ns!==undefined)stats.push(['Measurement time',elapsed(m.measurement_ns)]);
  }
  const streams=m.streams?.filter(s=>s.outcomes);
  const rejections=Object.entries(m.rejected??{}).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]);
  return <>
    {stats.length>0&&<div className="study-metrics">{stats.map(([label,value])=><div key={label}><small>{label}</small><strong>{value}</strong></div>)}</div>}
    {mod===1&&d.geometry&&<section className="observer-panel"><div className="observer-panel-heading"><h2>Detector assembly</h2><small>{d.trajectories?.length?'Sampled event trajectory':'Study geometry'}</small></div><div className="study-geometry"><Scene profile={d.profile as unknown as Profile} entries={d.entries} trajectories={d.trajectories??[]} live/></div></section>}
    {!!streams?.length&&<section className="observer-panel"><div className="observer-panel-heading"><h2>Detector response by primary</h2></div><div className="study-table-scroll"><table><thead><tr><th>Primary</th><th>Events</th><th>Crystal interaction</th><th>Either anode</th><th>Both anodes</th></tr></thead><tbody>{streams.map((s,i)=>{
      const o=s.outcomes!,a=o.joint?.anode;
      return <tr key={i}><th>{primaries[s.role]??s.role}</th><td>{format(o.total)}</td><td>{countShare(o.interaction.count,o.total)}</td><td>{a?countShare(o.total-a.neither.count,o.total):'—'}</td><td>{a?countShare(a.both.count,o.total):'—'}</td></tr>;
    })}</tbody></table></div></section>}
    {!!d.saved_queries.length&&<label className="observer-source">Results to display<select value={query} onChange={e=>{setSource(e.target.value);choose('');}}><option value="">Module overview</option>{d.saved_queries.map(q=><option key={q} value={q}>{q}</option>)}</select></label>}
    {query&&!chart&&<p className="study-empty">{saved.error||(saved.value?'This saved query is available as JSON under Study queries.':'Reading the saved query…')}</p>}
    {chart&&<section className="observer-panel"><div className="observer-panel-heading"><h2>{query?'Saved query · '+query:['','Energy deposition','Acquisition distributions','Lifetime spectra'][mod]}</h2>
      {charts.length>1&&<select aria-label="Measurement distribution" value={chart.title} onChange={e=>choose(e.target.value)}>{charts.map(c=><option key={c.title}>{c.title}</option>)}</select>}</div>
      <div className={'study-chart'+(chart.series.some(s=>s.points.length)&&!single?'':' empty-chart')}>{single?<><strong>One occupied time bin</strong><span>{format(single.low)} to {format(single.high)} ns</span><small>{chart.note}</small></>:chart.series.some(s=>s.points.length)?<Plot key={chart.title} data={chart} preferenceKey={'observer.'+d.run.id+'.'+d.run.attempt+'.'+query+'.'+chart.title}/>:<><strong>{chart.emptyText}</strong><small>{chart.note}</small></>}</div></section>}
    {rejections.length>0&&<details className="observer-detail"><summary>Rejected pairs · {format(rejections.reduce((n,[,v])=>n+v,0))}</summary>{rejections.map(([reason,n])=><div className="study-setting" key={reason}><span>{reason}</span><b>{format(n)}</b></div>)}</details>}
    {!chart&&!query&&!stats.length&&<p className="study-empty">{underway(d.run)?'Waiting for the first measurement from this attempt.':finished(d.run)?'No measurement distribution was recorded for this step.':'This step has no committed measurements.'}</p>}
    {d.context.queries.length>0&&<section className="observer-panel"><div className="observer-panel-heading"><h2>Study queries</h2></div>{d.context.queries.map(q=><div key={q} className="observer-query"><strong>{q}</strong>{d.saved_queries.includes(q)?<SaveResult path={'runs/'+d.run.id+'/queries/'+encodeURIComponent(q)} name={'query-'+q+'.json'} label="Result JSON"/>:<small>{finished(d.run)||underway(d.run)||d.run.status==='queued'?'Awaiting saved result':'No saved result'}</small>}</div>)}</section>}
  </>;
}

function TimingComparison({d,rows}:{d:Detail;rows:Comparison['rows']}){
  const peers=rows.filter(row=>row.id!==d.run.id&&['completed','partial'].includes(row.status));
  const [peerId,setPeer]=useState('');
  const peer=peers.find(v=>v.id===peerId)??peers[0];
  const other=useObservation<Detail>(peer?'runs/'+peer.id:null,true);
  const names=d.saved_queries.filter(n=>other.value?.saved_queries.includes(n));
  const [source,setSource]=useState<string|null>(null);
  const query=source===null?(names[0]??''):names.includes(source)?source:'';
  const snapshot=(id:string)=>query?'runs/'+id+'/queries/'+encodeURIComponent(query)+'/charts':null;
  const left=useObservation<{charts:ObserverChart[]}>(snapshot(d.run.id),true);
  const right=useObservation<{charts:ObserverChart[]}>(peer?snapshot(peer.id):null,true);
  const charts=query?left.value?.charts:d.charts;
  const others=query?right.value?.charts:other.value?.charts;
  const matched=charts?.filter(c=>c.timingGrid&&others?.some(v=>v.title===c.title&&JSON.stringify(v.timingGrid)===JSON.stringify(c.timingGrid)))??[];
  const [direction,setDirection]=useState('');
  const [stage,setStage]=useState(0);
  const a=matched.find(c=>c.title===direction)??matched.find(c=>c.series.some(s=>s.points.length))??matched[0];
  const b=others?.find(c=>c.title===a?.title);
  const index=a?.series[stage]&&b?.series[stage]?stage:0;
  if(!peer)return null;
  const traces=a&&b?[a.series[index],b.series[index]].map((s,i)=>({...s,name:(i?peer.name:d.run.name),color:i?'#466bb2':'#137f80',dashed:!!i})):[];
  const validBins=traces.flatMap(s=>s.bins??[]).filter(x=>x.count);
  const single=validBins.length>0&&validBins.every(x=>x.low===validBins[0].low&&x.high===validBins[0].high);
  const error=other.error||left.error||right.error;
  return <section className="observer-panel"><div className="observer-panel-heading"><h2>Lifetime comparison</h2><small>Counts per bin</small></div>
    <div className="comparison-controls"><label>Compare {d.run.name} with<select value={peer.id} onChange={e=>setPeer(e.target.value)}>{peers.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    {!!names.length&&<label>Result<select value={query} onChange={e=>setSource(e.target.value)}><option value="">Module overview</option>{names.map(n=><option key={n}>{n}</option>)}</select></label>}
    {matched.length>1&&a&&<label>Direction<select value={a.title} onChange={e=>setDirection(e.target.value)}>{matched.map(c=><option key={c.title}>{c.title}</option>)}</select></label>}
    {a&&b&&a.series.length>1&&b.series.length>1&&<label>Filter stage<select value={index} onChange={e=>setStage(Number(e.target.value))}>{a.series.map((s,i)=><option key={s.name} value={i}>{s.name}</option>)}</select></label>}</div>
    {error?<p className="study-empty">{error}</p>:a&&b?<div className={'study-chart'+(!validBins.length||single?' empty-chart':'')}>{!validBins.length?<strong>No pairs in this time range for either step</strong>:single?<><span>One occupied time bin · {format(validBins[0].low)} to {format(validBins[0].high)} ns</span><small>{traces.map(s=>s.name+' · '+format(s.bins?.[0]?.count??0)+' pairs').join(' | ')}</small></>:<Plot data={{...a,series:traces,title:a.title,note:traces.map(s=>s.name+' · '+format(s.bins?.reduce((n,x)=>n+x.count,0))+' in range').join('   |   ')+' · '+a.timingGrid![2]+' ps per bin'}} preferenceKey={'observer.compare.'+d.run.id+'.'+peer.id+'.'+query+'.'+a.title+'.'+index}/>}</div>:<p className="study-empty">{!charts||!others?'Loading both results…':'These results have no matching lifetime direction, binning and selection.'}</p>}</section>;
}

function Compare({d,select}:{d:Detail;select:(id:string)=>void}){
  const result=useObservation<Comparison>('runs/'+d.run.id+'/comparison');
  if(!result.value)return <p className="study-empty">{result.error||'Loading study steps…'}</p>;
  const {fields,rows}=result.value;
  const metric=['','Events processed','Waveform pairs','Accepted / read'][d.run.module];
  return <><section className="observer-panel"><div className="observer-panel-heading"><h2>Compare study steps</h2><small>Module {d.run.module} · {d.context.operation==='import'?'Imports':'Runs'}</small></div>
    {result.error&&<p role="status">{result.error}</p>}
    <div className="study-table-scroll"><table><thead><tr><th>Step</th><th>Input</th>{fields.map(f=><th key={f}>{f.replace(/^channels \/ ([AB]) \/ cfd_percent$/,'CFD $1 (%)').replaceAll('_',' ')}</th>)}<th>{metric}</th><th>Status</th></tr></thead><tbody>{rows.map(row=><tr key={row.id} className={row.id===d.run.id?'current':''}><th><button onClick={()=>select(row.id)}>{row.name}</button></th><td>{row.source||'Source simulation'}</td>{row.settings.map((v,i)=><td key={fields[i]}>{format(v)}</td>)}<td>{d.run.module===3&&row.total_processed!==undefined?format(row.accepted)+' / '+format(row.total_processed)+(row.total_processed?' · '+percent((row.accepted??0)/row.total_processed):''):format(row.total_events??row.completed??row.waveforms)}</td><td>{phase(row.status)}</td></tr>)}</tbody></table></div>
    {result.value.documents.length>0&&<div className="study-documents"><h2>Saved study documents</h2>{result.value.documents.map(doc=><SaveResult key={doc.id} path={'runs/'+d.run.id+'/documents/'+doc.id} name={doc.file} label={doc.name}/>)}</div>}
    <p className="observer-caption">Counts are from saved results. {rows.length>1&&fields.length>0?'Setting columns show differences between these steps.':''}</p></section>{d.run.module===3&&finished(d.run)&&<TimingComparison key={d.run.id} d={d} rows={rows}/>}</>;
}

export default function StudyObserver(){
  const study=new URLSearchParams(location.search).get('study');
  const overview=useObservation<Overview>(study?'status?study='+encodeURIComponent(study):'status');
  const [pinned,pin]=useState<string|null>(null);
  const [tab,chooseTab]=useState<'view'|'compare'|'settings'>('view');
  const runs=overview.value?.runs??[];
  const following=useRef<string|null>(null);
  const running=runs.filter(underway);
  const recent=[...runs].sort((a,b)=>b.updated-a.updated);
  const lastStudy=runs.filter(r=>r.study===recent[0]?.study);
  const lastStep=lastStudy.find(r=>r.status==='failed')??lastStudy.find(r=>r.status==='blocked')??lastStudy.filter(finished).at(-1);
  const latest=running.find(r=>r.id===following.current)??running[0]??lastStep??recent[0];
  useEffect(()=>{following.current=latest?.id??null;},[latest?.id]);
  const selected=runs.find(r=>r.id===pinned)??(pinned?undefined:latest);
  const detail=useObservation<Detail>(selected?'runs/'+selected.id+'?attempt='+selected.attempt+'&phase='+selected.status:pinned?'runs/'+pinned:null);
  const d=detail.value&&(!selected||(detail.value.run.attempt===selected.attempt&&detail.value.run.status===selected.status))?detail.value:undefined;
  const r=selected??d?.run,ctx=d?.context;
  const studyNames=new Map(overview.value?.studies.map(s=>[s.id,s.name]));
  const error=overview.error||detail.error;
  return <div className="study-observer">
    <header><strong className="study-wordmark"><img className="product-icon" src="/favicon.svg" width="24" height="24" alt=""/>TwinPALS <b>2.0</b></strong><span className="study-divider"/><span>Study observer</span><span className="study-chip"><Eye size={14}/>Read only</span><span className="study-live"><Radio size={14}/>{overview.value?running.length+' running':'Connecting'}</span></header>
    <main><aside className="study-list"><div className="study-heading"><Layers size={16}/><h2>Studies</h2></div>
    {!runs.length&&<p className="study-empty">{overview.value?'No study steps available.':'Connecting…'}</p>}
    {overview.value?.studies.map(s=><section key={s.id}><h3>{s.name}</h3>{runs.filter(v=>v.study===s.id).map(v=><button key={v.id} className={'study-run '+(r?.id===v.id?'chosen':'')} onClick={()=>pin(v.id)} aria-pressed={r?.id===v.id}><span className="study-run-row"><span className="study-module">M{v.module}</span><strong>{v.name}</strong></span><span className="study-run-state">{phase(v.status)}{underway(v)&&<span>{percent(v.progress)}</span>}</span>{underway(v)&&<progress max={1} value={v.progress}/>}</button>)}</section>)}</aside>
    <article>{error&&<div role="status" className="study-error">{error}</div>}
    {r?<><div className="study-title"><div><small>{studyNames.get(r.study)}{ctx?' · Step '+ctx.step+' of '+ctx.steps:''}</small><h1>{r.name}</h1></div><button className={!pinned?'chosen':''} onClick={()=>pin(pinned?null:r.id)} title={pinned?'Follow the active run':'Keep this run selected'}><Pin size={14}/>{pinned?'Pinned':'Following live'}</button></div>
    {ctx?.objective&&<p className="study-objective">{ctx.objective}</p>}
    <div className="study-metadata"><span className="study-chip">M{r.module} · {modules[r.module]}{ctx?.operation==='import'?' · Import':''}</span>{d&&setupSummary(d)&&<span>{setupSummary(d)}</span>}{ctx?.parent&&<span>Input from <strong>{ctx.parent}</strong></span>}{!!d?.input_files.length&&<span>{d.input_files.join(' · ')}</span>}{underway(r)&&<span>{r.workers} CPU · Attempt {r.attempt}</span>}</div>
    <div className={'study-phase state-'+r.status} role="status">{underway(r)&&<progress value={r.progress} max={1}/>}<b>{phase(r.status)}</b><span>{statusText(r,d)}</span>{underway(r)&&<strong>{percent(r.progress)}</strong>}</div>
    <div className="study-tabs">{([['view','Measurement',Activity],['compare','Study results',ChartColumn],['settings','Run settings',Settings2]] as const).map(([id,label,Icon])=><button key={id} className={tab===id?'chosen':''} onClick={()=>chooseTab(id)} aria-pressed={tab===id}><Icon size={14}/>{label}</button>)}</div>
    {d?tab==='settings'?(Object.keys(d.profile).length?<Settings value={d.profile}/>:<p className="study-empty">Recorded settings become available when the input header is read.</p>):tab==='compare'?<Compare d={d} select={pin}/>:<Measurement key={r.id+'-'+r.attempt} d={d}/>:<div className="study-empty">Reading step details…</div>}</>:<div className="study-empty">{overview.value?(study?'No steps found for this study.':'Waiting for a study'):'Connecting to the study service…'}</div>}</article>
    <aside className="study-events"><div className="study-heading"><Activity size={16}/><h2>Study activity</h2></div>{overview.value?.activity.filter(a=>a.study===r?.study).map(a=><div key={a.id} className="study-event"><time>{new Date(a.at*1000).toLocaleTimeString()}</time><div>{a.message}<small>{runs.find(v=>v.id===a.run)?.name}</small></div></div>)}</aside></main>
    <footer><span>Local study service</span><span>{running.reduce((n,v)=>n+v.workers,0)} {study?'study workers':'/ '+(overview.value?.cpu_total??'—')+' CPU workers'}</span><LegalNotices/><ReleaseUpdates observerToken={observerToken}/></footer>
  </div>;
}
