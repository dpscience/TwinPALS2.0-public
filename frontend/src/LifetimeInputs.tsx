// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useState,type ReactNode} from 'react';
import {Activity,Atom,Box,CircuitBoard,FileInput,FolderOpen,X} from 'lucide-react';
import Scene from './Scene';
import {M2Schematic} from './M2Schematic';
import {Modal} from './Modal';
import {transportGroups} from './RecordedSetup';
import {DetectorDrawings} from './DetectorDrawings';
import {Help} from './Fields';
import {percent} from './api';
import {plotDelayMs,primaryLabels as primary,type InputInspection,type SourceStream} from './m3types';

const n=(v:number|null|undefined)=>typeof v==='number'?v.toLocaleString('en-GB',{maximumFractionDigits:3}):'—';
const isotope=(s:SourceStream)=>s.source==='na22'?'Na-22':s.source==='co60'?'Co-60':s.source;
const trigger=(s:SourceStream)=>s.acquisition.trigger==='coincidence'?'A AND B':s.acquisition.trigger==='either'?'A OR B':s.acquisition.trigger??'—';
const clock=(s:SourceStream)=>s.digitizer.samples&&s.digitizer.rate_GSps?n(s.digitizer.samples/s.digitizer.rate_GSps)+' ns':'—';
function factLines(value:string){return value.split(' · ').map((part,i)=><span className="m3-fact-line" key={i}>{part.replace(/(\d) (?=mm\b|mV\b|ns\b|ps\b|keV\b|Bq\b|GS\/s\b|GB\b|dB\b|bit\b|V\b|Ω)/g,'$1\u00a0')}</span>);}
function Facts({rows}:{rows:[string,string][]}){return <dl className="m3-source-list">{rows.map(([key,value])=><div key={key}><dt>{key}</dt><dd>{factLines(value)}</dd></div>)}</dl>;}

const channelIds=['A','B'] as const;
function InstrumentTable({title,rows}:{title:string;rows:[string,ReactNode[]][]}){
 return <section className="m3-settings-section"><h3>{title}</h3><table className="m3-channel-table m3-instrument-table" aria-label={title}><thead><tr><td/>{channelIds.map(ch=><th scope="col" key={ch}><b className={'m3-channel '+ch.toLowerCase()}>Channel {ch}</b></th>)}</tr></thead><tbody>
 {rows.filter(([,values])=>values.some(v=>v!=null)).map(([label,values])=><tr key={label}><th scope="row">{label}</th>{channelIds.map((ch,i)=><td key={ch}>{values[i]||'—'}</td>)}</tr>)}</tbody></table></section>;
}
function recordedValues(s:SourceStream,key:string,group:'instrument'|'detectors'='instrument'){
 return channelIds.map(ch=>{
  const rows=s.inputs.map(input=>({role:primary[input.role??'']??input.role,value:input.apparatus?.[group]?.[ch]?.[key]}));
  if(!rows.some(row=>row.value))return null;
  if(rows.every(row=>row.value===rows[0].value))return factLines(rows[0].value!);
  return rows.map((row,i)=><span className="m3-role-fact" key={i}><small>{row.role}</small>{factLines(row.value??'—')}</span>);
 });
}
export function StreamInputs({path,inspection,locked,inspecting,reload,change,browse}:{path:string;inspection:InputInspection;locked:boolean;inspecting:boolean;reload:()=>void;change:(v:string)=>void;browse:(path:string)=>Promise<string|null>}){
 const s=inspection.streams[0],err=inspection.errors[0];
 const sampleRate=n(s?.digitizer.rate_GSps)+' GS/s';
 const deviceName=s?.digitizer.name?.split(' · ').filter(part=>part!==sampleRate).join(' · ')||'—';
 return <><section className="m3-settings-section"><div className="input-reload-heading"><h3>Pulse stream <Help text="Select one Module 2 pulse stream. A stopped or partial recording contributes its complete waveform pairs. Stop reading to change the input."/></h3><button disabled={locked||inspecting||!path.trim()} onClick={reload} title="Read the header and file size again after a Module 2 recording changes at this path">{inspecting&&!!path&&<span className="spinner"/>}Reload input</button></div>
 <fieldset className="m3-stream-picker" disabled={locked}><div className="lifetime-input"><input aria-label="Pulse stream path" value={path} placeholder="Select a Module 2 pulse stream" onChange={e=>change(e.target.value)}/><button title="Browse pulse stream" onClick={async()=>{const v=await browse(path);if(v)change(v);}}><FolderOpen size={15}/></button><button title="Clear pulse stream" disabled={!path} onClick={()=>change('')}><X size={13}/></button></div></fieldset>
 {err&&<p role="alert" className="m3-error">{err.message}</p>}</section>{s&&<>
 <section className="m3-settings-section"><h3>Recording</h3><Facts rows={[[ 'File',s.name],['Size',n(s.bytes/1e9)+' GB'+(s.partial?' · partial':'')],['Recorded',s.created_utc?new Date(s.created_utc).toLocaleString():'—'],...(s.class_filter&&s.class_filter!=='all'?[['Recorded class',s.class_filter] as [string,string]]:[])]}/></section>
 <section className="m3-settings-section"><h3>Source</h3><Facts rows={[[ 'Isotope',isotope(s)],['Activity',n(s.activity_Bq)+' Bq'],['Primaries',s.inputs.map(x=>primary[x.role??'']??x.role).join(' · ')]]}/></section>
 <InstrumentTable title="Scintillators" rows={[[ 'Material',recordedValues(s,'Crystal','detectors')],...['Shape','Front face','Rear face','Cross section','Length'].map((k):[string,ReactNode[]]=>[k,recordedValues(s,k)])]}/>
 <InstrumentTable title="Photomultipliers" rows={['Model','Bias voltage','Load','Cathode shape','Active face'].map(k=>[k,recordedValues(s,k)])}/>
 <InstrumentTable title="Analogue channels" rows={[[ 'ADC range',s.adc.map(a=>factLines(n(a.low)+'…'+n(a.high)+' mV'))],['Polarity',s.adc.map(a=>a.polarity)],['Attenuation',s.channels.map(c=>factLines(n(c.attenuation_dB)+' dB'))],['Cable delay',s.channels.map(c=>c.cable_delay_ns==null?'Unrecorded':factLines(n(c.cable_delay_ns)+' ns'))]]}/>
 <section className="m3-settings-section"><h3>Digitizer &amp; trigger</h3><Facts rows={[[ 'Digitizer',deviceName],['Samples',n(s.digitizer.samples)],['Sample rate',sampleRate],['Readout window',clock(s)],['ADC resolution',n(s.digitizer.adc_bits)+' bit'],['Trigger',trigger(s)],...(s.acquisition.trigger==='coincidence'?[['Coincidence',n(s.acquisition.coincidence_ns)+' ns'] as [string,string]]:[]),...channelIds.map((ch,i):[string,string]=>['Threshold '+ch,n(s.channels[i]?.threshold_mV)+' mV'])]}/></section>
 </>}</>;
}

function SourceTiming({s}:{s:SourceStream}){
 if(s.source==='co60')return <section className="m3-overview-card source-timing"><h3><Atom size={15}/>Co-60 cascade</h3><div className="m3-cascade" role="img" aria-label="One decay emits the correlated 1173 and 1332 keV gamma rays"><b>Co-60 decay</b><span>→</span><b>1173 keV γ</b><span>→</span><b>1332 keV γ</b></div><p>Both transport records share a decay. Module 2 models the cascade as prompt.</p></section>;
 return <section className="m3-overview-card source-timing"><h3><Activity size={15}/>Simulated lifetimes</h3><table><thead><tr><th>Component</th><th>Lifetime</th><th colSpan={2}>Intensity</th></tr></thead><tbody>{s.lifetimes.map((c,i)=><tr key={i}><td>{c.name}<small>{c.distribution}</small></td><td>{n(c.tau_ns*1000)} ps</td><td><span className="m3-intensity" title={c.name+' · '+percent(c.intensity*100)}><i style={{width:(c.intensity*100)+'%'}}/></span></td><td>{percent(c.intensity*100)}</td></tr>)}</tbody></table></section>;
}

export function InputDiagram({source:s,loading}:{source?:SourceStream;loading:boolean}){
 const [index,setIndex]=useState(0),[details,setDetails]=useState(false),[slow,setSlow]=useState(false);
 useEffect(()=>{
  if(!loading){setSlow(false);return;}
  const timer=setTimeout(()=>setSlow(true),plotDelayMs);
  return ()=>clearTimeout(timer);
 },[loading]);
 if(!s)return <div className="m3-input-empty" aria-busy={loading}>{loading&&slow?<><span className="spinner"/>Reading stream header…</>:<><FileInput size={27}/>{!loading&&<p>Select a Module 2 pulse stream in Input to see its recorded setup.</p>}</>}</div>;
 const group=transportGroups(s.inputs),selected=s.inputs[index]??s.inputs[0],geometry=selected?.setup,e=s.electronics;
 const hasScene=geometry?.detectors?.length===2&&geometry.sample&&geometry.shields&&geometry.source_geometry&&geometry.assembly;
 const maxima=s.inputs.every(p=>p.maximum_mV?.length===2)?[0,1].map(i=>Math.max(...s.inputs.map(p=>p.maximum_mV![i]))):undefined;
 const chain=e?.device?.id&&e.profile?.digitization&&e.responses.length===2?{profile:e.profile,device:e.device,recorded:{digitization:e.profile.digitization,dead:e.profile.acquisition.dead_ns,responses:e.responses,maximum:maxima,source:isotope(s)}}:null;
 return <div className="m3-overview">
 <div className="m3-overview-models"><section className="m3-overview-card m3-geometry"><header><h3><Box size={15}/>Detector assembly</h3>{group.length>1&&<select aria-label="Transport geometry" value={index} onChange={e=>setIndex(+e.target.value)}>{s.inputs.map((p,i)=><option value={i} key={p.role}>{primary[p.role??'']??p.role}</option>)}</select>}<button disabled={!selected?.apparatus} onClick={()=>setDetails(true)}>Setup details</button></header>
 {hasScene?<Scene key={selected.role} profile={geometry} entries={selected.entries} archived/>:<p className="m3-input-empty">Geometry was not recorded in this transport stream.</p>}
 <div className="m3-apparatus-key">{(['A','B'] as const).map(ch=><div key={ch}><b className={'m3-channel '+ch.toLowerCase()}>Detector {ch}</b><span>{selected?.apparatus?.detectors[ch]?.Crystal??'—'}<small>{selected?.apparatus?.detectors[ch]?.PMT??'—'}</small></span></div>)}</div></section>
 <section className="m3-overview-card m3-electronics"><header><h3><CircuitBoard size={15}/>Acquisition chain</h3><div className="m3-cable-key" aria-label="Recorded cable delays"><span>Cable delay</span>{channelIds.map((ch,i)=><b className={'m3-channel '+ch.toLowerCase()} key={ch}>{ch} · {s.channels[i]?.cable_delay_ns==null?'Unrecorded':n(s.channels[i].cable_delay_ns)+' ns'}</b>)}</div></header>{chain?<M2Schematic {...chain}/>:<p>Digitizer schematic unavailable in this stream.</p>}</section></div>
 <div className="m3-overview-records"><SourceTiming s={s}/><section className="m3-overview-card"><h3><FileInput size={15}/>Transport records</h3>
 {s.inputs.map(p=><div className="m3-transport-file" key={p.role}><b>{primary[p.role??'']??p.role}</b><span title={p.path}>{p.path.split(/[\\/]/).at(-1)}</span></div>)}
 <div className="m3-recorded-sample">{['Left sample','Right sample','Source foils'].map(k=>selected?.apparatus?.source[k]&&<div key={k}><span>{k}</span><b>{selected.apparatus.source[k]}</b></div>)}</div></section></div>

 {details&&<Modal wide title="Recorded detector setup" close={()=>setDetails(false)}><DetectorDrawings input={selected}/></Modal>}</div>;
}
