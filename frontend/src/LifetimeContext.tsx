// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';
import {primaryLabels} from './m3types';
type Source={path:string;created_utc:string;source:string;activity_Bq:number;lifetimes:{name:string;tau_ns:number;intensity:number;distribution:string}[];digitizer:{name?:string;samples?:number;rate_GSps?:number};acquisition?:{trigger?:string;coincidence_ns?:number;trigger_delay_ns?:number};inputs:{path:string;role:string;physics:Record<string,unknown>}[]};
export function LifetimeContext({value}:{value:unknown}){
 const streams=(value as {streams:Source[]}).streams;
 return <div className="lifetime-context">{streams.map((s,i)=><section key={i}>
  <h3>{s.source==='na22'?'Na-22':'Co-60'} · {s.digitizer.name??'Digitizer'}</h3><p className="lifetime-path">{s.path}</p>
  <p>{s.created_utc?new Date(s.created_utc).toLocaleString():''} · Activity {s.activity_Bq?.toLocaleString()} Bq</p>
  {s.digitizer.samples&&s.digitizer.rate_GSps&&<p>{s.digitizer.samples.toLocaleString()} samples per channel · {s.digitizer.rate_GSps} GS/s · {Number((s.digitizer.samples/s.digitizer.rate_GSps).toPrecision(6))} ns acquisition window</p>}
  {s.acquisition?.trigger&&<p>Module 2 trigger · {s.acquisition.trigger==='coincidence'?'A AND B':s.acquisition.trigger}{s.acquisition.trigger==='coincidence'&&s.acquisition.coincidence_ns!==undefined&&' · '+s.acquisition.coincidence_ns+' ns coincidence window'}{s.acquisition.trigger_delay_ns!==undefined&&' · '+s.acquisition.trigger_delay_ns+' ns common delay'}</p>}
  <table><thead><tr><th>Simulated component</th><th>Lifetime</th><th>Intensity</th><th>Distribution</th></tr></thead><tbody>{s.lifetimes.map((c,j)=><tr key={j}><td>{c.name}</td><td>{(c.tau_ns*1000).toLocaleString()} ps</td><td>{percent(c.intensity*100)}</td><td>{c.distribution}</td></tr>)}</tbody></table>
  <details><summary>Module 1 transport inputs</summary>{s.inputs.map((v,k)=><div key={k}><p className="lifetime-path">{v.path}</p><p>{Object.entries(v.physics).filter(([,x])=>typeof x!=='object').map(([k,x])=>k.replaceAll('_',' ')+' '+String(x)).join(' · ')}</p></div>)}</details></section>)}</div>;
}
type Route={detector:string;primary:number;visits:string[];count:number};
export function primaryName(roles:string[]|undefined,role:number){return primaryLabels[roles?.[role]??'']??('Primary role '+role);}
export function LifetimeRoutes({value,roles}:{value:unknown[];roles?:string[]}){
 return <>{(value as {role:number;record:number;provenance?:{crystal?:{routes?:Route[]};anode?:{routes?:Route[]}}}[]).map((v,i)=><section key={i}><strong>Transport record {v.record} · {primaryName(roles,v.role)}</strong>{(['crystal','anode'] as const).map(k=><div key={k}>{v.provenance?.[k]?.routes?.map((r,j)=><p key={j}>{k==='crystal'?'Crystal':'Anode'} {r.detector} · {r.visits.join(' → ')}{r.count>1?` · ${r.count} contributions`:''}</p>)}</div>)}</section>)}</>;
}
