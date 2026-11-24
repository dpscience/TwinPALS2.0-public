// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useContext,useState,type CSSProperties} from 'react';
import {ChartNoAxesColumn,ChevronDown,ChevronRight} from 'lucide-react';
import {contributionName,traceColor} from './ContributionGraphic';
import {Help} from './Fields';
import {classKeys} from './lifetimeEditing';
import {SpectrumHover} from './SpectrumLegend';
import {subtypeFor,subtypeKeys} from './spectrumSubtypes';
import type {SpectrumComparison} from './m3types';

type Props={isotope?:string;comparison?:SpectrumComparison;categories?:string[]};
function percent(count:number,total:number,digits=3){
 if(!total)return '—';
 const share=100*count/total;
 if(count>0 && share<10**-digits)return '<'+(10**-digits).toLocaleString(undefined,{maximumFractionDigits:digits})+'%';
 return share.toLocaleString(undefined,{maximumFractionDigits:digits})+'%';
}

export function ContributionShares({isotope,comparison,categories}:Props){
 const {active}=useContext(SpectrumHover);
 const [open,setOpen]=useState<string[]>([]);
 const stages=comparison?.stages;
 const parents=categories??classKeys.filter(k=>k!=='annihilation_pair'||isotope!=='co60');
 const children=subtypeKeys(isotope,Object.keys(stages?.[0].subclasses??{}));
 function row(key:string,parent:boolean,canExpand:boolean){
  const expanded=open.includes(key), name=contributionName(key,isotope);
  return <div className={'m3-share-row'+(parent?'':' child')} key={key} data-spectrum-trace={key}
   data-lit={active===key} data-related={parent&&!!active&&subtypeFor(active)?.parent===key} style={{'--share-color':traceColor(key)} as CSSProperties}>
   {canExpand?<button className="m3-share-name" aria-expanded={expanded} onClick={()=>setOpen(v=>v.includes(key)?v.filter(k=>k!==key):[...v,key])}>
    {expanded?<ChevronDown size={12}/>:<ChevronRight size={12}/>}<span>{name}</span></button>:<span tabIndex={0} className="m3-share-name leaf">{name}</span>}
   {[0,1].map(i=>{
    const stage=stages?.[i], n=(parent?stage?.classes:stage?.subclasses)?.[key]??0,total=stage?.phs[0].counts??0;
    const enabled=i===0||comparison?.filter_active, value=enabled?percent(n,total):'—';
    return <span key={i} className={'m3-share-cell stage-'+i} title={!enabled?'Optional filters off':(i?'After':'Before')+' filters · '+n.toLocaleString()+' / '+total.toLocaleString()+' pairs · '+percent(n,total,6)}>
     <span className="m3-share-track"><i style={{width:(enabled&&total?100*n/total:0)+'%'}}/></span><small>{value}</small></span>;
   })}</div>;
 }
 return <section className="m3-settings-section m3-share-chart"><h3><ChartNoAxesColumn size={15}/>Contribution shares <Help text="The two bars share a 0–100% scale. Each percentage uses all directional pairs in its own filter stage. Expand a class to compare its subtypes. Hover or focus a row to identify its trace in the plots."/></h3>
  <div className="m3-share-head"><span>Gamma energies (keV)</span><b>Before filters</b><b>{comparison&&!comparison.filter_active?'Filters off':'After filters'}</b></div>
  {parents.map(k=>{
   const sub=children.filter(s=>subtypeFor(s)?.parent===k);
   return <div className="m3-share-group" key={k}>{row(k,true,sub.length>0)}{open.includes(k)&&sub.map(s=>row(s,false,false))}</div>;
  })}</section>;
}
