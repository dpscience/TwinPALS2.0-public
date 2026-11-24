// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {OriginBadge} from './LightOrigin';
import {useEffect,useRef,useState} from 'react';
import {Plot} from './Plot';
import type {PlotData} from './Plot';
import {api,number} from './api';
import {PersistencePlot} from './PersistencePlot';
import {CathodeMap} from './CathodeMap';
import {usePreference} from './Preferences';
import {roleNames} from './Simulation';
import {pollDensityBank} from './densityPolling';
import type {DensityBank} from './densityPolling';
import {processingProgress} from './processingProgress';
import type {StreamProgress} from './processingProgress';
type Source={paths?:string[];run_id?:string};
type EventRef={event_id:number;role:string};
type EventPlots={contributions:PlotData["series"];provenance:{detector:string;kind:string;scintillation:number;cherenkov:number;births:{label:string;photons:number}[]}[];pulse:PlotData;arrivals:PlotData & {summary:{detector:string;count:number;mean_ns:number|null}[]}};
const pulseExplanation={text:'Anode current of this retained event, relative to gamma emission.\n- Every QE-accepted photon arrival drives one charge-normalized Erlang response. The stored independent per-photoelectron TTS and calibrated transit time are included.\n- Integrated charge magnitude = Npe × elementary charge × gain. Current is in mA; output voltage is current × the stored effective load.\n- No source overlap, digitizer, sampled positron lifetime or cable delay is present. Module 2 applies those later.\n- The stored analytic pulse has an infinite tail. The plotted interval leaves less than 10⁻¹² of each photoelectron charge beyond its upper limit.'};

export function DetectorInset({source,preview,bins,roles,revision,mode,scope='',processingStreams=[],accumulating=false}:{processingStreams?:StreamProgress[];accumulating?:boolean;scope?:string;mode?:'map'|'persistence';source:Source;preview?:EventRef;bins:number;roles:string[];revision:number}){
 const [choice,setChoice]=usePreference('detector_inset'),{detector}=choice;
 const tab=mode??choice.tab,eventMode=tab==='current'||tab==='arrivals';
 const primary=choice.primary==='all'||roles.includes(choice.primary)?choice.primary:'all';
 const inset=useRef<HTMLDivElement>(null);
 const [eventPlots,setEventPlots]=useState<{event:EventRef;plots:EventPlots}|null>(null);
 const [bank,setBank]=useState<DensityBank|null>(null);
 const map=bank?.bins===bins?bank.maps.find(v=>v.detector===detector&&v.primary===primary)??null:null;
 const density=bank?.bins===bins?bank.persistence.find(v=>v.detector===detector&&v.primary===primary&&(v.origin??'all')===(choice.origin??'all'))??null:null;
 const progress=processingProgress(processingStreams,primary);
 const included=bank?.bins===bins?Object.entries(bank.processed_events??{}).reduce((n,[role,count])=>n+(primary==='all'||primary===role?count:0),0):0;
 const components=choice.contributions;
 const setComponents=(value:boolean)=>setChoice(v=>({...v,contributions:value}));
 const [error,setError]=useState(''),[densityError,setDensityError]=useState(''),[busy,setBusy]=useState(false);
 const activity={active:!densityError&&(accumulating||included<progress.processed),processed:included,total:progress.total,label:'≥'};
 const state=useRef({source,preview,bins,detector,primary,revision,tab});
 state.current={source,preview,bins,detector,primary,revision,tab};
 const key=JSON.stringify(source);
 useEffect(()=>{
  const element=inset.current,parent=element?.closest('.scene-panel') as HTMLElement|null;
  if(!element||!parent)return;
  const observer=new ResizeObserver(()=>parent.style.setProperty('--detector-inset-height',`${element.getBoundingClientRect().height}px`));
  observer.observe(element);
  return()=>{observer.disconnect();parent.style.removeProperty('--detector-inset-height');};
 },[]);
 useEffect(()=>{setEventPlots(null);setBank(null);},[key]);

 // Fetch a complete prepared bank independently of tab/filter choice. Changing
 // detector or ancestry is a local lookup, including the first visit to a tab.
 useEffect(()=>{
  setDensityError('');
  return pollDensityBank(source,bins,setBank,setDensityError);
 },[key,bins]);

 useEffect(()=>{setEventPlots(null);},[scope]);
 // Load both event views together so changing tabs cannot pair different events.
 const requestMode=eventMode?'event':tab;
 useEffect(()=>{
  if(!eventMode)return;
  let stopped=false,timer:ReturnType<typeof setTimeout>,last='';
  const controller=new AbortController();
  const tick=async()=>{
   const s=state.current,isEvent=s.tab==='current'||s.tab==='arrivals';
   const version=JSON.stringify(isEvent?['event',s.preview?.role,s.preview?.event_id,s.bins]:[s.tab,s.revision,s.bins,s.detector,s.primary]);
   if(version!==last){
    setError('');if(!last)setBusy(true);
    const request=(body:object)=>({method:'POST',body:JSON.stringify(body),signal:controller.signal});
    try{
     if(isEvent&&s.preview){
      const result=await api<EventPlots>('/m1/event-plots',request({...s.source,...s.preview,bins:s.bins}));
      if(!stopped&&state.current.preview)setEventPlots({event:s.preview,plots:{...result,pulse:{...result.pulse,explanation:pulseExplanation}}});
     }
     last=version;
    }catch(e){
     if(!stopped){setError((e as Error).message);setBusy(false);}
     // Retry temporarily unavailable previews, including while paused.
    }finally{if(!stopped&&s.tab!=='persistence')setBusy(false);}
   }
   if(!stopped)timer=setTimeout(tick,isEvent?100:500);
  };
  void tick();return()=>{stopped=true;clearTimeout(timer);controller.abort();};
 },[key,requestMode,bins,scope]);

 const visible=preview?eventPlots:null;
 const shown=visible?.event,arrivals=visible?.plots.arrivals;
 const eventPending=!!preview&&(!shown||shown.event_id!==preview.event_id||shown.role!==preview.role);
 return <div ref={inset} className={mode?'density-analysis':'detector-inset'}>
  {!mode&&<nav aria-label="Detector inset">
   <button title="Cathode arrival times of QE-accepted photons for the same preview event as Anode I(t)" className={tab==='arrivals'?'active':''} onClick={()=>setChoice(v=>({...v,tab:'arrivals'}))}>Arrival times</button>
   <button title="Anode current of the selected preview event, including PMT transit time and TTS" className={tab==='current'?'active':''} onClick={()=>setChoice(v=>({...v,tab:'current'}))}>Anode I(t)</button>
   <button title="All charge-normalized anode pulses, overlaid without time alignment" className={tab==='persistence'?'active':''} onClick={()=>setChoice(v=>({...v,tab:'persistence'}))}>Persistence</button>
   <button title="Accumulated QE-accepted photocathode hit positions from all events" className={tab==='map'?'active':''} onClick={()=>setChoice(v=>({...v,tab:'map'}))}>Cathode map</button>
  </nav>}
  <div className="inset-body">
  {!eventMode?<>
   <div className={`inset-filters ${tab==='persistence'?'with-origin':''}`}>
    <select aria-label="Inset detector" title="Select detector A or B" value={detector} onChange={e=>setChoice(v=>({...v,detector:e.target.value as 'A'|'B'}))}><option value="A">Detector A</option><option value="B">Detector B</option></select>
    <select aria-label="Inset primary" title="Primary ancestry; includes all events, independently of the preview filter" value={primary} onChange={e=>setChoice(v=>({...v,primary:e.target.value}))}><option value="all">All primaries</option>{roles.map(r=><option key={r} value={r}>{roleNames[r]}</option>)}</select>
    {tab==='persistence'&&<select aria-label="Persistence origin" title="Whole anode pulses classified by accepted light: scintillation, Cherenkov, or both. All selections are prepared in the background." value={choice.origin??'all'} onChange={e=>setChoice(v=>({...v,origin:e.target.value}))}><option value="all">All origins</option><option value="scintillation">Scintillation</option><option value="cherenkov">Cherenkov</option><option value="mixed">Mixed</option></select>}
   </div>
   {tab==='persistence'?<PersistencePlot activity={activity} data={density} busy={!error&&!densityError&&!density}/>:<CathodeMap activity={activity} data={map} busy={!error&&!densityError&&!map}/>}
  </>:<>
   <div className="event-origin-row">{visible?.plots.provenance?.map(p=><span key={p.detector} title={`${p.scintillation} scintillation + ${p.cherenkov} Cherenkov photoelectrons${p.births.length?' · '+p.births.map(b=>`${b.label}: ${b.photons}`).join(', '):''}`}><OriginBadge kind={p.kind}>{p.detector} · {p.kind==='none'?'No pulse':p.kind==='mixed'?'Mixed':p.kind==='cherenkov'?'Cherenkov':'Scintillation'}</OriginBadge></span>)}{tab==='current'&&<label title="Separate currents from accepted scintillation and Cherenkov photons; their sum equals the total detector current"><input type="checkbox" checked={components} onChange={e=>setComponents(e.target.checked)}/>Contributions</label>}</div>
   {visible?<Plot data={tab==='arrivals'?visible.plots.arrivals:components?{...visible.plots.pulse,series:visible.plots.contributions}:visible.plots.pulse} preview compact preferenceKey={tab==='arrivals'?'event-arrivals':'current-event'}/>:<div className="inset-empty" role="status">{busy&&<span className="spinner"/>}{preview?'Loading selected event…':'No retained event matches this selection'}</div>}
   {tab==='arrivals'&&arrivals&&<div className="arrival-counts">{arrivals.summary.map(s=><span key={s.detector} title={`${s.count} QE-accepted photons${s.mean_ns===null?'; mean undefined':`; mean arrival ${number(s.mean_ns,4)} ns after gamma emission`}`}><i style={{background:s.detector==='A'?'#198f8c':'#688aca'}}/><b>{s.detector}</b> {number(s.count)} photons{s.mean_ns!==null&&<> · mean {number(s.mean_ns,3)} ns</>}</span>)}</div>}
   <span className="inset-caption">{shown?`${roleNames[shown.role]} · event ${shown.event_id}`:'Retained event preview'}{eventPending&&shown&&<span className="event-fetch" title="The previous event stays visible until the selected event has loaded" role="status"><span className="spinner"/>Updating event</span>}</span>
  </>}
  {(error||densityError)&&<p className="inline-error">{error||densityError}</p>}
  </div>
 </div>;
}
