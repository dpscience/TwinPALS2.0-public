// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {memo,useMemo,useState} from 'react';
import {ArrowRight,AudioWaveform,GitBranch,Layers3,Route,ScanLine,Zap} from 'lucide-react';
import {Help} from './Fields';
import {OriginBadge,lightNames} from './LightOrigin';
import {Modal} from './Modal';
import {categoryNames,type LifetimeWave,type PulseRoute} from './m3types';
import {primaryName} from './LifetimeContext';

const componentLabel=(value:string)=>({'Sample left_foil':'Left source foil','Sample right_foil':'Right source foil','Sample left_sample':'Left sample','Sample right_sample':'Right sample'}[value]??value);
const time=(ns:number)=>Number(ns.toFixed(3)).toLocaleString('en-GB',{maximumFractionDigits:3});
type Occurrence=LifetimeWave['truth']['selected'][number][number];
type Choice={sequence:number;contributor:number;path:number};

function channelRoutes(wave:LifetimeWave|null,channel:number){
 const contributors=wave?.truth.selected[channel]??[];
 const name='AB'[channel];
 const records=new Map(wave?.transport_truth.map(record=>[record.role+'/'+record.record,record]));
 let scintillation=0,cherenkov=0,known=contributors.length>0;
 const seen=new Set<string>();
 const choices=contributors.map(pulse=>{
  const recordKey=pulse.role+'/'+pulse.record,occurrence=recordKey+'/'+pulse.decay;
  const routes=(records.get(recordKey)?.paths??[]).filter(route=>route.detector===name);
  const count=(route:PulseRoute)=>route.by_cf?.[pulse.decay];
  routes.sort((a,b)=>(count(b)??0)-(count(a)??0)||b.count-a.count);
  if(!seen.has(occurrence)){
   seen.add(occurrence);
   if(!routes.length)known=false;
   for(const route of routes){
    const n=count(route);
    if(n===undefined)known=false;
    else if(route.origin==='Scintillation')scintillation+=n;
    else if(route.origin==='Cherenkov')cherenkov+=n;
   }
  }
  return {pulse,routes};
 });
 const kind=scintillation&&cherenkov?'mixed':!known?'unknown':scintillation?'scintillation':cherenkov?'cherenkov':'none';
 return {choices,kind,scintillation,cherenkov};
}

function Branch({route,pulse}:{route:PulseRoute;pulse:Occurrence}){
 const ch=route.detector,arrivals=route.cathode_arrival_ns,onsets=route.by_cf?.[pulse.decay];
 const arrivalText=arrivals?(time(arrivals[0])===time(arrivals[1])?time(arrivals[0]):time(arrivals[0])+'–'+time(arrivals[1]))+' ns after γ emission':undefined;
 return <ol className="m3-path-stages">
  {route.steps.map((step,i)=><li key={i} className={step.process?'scatter':''}>
   {step.process?<GitBranch/>:<Layers3/>}<span>{step.process?(step.backscatter?'Backscatter · ':'')+step.process:componentLabel(step.component)}
   {step.process&&<small>{componentLabel(step.component)}{step.angle_deg!=null?' · '+step.angle_deg+'°':''}</small>}</span></li>)}
  <li className={'m3-light-step '+route.origin.toLowerCase()}><Zap/><span>{route.origin}<small>Light born in {componentLabel(route.birth)}</small></span></li>
  <li className="m3-light-arrival"><ScanLine/><span>Photocathode {ch}{arrivalText&&<small>{arrivalText}</small>}</span></li>
  <li className="m3-anode-step"><AudioWaveform/><span>Anode {ch}{onsets!==undefined&&<small>{onsets.toLocaleString()} PE {onsets===1?'response':'responses'} started by CF</small>}</span></li>
 </ol>;
}

function ChannelPath({wave,i,hold,pick,choose}:{wave:LifetimeWave|null;i:number;hold?:()=>void;pick:Choice|null;choose:(value:Choice)=>void}){
 const ch='AB'[i],cf=wave?.features[i];
 const {choices,kind,scintillation,cherenkov}=useMemo(()=>channelRoutes(wave,i),[wave,i]);
 const current=pick?.sequence===wave?.sequence?pick:null;
 const selected=current&&choices[current.contributor]?current.contributor:0;
 const contributor=choices[selected],routes=contributor?.routes??[];
 const pathIndex=current&&current.contributor===selected&&routes[current.path]?current.path:0;
 const route=routes[pathIndex];
 const select=(index:number,path:number)=>{if(wave){hold?.();choose({sequence:wave.sequence,contributor:index,path});}};
 const empty=wave?(cf?.valid?'No overlapping record':'No CF crossing'):'No waveform pair';
 const light=!wave?'Awaiting pulse':!cf?.valid?'No CF crossing':kind==='unknown'?'Light unavailable':(kind==='none'?'No PE':lightNames[kind])+' at CF';
 return <section className="m3-channel-path" data-channel={ch}>
  <header><b className={'m3-channel '+ch.toLowerCase()}>Channel {ch}</b>
   <span className="m3-cf-light" title={kind==='unknown'?'The recording has no complete light attribution at this crossing.':scintillation.toLocaleString()+' scintillation and '+cherenkov.toLocaleString()+' Cherenkov PE onsets by CF, across this channel’s overlapping records.'}><OriginBadge kind={kind==='unknown'?'none':kind}>{light}</OriginBadge></span>
   <span className="m3-cf-time">{cf?.valid?'CF '+cf.cfd_ns.toFixed(3)+' ns':'CF —'}</span></header>
  <div className="m3-path-choice">
   <label><span>Decay</span><select aria-label={'Channel '+ch+' transport contributor'} value={selected} disabled={choices.length<2}
    onPointerDown={choices.length>1?hold:undefined} onChange={e=>select(Number(e.target.value),0)}>
    {!choices.length&&<option value={0}>{empty}</option>}
    {choices.map(({pulse},j)=><option key={j} value={j} title={'Record '+pulse.record.toLocaleString()+' · '+(lightNames[pulse.light_origin]??pulse.light_origin)}>{pulse.decay.toLocaleString()} · {primaryName(wave?.primary_roles,pulse.role)} · #{pulse.record.toLocaleString()}</option>)}
   </select></label>
   <label><span>Path</span><select aria-label={'Channel '+ch+' recorded branch'} value={pathIndex} disabled={routes.length<2}
    onPointerDown={routes.length>1?hold:undefined} onChange={e=>select(selected,Number(e.target.value))}>
    {!routes.length&&<option value={0}>No recorded path</option>}
    {routes.map((r,j)=><option key={j} value={j}>{j+1}/{routes.length} · {r.origin} · {componentLabel(r.birth)}</option>)}
   </select></label>
  </div>
  {route&&contributor&&<div className="m3-branch-body"><Branch route={route} pulse={contributor.pulse}/></div>}
 </section>;
}

const explanation='Each channel follows the selected waveform pulse. Decay lists the overlapping records with their gamma energy and record ID. Path selects a recorded branch by light type and birth material. The channel badge combines photoelectron responses that started by its CF crossing. Mixed means both scintillation and Cherenkov contributed by that time. The diagram follows the recorded particle history to light production, then the measured photocathode arrival and PMT response. Intermediate optical reflections are unavailable. Photocathode times are relative to gamma emission. CF times use the digitizer window. Choosing a record or path holds the waveform preview while acquisition continues.';
export const PulseTransport=memo(function PulseTransport({wave,hold}:{wave:LifetimeWave|null;hold?:()=>void}){
 const [detail,setDetail]=useState<LifetimeWave|null>(null);
 const [picks,setPicks]=useState<(Choice|null)[]>([null,null]);
 const lanes=(sample:LifetimeWave|null,holdPreview?:()=>void)=>[0,1].map(i=><ChannelPath key={i} i={i} wave={sample}
  pick={picks[i]} hold={holdPreview} choose={value=>setPicks(previous=>previous.map((choice,ch)=>ch===i?value:choice))}/>);
 const category=wave?categoryNames[wave.truth.category]:'No pair selected';
 return <aside className="m3-transport-panel" aria-label="Selected pulse transport">
  <header><div className="m3-path-title"><Route size={16}/><h3>Pulse transport</h3><Help text={explanation}/></div>
   <strong className="m3-pair-id">{wave?'Pair '+wave.id.toLocaleString():'Selected pair'}</strong>
   <span className="m3-pair-category">{category}</span>
   <button className="m3-open-path" disabled={!wave} onClick={()=>{hold?.();setDetail(wave);}}>View paths <ArrowRight size={12}/></button>
  </header>
  <div className="m3-wide-path">{lanes(wave,hold)}</div>
  {detail&&<Modal wide title={'Pulse transport · pair '+detail.id.toLocaleString()} close={()=>setDetail(null)}>
   <p className="m3-path-dialog-class">{categoryNames[detail.truth.category]}</p><div className="m3-path-dialog">{lanes(detail)}</div>
  </Modal>}
 </aside>;
});
