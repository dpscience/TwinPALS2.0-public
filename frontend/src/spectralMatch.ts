// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {Entry} from './types';
import type {PlotData,PlotSeries} from './Plot';
const hc=1239.8419843320026;
type Points=[number,number][];
const area=(p:Points)=>p.slice(1).reduce((s,b,i)=>s+(b[0]-p[i][0])*(b[1]+p[i][1])/2,0);
function interpolate(p:Points,x:number){
 if(!p.length||x<p[0][0]||x>p[p.length-1][0])return 0;
 let lo=0,hi=p.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(p[m][0]<=x)lo=m;else hi=m;}
 if(hi===lo)return p[lo][1];const a=p[lo],b=p[hi];return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0]);
}
function emissionSeries(scint?:Entry):PlotSeries|undefined{
 if(!scint)return;
 const components=(scint.properties.components??[]) as {curve:string;fraction:number}[];
 const energy=components.flatMap(component=>{const c=scint.curves.find(c=>c.name===component.curve);if(!c)return [];
  const densityNm=c.y_unit==='1/nm'||(['1','relative'].includes(c.y_unit)&&scint.properties.spectral_interpretation==='photon_density_per_wavelength');
  const points:Points=c.points.map(([x,y])=>[c.x_unit==='nm'?hc/x:x,y*(densityNm?x*x/hc:1)] as [number,number]).sort((a,b)=>a[0]-b[0]);
  const norm=area(points);return norm>0?[{points:points.map(([x,y])=>[x,y/norm] as [number,number]),fraction:component.fraction}]:[];
 });
 if(!energy.length)return;
 const knots=energy.flatMap(c=>c.points.map(p=>hc/p[0]));const min=Math.min(...knots),max=Math.max(...knots);
 // Sample the same piecewise-linear energy density used by transport, then
 // apply dE/dlambda. This preserves component photon fractions before scaling.
 const wavelengths=[...new Set([...knots,...Array.from({length:1201},(_,i)=>min+(max-min)*i/1200)])].sort((a,b)=>a-b);
 const emission:Points=wavelengths.map(w=>[w,energy.reduce((sum,c)=>sum+c.fraction*interpolate(c.points,hc/w),0)*hc/(w*w)]);
 const peak=Math.max(...emission.map(p=>p[1]));
 if(!(peak>0))return;
 return {name:`${scint.name} · emission peak = 100%`,color:'#159c9b',points:emission.map(([x,y])=>[x,100*y/peak])};
}

export function spectralMatch(scint:Entry|undefined,cathode:Entry|undefined):PlotData{
 const empty:PlotData={title:'Emission and quantum efficiency',xLabel:'Wavelength (nm)',yLabel:'Emission peak / absolute QE (%)',series:[]};
 const emission=emissionSeries(scint);
 if(!emission||!cathode)return empty;
 const qe=cathode.curves.find(c=>c.name==='quantum_efficiency');if(!qe)return empty;
 const qePoints:Points=qe.points.map(([x,y])=>[qe.x_unit==='nm'?x:hc/x,y*(['%','percent'].includes(qe.y_unit)?1:100)] as [number,number]).sort((a,b)=>a[0]-b[0]);
 return {...empty,series:[emission,{name:`${cathode.name} · absolute QE`,color:'#9168c5',points:qePoints}],note:'Emission is scaled to its peak for comparison. QE is absolute. Transport and window effects are not included in this overlay.'};
}

export function photocathodeSpectrum(rows:[number,number,number,number][],scint?:Entry):PlotData{
 const emission=emissionSeries(scint);
 const series:PlotSeries[]=['Reflected','Absorbed','Transmitted'].map((name,i)=>({
  name,color:['#3977af','#007f79','#a85823'][i],points:rows.map(row=>[row[0],100*row[i+1]])
 }));
 if(emission)series.push({...emission,dashed:true});
 return {
  title:'Photocathode film at normal incidence',xLabel:'Wavelength (nm)',
  yLabel:emission?'Incident light / emission peak (%)':'Incident light (%)',fixedY:[0,100],series,
  note:'Film fractions cover the shared n and k range. Absorption includes photons that produce no photoelectron.'+
   (emission?' The scintillator emission is scaled to its own peak.':'')
 };
}
