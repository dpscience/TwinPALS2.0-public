// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {Entry} from './types';
import {curveProblem} from './MaterialCurveEditor';
export function invalidProperties(entry:Entry){
 const p=entry.properties,issues:string[]=[];
 if(!entry.name.trim())issues.push('Name');
 for(const key of ['density_g_cm3','light_yield_per_MeV','refractive_index','absorption_length_mm'])if(key in p&&(!Number.isFinite(p[key])||Number(p[key])<=0))issues.push(key.replaceAll('_',' '));
 const composition=Object.values((p.composition??{}) as Record<string,number>);
 if(!['pmt','digitizer'].includes(entry.category)&&(!composition.length||composition.some(n=>!Number.isFinite(n)||n<=0)||p.composition_basis==='mass_fraction'&&Math.abs(composition.reduce((a,b)=>a+b,0)-1)>1e-6))issues.push('Composition');
 const components=(p.components??[]) as {fraction:number;rise_time_ns:number;decay_time_ns:number}[];
 if(components.length&&(Math.abs(components.reduce((n,c)=>n+c.fraction,0)-1)>1e-6||components.some(c=>!Number.isFinite(c.fraction)||c.fraction<0||c.fraction>1||!Number.isFinite(c.rise_time_ns)||c.rise_time_ns<0||!Number.isFinite(c.decay_time_ns)||c.decay_time_ns<=0)))issues.push('Emission timing / fractions');
 if(entry.curves.some(c=>curveProblem(c,entry.category!=='pmt'||entry.properties.cathode_reflections===true)))issues.push('Curve values / units');
 if(entry.category==='pmt'){
  for(const key of ['window_thickness_mm','window_diameter_mm','window_width_mm','window_height_mm','photocathode_diameter_mm','photocathode_width_mm','photocathode_height_mm','tube_diameter_mm','tube_width_mm','tube_length_mm'])if(key in p&&(!Number.isFinite(p[key])||Number(p[key])<=0))issues.push(key.replaceAll('_',' '));
  for(const key of ['cathode_gap_mm','tts_ns','transit_ns'])if(key in p&&(!Number.isFinite(p[key])||Number(p[key])<0))issues.push(key.replaceAll('_',' '));
  for(const prefix of ['window','photocathode']){
   const square=p.tube_shape==='square',w=Number(p[prefix+'_width_mm']),h=Number(p[prefix+'_height_mm']);
   const span=p[prefix+'_shape']==='rect'?(square?Math.max(w,h):Math.hypot(w,h)):Number(p[prefix+'_diameter_mm']);
   if(span>Number(square?p.tube_width_mm:p.tube_diameter_mm)+1e-8)issues.push(prefix+' exceeds tube size');
  }
  if(Number(p.tube_length_mm)<=Number(p.window_thickness_mm)+Number(p.cathode_gap_mm)+.05)issues.push('Tube length / cathode position');
  if(p.window_material)issues.push(...invalidProperties(p.window_material as Entry).map(k=>'Window: '+k));
 }
 return issues;
}
export function missingProperties(entry:Entry){
 const p=entry.properties,curves=new Set(entry.curves.map(c=>c.name)),missing:string[]=[];
 if(['scintillator','coupling','window'].includes(entry.category))for(const [curve,scalar,label] of [['refractive_index','refractive_index','Refractive index'],['absorption_length','absorption_length_mm','Absorption length']])if(!curves.has(curve)&&!(scalar in p))missing.push(label);
 if(entry.category==='scintillator'){
  if(!p.light_yield_per_MeV)missing.push('Light yield');
  const components=(p.components??[]) as {curve:string;rise_time_ns?:number;decay_time_ns?:number}[];
  if(!components.length||components.some(c=>!curves.has(c.curve)))missing.push('Emission spectrum');
  if(components.some(c=>c.rise_time_ns==null||c.decay_time_ns==null))missing.push('Rise / decay time');
 }
 if(entry.category==='pmt'&&!curves.has('quantum_efficiency'))missing.push('Quantum efficiency');
 if(entry.category==='pmt'){for(const k of ['window_shape','window_diameter_mm','window_width_mm','window_height_mm','window_thickness_mm','photocathode_shape','photocathode_diameter_mm','photocathode_width_mm','photocathode_height_mm','cathode_gap_mm',p.tube_shape==='square'?'tube_width_mm':'tube_diameter_mm','tube_length_mm','dynodes','gain','gain_hv_V','rise_ns','rise_hv_V','transit_ns','transit_hv_V','tts_ns','tts_hv_V','tts_convention','hv_min_V','hv_max_V','hv_absolute_max_V','reference_load_ohm','calibration_flash_fwhm_ns'])if(!(k in p))missing.push(k.replaceAll('_',' '));if(!curves.has('gain_hv')&&!p.gain_exponent)missing.push('Gain curve / exponent');if(!p.window_material)missing.push('Window glass');else missing.push(...missingProperties(p.window_material as Entry).map(k=>'Window: '+k));}
 if(entry.category==='pmt'&&p.cathode_reflections)missing.push(...missingCathodeFilm(entry));
 return missing;
}
function missingCathodeFilm(entry:Entry){
 const p=entry.properties,missing:string[]=[];
 const curves=entry.curves.filter(c=>c.name==='cathode_n'||c.name==='cathode_k');
 const refs=(entry.provenance.references??[]) as {properties?:string[]}[];
 const bounds:number[][]=[];
 for(const [key,label] of [['cathode_film_nm','Cathode film thickness'],['cathode_n','Cathode refractive index n'],['cathode_k','Cathode extinction coefficient k']]){
  if(key==='cathode_film_nm'){
   if(!(Number(p[key])>0))missing.push(label);
  }else{
   const curve=curves.find(c=>c.name===key);
   if(!curve||curveProblem(curve))missing.push(label);
   else{
    const nm=curve.points.map(([x])=>curve.x_unit==='eV'?1239.8419843320026/x:x);
    bounds.push([Math.min(...nm),Math.max(...nm)]);
   }
  }
  if(!refs.some(r=>r.properties?.includes(key)))missing.push(label+' reference');
 }
 if(bounds.length===2&&Math.max(bounds[0][0],bounds[1][0])>=Math.min(bounds[0][1],bounds[1][1]))missing.push('Overlapping cathode n and k spectral range');
 return missing;
}

export function cathodeReflectionIssue(entry?:Entry):string{
 if(!entry)return 'Select a photomultiplier to check its reflection data.';
 if(!entry.properties.cathode_reflections){
  if(!entry.curves.some(c=>c.name==='cathode_n'||c.name==='cathode_k'))return 'No photocathode reflection curves are stored for this PMT.';
  return 'Photocathode reflections are disabled in the PMT catalogue entry.';
 }
 const missing=missingCathodeFilm(entry);
 return missing.length?'Incomplete PMT reflection data: '+missing.join(', ')+'.':'';
}

export function MaterialStatus({entry,draft=false}:{entry:Entry;draft?:boolean}){
 const missing=missingProperties(entry),invalid=invalidProperties(entry);
 return <span className={`material-status ${draft?'draft':invalid.length?'invalid':missing.length?'incomplete':'complete'}`} title={draft?'Not saved yet':invalid.length?'Check: '+invalid.join(', '):missing.length?'Missing: '+missing.join(', '):'All required simulation inputs are present. This does not certify experimental accuracy.'}>{draft?'Draft':invalid.length?'Invalid':missing.length?'Incomplete':'Complete'}</span>;
}
