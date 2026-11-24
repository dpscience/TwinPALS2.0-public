// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useState} from 'react';
import {Atom,Box,Layers3} from 'lucide-react';
import type {RecordedApparatus,SourceStream,TransportInput} from './m3types';

import {primaryLabels as roleNames} from './m3types';
const roleName=(input:TransportInput,index:number)=>roleNames[input.role??'']??input.role??('Input '+(index+1));
const sections=['Source and samples','Detector A','Detector B'] as const;
const rows=(apparatus:RecordedApparatus|undefined,section:number)=>section===0?apparatus?.source:apparatus?.detectors[section===1?'A':'B'];
const absent='Not recorded';

export function transportGroups(inputs:TransportInput[]){
 const groups:{roles:string[];apparatus?:RecordedApparatus}[]=[];
 inputs.forEach((input,i)=>{
  const existing=groups.find(g=>JSON.stringify(g.apparatus)===JSON.stringify(input.apparatus));
  if(existing)existing.roles.push(roleName(input,i));
  else groups.push({roles:[roleName(input,i)],apparatus:input.apparatus});
 });
 return groups;
}

export function apparatusProperties(streams:SourceStream[]):[string,(s:SourceStream)=>string][]{
 const result:[string,(s:SourceStream)=>string][]=[];
 result.push(['Transport primaries',s=>s.inputs.map(roleName).join(' / ')||absent]);
 sections.forEach((name,i)=>{
  const keys=new Set(streams.flatMap(s=>s.inputs.flatMap(v=>Object.keys(rows(v.apparatus,i)??{}))));
  for(const key of keys)result.push([name+' · '+key,s=>{
   const values=s.inputs.map((v,j)=>({role:roleName(v,j),value:rows(v.apparatus,i)?.[key]??absent}));
   return new Set(values.map(v=>v.value)).size>1?values.map(v=>v.role+' · '+v.value).join(' / '):values[0]?.value??absent;
  }]);
 });
 return result;
}

export function ApparatusCards({apparatus,all=false}:{apparatus?:RecordedApparatus;all?:boolean}){
 const summary=[['Source','Sample','Left sample','Right sample','Source foils'],['Crystal','Geometry','PMT'],['Crystal','Geometry','PMT']];
 return <div className="m3-apparatus-cards">{sections.map((name,i)=>{
  const values=rows(apparatus,i)??{},entries=Object.entries(values).filter(([k])=>all||summary[i].includes(k));
  return <section key={name}><h4>{i===0?<Atom size={14}/>:<Box size={14}/>} {name}</h4>
   {entries.length?<dl>{entries.map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>:<p>{absent} in this transport header.</p>}</section>;
 })}</div>;
}

export function RecordedSetup({inputs}:{inputs:TransportInput[]}){
 const groups=transportGroups(inputs),[selection,setSelection]=useState(0),[all,setAll]=useState(false);
 const active=groups[selection]??groups[0];
 return <section className="m3-apparatus"><header><h3><Layers3 size={15}/>Module 1 detector setup</h3>
  {groups.length>1?<label>Transport input <select value={selection} onChange={e=>setSelection(+e.target.value)}>{groups.map((group,i)=><option key={i} value={i}>{group.roles.join(' / ')}</option>)}</select></label>:active&&<span className="m3-transport-role">{active.roles.join(' / ')}</span>}
  {active?.apparatus&&<button aria-expanded={all} onClick={()=>setAll(!all)}>{all?'Show summary':'Setup details'}</button>}</header>
  {active?<ApparatusCards apparatus={active.apparatus} all={all}/>:<p>Module 1 geometry was not recorded in this stream.</p>}
 </section>;
}
