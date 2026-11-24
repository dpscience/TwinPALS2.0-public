// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Atom,Box} from 'lucide-react';
import type {Detector,Profile,SampleSide} from './m1types';
import type {TransportInput} from './m3types';

const mm=(v:number|undefined)=>Number.isFinite(v)?v+' mm':'—';
function Dimension({x1,x2,y,label}:{x1:number;x2:number;y:number;label:string}){
 return <g className="m3-dimension"><path d={`M${x1} ${y-4}v8m0 -4H${x2}m0 -4v8`}/><text x={(x1+x2)/2} y={y+15} textAnchor="middle">{label}</text></g>;
}
function CrystalSketch({d}:{d:Detector}){
 const dims=d.dimensions,taper=d.shape==='cone'||d.shape==='pyramid',round=d.shape==='cone'||d.shape==='cylinder';
 const front=round?(taper?dims.front_diameter_mm:dims.diameter_mm):(taper?dims.front_height_mm:dims.height_mm);
 const rear=round?(taper?dims.rear_diameter_mm:dims.diameter_mm):(taper?dims.rear_height_mm:dims.height_mm);
 if(![front,rear,dims.length_mm].every(v=>Number.isFinite(v)&&v>0))return null;
 const size=Math.min(66/Math.max(front,rear),142/dims.length_mm),a=front*size/2,b=rear*size/2,x1=140-dims.length_mm*size/2,x2=280-x1,y=69;
 const face=(end:'front'|'rear')=>round?'Ø '+mm(end==='front'?front:rear):((taper?dims[end==='front'?'front_width_mm':'rear_width_mm']:dims.width_mm)??'—')+' × '+mm(end==='front'?front:rear);
 return <svg viewBox="0 0 280 138" role="img" aria-label={d.shape+' crystal, front '+face('front')+', rear '+face('rear')+', length '+mm(dims.length_mm)}>
  <path d={`M${x1} ${y-a}L${x2} ${y-b}V${y+b}L${x1} ${y+a}Z`} className="m3-crystal-body"/>
  {round?<ellipse cx={x2} cy={y} rx={Math.min(7,b*.22)} ry={b} className="m3-crystal-face"/>:<path d={`M${x1} ${y-a}l7 -5L${x2+7} ${y-b-5}v${2*b}l-7 5m0 -${2*b}l7 -5`} className="m3-crystal-facet"/>}
  <path className="m3-leader" d={`M${x1} ${y-a}L${x1-10} 32H17M${x2} ${y-b}L${x2+10} 32H263`}/>
  <text x="16" y="23">Front · {face('front')}</text><text x="264" y="23" textAnchor="end">Rear · {face('rear')}</text>
  <Dimension x1={x1} x2={x2} y={111} label={mm(dims.length_mm)+' length'}/>
 </svg>;
}
function SampleSketch({p}:{p:Profile}){
 const sample=p.sample,g=p.source_geometry;
 if(!g)return null;
 const side=(v:SampleSide|undefined)=>!v?'—':v.shape==='box'?v.width_mm+' × '+mm(v.height_mm):'Ø '+mm(v.diameter_mm);
 const slab=(v:SampleSide,x:number,name:string)=><g key={name}><rect x={x} y="49" width="42" height="52" rx={v.shape==='box'?0:4} className="m3-sample-body"/>
  <text x={x+21} y="25" textAnchor="middle">{name}</text><text x={x+21} y="40" textAnchor="middle">{side(v)}</text>
  <Dimension x1={x} x2={x+42} y={110} label={mm(v.thickness_mm)}/></g>;
 return <svg viewBox="0 0 280 138" role="img" aria-label="Recorded source and sample cross-section, exploded schematic">
  {sample?.enabled&&sample.left&&slab(sample.left,37,'Left sample')}{sample?.enabled&&sample.right&&slab(sample.right,201,'Right sample')}
  {sample?.foil_enabled&&<g className="m3-foil"><rect x="103" y="51" width="4" height="48"/><rect x="173" y="51" width="4" height="48"/></g>}
  <path d="M16 75H264" className="m3-axis"/>{g.radius_mm===0&&g.thickness_mm===0?<circle cx="140" cy="75" r="4" fill="#b77528"/>:<rect x="136" y="57" width="8" height="36" rx="3" fill="#b77528"/>}
  <text x="140" y="40" textAnchor="middle">{g.radius_mm===0&&g.thickness_mm===0?'Point source':'Source'}</text>
  {sample?.foil_enabled&&<><path className="m3-leader" d="M105 101v8l12 8m58-16v8l-12 8"/><text x="140" y="129" textAnchor="middle">Foils</text></>}
 </svg>;
}
function Properties({values}:{values?:Record<string,string>}){
 return values&&Object.keys(values).length?<dl>{Object.entries(values).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>:<p>Details unavailable in this recording.</p>;
}
export function DetectorDrawings({input}:{input?:TransportInput}){
 const p=input?.setup,a=input?.apparatus;
 return <div className="m3-drawings"><section className="m3-source-drawing"><header><Atom size={16}/><h3>Source and samples</h3><span>Exploded section</span></header>
 <div className="m3-source-detail">{p?.source_geometry&&<figure><SampleSketch p={p}/><figcaption>{p.source_geometry.radius_mm>0&&<span>Source · Ø {mm(2*p.source_geometry.radius_mm)} · {mm(p.source_geometry.thickness_mm)} thick</span>}{p.sample?.foil_enabled&&<span>Foils · Ø {mm(p.sample.foil_diameter_mm)} · {mm(p.sample.foil_thickness_mm)} each</span>}</figcaption></figure>}<Properties values={a?.source}/></div></section>
 {(['A','B'] as const).map(ch=>{const d=p?.detectors?.find(v=>v.id===ch),facts=a?.detectors[ch];return <section key={ch} data-channel={ch}><header><Box size={16}/><h3>Detector {ch}</h3><span>{d?.shape}</span></header>
 {d?.dimensions&&<figure><CrystalSketch d={d}/></figure>}<Properties values={facts}/></section>;})}</div>;
}
