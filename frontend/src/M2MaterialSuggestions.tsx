// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {DatabaseLink} from './DatabaseLink';
import {ArrowUpRight,AlertTriangle} from 'lucide-react';
import {Help} from './Fields';
import type {PulseInput,Lifetime} from './m2types';
export function M2MaterialSuggestions({inputs,values}:{inputs:PulseInput|null;values:Lifetime[]}){
 if(!inputs?.materials?.length)return null;
 return <section className="lifetime-suggestions"><h3>Materials from Module 1 <Help text="Names and left/right assignment come from the input stream. Optional lifetime values come from the current database. They are alternatives, not automatic mixture fractions; Module 1 does not simulate positron implantation. Co-60 has no positron-lifetime contribution."/></h3>
 {inputs.materials.map(m=>{
  const match=values.some(v=>v.origin===(m.position==='foil'?'source':'sample')&&m.lifetimes.some(c=>Math.abs(v.tau_ns*1000-c.tau_ps)<.5));
  return <section key={m.position} className="lifetime-proposal">
   <header><div><small>{m.position==='foil'?'Source foil':m.position==='left'?'Left sample':'Right sample'}</small><strong>{m.name}</strong></div>{m.present&&<DatabaseLink id={m.id} category={m.category}/>}</header>
   {m.lifetimes.length?<><ul className="lifetime-alternatives">{m.lifetimes.map((c,i)=><li key={i}><span title={`${c.state}\n${c.comment}`}><b>{c.tau_ps} ps</b><small>{c.method}</small></span><a href={/^https?:\/\//.test(c.reference_url)?c.reference_url:undefined} target="_blank" rel="noopener noreferrer" title={`${c.reference_title}\n${c.reference_url}`} aria-label={`Reference for ${m.name}, ${c.tau_ps} ps`}><ArrowUpRight size={14}/></a></li>)}</ul>{inputs.isotope==='na22'&&!match&&<p className="lifetime-mismatch"><AlertTriangle size={13}/><span>Selected {m.position==='foil'?'source':'sample'} lifetimes differ from these reference values.</span></p>}</>:<p className="lifetime-unavailable">No lifetime available.</p>}
  </section>;
 })}</section>;
}
