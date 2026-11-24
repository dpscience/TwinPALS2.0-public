// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {api} from './api';
import {Plot,type PlotData,type PlotSeries} from './Plot';
import {PulseTransport} from './PulseTransport';
import {baselineRegions,gateReason,plotDelayMs,type Adc,type LifetimeChannel,type LifetimeJob,type LifetimeWave,type MonitorView} from './m3types';
import {LiveNumber} from './LifetimeTuning';

type Wave=LifetimeWave & {smoothed:(number[]|null)[];interpolated:([number,number][]|null)[];adc:Adc[]};
type Snapshot={key:string;wave:Wave;sequences:number[]};
const fmt=(v:number|null|undefined)=>v==null?'—':Number(v.toPrecision(5)).toLocaleString('en-GB',{maximumFractionDigits:4});
export function LifetimePair({job,channels,m,patch,adc,rule,retained,setRetained,visible,runSignal}:{runSignal:AbortSignal;job:LifetimeJob|null;channels:LifetimeChannel[];m:MonitorView;patch:(v:MonitorView)=>void;adc:Adc[];rule:'first'|'highest';retained:number;setRetained:(n:number)=>void;visible:boolean}){
 const [sample,setSample]=useState<Snapshot|null>(null),[error,setError]=useState('');
 const [delayed,setDelayed]=useState<{key:string;sequence:number}|null>(null);
 const [frozen,freeze]=useState<{key:string;sequences:number[];index:number}|null>(null);
 const epoch=[job?.id,job?.preview_generation,retained,rule,JSON.stringify(channels)].join('|');
 const paused=frozen?.key===epoch?frozen:null;
 const inSession=!!job&&['running','paused','pausing','stopping'].includes(job.status);
 const aligned=!inSession||(!job.pending&&job.profile.preview_count===retained&&job.profile.pulse_selection===rule&&JSON.stringify(job.profile.channels)===JSON.stringify(channels));
 const sequences=aligned?(paused?.sequences??job?.preview.slice(-retained).map(v=>v.sequence)??[]):[];
 const seq=paused?sequences[paused.index]:sequences.at(-1);
 const options=JSON.stringify({id:job?.id,channels,traces:m.traces,pulse_selection:rule});
 const key=epoch+'|'+options;
 const latest=useRef({seq,sequences});latest.current={seq,sequences};
 const hasPair=seq!==undefined;
 // At most one waveform request at a time. A faster acquisition cannot starve the preview.
 useEffect(()=>{
  if(!visible||!hasPair||runSignal.aborted)return;
  const abort=new AbortController();let timer:ReturnType<typeof setTimeout>,probe:ReturnType<typeof setTimeout>,last:number|undefined;
  const signal=AbortSignal.any([abort.signal,runSignal]);
  const read=async()=>{
   if(signal.aborted)return;
   const request=latest.current;
   try{if(request.seq!==undefined&&request.seq!==last){
    const sequence=request.seq;
    probe=setTimeout(()=>{if(!signal.aborted)setDelayed({key,sequence});},plotDelayMs);
    const w=await api<Wave>('/m3/waveform/'+request.seq,{method:'POST',body:options,signal});
    if(!signal.aborted){last=request.seq;setSample({key,wave:w,sequences:request.sequences});setError('');}
   }}catch(e){if(!signal.aborted)setError((e as Error).message);}
   finally{clearTimeout(probe);if(!signal.aborted)setDelayed(null);}
   if(!signal.aborted&&!paused&&inSession)timer=setTimeout(read,350);
  };
  setDelayed(null);void read();return ()=>{abort.abort();clearTimeout(timer);clearTimeout(probe);};
 },[visible,hasPair,key,paused,options,inSession,runSignal,inSession?undefined:seq]);
 const wave=sample?.key===key&&aligned&&(!paused||sample.wave.sequence===seq)?sample.wave:null;
 const display=wave??(paused&&sample?.key===key?sample.wave:null);
 const waiting=!!job&&!error&&(!display||!!paused&&!wave);
 const plots=useMemo(()=>[0,1].map((i):PlotData=>{
  const f=display?.features[i],x=display?.samples[2*i]??[],y=display?.samples[2*i+1]??[],bounds=display?.adc[i]??adc[i],colors=['#128c90','#6685c7'];
  const pts=(v:number[])=>x.map((t,j)=>[t,v[j]] as [number,number]);
  const series:PlotSeries[]=[{name:'ADC samples',color:colors[i],points:pts(y)}];
  if(display?.smoothed[i])series.push({name:'Median-filtered pulse',color:'#b27630',points:pts(display.smoothed[i]!),dashed:true});
  if(display?.interpolated[i])series.push({name:'Interpolated pulse',color:'#984d94',points:display.interpolated[i]!,dashed:true});
  const region=baselineRegions(m.show_baseline)[i]?f?.baseline_region:undefined;
  const levels:NonNullable<PlotData['levels']>=[];
  if(region&&f)levels.push({y:f.baseline,label:'Baseline '+fmt(f.baseline)+' mV',color:'#548069'});
  if(f?.valid)levels.push({y:f.cfd_level_mV!,label:'CF '+fmt(f.cfd_percent!)+'%',color:'#9970a8'});
  return {title:'Waveform · '+'AB'[i],xLabel:'Time in acquisition window (ns)',yLabel:'Voltage (mV)',series,
   fixedY:m.autoscale[i]?undefined:[bounds?.low??-500,bounds?.high??500],markerLabelsOutside:true,hideMarkerReadouts:true,
   levels,bands:region?[{low:region.start_ns,high:region.end_ns,color:'#548069',label:'Baseline region',description:region.count+' ADC samples · '+fmt(region.start_ns)+' to '+fmt(region.end_ns)+' ns'}]:[],
   markers:f?.valid?[{x:f.peak_ns,label:'Selected peak',color:colors[i]},{x:f.cfd_ns,label:'CF time',color:'#86609a'}]:[],emptyText:'No waveform pairs'};
 }),[display,m.autoscale,m.show_baseline,adc]);
 const holdPreview=useCallback(()=>{
  if(!paused&&sample&&wave)freeze({key:epoch,sequences:sample.sequences,index:sample.sequences.length-1});
 },[epoch,paused,sample,wave]);
 const pos=paused?paused.index+1:(sample?.key===key?sample.sequences.length:0);
 return <div className="m3-pulse-view"><div className="m3-timing-content"><div className="m3-timing-grid">{plots.map((data,i)=>{
  const f=display?.features[i],gate=display?.gates[i];
  const quantities:[string,number|null|undefined,string][]=[['Height',f?.height,'mV'],['Peak time',f?.peak_ns,'ns'],['CF time',f?.valid?f.cfd_ns:null,'ns'],['Rise 10–90%',f?.rise_ns,'ns'],['Fall 90–10%',f?.fall_ns,'ns']];
  return <section className="m3-timing-cell" key={i}><div className="lifetime-waveform"><Plot data={data} preferenceKey={'module3.timing.'+i} activity={visible&&delayed?.key===key&&display?.sequence!==delayed.sequence?{active:true,description:'Reading waveform pair '+delayed.sequence.toLocaleString()+' from the pulse stream.'}:undefined} titleAdornment={<label className="m3-auto"><input type="checkbox" checked={m.autoscale[i]} onChange={e=>{const autoscale:[boolean,boolean]=[...m.autoscale];autoscale[i]=e.target.checked;patch({...m,autoscale});}}/>Autoscale voltage</label>}/></div>
  <div className="m3-pulse-readout"><div><small>Window / selection</small><b title={gate&&!gate[0]?gateReason(gate[1]):undefined} className={'m3-pill '+(gate?.[0]??'')}>{gate?.[0]?gate[0]==='start'?'Start window':'Stop window':gate?gateReason(gate[1]):'—'}</b></div>{quantities.map(([label,v,unit])=><div key={label}><small>{label}</small><output>{fmt(v)} {v!=null&&unit}</output></div>)}</div></section>;
 })}</div><PulseTransport wave={display} hold={holdPreview}/></div><div className="m2-preview-controls m3-preview-controls">
 <button disabled={!wave&&!paused} onClick={()=>{if(paused)freeze(null);else holdPreview();}}>{paused?'Resume preview':'Pause preview'}</button>
 <button disabled={!paused||paused.index===0||waiting} onClick={()=>paused&&freeze({...paused,index:paused.index-1})}>Previous</button>
 <button disabled={!paused||paused.index===paused.sequences.length-1||waiting} onClick={()=>paused&&freeze({...paused,index:paused.index+1})}>Next</button>
 <span className="preview-position">{pos} / {paused?.sequences.length??pos}</span>
 <label className="m3-retained">Retained pairs <LiveNumber name="Retained preview pairs" value={retained} min={1} max={256} step={1} confirmEdit change={setRetained}/></label>
 {error&&<span role="alert">{error}</span>}</div></div>;
}

