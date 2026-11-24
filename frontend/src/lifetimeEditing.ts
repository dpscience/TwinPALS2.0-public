// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {LifetimeChannel,LifetimeViews} from './m3types';
import {categoryNames} from './m3types';
export type WindowRole='start'|'stop';
export const classKeys=Object.keys(categoryNames);
export const classColors:Record<string,string>={correlated:'#087e83',annihilation_pair:'#6652a3',same_primary:'#386fb0',accidental:'#ae721e',pileup_same_decay:'#a34778',pileup_multiple_decays:'#854e34',unresolved:'#738395'};
export const directionNames:Record<string,string>={AB:'A → B',BA:'B → A',SS:'Stop–Stop coincidence'};
export const originNames={all:'All light origins',scintillation:'Scintillation',cherenkov:'Cherenkov',mixed:'Mixed',unknown:'Unknown'};
export const scatterNames={all:'All paths',none:'No scattering',any:'Any scattering',shield:'Shielding',sample:'Sample / source / foil',other_detector:'Opposite crystal'};
export function chosenClasses(view:Pick<LifetimeViews,'category'|'categories'>){return view.categories??(view.category==='all'?classKeys:[view.category]);}
export function displaySettings(v:Pick<LifetimeViews,'bin_ps'|'zero_ps'|'low_ns'|'high_ns'|'category'|'categories'|'individual'|'origin'|'scatter'>){return {bin_ps:v.bin_ps,zero_ps:v.zero_ps,low_ns:v.low_ns,high_ns:v.high_ns,category:v.category,categories:v.categories??null,individual:v.individual??false,origin:v.origin,scatter:v.scatter};}
export function gateError(channels:LifetimeChannel[]){
 for(const [i,c] of channels.entries()){
  const prefix='Channel '+'AB'[i]+' · ';
  for(const role of ['start','stop'] as const){
   const g=c[role];if(g.phs.low<0||g.phs.high<=g.phs.low)return prefix+'the '+role+' upper edge must exceed its lower edge.';
   if(g.area.below<0||g.area.above<0||g.shape.radius_rise<=0||g.shape.radius_fall<=0||g.shape.rise<0||g.shape.fall<0)return prefix+'check filter widths, radii and centre.';
  }
  if(Math.max(c.start.phs.low,c.stop.phs.low)<Math.min(c.start.phs.high,c.stop.phs.high))return prefix+'Start and Stop windows overlap.';
  if(c.cfd_percent<=0||c.cfd_percent>=100||!Number.isInteger(c.baseline_samples)||c.baseline_samples<4||c.baseline_samples>4096||c.minimum_height_mV<=0)return prefix+'check CF, baseline and minimum height.';
  if(!Number.isInteger(c.median_samples)||c.median_samples<1||c.median_samples>31||c.median_samples%2!==1)return prefix+'median width must be odd (1 to 31).';
 }
 return '';
}
export function moveEdge(c:LifetimeChannel,role:WindowRole,edge:'low'|'high',wanted:number){
 const current=c[role].phs,other=c[role==='start'?'stop':'start'].phs;
 const distance=.01;
 const min=edge==='low'?Math.max(0,other.high<=current.low?other.high:0):current.low+distance;
 const max=edge==='low'?current.high-distance:(other.low>=current.high?other.low:Infinity);
 return Math.round(Math.max(min,Math.min(max,wanted))*100)/100;
}
export function diagnosticFraction(area:[number,number][],shape:[number,number,number][],c:LifetimeChannel,role:WindowRole){
 const gate=c[role];let window=0,passes=0;
 for(let i=0;i<Math.min(area.length,shape.length);i++){
  const [height,integral]=area[i];if(height<gate.phs.low||height>=gate.phs.high)continue;
  window++;const b=gate.area,res=integral-height*b.slope-b.intercept;
  if(b.enabled&&(res < -b.below||res>b.above))continue;
  const s=gate.shape,a=s.angle_deg*Math.PI/180,x=shape[i][0]-s.rise,y=shape[i][1]-s.fall;
  const u=(x*Math.cos(a)+y*Math.sin(a))/s.radius_rise,v=(-x*Math.sin(a)+y*Math.cos(a))/s.radius_fall;
  if(!s.enabled||u*u+v*v<=1)passes++;
 }
 return {window,passes};
}

