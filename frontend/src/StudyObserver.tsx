// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect, useState} from 'react';
import {Activity, Eye, Layers, Pin, Radio, Settings2} from 'lucide-react';
import Scene from './Scene';
import LegalNotices from './LegalNotices';
import ReleaseUpdates from './ReleaseUpdates';
import {Plot} from './Plot';
import type {PlotData} from './Plot';
import type {M1Run, Profile} from './m1types';
import type {Entry} from './types';
import './study-observer.css';

type Run={id:string;study:string;name:string;module:number;status:string;progress:number;attempt:number;workers:number;message:string;updated:number};
type Overview={studies:{id:string;name:string}[];runs:Run[];activity:{id:number;at:number;message:string;study:string|null;run:string|null}[];cpu_total:number};
type Detail={run:Run;profile:Record<string,unknown>;metrics:Record<string,unknown>;plot?:PlotData;trajectories?:M1Run['trajectories'];entries?:Entry[]};
const modules=['','Detector response','Digitizer acquisition','Lifetime spectrum'];
const phase=(name:string)=>name.slice(0,1).toUpperCase()+name.slice(1);
const percent=(value:number)=>(100*value).toLocaleString(undefined,{maximumFractionDigits:1})+'%';
const format=(v:unknown)=>typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:3}):String(v??'—');
const measured:Record<string,string>={completed:'Events processed',waveforms:'Waveform pairs',total_processed:'Pairs analyzed',accepted:'Accepted pairs',measurement_ns:'Measurement time (ns)',acquisition_rate_Hz:'Acquisition rate (Hz)',total_events:'Events read',elapsed_s:'Elapsed time (s)'};

function credential(){
  const incoming=location.hash.slice(1);
  if(incoming){
    sessionStorage.setItem('twinpals-observer',incoming);
    history.replaceState(null,'',location.pathname+location.search);
  }
  return sessionStorage.getItem('twinpals-observer')||'';
}
const observerToken=location.pathname==='/observe'?credential():'';

function useObservation<T>(path:string|null){
  const [reply,setReply]=useState<{path:string;value:T}|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    if(!path)return;
    const target=path;
    const abort=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    async function refresh(){
      try{
        const response=await fetch('/observe/api/'+target,{signal:abort.signal,cache:'no-store',headers:{Authorization:'Bearer '+observerToken}});
        if(!response.ok)throw Error(response.status===403?'Open the observer link supplied by the MCP server.':'The study service is reconnecting.');
        const value=await response.json() as T;
        if(!abort.signal.aborted){setReply({path:target,value});setError('');}
      }catch(reason){
        if(!abort.signal.aborted)setError(reason instanceof TypeError?'Reconnecting to the local study service…':String((reason as Error).message));
      }finally{
        if(!abort.signal.aborted)timer=setTimeout(refresh,1500);
      }
    }
    void refresh();
    return ()=>{abort.abort();clearTimeout(timer);};
  },[path]);
  return {value:reply?.path===path?reply?.value:undefined,error};
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

export default function StudyObserver(){
  const overview=useObservation<Overview>('status');
  const [pinned,pin]=useState<string|null>(null);
  const [tab,chooseTab]=useState<'view'|'settings'>('view');
  const runs=overview.value?.runs??[];
  const active=runs.filter(r=>r.status==='running').sort((a,b)=>a.id.localeCompare(b.id));
  const study=new URLSearchParams(location.search).get('study');
  const latest=active.find(r=>r.study===study)??runs.find(r=>r.study===study)??active[0]??runs.find(r=>r.status!=='queued')??runs[0];
  const selected=runs.find(r=>r.id===pinned)??latest;
  const detail=useObservation<Detail>(selected?'runs/'+selected.id:null);
  const d=detail.value;
  const metrics=Object.entries(d?.metrics??{}).filter(([k])=>k in measured);
  const error=overview.error||detail.error;
  const studyNames=new Map(overview.value?.studies.map(s=>[s.id,s.name]));
  const running=runs.filter(r=>r.status==='running'||r.status==='cancelling');
  return <div className="study-observer">
    <header><strong className="study-wordmark"><img className="product-icon" src="/favicon.svg" width="24" height="24" alt=""/>TwinPALS <b>2.0</b></strong><span className="study-divider"/><span>Study observer</span><span className="study-chip"><Eye size={14}/>Read only</span><span className="study-live"><Radio size={14}/>{overview.value?running.length+' running':'Connecting'}</span></header>
    <main>
      <aside className="study-list"><div className="study-heading"><Layers size={16}/><h2>Studies</h2></div>
        {!runs.length&&<p className="study-empty">{overview.value?'Submitted studies will appear here.':'Connecting to the study service…'}</p>}
        {overview.value?.studies.map(s=><section key={s.id}><h3>{s.name}</h3>{runs.filter(r=>r.study===s.id).sort((a,b)=>a.module-b.module||a.name.localeCompare(b.name)).map(r=><button key={r.id} className={'study-run '+(selected?.id===r.id?'chosen':'')} onClick={()=>pin(r.id)} aria-pressed={selected?.id===r.id}>
          <span className="study-run-row"><span className="study-module">M{r.module}</span><strong>{r.name}</strong></span>
          <span className="study-run-state">{phase(r.status)}<span>{percent(r.progress)}</span></span>
          <progress max={1} value={r.progress}/></button>)}</section>)}
      </aside>
      <article>{error&&<div role="status" className="study-error">{error}</div>}
        {selected?<><div className="study-title"><div><small>{studyNames.get(selected.study)}</small><h1>{selected.name}</h1></div>
          <button className={!pinned?'chosen':''} onClick={()=>pin(pinned?null:selected.id)} title={pinned?'Follow the currently running experiment':'Keep this run selected'}><Pin size={14}/>{pinned?'Pinned':'Following live'}</button></div>
          <div className="study-metadata"><span className="study-chip">Module {selected.module} · {modules[selected.module]}</span><span>{selected.workers} CPU</span><span>Attempt {selected.attempt}</span><span>{phase(selected.status)} · {percent(selected.progress)}</span></div>
          <div className="study-tabs"><button className={tab==='view'?'chosen':''} onClick={()=>chooseTab('view')}><Activity size={14}/>Measurement</button><button className={tab==='settings'?'chosen':''} onClick={()=>chooseTab('settings')}><Settings2 size={14}/>Run settings</button></div>
          {tab==='settings'?(d&&<Settings value={d.profile}/>):<>
            {metrics.length>0&&<div className="study-metrics">{metrics.map(([k,v])=><div key={k}><small>{measured[k]}</small><strong>{format(v)}</strong></div>)}</div>}
            <div className={'study-figures '+(selected.module===1?'with-geometry':'')}>
              {d&&selected.module===1&&<div className="study-geometry"><Scene profile={d.profile as unknown as Profile} entries={d.entries} trajectories={d.trajectories??[]} live/></div>}
              {d?.plot?<section className="study-chart"><Plot data={d.plot} preferenceKey={'observer-m'+selected.module}/></section>:<div className="study-empty">{selected.message||'Waiting for measurement data'}</div>}
            </div>
          </>}
        </>:<div className="study-empty">Waiting for a study</div>}
      </article>
      <aside className="study-events"><div className="study-heading"><Activity size={16}/><h2>Activity</h2></div>{overview.value?.activity.map(a=><div key={a.id} className="study-event"><time>{new Date(a.at*1000).toLocaleTimeString()}</time><div>{a.message}<small>{runs.find(r=>r.id===a.run)?.name??studyNames.get(a.study??'')??''}</small></div></div>)}</aside>
    </main>
    <footer><span>Local study service</span><span>{running.reduce((n,r)=>n+r.workers,0)} / {overview.value?.cpu_total??'—'} CPU workers</span><LegalNotices/><ReleaseUpdates observerToken={observerToken}/></footer>
  </div>;
}

